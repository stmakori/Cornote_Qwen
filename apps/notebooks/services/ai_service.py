import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import httpx
from django.conf import settings
from anthropic import Anthropic, Omit
from openai import OpenAI

logger = logging.getLogger(__name__)

try:
    from gtts import gTTS
except ImportError:  # pragma: no cover - handled at runtime
    gTTS = None

ANTHROPIC_API_VERSION = '2023-06-01'

# ── Provider helpers ───────────────────────────────────────────
#
# Qwen (via the ModelScope OpenAI-compatible API) is the primary provider for
# all text generation: notes formatting, question generation, grading, hints,
# and tutor chat. Anthropic Claude is kept as a separate pathway used only for
# scanned-page math OCR/vision transcription (see transcribe_scanned_page_image),
# since that's the one call that needs a vision-capable model.

def _http_timeout():
    from httpx import Timeout

    t = float(getattr(settings, 'AI_REQUEST_TIMEOUT', 120))
    return Timeout(t, connect=min(30.0, t))


def _get_qwen_client():
    """Return an OpenAI-compatible client for Qwen (ModelScope inference API).

    Used for all text generation calls (_chat).
    """
    api_key = getattr(settings, 'QWEN_API_KEY', '')
    if not api_key:
        raise ValueError('QWEN_API_KEY must be set in .env')
    return OpenAI(
        api_key=api_key,
        base_url=getattr(settings, 'QWEN_BASE_URL', 'https://api-inference.modelscope.ai/v1'),
        timeout=_http_timeout(),
    )


def _get_anthropic_client():
    """Return an Anthropic client configured for the current deployment.

    Uses bearer auth for the AWS-hosted Claude key and includes the workspace
    header. Only used for scanned-page math OCR/vision transcription.
    """
    headers: dict[str, str | Omit] = {}
    workspace_id = getattr(settings, 'ANTHROPIC_WORKSPACE_ID', '')
    if workspace_id:
        headers['anthropic-workspace-id'] = workspace_id
    auth_token = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not auth_token:
        raise ValueError('ANTHROPIC_API_KEY must be set in .env')

    headers['X-Api-Key'] = Omit()
    return Anthropic(
        api_key=Omit(),
        auth_token=auth_token,
        base_url=getattr(settings, 'ANTHROPIC_BASE_URL', 'https://api.anthropic.com'),
        default_headers=headers or None,
        timeout=_http_timeout(),
    )


def _merge_message_content(content) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get('type') == 'text':
                    parts.append(block.get('text', ''))
                elif 'text' in block:
                    parts.append(str(block.get('text', '')))
        return ''.join(parts)
    return str(content)


def _prepare_openai_messages(messages, json_mode=False):
    openai_messages: list[dict] = []
    for message in messages:
        role = message.get('role')
        content = _merge_message_content(message.get('content'))
        if not content:
            continue
        if role in ('system', 'user', 'assistant'):
            openai_messages.append({'role': role, 'content': content})

    if json_mode:
        note = 'Return only valid JSON. Do not wrap the response in markdown fences.'
        if openai_messages and openai_messages[0]['role'] == 'system':
            openai_messages[0]['content'] = f"{openai_messages[0]['content']}\n\n{note}"
        else:
            openai_messages.insert(0, {'role': 'system', 'content': note})
    return openai_messages


def friendly_error(exc) -> str:
    """Convert an API exception into a short, actionable message for the user."""
    if isinstance(exc, ValueError):
        return str(exc)
    try:
        from openai import (
            APIConnectionError,
            APIError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            RateLimitError,
        )

        if isinstance(exc, AuthenticationError):
            return 'Invalid Qwen API key - check QWEN_API_KEY in .env.'
        if isinstance(exc, RateLimitError):
            return 'Rate limit reached - wait a moment and try again.'
        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            return 'Could not connect to the AI service - check your internet connection.'
        if isinstance(exc, BadRequestError):
            return f'Request rejected by the AI service: {str(exc)[:120]}'
        if isinstance(exc, APIError):
            return 'AI service error - try again shortly.'
    except ImportError:
        pass
    try:
        from anthropic import APIConnectionError, APIError, APITimeoutError, BadRequestError, AuthenticationError, RateLimitError

        if isinstance(exc, AuthenticationError):
            return 'Invalid Claude auth token - check ANTHROPIC_API_KEY in .env.'
        if isinstance(exc, RateLimitError):
            return 'Rate limit reached - wait a moment and try again.'
        if isinstance(exc, (APIConnectionError, APITimeoutError)):
            return 'Could not connect to the AI service - check your internet connection.'
        if isinstance(exc, BadRequestError):
            return f'Request rejected by the AI service: {str(exc)[:120]}'
        if isinstance(exc, APIError):
            return 'AI service error - try again shortly.'
    except ImportError:
        pass
    return 'Unexpected error - please try again.'


