"""Teacher question bank: lets a teacher hand-author a Question without first
uploading a PDF.

Every Question must hang off a Notebook (and Notebook.pdf_file is required), so
each teacher gets one lazily-created "My Question Bank" Notebook holding a
placeholder PDF. Because it's an ordinary Notebook owned by the teacher, bank
questions automatically show up in the assignment question-picker
(`Question.objects.filter(notebook__user=teacher)`) with no extra plumbing.
"""
from django.core.files.base import ContentFile
from django.db.models import Max

from ..models import Notebook, Question

BANK_TITLE = 'My Question Bank'

# Question types a teacher can author by hand in the simple modal form. Matching
# and ordering need richer editors than a hackathon-scale form warrants.
MANUAL_QUESTION_TYPES = (
    Question.QUESTION_TYPE_SHORT_ANSWER,
    Question.QUESTION_TYPE_TRUE_FALSE,
    Question.QUESTION_TYPE_MULTIPLE_CHOICE,
    Question.QUESTION_TYPE_FILL_BLANK,
)

# Minimal but structurally valid one-page PDF so "view source"/"download" on the
# bank notebook don't 404 (same shape as demo_data's placeholder).
_PLACEHOLDER_PDF = (
    b'%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
    b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
    b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n'
    b'trailer<</Size 4/Root 1 0 R>>\n%%EOF'
)


class QuestionBankError(ValueError):
    """Raised for user-facing validation problems; the message is safe to flash."""


def get_or_create_bank(user):
    """Return the teacher's bank Notebook, creating it on first use."""
    bank = Notebook.objects.filter(user=user, title=BANK_TITLE).order_by('created_at').first()
    if bank is not None:
        return bank
    bank = Notebook(
        user=user,
        title=BANK_TITLE,
        description='Questions you wrote yourself for class assignments.',
        status=Notebook.STATUS_READY,
        processing_stage=Notebook.STAGE_READY,
        notes_content='Hand-authored questions for assignments live here.',
    )
    bank.pdf_file.save('question_bank.pdf', ContentFile(_PLACEHOLDER_PDF), save=False)
    bank.save()
    return bank


def _split_lines(raw):
    """Choices come one per line; fall back to comma-separated for one-liners."""
    raw = (raw or '').strip()
    if not raw:
        return []
    parts = raw.splitlines() if '\n' in raw else raw.split(',')
    seen, out = set(), []
    for part in parts:
        part = part.strip()
        if part and part.lower() not in seen:
            seen.add(part.lower())
            out.append(part)
    return out


def _split_keywords(raw):
    return [k.strip() for k in (raw or '').split(',') if k.strip()]


def create_bank_question(user, data):
    """Validate a POSTed form dict and create the Question in the user's bank.

    `data` is a QueryDict-like mapping (``.get``). Raises QuestionBankError with
    a human-readable message on bad input; nothing is written in that case.
    """
    question_text = (data.get('question_text') or '').strip()
    if not question_text:
        raise QuestionBankError('Question text is required.')

    question_type = (data.get('question_type') or Question.QUESTION_TYPE_SHORT_ANSWER).strip()
    if question_type not in MANUAL_QUESTION_TYPES:
        raise QuestionBankError('That question type cannot be authored by hand.')

    expected_answer = (data.get('expected_answer') or '').strip()
    expected_keywords = _split_keywords(data.get('expected_keywords'))
    is_math = str(data.get('is_math') or '').lower() in ('1', 'true', 'on', 'yes')
    choices, correct_choices = [], []

    if question_type == Question.QUESTION_TYPE_TRUE_FALSE:
        if expected_answer.lower() not in ('true', 'false'):
            raise QuestionBankError('True/False questions need "True" or "False" as the answer.')
        expected_answer = expected_answer.capitalize()
        is_math = False

    elif question_type == Question.QUESTION_TYPE_MULTIPLE_CHOICE:
        choices = _split_lines(data.get('choices'))
        if len(choices) < 2:
            raise QuestionBankError('Multiple choice questions need at least 2 distinct choices (one per line).')
        raw_index = (data.get('correct_choice') or '').strip()
        try:
            index = int(raw_index) - 1
        except ValueError:
            raise QuestionBankError('Pick which choice is correct (enter its number).')
        if not 0 <= index < len(choices):
            raise QuestionBankError(f'Correct choice must be between 1 and {len(choices)}.')
        correct_choices = [choices[index]]
        expected_answer = choices[index]
        is_math = False

    else:  # short_answer / fill_blank - AI (or symbolic math) graded, needs a reference answer
        if not expected_answer:
            raise QuestionBankError('An expected answer is required so the question can be graded.')

    bank = get_or_create_bank(user)
    next_index = (bank.questions.aggregate(m=Max('order_index'))['m'] or 0) + 1
    return Question.objects.create(
        notebook=bank,
        order_index=next_index,
        question_type=question_type,
        is_math=is_math,
        question_text=question_text,
        expected_answer=expected_answer,
        expected_keywords=expected_keywords,
        choices=choices,
        correct_choices=correct_choices,
    )
