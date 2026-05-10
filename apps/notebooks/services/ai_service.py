import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Provider helpers ───────────────────────────────────────────

def _get_client():
    """Return an OpenAI-compatible client for the configured AI provider."""
    from openai import OpenAI
    provider = settings.AI_PROVIDER
    if provider == 'groq':
        if not settings.GROQ_API_KEY:
            raise ValueError('GROQ_API_KEY is not set. Add it to your .env file.')
        return OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url='https://api.groq.com/openai/v1',
        )
    if provider == 'openai':
        if not settings.OPENAI_API_KEY:
            raise ValueError('OPENAI_API_KEY is not set. Add it to your .env file.')
        return OpenAI(api_key=settings.OPENAI_API_KEY)
    raise ValueError(
        f'Unknown AI_PROVIDER "{provider}" in settings. Must be "openai" or "groq".'
    )


def friendly_error(exc) -> str:
    """Convert an API exception into a short, actionable message for the user."""
    try:
        from openai import AuthenticationError, RateLimitError, APIConnectionError, BadRequestError, APIStatusError
        if isinstance(exc, AuthenticationError):
            provider = settings.AI_PROVIDER.upper()
            return f'Invalid API key - check your {provider}_API_KEY in .env.'
        if isinstance(exc, RateLimitError):
            return 'Rate limit reached - wait a moment and try again.'
        if isinstance(exc, APIConnectionError):
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
    return 'gpt-4o-mini'


def _chat(messages, temperature=0.5, max_tokens=1000, json_mode=False):
    """Single entry point for all chat completions."""
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


def generate_audio_summary(text: str) -> bytes:
    """
    Generate audio using OpenAI TTS.
    Always uses OpenAI regardless of AI_PROVIDER - Groq has no TTS endpoint.
    """
    if not text or not text.strip():
        raise ValueError('No text provided for audio generation.')
    if not settings.OPENAI_API_KEY:
        raise ValueError('Audio summaries require OPENAI_API_KEY even when using Groq for text.')

    from openai import OpenAI
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.audio.speech.create(
        model='tts-1',
        voice='nova',
        input=text[:5000],
    )
    return response.content