def _qwen_model():
    return settings.QWEN_MODEL_ID


def _anthropic_model():
    return settings.ANTHROPIC_MODEL_ID


def _is_transient_ai_error(exc) -> bool:
    try:
        from openai import APIConnectionError, APITimeoutError, RateLimitError, APIError

        if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
            return True
        if isinstance(exc, APIError) and getattr(exc, 'status_code', 0) in (429, 500, 502, 503, 504):
            return True
    except ImportError:
        pass
    try:
        from anthropic import APIConnectionError, APITimeoutError, RateLimitError, APIError

        if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
            return True
        if isinstance(exc, APIError) and getattr(exc, 'status_code', 0) in (429, 500, 502, 503, 504):
            return True
    except ImportError:
        pass
    return False


def _chat_once(messages, temperature=0.5, max_tokens=1000, json_mode=False):
    client = _get_qwen_client()
    try:
        openai_messages = _prepare_openai_messages(messages, json_mode)
        response = client.chat.completions.create(
            model=_qwen_model(),
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = (response.choices[0].message.content or '').strip()
        if not text:
            raise ValueError('Qwen returned empty response.')
        return text
    finally:
        if hasattr(client, 'close'):
            client.close()


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


def _vision_once(image_b64: str, prompt: str, max_tokens: int = 2000) -> str:
    client = _get_anthropic_client()
    try:
        response = client.messages.create(
            model=_anthropic_model(),
            max_tokens=max_tokens,
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': image_b64}},
                    {'type': 'text', 'text': prompt},
                ],
            }],
        )
        text_parts = []
        for block in getattr(response, 'content', []) or []:
            if getattr(block, 'type', None) == 'text':
                text_parts.append(getattr(block, 'text', '') or '')
        text = ''.join(text_parts).strip()
        if not text:
            raise ValueError('Claude returned empty response.')
        return text
    finally:
        if hasattr(client, 'close'):
            client.close()


def _vision_chat(image_b64: str, prompt: str, max_tokens: int = 2000) -> str:
    """Same retry-on-transient-error behavior as _chat, for a single-image vision call."""
    attempts = int(getattr(settings, 'AI_MAX_RETRIES', 3))
    last_exc = None
    for attempt in range(attempts):
        try:
            return _vision_once(image_b64, prompt, max_tokens)
        except Exception as exc:
            last_exc = exc
            if not _is_transient_ai_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(1.5 * (2**attempt))
    raise last_exc


_MATH_OCR_PROMPT = (
    'Transcribe all text on this scanned page exactly as written. Render any mathematical '
    'notation (fractions, exponents, roots, summations, integrals, Greek letters, equations) '
    'as LaTeX: $...$ for inline math, $$...$$ for a standalone equation. Preserve headings, '
    'lists, and structure using Markdown. Respond with ONLY the transcribed content, nothing else.'
)


def transcribe_scanned_page_image(image) -> str:
    """Transcribe a scanned page (a PIL Image) into Markdown text, rendering any math
    notation as LaTeX so it survives OCR instead of turning into garbled symbols.

    Used as the primary OCR path for scanned PDFs - Tesseract has no concept of LaTeX
    and mangles fractions/exponents/roots into unreadable plain text, while Claude's
    vision can read handwritten or printed math and transcribe it properly.
    """
    import base64
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format='PNG')
    image_b64 = base64.b64encode(buffer.getvalue()).decode('ascii')
    return _vision_chat(image_b64, _MATH_OCR_PROMPT)


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


