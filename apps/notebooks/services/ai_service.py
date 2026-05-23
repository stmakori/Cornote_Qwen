import json
import logging
import time
from io import BytesIO
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    from gtts import gTTS
except ImportError:  # pragma: no cover - handled at runtime
    gTTS = None

try:
    import edge_tts
except ImportError:  # pragma: no cover - handled at runtime
    edge_tts = None

# ── Provider helpers ───────────────────────────────────────────

def _http_timeout():
    from httpx import Timeout

    t = float(getattr(settings, 'AI_REQUEST_TIMEOUT', 120))
    return Timeout(t, connect=min(30.0, t))


def _get_client():
    """Return an OpenAI-compatible client for the configured AI provider."""
    from openai import OpenAI

    provider = settings.AI_PROVIDER
    timeout = _http_timeout()
    if provider == 'groq':
        if not settings.GROQ_API_KEY:
            raise ValueError('GROQ_API_KEY is not set. Add it to your .env file.')
        return OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url='https://api.groq.com/openai/v1',
            timeout=timeout,
        )
    if provider == 'gemini':
        if not settings.GEMINI_API_KEY:
            raise ValueError('GEMINI_API_KEY is not set. Add it to your .env file.')
        return OpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url='https://generativelanguage.googleapis.com/v1beta/openai/',
            timeout=timeout,
        )
    if provider == 'openai':
        if not settings.OPENAI_API_KEY:
            raise ValueError('OPENAI_API_KEY is not set. Add it to your .env file.')
        return OpenAI(api_key=settings.OPENAI_API_KEY, timeout=timeout)
    raise ValueError(
        f'Unknown AI_PROVIDER "{provider}" in settings. Must be "openai", "groq", or "gemini".'
    )


def friendly_error(exc) -> str:
    """Convert an API exception into a short, actionable message for the user."""
    try:
        from openai import AuthenticationError, RateLimitError, APIConnectionError, BadRequestError, APIStatusError, APITimeoutError
        if isinstance(exc, AuthenticationError):
            provider = settings.AI_PROVIDER.upper()
            return f'Invalid API key - check your {provider}_API_KEY in .env.'
        if isinstance(exc, RateLimitError):
            return 'Rate limit reached - wait a moment and try again.'
        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            return 'Could not connect to the AI service - check your internet connection.'
        if isinstance(exc, BadRequestError):
            return f'Request rejected by the AI service: {exc.message[:120]}'
        if isinstance(exc, APIStatusError):
            return f'AI service error ({exc.status_code}) - try again shortly.'
    except ImportError:
        pass
    if isinstance(exc, ValueError):
        return str(exc)
    return 'Unexpected error - please try again.'


def _model():
    if settings.AI_PROVIDER == 'groq':
        return settings.GROQ_MODEL_ID
    if settings.AI_PROVIDER == 'gemini':
        return settings.GEMINI_MODEL_ID
    return getattr(settings, 'OPENAI_CHAT_MODEL', 'gpt-4o-mini')


def _is_transient_ai_error(exc) -> bool:
    try:
        from openai import RateLimitError, APIConnectionError, APITimeoutError, APIStatusError

        if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
            return True
        if isinstance(exc, APIStatusError) and getattr(exc, 'status_code', 0) in (
            429, 500, 502, 503, 504
        ):
            return True
    except ImportError:
        pass
    return False


