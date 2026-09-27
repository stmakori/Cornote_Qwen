"""Shared tools for Cornote's agents.

Every tool is bound to one AgentContext (one student + one notebook), so an
agent can only ever read or change that student's own notebook. Tools log each
call into ctx.steps, which is saved on the AgentRun as an audit trail and shown
in the UI ("what did the agent actually do?").
"""
import functools
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Max
from django.utils import timezone

from ..models import Answer, Question, QuestionReview, StudyPlan, StudySession

_STOPWORDS = {
    'the', 'and', 'for', 'that', 'with', 'this', 'from', 'what', 'which', 'when',
    'where', 'why', 'how', 'are', 'was', 'were', 'is', 'of', 'to', 'in', 'on',
    'a', 'an', 'it', 'its', 'be', 'by', 'as', 'or', 'at', 'does', 'do', 'did',
    'explain', 'describe', 'about', 'into', 'their', 'there', 'these', 'those',
}

MISTAKE_TYPES = ('missed_concept', 'partial_understanding', 'misread_question', 'careless_slip')
MAX_FOLLOWUPS_PER_RUN = 2


@dataclass
class AgentContext:
    user: object
    notebook: object
    steps: list = field(default_factory=list)
    followups_created: int = 0
    calls: int = 0
    owner_thread: int = field(default_factory=threading.get_ident)

    @property
    def budget(self):
        return int(getattr(settings, 'AGENT_MAX_TOOL_CALLS', 10))


# ─────────────────────────── helpers ───────────────────────────

def _short(text, n=160):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[: n - 1] + '…'


def _tokens(text):
    return {w for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) > 2 and w not in _STOPWORDS}


def split_passages(text, max_chars=900):
    """Split notes into numbered passages (paragraphs, long ones chunked)."""
    passages = []
    for block in re.split(r'\n\s*\n', text or ''):
        block = block.strip()
        while len(block) > max_chars:
            cut = block.rfind('. ', 0, max_chars)
            cut = cut + 1 if cut > max_chars // 2 else max_chars
            passages.append(block[:cut].strip())
            block = block[cut:].strip()
        if block:
            passages.append(block)
    return passages


def search_passages(text, query, max_results=2):
    """Keyword-overlap search. Returns [(index, score, passage)], best first."""
    q = _tokens(query)
    if not q:
        return []
    scored = []
    for idx, passage in enumerate(split_passages(text), start=1):
        p = _tokens(passage)
        overlap = len(q & p)
        if overlap:
            scored.append((idx, overlap / len(q), passage))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:max_results]


def _log(ctx, name, args, result):
    ctx.steps.append({'tool': name, 'input': _short(json.dumps(args, default=str), 200), 'result': _short(result, 240)})
    return result


def _over_budget(ctx):
    ctx.calls += 1
    return ctx.calls > ctx.budget


BUDGET_MSG = 'Tool budget used up. Do not call more tools; give your final answer now.'


def _notebook_question(ctx, question_id):
    try:
        return Question.objects.select_related('topic').get(pk=int(question_id), notebook=ctx.notebook)
    except (Question.DoesNotExist, TypeError, ValueError):
        return None


def _notes_text(ctx):
    return ctx.notebook.notes_content or ctx.notebook.pdf_text or ''


# ─────────────────────────── tools ───────────────────────────