def _error_message_from_response(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            error = data.get('error')
            if isinstance(error, dict):
                message = error.get('message') or error.get('type')
                if message:
                    return str(message)
            if isinstance(error, str):
                return error
            message = data.get('message') or data.get('detail')
            if message:
                return str(message)
    except Exception:
        pass
    text = response.text.strip()
    return text[:160] if text else 'Request was rejected by the AI service.'
def _deduplicate_sections(text: str) -> str:
    """Strip any ## section whose heading already appeared earlier (model loop guard)."""
    import re

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


_QUESTION_TYPE_CYCLE = [
    'short_answer',
    'multiple_choice',
    'true_false',
    'fill_blank',
    'multiple_select',
    'matching',
    'ordering',
]

_QUESTION_TYPE_SPEC = {
    'short_answer': (
        'Open-ended question. Fill "expected_answer" with a model answer and "expected_keywords" with '
        '3-6 concepts a good answer should include. Leave "choices", "correct_choices", "matching_pairs" '
        'and "correct_order" as empty lists.'
    ),
    'fill_blank': (
        'Write "question_text" as a sentence from the material with a key term replaced by "_____". '
        'Put the missing word/phrase in "expected_answer". Leave "choices", "correct_choices", '
        '"matching_pairs" and "correct_order" as empty lists.'
    ),
    'true_false': (
        'Write a statement that is either true or false based on the material. Set "expected_answer" to '
        'exactly "True" or "False". Set "choices" to ["True", "False"]. Leave "correct_choices", '
        '"matching_pairs" and "correct_order" as empty lists.'
    ),
    'multiple_choice': (
        'Provide "choices": a list of exactly 4 plausible answer strings (one correct, three convincing '
        'distractors). Set "expected_answer" and "correct_choices" (a one-item list) to the exact text of '
        'the correct choice. Leave "matching_pairs" and "correct_order" as empty lists.'
    ),
    'multiple_select': (
        'Provide "choices": a list of 4-6 answer strings where 2-3 are correct. Set "correct_choices" to '
        'the list of correct choice strings, and "expected_answer" to those correct choices joined with ", ". '
        'Leave "matching_pairs" and "correct_order" as empty lists.'
    ),
    'matching': (
        'Provide "matching_pairs": a list of 3-5 objects like {"left": "term", "right": "matching definition"} '
        'built from the material. Set "expected_answer" to a readable rendition, e.g. '
        '"term1 - definition1, term2 - definition2". Leave "choices", "correct_choices" and "correct_order" '
        'as empty lists.'
    ),
    'ordering': (
        'Provide "correct_order": a list of 3-5 strings that are steps/events/items from the material in '
        'their correct sequence. Set "expected_answer" to that sequence joined with " -> ". Leave "choices", '
        '"correct_choices" and "matching_pairs" as empty lists.'
    ),
}


def generate_questions(pdf_text: str, count: int = 5) -> list[dict]:
    count = max(1, min(int(count), 10))
    type_plan = [_QUESTION_TYPE_CYCLE[i % len(_QUESTION_TYPE_CYCLE)] for i in range(count)]
    plan_lines = '\n'.join(
        f'{i + 1}. type="{qtype}" - {_QUESTION_TYPE_SPEC[qtype]}'
        for i, qtype in enumerate(type_plan)
    )

    prompt = f"""You are an expert educator creating a varied set of Cornell-style study questions.

Given the following text from a student's PDF, generate exactly {count} questions that test deep \
understanding of the key concepts. Each question must follow the type and format instructions below \
for its position - use a mix of question styles rather than making them all the same.

QUESTION PLAN:
{plan_lines}

Every question object must include ALL of these keys, using empty lists ([]) for any that don't apply \
to that question's type per the instructions above: "question_text", "question_type", "expected_answer", \
"expected_keywords", "choices", "correct_choices", "matching_pairs", "correct_order", "is_math".

MATH QUESTIONS: if the source material is mathematical (equations, formulas, numeric problems), set \
"is_math" to true and write any mathematical notation in "question_text" and "expected_answer" as LaTeX \
($...$ for inline, $$...$$ for a standalone equation). Keep "expected_answer" a single clean expression \
or number (e.g. "2x + 2" or "$\\frac{{1}}{{2}}$"), not a sentence, so it can be checked automatically - \
unless the question is a word problem that genuinely needs a worked explanation. For every other \
question, set "is_math" to false.

PDF TEXT:
{pdf_text}

Respond ONLY with valid JSON in this exact format:
{{
  "questions": [
    {{
      "question_text": "...",
      "question_type": "short_answer|multiple_choice|true_false|fill_blank|multiple_select|matching|ordering",
      "expected_answer": "...",
      "expected_keywords": ["keyword1", "keyword2"],
      "choices": [],
      "correct_choices": [],
      "matching_pairs": [],
      "correct_order": [],
      "is_math": false
    }}
  ]
}}"""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.7,
        max_tokens=1200 + (count * 800),
        json_mode=True,
    )
    data = _parse_json(content, fallback={'questions': []})
    questions = data.get('questions', [])
    if not questions:
        raise ValueError('AI returned no questions.')

    # Defensive normalization: fall back to short_answer if the AI produced an
    # unknown/malformed type so the UI always has a safe rendering path.
    valid_types = set(_QUESTION_TYPE_CYCLE)
    for q in questions:
        if q.get('question_type') not in valid_types:
            q['question_type'] = 'short_answer'
        for list_field in ('expected_keywords', 'choices', 'correct_choices', 'matching_pairs', 'correct_order'):
            if not isinstance(q.get(list_field), list):
                q[list_field] = []
        q['is_math'] = bool(q.get('is_math'))

    return questions