def _chat_once(messages, temperature=0.5, max_tokens=1000, json_mode=False):
    client = _get_client()
    kwargs = dict(
        model=_model(),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def _chat(messages, temperature=0.5, max_tokens=1000, json_mode=False):
    """Chat completions with retries on transient provider errors."""
    attempts = int(getattr(settings, 'AI_MAX_RETRIES', 3))
    last_exc = None
    for attempt in range(attempts):
        try:
            return _chat_once(messages, temperature, max_tokens, json_mode)
        except Exception as exc:
            last_exc = exc
            if not _is_transient_ai_error(exc) or attempt >= attempts - 1:
                raise
            delay = 1.5 * (2**attempt)
            logger.warning(
                'AI chat failed (attempt %s/%s), retrying in %.1fs: %s',
                attempt + 1,
                attempts,
                delay,
                exc,
            )
            time.sleep(delay)
    raise last_exc


def _parse_json(content, fallback=None):
    """Parse JSON from model output, stripping markdown fences if present."""
    text = content.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[-1]
        text = text.rsplit('```', 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning('Failed to parse JSON from AI response: %s', text[:200])
        return fallback if fallback is not None else {}


# ── Public API ─────────────────────────────────────────────────

def _deduplicate_sections(text: str) -> str:
    """Strip any ## section whose heading already appeared earlier (model loop guard)."""
    import re
    # Split at every line that starts a ## heading, keeping the delimiter on the right part
    parts = re.split(r'\n(?=## )', text)
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        m = re.match(r'## (.+?)(?:\n|$)', part)
        if m:
            key = m.group(1).strip().lower()
            if key in seen:
                continue  # whole repeated section dropped
            seen.add(key)
        kept.append(part)
    return '\n'.join(kept)


def _format_chunk(chunk: str, chunk_num: int, total_chunks: int) -> str:
    """Format a single chunk of text as Markdown notes."""
    context = f" (part {chunk_num} of {total_chunks})" if total_chunks > 1 else ""
    prompt = f"""You are a study-notes formatter. The text below was extracted from a student's document{context} and may be messy (broken lines, page numbers, no headings).

Reformat it into clean, well-structured Markdown following these rules:

STRUCTURE — identify and mark different levels clearly:
- `## Heading` — use for every distinct major topic or section title found in the text
- `### Sub-heading` — use for sub-topics or named sub-sections within a major section
- `#### Minor heading` — use for named items within a sub-section (e.g. a specific law, theorem, or concept with its own block)
- Do not invent headings; only promote text that already acts as a title or section label
- Place a blank line before and after every heading

CONTENT inside sections:
- Use `- ` bullet points for lists of facts, steps, properties, or examples
- Use `**term**` bold for key vocabulary, defined terms, and important names
- Use `> blockquote` for formal definitions (e.g. "Definition: ...")
- Use numbered lists `1.` only when order matters (steps, processes, ranked items)
- Write concisely — prefer bullet points over full prose sentences

CLEANUP:
- Remove page numbers, running headers/footers, and extraction artifacts
- Preserve ALL information — do not skip or summarise content
- Do not add content that isn't in the original text
- Output each section EXACTLY ONCE — stop as soon as all input content is formatted

Text to format:
{chunk}

Return only the formatted Markdown, nothing else."""

    result = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.2,
        max_tokens=8000,
    )
    return _deduplicate_sections(result)


def _strip_repeated_page_headers(text: str) -> str:
    """Strip PDF running page headers fused to the start of every paragraph.

    pdfplumber + _clean_text joins each page's header line with the first
    content line, producing paragraphs that all share a long common prefix
    (e.g. 'ACMP446:… yegen8@gmail.com') but then diverge.  We find that
    shared prefix and strip it, keeping the actual content that follows.
    """
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    n = len(paragraphs)
    if n < 3:
        return text

    min_share = max(3, int(n * 0.4))  # prefix must appear in ≥40% of paragraphs

    # Extend the prefix character-by-character as long as min_share paragraphs agree
    ref = paragraphs[0]
    prefix_len = 0
    for i in range(1, min(len(ref) + 1, 300)):
        candidate = ref[:i]
        if sum(1 for p in paragraphs if p.startswith(candidate)) >= min_share:
            prefix_len = i
        else:
            break

    if prefix_len < 10:  # too short to be a real running header
        return text

    header = ref[:prefix_len]
    cleaned = []
    for p in paragraphs:
        if p.startswith(header):
            remainder = p[prefix_len:].strip()
            if remainder:
                cleaned.append(remainder)
        else:
            cleaned.append(p)

    return '\n\n'.join(cleaned)


def format_notes_as_markdown(text: str) -> str:
    """Reformat raw extracted document text into clean structured Markdown notes.

    Splits large documents into chunks to avoid hitting output token limits,
    which causes models to repeat sections.
    """
    CHUNK_SIZE = 6000   # chars per chunk — leaves room for 8000-token output
    MAX_CHARS  = 80000  # ~50 pages; beyond this the document is truncated
    text = _strip_repeated_page_headers(text.strip())
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    if len(text) <= CHUNK_SIZE:
        return _format_chunk(text, 1, 1)

    # Split on paragraph boundaries to avoid cutting mid-sentence
    paragraphs = text.split('\n\n')
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > CHUNK_SIZE and current:
            chunks.append('\n\n'.join(current))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para) + 2

    if current:
        chunks.append('\n\n'.join(current))

    formatted_parts = [
        _format_chunk(chunk, i + 1, len(chunks))
        for i, chunk in enumerate(chunks)
    ]
    return _deduplicate_sections('\n\n'.join(formatted_parts))