def _thread_safe(ctx):
    """Close the DB connection after a tool call made from a different thread
    than the one that created ctx, so background-thread runs don't leak
    connections (the request/background thread manages its own).
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            finally:
                if threading.get_ident() != ctx.owner_thread:
                    connection.close()
        return wrapper
    return decorator


def build_tools(ctx, names):
    """Return the requested tools, bound to ctx."""
    safe = _thread_safe(ctx)

    @safe
    def search_notes(query: str, max_results: int = 2) -> str:
        """Search the student's own notes for passages about a concept.

        Returns numbered passages like [P12] you can cite. Use this before
        explaining a concept or judging whether a question is supported.

        Args:
            query: Key words describing the concept to look up.
            max_results: How many passages to return (1-3).
        """
        if _over_budget(ctx):
            return BUDGET_MSG
        hits = search_passages(_notes_text(ctx), query, max(1, min(int(max_results), 3)))
        if not hits:
            result = 'No matching passage found in the notes.'
        else:
            result = '\n\n'.join(f'[P{idx}] (match {score:.0%}) {passage[:700]}' for idx, score, passage in hits)
        return _log(ctx, 'search_notes', {'query': query}, result)

    @safe
    def get_question(question_id: int) -> str:
        """Get one question with the student's answer, grade and grader feedback.

        Args:
            question_id: The question's id.
        """
        if _over_budget(ctx):
            return BUDGET_MSG
        q = _notebook_question(ctx, question_id)
        if q is None:
            return _log(ctx, 'get_question', {'question_id': question_id}, 'Question not found in this notebook.')
        answer = getattr(q, 'answer', None)
        data = {
            'id': q.pk,
            'type': q.question_type,
            'topic': q.topic.name if q.topic else 'General',
            'question': q.question_text,
            'expected_answer': q.expected_answer,
            'expected_keywords': q.expected_keywords,
            'choices': q.choices or None,
            'student_answer': answer.user_answer if answer else '',
            'grade': answer.grade if answer else 'ungraded',
            'grader_feedback': answer.feedback if answer else '',
        }
        return _log(ctx, 'get_question', {'question_id': question_id}, json.dumps(data, default=str))

    @safe
    def get_performance() -> str:
        """Summarise how the student is doing: results per topic and the questions they missed."""
        if _over_budget(ctx):
            return BUDGET_MSG
        topics = {}
        missed = []
        reviews = {
            r.question_id: r.difficulty_score
            for r in QuestionReview.objects.filter(user=ctx.user, question__notebook=ctx.notebook)
        }
        for q in ctx.notebook.questions.select_related('topic', 'answer'):
            name = q.topic.name if q.topic else 'General'
            stats = topics.setdefault(name, {'correct': 0, 'partial': 0, 'incorrect': 0, 'ungraded': 0})
            answer = getattr(q, 'answer', None)
            grade = answer.grade if answer else Answer.GRADE_UNGRADED
            stats[grade] = stats.get(grade, 0) + 1
            if grade in (Answer.GRADE_INCORRECT, Answer.GRADE_PARTIAL):
                missed.append({
                    'id': q.pk, 'topic': name, 'grade': grade,
                    'question': _short(q.question_text, 120),
                    'difficulty_score': reviews.get(q.pk, 0),
                    'is_followup': q.created_by_agent,
                })
        missed.sort(key=lambda m: m['difficulty_score'], reverse=True)
        data = {'topics': topics, 'missed_questions': missed[:15]}
        return _log(ctx, 'get_performance', {}, json.dumps(data))

    @safe
    def get_schedule_context() -> str:
        """Get today's date, the exam date, days left, reviews due, recent study time and the current plan."""
        if _over_budget(ctx):
            return BUDGET_MSG
        today = timezone.localdate()
        plan = StudyPlan.objects.filter(notebook=ctx.notebook).first()
        week_ago = timezone.now() - timedelta(days=7)
        sessions = StudySession.objects.filter(notebook=ctx.notebook, started_at__gte=week_ago)
        data = {
            'today': today.isoformat(),
            'exam_date': plan.exam_date.isoformat() if plan and plan.exam_date else None,
            'days_left': (plan.exam_date - today).days if plan and plan.exam_date else None,
            'reviews_due_now': QuestionReview.objects.filter(
                user=ctx.user, question__notebook=ctx.notebook, next_review__lte=timezone.now()
            ).count(),
            'pomodoro_cycles_last_7_days': sum(s.cycles_completed for s in sessions),
            'current_plan_version': plan.version if plan else 0,
            'current_plan': (plan.days if plan else [])[:14],
        }
        return _log(ctx, 'get_schedule_context', {}, json.dumps(data, default=str))

    @safe
    def create_followup_question(
        source_question_id: int,
        question_text: str,
        expected_answer: str,
        expected_keywords: list[str],
        mistake_type: str,
    ) -> str:
        """Create a follow-up question that re-tests the same weak point, scheduled for the next session (tomorrow).

        Args:
            source_question_id: The id of the question the student got wrong.
            question_text: A new short-answer question on the same concept (not a copy).
            expected_answer: The model answer.
            expected_keywords: 2-5 key concepts a correct answer must mention.
            mistake_type: One of missed_concept, partial_understanding, misread_question, careless_slip.
        """
        if _over_budget(ctx):
            return BUDGET_MSG
        args = {'source_question_id': source_question_id, 'mistake_type': mistake_type}
        source = _notebook_question(ctx, source_question_id)
        if source is None:
            return _log(ctx, 'create_followup_question', args, 'Source question not found in this notebook.')
        if ctx.followups_created >= MAX_FOLLOWUPS_PER_RUN:
            return _log(ctx, 'create_followup_question', args, 'Follow-up limit reached for this run.')
        if not (question_text or '').strip():
            return _log(ctx, 'create_followup_question', args, 'question_text is required.')
        mistake = mistake_type if mistake_type in MISTAKE_TYPES else 'missed_concept'
        note = f'Follow-up to Q{source.order_index} ({mistake.replace("_", " ")})'

        # Re-use an unanswered follow-up for the same source instead of piling up duplicates.
        existing = source.followups.filter(created_by_agent=True, answer__grade=Answer.GRADE_UNGRADED).first()
        if existing:
            existing.question_text = question_text.strip()
            existing.expected_answer = expected_answer or ''
            existing.expected_keywords = list(expected_keywords or [])[:5]
            existing.agent_note = note
            existing.save()
            followup = existing
        else:
            next_index = (ctx.notebook.questions.aggregate(m=Max('order_index'))['m'] or 0) + 1
            followup = Question.objects.create(
                notebook=ctx.notebook,
                topic=source.topic,
                question_text=question_text.strip(),
                question_type=Question.QUESTION_TYPE_SHORT_ANSWER,
                expected_answer=expected_answer or '',
                expected_keywords=list(expected_keywords or [])[:5],
                difficulty=source.difficulty,
                order_index=next_index,
                needs_review=True,
                created_by_agent=True,
                source_question=source,
                agent_note=note,
            )
            Answer.objects.create(question=followup, user=ctx.user)

        # Schedule it for tomorrow in the spaced-repetition queue.
        # (next_review is auto_now_add, so set it with an update after creation.)
        review, _ = QuestionReview.objects.get_or_create(question=followup, user=ctx.user)
        QuestionReview.objects.filter(pk=review.pk).update(
            next_review=timezone.now() + timedelta(days=1), difficulty_score=50,
        )
        ctx.followups_created += 1
        return _log(ctx, 'create_followup_question', args,
                    f'Created follow-up question id={followup.pk}, due tomorrow.')

    @safe
    def save_study_plan(days: list[dict], rationale: str) -> str:
        """Save the day-by-day study plan (replaces the previous version).

        Args:
            days: List of days, each {"date": "YYYY-MM-DD", "focus": str, "tasks": [str], "minutes": int}.
                  Start today, end on or before the exam date.
            rationale: 1-3 sentences on why the plan looks like this (and what changed, if re-planning).
        """
        if _over_budget(ctx):
            return BUDGET_MSG
        max_days = int(getattr(settings, 'AGENT_MAX_PLAN_DAYS', 14))
        today = timezone.localdate()
        clean = []
        for item in (days or [])[:max_days]:
            if not isinstance(item, dict):
                continue
            try:
                day = date.fromisoformat(str(item.get('date', ''))[:10])
            except ValueError:
                continue
            if day < today:
                continue
            tasks = item.get('tasks') or []
            if isinstance(tasks, str):
                tasks = [tasks]
            try:
                minutes = max(10, min(int(item.get('minutes') or 30), 240))
            except (TypeError, ValueError):
                minutes = 30
            clean.append({
                'date': day.isoformat(),
                'focus': _short(item.get('focus', ''), 120),
                'tasks': [_short(t, 140) for t in tasks][:5],
                'minutes': minutes,
            })
        if not clean:
            return _log(ctx, 'save_study_plan', {'days': len(days or [])},
                        'No valid days. Each day needs a date (YYYY-MM-DD, today or later), focus, tasks and minutes.')
        clean.sort(key=lambda d: d['date'])
        plan, _ = StudyPlan.objects.get_or_create(notebook=ctx.notebook)
        plan.days = clean
        plan.rationale = _short(rationale, 600)
        plan.version += 1
        plan.save()
        return _log(ctx, 'save_study_plan', {'days': len(clean)}, f'Saved plan v{plan.version} with {len(clean)} days.')

    @safe
    def list_questions() -> str:
        """List this notebook's questions (id, type, text, expected answer) for review."""
        if _over_budget(ctx):
            return BUDGET_MSG
        rows = [
            {'id': q.pk, 'type': q.question_type, 'question': _short(q.question_text, 200),
             'expected_answer': _short(q.expected_answer, 160)}
            for q in ctx.notebook.questions.filter(created_by_agent=False)
        ]
        return _log(ctx, 'list_questions', {}, json.dumps(rows))

    @safe
    def flag_question(question_id: int, reason: str) -> str:
        """Flag a question for review because it is not supported by the notes or is ambiguous.

        Args:
            question_id: The question's id.
            reason: Short reason shown to the student.
        """
        if _over_budget(ctx):
            return BUDGET_MSG
        q = _notebook_question(ctx, question_id)
        if q is None:
            return _log(ctx, 'flag_question', {'question_id': question_id}, 'Question not found in this notebook.')
        q.needs_review = True
        q.agent_note = _short(f'Verifier: {reason}', 250)
        q.save(update_fields=['needs_review', 'agent_note'])
        return _log(ctx, 'flag_question', {'question_id': question_id}, f'Flagged Q{q.order_index}.')

    available = {
        'search_notes': search_notes,
        'get_question': get_question,
        'get_performance': get_performance,
        'get_schedule_context': get_schedule_context,
        'create_followup_question': create_followup_question,
        'save_study_plan': save_study_plan,
        'list_questions': list_questions,
        'flag_question': flag_question,
    }
    return [available[n] for n in names]