def grade_answer(question_text: str, expected_answer: str, expected_keywords: list, user_answer: str) -> dict:
    if not user_answer or not user_answer.strip():
        keywords_str = ', '.join(expected_keywords) if expected_keywords else 'N/A'
        return {'grade': 'incorrect', 'feedback': f'No answer provided. Expected concepts: {keywords_str}'}

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
        temperature=0.5,
        max_tokens=300,
        json_mode=True,
    )
    data = _parse_json(content, fallback={'grade': 'incorrect', 'feedback': 'No feedback available.'})
    grade = data.get('grade', 'incorrect')
    if grade not in ('correct', 'partial', 'incorrect'):
        grade = 'incorrect'
    return {'grade': grade, 'feedback': data.get('feedback', 'No feedback available.')}


def grade_answer_batch(items: list, max_workers: int = 6) -> list:
    """Grade several free-text answers concurrently.

    Each AI grading call is a blocking network request; running them one at a
    time (as Grade All / exam finalization used to) means an N-question batch
    takes N times as long as it needs to. httpx releases the GIL during I/O,
    so a small thread pool gets real wall-clock speedup here without touching
    the Django ORM from worker threads (callers save results after this
    returns, on the calling thread).

    `items` is a list of dicts with keys: question_text, expected_answer,
    expected_keywords, user_answer. Returns a list of dicts in the same order:
    {'ok': True, 'grade': ..., 'feedback': ...} or {'ok': False, 'error': '...'}.
    """
    results = [None] * len(items)
    if not items:
        return results

    def _run(index, item):
        try:
            result = grade_answer(**item)
            return index, {'ok': True, **result}
        except Exception as exc:
            return index, {'ok': False, 'error': friendly_error(exc)}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as executor:
        futures = [executor.submit(_run, i, item) for i, item in enumerate(items)]
        for future in futures:
            index, result = future.result()
            results[index] = result
    return results


def generate_hint(question_text: str, expected_answer: str, expected_keywords: list, level: int = 1) -> str:
    level = 1 if level not in (1, 2) else level
    keywords_str = ', '.join(expected_keywords) if expected_keywords else 'N/A'

    if level == 1:
        guidance = (
            'Give a gentle, high-level conceptual nudge that points the student toward the right area of '
            'thinking, without naming the answer, a synonym of the answer, or any of the expected keywords.'
        )
    else:
        guidance = (
            'Give a more specific pointer than a first hint would - you may reference the general topic or '
            'category the answer belongs to - but still do NOT state the answer itself or any of the expected '
            'keywords verbatim.'
        )

    prompt = f"""You are a supportive tutor helping a student who is stuck on a study question.

Question: {question_text}
Model answer (for your reference only - never reveal this to the student): {expected_answer}
Expected key concepts (for your reference only - never reveal these verbatim): {keywords_str}

{guidance}

Respond with ONLY the hint text itself (1-2 short sentences), no preamble, no labels."""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.6,
        max_tokens=150,
    )
    return content.strip()