def generate_questions(pdf_text: str) -> list[dict]:
    prompt = f"""You are an expert educator creating Cornell-style study questions.

Given the following text from a student's PDF, generate 5 to 10 open-ended study questions \
that test deep understanding of the key concepts. Questions should be specific, meaningful, \
and require the student to think critically.

For each question, provide:
- The question itself
- A model answer that a well-prepared student would give
- 3-6 key keywords or concepts that a good answer should include

PDF TEXT:
{pdf_text}

Respond ONLY with valid JSON in this exact format:
{{
  "questions": [
    {{
      "question_text": "...",
      "expected_answer": "...",
      "expected_keywords": ["keyword1", "keyword2", "keyword3"]
    }}
  ]
}}"""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.7,
        max_tokens=2000,
        json_mode=True,
    )
    data = _parse_json(content, fallback={'questions': []})
    questions = data.get('questions', [])
    if not questions:
        raise ValueError('AI returned no questions.')
    return questions


def grade_answer(question_text: str, expected_answer: str, expected_keywords: list, user_answer: str) -> dict:
    if not user_answer or not user_answer.strip():
        return {'grade': 'incorrect', 'feedback': 'No answer provided.'}

    keywords_str = ', '.join(expected_keywords) if expected_keywords else 'N/A'
    prompt = f"""You are a supportive but honest teacher grading a student's answer.

Question: {question_text}

Expected key concepts/keywords: {keywords_str}
Model answer: {expected_answer}

Student's answer: {user_answer}

Grade as:
- "correct" - fully addresses the question with key concepts present
- "partial" - partially correct, missing some important ideas
- "incorrect" - wrong or does not address the question

Provide brief, encouraging feedback (1-2 sentences).

Respond ONLY with valid JSON:
{{
  "grade": "correct|partial|incorrect",
  "feedback": "..."
}}"""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.3,
        max_tokens=300,
        json_mode=True,
    )
    data = _parse_json(content, fallback={'grade': 'incorrect', 'feedback': 'No feedback available.'})
    grade = data.get('grade', 'incorrect')
    if grade not in ('correct', 'partial', 'incorrect'):
        grade = 'incorrect'
    return {'grade': grade, 'feedback': data.get('feedback', 'No feedback available.')}


def evaluate_summary(pdf_text: str, key_points: list, user_summary: str) -> dict:
    if not user_summary or not user_summary.strip():
        return {
            'included_points': [],
            'missed_points': key_points,
            'feedback_text': 'No summary was provided. Try summarising the main ideas in your own words.',
        }

    key_points_str = '\n'.join(f'- {p}' for p in key_points) if key_points else 'See PDF content below.'
    prompt = f"""You are a supportive teacher reviewing a student's summary of study material.

Key concepts/points from the material:
{key_points_str}

Reference text (first portion):
{pdf_text[:3000]}

Student's summary:
{user_summary}

Identify which key points were included and which were missed, and give 2-3 sentences of feedback.

Respond ONLY with valid JSON:
{{
  "included_points": ["..."],
  "missed_points": ["..."],
  "feedback_text": "..."
}}"""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.4,
        max_tokens=800,
        json_mode=True,
    )
    data = _parse_json(content, fallback={})
    return {
        'included_points': data.get('included_points', []),
        'missed_points': data.get('missed_points', []),
        'feedback_text': data.get('feedback_text', ''),
    }