# ─────────────────────── tool schemas (Anthropic tool-use format) ───────────────────────

TOOL_SPECS = {
    'search_notes': {
        'name': 'search_notes',
        'description': (
            "Search the student's own notes for passages about a concept. Returns numbered "
            "passages like [P12] you can cite. Use this before explaining a concept or judging "
            "whether a question is supported."
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': 'Key words describing the concept to look up.'},
                'max_results': {'type': 'integer', 'description': 'How many passages to return (1-3).', 'default': 2},
            },
            'required': ['query'],
        },
    },
    'get_question': {
        'name': 'get_question',
        'description': "Get one question with the student's answer, grade and grader feedback.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'question_id': {'type': 'integer', 'description': "The question's id."},
            },
            'required': ['question_id'],
        },
    },
    'get_performance': {
        'name': 'get_performance',
        'description': "Summarise how the student is doing: results per topic and the questions they missed.",
        'input_schema': {'type': 'object', 'properties': {}},
    },
    'get_schedule_context': {
        'name': 'get_schedule_context',
        'description': (
            "Get today's date, the exam date, days left, reviews due, recent study time and the current plan."
        ),
        'input_schema': {'type': 'object', 'properties': {}},
    },
    'create_followup_question': {
        'name': 'create_followup_question',
        'description': (
            "Create a follow-up question that re-tests the same weak point, scheduled for the "
            "next session (tomorrow)."
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'source_question_id': {'type': 'integer', 'description': 'The id of the question the student got wrong.'},
                'question_text': {'type': 'string', 'description': 'A new short-answer question on the same concept (not a copy).'},
                'expected_answer': {'type': 'string', 'description': 'The model answer.'},
                'expected_keywords': {
                    'type': 'array', 'items': {'type': 'string'},
                    'description': '2-5 key concepts a correct answer must mention.',
                },
                'mistake_type': {
                    'type': 'string',
                    'enum': list(MISTAKE_TYPES),
                    'description': 'The kind of mistake the student made.',
                },
            },
            'required': ['source_question_id', 'question_text', 'expected_answer', 'expected_keywords', 'mistake_type'],
        },
    },
    'save_study_plan': {
        'name': 'save_study_plan',
        'description': "Save the day-by-day study plan (replaces the previous version).",
        'input_schema': {
            'type': 'object',
            'properties': {
                'days': {
                    'type': 'array',
                    'description': (
                        'List of days, each {"date": "YYYY-MM-DD", "focus": str, "tasks": [str], "minutes": int}. '
                        'Start today, end on or before the exam date.'
                    ),
                    'items': {
                        'type': 'object',
                        'properties': {
                            'date': {'type': 'string'},
                            'focus': {'type': 'string'},
                            'tasks': {'type': 'array', 'items': {'type': 'string'}},
                            'minutes': {'type': 'integer'},
                        },
                    },
                },
                'rationale': {
                    'type': 'string',
                    'description': '1-3 sentences on why the plan looks like this (and what changed, if re-planning).',
                },
            },
            'required': ['days', 'rationale'],
        },
    },
    'list_questions': {
        'name': 'list_questions',
        'description': "List this notebook's questions (id, type, text, expected answer) for review.",
        'input_schema': {'type': 'object', 'properties': {}},
    },
    'flag_question': {
        'name': 'flag_question',
        'description': (
            "Flag a question for review because it is not supported by the notes or is ambiguous."
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'question_id': {'type': 'integer', 'description': "The question's id."},
                'reason': {'type': 'string', 'description': 'Short reason shown to the student.'},
            },
            'required': ['question_id', 'reason'],
        },
    },
}