def answer_notebook_question(pdf_text: str, history: list[dict], question: str) -> str:
    """Answer a student's question grounded in one notebook's material.

    `history` is prior turns as [{'role': 'user'|'assistant', 'content': ...}],
    oldest first - kept short since it's just for conversational continuity,
    not additional source material.
    """
    context = (pdf_text or '').strip()[:12000]
    system_prompt = (
        'You are a helpful, encouraging study tutor. Answer the student\'s question using the '
        'reference material below as your source of truth. If the material does not cover what '
        'they are asking, say so plainly rather than inventing an answer. Keep answers concise '
        '(2-5 sentences) unless the student explicitly asks for more depth.\n\n'
        f'REFERENCE MATERIAL:\n{context}'
    )
    messages = [{'role': 'system', 'content': system_prompt}]
    for turn in history[-10:]:
        role = turn.get('role')
        content = turn.get('content')
        if role in ('user', 'assistant') and content:
            messages.append({'role': role, 'content': content})
    messages.append({'role': 'user', 'content': question})

    return _chat(messages, temperature=0.4, max_tokens=500).strip()


def evaluate_summary(pdf_text: str, key_points: list, user_summary: str) -> dict:
    if not user_summary or not user_summary.strip():
        return {
            'included_points': [],
            'missed_points': key_points,
            'feedback_text': 'No summary was provided. Here is what you missed:',
        }

    key_points_section = ''
    if key_points:
        key_points_section = (
            'Key concepts from the material:\n'
            + '\n'.join(f'- {p}' for p in key_points)
            + '\n\n'
        )

    prompt = f"""You are a knowledgeable teacher evaluating a student's summary. Be direct and specific.

REFERENCE MATERIAL (source of truth):
{pdf_text[:3000]}

{key_points_section}STUDENT'S SUMMARY:
{user_summary}

Evaluate the student's summary thoroughly:
1. List every key concept the student covered correctly in "included_points".
2. List every important concept that is MISSING from their summary in "missed_points".
3. For any statement that is INCORRECT or INACCURATE, add it to "missed_points" using this exact format: "Correction: [student wrote X, but the correct information is Y]"
4. If the summary is off-topic or unrelated to the material, state this explicitly in "feedback_text" and briefly describe what the material actually covers.
5. Write 2-3 sentences of direct, actionable feedback in "feedback_text" — be specific about what to improve, not just encouraging.

Respond ONLY with valid JSON:
{{
  "included_points": ["concept the student covered correctly"],
  "missed_points": ["missing concept", "Correction: student wrote X but actually Y"],
  "feedback_text": "Direct, specific feedback here"
}}"""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.5,
        max_tokens=1000,
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

From the following text, identify 15-25 key concepts or facts that a student should \
know after studying this material. Be concise - each point should be one sentence.

TEXT:
{pdf_text[:40000]}

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


def extract_topics(pdf_text: str) -> list[dict]:
    """Break the material into an ordered sequence of topics to study, easiest
    first, each one assumed to build on the ones before it (a simple linear
    prerequisite chain - good enough for "what order should I study this in",
    not a full dependency graph)."""
    prompt = f"""You are an educator designing a study sequence for a student new to this material.

From the following text, identify 4-8 topics/concepts a student should learn, in the ORDER
they should be studied - foundational ideas first, things that build on them later.

TEXT:
{pdf_text[:40000]}

Respond ONLY with valid JSON, topics already in study order:
{{
  "topics": [
    {{
      "name": "Short topic name (a few words)",
      "description": "One sentence on what this topic covers",
      "difficulty_level": 1
    }}
  ]
}}
difficulty_level must be 1 (easy/foundational), 2 (medium), or 3 (hard/advanced)."""

    content = _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.5,
        max_tokens=800,
        json_mode=True,
    )
    data = _parse_json(content, fallback={'topics': []})
    topics = data.get('topics', [])

    cleaned = []
    for t in topics:
        if not isinstance(t, dict) or not t.get('name'):
            continue
        difficulty = t.get('difficulty_level', 2)
        if difficulty not in (1, 2, 3):
            difficulty = 2
        cleaned.append({
            'name': str(t['name'])[:255],
            'description': str(t.get('description', '')),
            'difficulty_level': difficulty,
        })
    return cleaned