def extract_key_points(pdf_text: str) -> list[str]:
    prompt = f"""You are an educator extracting the most important learning points from a text.

From the following text, identify 5-10 key concepts or facts that a student should \
know after studying this material. Be concise - each point should be one sentence.

TEXT:
{pdf_text[:6000]}

Respond ONLY with valid JSON:
{{
  "key_points": ["Key point 1", "Key point 2", ...]
}}"""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.5,
        max_tokens=600,
        json_mode=True,
    )
    data = _parse_json(content, fallback={'key_points': []})
    return data.get('key_points', [])


def generate_notes_summary(pdf_text: str) -> str:
    prompt = f"""You are an expert educator creating a concise study summary.

From the following study material, create a well-organised summary that:
- Captures the most important concepts
- Uses clear formatting with sections
- Is suitable for quick review before exams
- Is roughly 200-300 words
- Uses bullet points where appropriate

MATERIAL:
{pdf_text[:8000]}

Provide a clear, well-structured summary."""

    return _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.5,
        max_tokens=1500,
        json_mode=False,
    )


def generate_audio_summary(text: str) -> tuple[bytes, str, str]:
    """
    Generate a server-side summary audio file.

    Returns a tuple of (audio_bytes, file_extension, content_type).
    OpenAI/Groq use MP3. Gemini uses the native Gemini TTS API when it works
    and returns WAV, otherwise the function falls back to MP3-producing engines.
    """
    if not text or not text.strip():
        raise ValueError('No text provided for audio generation.')

    text = text[:5000]

    def _gemini_tts_bytes(summary_text: str) -> bytes:
        import wave
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=getattr(settings, 'GEMINI_TTS_MODEL_ID', 'gemini-2.5-flash-preview-tts'),
            contents=summary_text,
            config=types.GenerateContentConfig(
                response_modalities=['AUDIO'],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=getattr(settings, 'GEMINI_TTS_VOICE', 'Kore'),
                        )
                    )
                ),
            ),
        )
        part = response.candidates[0].content.parts[0]
        pcm_data = part.inline_data.data
        if not pcm_data:
            raise ValueError('Gemini TTS returned empty audio data.')

        # Gemini returns raw PCM (24kHz, 16-bit, mono) — wrap in a WAV container
        buf = BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_data)
        return buf.getvalue()

    # Try provider-specific TTS first (supports 'openai' and 'gemini' via _get_client)
    try:
        provider = settings.AI_PROVIDER
        if provider == 'openai':
            client = _get_client()
            model = getattr(settings, 'OPENAI_TTS_MODEL', 'tts-1')
            try:
                response = client.audio.speech.create(
                    model=model,
                    voice=getattr(settings, 'TTS_VOICE', 'alloy'),
                    input=text,
                )
                # Some clients return bytes in `.content`, others return raw bytes
                audio_bytes = getattr(response, 'content', response)
                return audio_bytes, 'mp3', 'audio/mpeg'
            except Exception as exc:  # pragma: no cover - provider runtime errors
                logger.warning('Provider TTS failed: %s', exc)
                # If provider TTS fails in a recoverable way, fall through below.

        if provider == 'gemini':
            try:
                return _gemini_tts_bytes(text), 'wav', 'audio/wav'
            except Exception as exc:
                logger.warning('Gemini native TTS failed: %s', exc)

    except Exception:  # pragma: no cover - _get_client() errors surfaced via friendly_error elsewhere
        pass

    # Fallbacks: edge-tts, then gTTS.
    if edge_tts is not None:
        try:
            import asyncio
            import tempfile
            from pathlib import Path

            async def _save_to_tempfile() -> bytes:
                summary_text = text
                voice = getattr(settings, 'EDGE_TTS_VOICE', 'en-US-JennyNeural')
                communicator = edge_tts.Communicate(summary_text, voice)
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                    temp_path = Path(tmp.name)
                try:
                    await communicator.save(str(temp_path))
                    return temp_path.read_bytes()
                finally:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            return asyncio.run(_save_to_tempfile()), 'mp3', 'audio/mpeg'
        except Exception as exc:
            logger.warning('edge-tts fallback failed: %s', exc)

    if gTTS is None:
        raise ValueError('Audio summaries need Gemini TTS, edge-tts, or gTTS installed.')

    buffer = BytesIO()
    gTTS(text=text, lang='en').write_to_fp(buffer)
    return buffer.getvalue(), 'mp3', 'audio/mpeg'
