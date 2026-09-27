"""Triggers that start agents automatically - the student never has to ask."""
import logging
import threading

from django.conf import settings
from django.db import connection

from ..models import StudyPlan
from . import workflows

logger = logging.getLogger(__name__)


def enabled():
    return bool(getattr(settings, 'AGENTS_ENABLED', True))


def _spawn(fn, *args):
    """Run fn in a background thread so the page responds immediately."""
    if getattr(settings, 'AGENTS_RUN_INLINE', False):
        fn(*args)
        return

    def target():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            logger.exception('Background agent task failed')
        finally:
            connection.close()

    threading.Thread(target=target, daemon=True).start()


def _after_grading_task(user, notebook, missed_questions):
    limit = int(getattr(settings, 'AGENT_MAX_FEEDBACK_PER_GRADING', 3))
    for question in missed_questions[:limit]:
        workflows.run_feedback(user, notebook, question)
    # Re-plan automatically whenever results change (only once a plan or exam date exists,
    # so students who never asked for a plan don't get one silently).
    if StudyPlan.objects.filter(notebook=notebook).exists():
        workflows.run_study_plan(user, notebook, trigger='after_grading')


def after_grading(user, notebook, missed_questions):
    """Feedback agent for each missed question, then an automatic re-plan."""
    if enabled() and (missed_questions or StudyPlan.objects.filter(notebook=notebook).exists()):
        _spawn(_after_grading_task, user, notebook, list(missed_questions))


def after_questions_generated(notebook):
    """Verifier agent. Called from the processing thread, after the notebook is ready."""
    if enabled() and notebook.questions.exists():
        try:
            workflows.run_verifier(notebook)
        except Exception:  # noqa: BLE001
            logger.exception('Verifier failed for notebook %s', notebook.pk)


def exam_date_set(user, notebook):
    if enabled():
        _spawn(workflows.run_study_plan, user, notebook, 'exam_date_set')


def replan(user, notebook):
    if enabled():
        _spawn(workflows.run_study_plan, user, notebook, 'manual')