def _summarize_chunk(chunk: str, chunk_num: int, total: int) -> str:
    """Extract key points from one chunk of the document."""
    part_label = f" (part {chunk_num} of {total})" if total > 1 else ""
    prompt = f"""You are an expert educator. Extract ALL key concepts, facts, definitions, and important details from the study material below{part_label}.

Rules:
- Use ## headings for each distinct topic found in this section
- Use bullet points under each heading
- Bold **key terms**
- Keep every important fact — do not skip anything. Be extremely comprehensive.
- Detail every single topic thoroughly.
- Do not add anything not in the text

MATERIAL:
{chunk}

Return only the structured key points."""

    return _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.3,
        max_tokens=4000,
    )


def _consolidate_summaries(parts: list[str]) -> str:
    """Merge chunk summaries into one clean, complete summary."""
    combined = '\n\n---\n\n'.join(parts)
    prompt = f"""You are an expert educator. Below are structured key-point extracts from different sections of a student's study document. Combine them into one complete, well-organised summary.

Rules:
- Merge related topics under unified ## section headings
- Eliminate exact duplicates but keep all unique facts
- Use bullet points and sub-bullets throughout
- Bold **key terms** and definitions
- Write a highly detailed summary (aim for 1000 to 1500 words).
- Do NOT leave out any section or topic. Detail the concepts thoroughly to ensure it covers the ENTIRE document.
- It is CRITICAL that you complete the summary with a proper conclusion and do NOT cut off abruptly.

SECTION EXTRACTS:
{combined}

Return only the final merged summary."""

    return _chat(
        [{'role': 'user', 'content': prompt}],
        temperature=0.4,
        max_tokens=8000,
    )


def generate_notes_summary(pdf_text: str) -> str:
    """Map-reduce summary: covers the full document regardless of length."""
    CHUNK_SIZE = 10000  # chars — safe input size per API call
    CONSOLIDATE_BATCH = 4  # max parts to merge in a single consolidation pass

    text = pdf_text.strip()
    if not text:
        return ''

    if len(text) <= CHUNK_SIZE:
        return _consolidate_summaries([_summarize_chunk(text, 1, 1)])

    # Split on paragraph boundaries
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

    parts = [_summarize_chunk(c, i + 1, len(chunks)) for i, c in enumerate(chunks)]

    # Hierarchical consolidation: repeatedly merge in batches until one pass remains.
    # This ensures no single consolidation call receives more input than it can handle,
    # so the full document is always covered regardless of length.
    while len(parts) > CONSOLIDATE_BATCH:
        batched: list[str] = []
        for i in range(0, len(parts), CONSOLIDATE_BATCH):
            batched.append(_consolidate_summaries(parts[i : i + CONSOLIDATE_BATCH]))
        parts = batched

    return _consolidate_summaries(parts)


def generate_audio_summary(text: str) -> tuple[bytes, str, str]:
    """
    Generate a server-side summary audio file.

    Returns a tuple of (audio_bytes, file_extension, content_type).
    The current implementation returns MP3 audio using gTTS.
    """
    if not text or not text.strip():
        raise ValueError('No text provided for audio generation.')

    text = text[:5000]
    if gTTS is None:
        raise ValueError('Audio generation failed. Install gTTS: pip install gTTS')

    try:
        buffer = BytesIO()
        gTTS(text=text, lang='en').write_to_fp(buffer)
        audio_bytes = buffer.getvalue()
        if not audio_bytes:
            raise ValueError('gTTS returned empty audio.')
        return audio_bytes, 'mp3', 'audio/mpeg'
    except Exception as exc:
        logger.warning('gTTS fallback failed: %s', exc)
        raise
