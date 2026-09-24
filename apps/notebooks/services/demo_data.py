"""Seeds (and resets) a 'demo' account so a hackathon judge or first-time
visitor can explore the whole app without uploading their own PDF first.

Deliberately has zero AI calls - everything here is hardcoded so it's instant
and works even if QWEN_API_KEY isn't configured. Structured-question
answers are graded through the real `grading` module (not hardcoded grade
strings) so if a visitor clicks "Grade All" again, the result stays consistent.
"""
import secrets
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.utils import timezone

from . import grading
from ..models import (
    Answer, Badge, LearningPath, Notebook, Notification, NotebookChatMessage,
    Question, StudyAnalytics, StudyGroup, Summary, Topic, UserAchievement,
)

# Every demo-related account (the visitor's sandbox AND its seeded friend) is
# named with this prefix, so stale-account cleanup can find them all with one
# `username__startswith` filter.
DEMO_USERNAME_PREFIX = 'demo_'

# Demo accounts older than this are deleted the next time someone clicks
# "Try Demo", so the auth_user table doesn't grow unbounded over a multi-day event.
DEMO_ACCOUNT_MAX_AGE = timedelta(hours=1)

# A minimal (blank-page) but structurally valid one-page PDF, so "view source"
# and "download" work without needing a real uploaded file on disk.
_PLACEHOLDER_PDF = (
    b'%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
    b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
    b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n'
    b'trailer<</Size 4/Root 1 0 R>>\n%%EOF'
)

_PDF_TEXT = (
    "Cell Biology Basics\n\n"
    "The cell is the basic structural and functional unit of life. Every cell is "
    "enclosed by a cell membrane, a selectively permeable barrier that controls what "
    "enters and leaves the cell. Inside, the nucleus houses the cell's genetic "
    "material (DNA) and controls the cell's activities. Mitochondria are organelles "
    "that produce ATP through cellular respiration, acting as the powerhouse of the "
    "cell. Ribosomes build proteins by translating messenger RNA. Cells divide "
    "through a process called mitosis, producing two genetically identical daughter "
    "cells."
)

_NOTES_MARKDOWN = """## Cell Structure

- **Cell membrane** - selectively permeable barrier controlling what enters/leaves the cell
- **Nucleus** - houses DNA, controls cell activities
- **Mitochondria** - produces ATP via cellular respiration ("powerhouse of the cell")
- **Ribosomes** - build proteins by translating mRNA

## Cell Division

> Definition: Mitosis is the process by which a cell divides to produce two genetically identical daughter cells.
"""


def _create_source_notebook(user, title, pdf_text, notes_content):
    notebook = Notebook(
        user=user,
        title=title,
        pdf_text=pdf_text,
        notes_content=notes_content,
        status=Notebook.STATUS_READY,
        processing_stage=Notebook.STAGE_READY,
    )
    notebook.pdf_file.save('cell_biology.pdf', ContentFile(_PLACEHOLDER_PDF), save=False)
    notebook.save()
    return notebook


def _add_question(notebook, user, order_index, *, question_type, question_text,
                   expected_answer='', expected_keywords=None, choices=None,
                   correct_choices=None, matching_pairs=None, correct_order=None,
                   user_answer='', hardcoded_grade=None, hardcoded_feedback='', is_math=False):
    question = Question.objects.create(
        notebook=notebook,
        order_index=order_index,
        question_type=question_type,
        is_math=is_math,
        question_text=question_text,
        expected_answer=expected_answer,
        expected_keywords=expected_keywords or [],
        choices=choices or [],
        correct_choices=correct_choices or [],
        matching_pairs=matching_pairs or [],
        correct_order=correct_order or [],
    )

    if not user_answer:
        Answer.objects.create(question=question, user=user)
        return question

    structured = grading.grade_structured_answer(question, user_answer)
    if structured is not None:
        grade, feedback = structured['grade'], structured['feedback']
    else:
        grade, feedback = hardcoded_grade, hardcoded_feedback

    Answer.objects.create(
        question=question, user=user, user_answer=user_answer,
        grade=grade, feedback=feedback, graded_at=timezone.now(),
    )
    return question


def _seed_notebook_and_questions(demo):
    notebook = _create_source_notebook(demo, 'Cell Biology Basics', _PDF_TEXT, _NOTES_MARKDOWN)
    Summary.objects.create(
        notebook=notebook,
        ai_summary=_NOTES_MARKDOWN,
        key_points=[
            'The cell membrane is selectively permeable.',
            'The nucleus stores DNA and controls the cell.',
            'Mitochondria produce ATP via cellular respiration.',
            'Ribosomes translate mRNA into proteins.',
            'Mitosis produces two identical daughter cells.',
        ],
    )

    _add_question(
        notebook, demo, 0,
        question_type=Question.QUESTION_TYPE_SHORT_ANSWER,
        question_text='What is the function of the mitochondria?',
        expected_answer='It produces ATP through cellular respiration, acting as the powerhouse of the cell.',
        expected_keywords=['ATP', 'energy', 'cellular respiration'],
        user_answer='It makes energy for the cell.',
        hardcoded_grade=Answer.GRADE_PARTIAL,
        hardcoded_feedback='Good high-level idea, but try to mention ATP and cellular respiration specifically.',
    )
    _add_question(
        notebook, demo, 1,
        question_type=Question.QUESTION_TYPE_MULTIPLE_CHOICE,
        question_text="Which organelle contains the cell's genetic material?",
        expected_answer='Nucleus',
        choices=['Mitochondria', 'Nucleus', 'Ribosome', 'Golgi apparatus'],
        correct_choices=['Nucleus'],
        user_answer='Nucleus',
    )
    _add_question(
        notebook, demo, 2,
        question_type=Question.QUESTION_TYPE_TRUE_FALSE,
        question_text='The cell membrane is completely impermeable to all substances.',
        expected_answer='False',
        choices=['True', 'False'],
        user_answer='True',
    )
    _add_question(
        notebook, demo, 3,
        question_type=Question.QUESTION_TYPE_FILL_BLANK,
        question_text='The process by which cells divide is called _____.',
        expected_answer='mitosis',
        user_answer='mitosis',
        hardcoded_grade=Answer.GRADE_CORRECT,
        hardcoded_feedback='Correct!',
    )
    _add_question(
        notebook, demo, 4,
        question_type=Question.QUESTION_TYPE_MULTIPLE_SELECT,
        question_text='Which of the following are organelles? (select all that apply)',
        expected_answer='Nucleus, Mitochondria, Ribosome',
        choices=['Nucleus', 'Mitochondria', 'Cytoplasm', 'Ribosome', 'Cell wall'],
        correct_choices=['Nucleus', 'Mitochondria', 'Ribosome'],
        # left unanswered on purpose - shows the "not yet graded" state too
    )
    _add_question(
        notebook, demo, 5,
        question_type=Question.QUESTION_TYPE_MATCHING,
        question_text='Match each organelle to its function.',
        expected_answer='Nucleus - controls cell activities, Mitochondria - produces energy, Ribosome - builds proteins',
        matching_pairs=[
            {'left': 'Nucleus', 'right': 'Controls cell activities'},
            {'left': 'Mitochondria', 'right': 'Produces energy'},
            {'left': 'Ribosome', 'right': 'Builds proteins'},
        ],
        user_answer='Nucleus => Controls cell activities ~ Mitochondria => Produces energy ~ Ribosome => Builds proteins',
    )
    _add_question(
        notebook, demo, 6,
        question_type=Question.QUESTION_TYPE_ORDERING,
        question_text='Put these stages of mitosis in the correct order.',
        expected_answer='Prophase -> Metaphase -> Anaphase -> Telophase',
        correct_order=['Prophase', 'Metaphase', 'Anaphase', 'Telophase'],
        user_answer='Prophase → Anaphase → Metaphase → Telophase',
    )

    NotebookChatMessage.objects.create(
        notebook=notebook, user=demo, role=NotebookChatMessage.ROLE_USER,
        content='What is the function of the mitochondria?',
    )
    NotebookChatMessage.objects.create(
        notebook=notebook, user=demo, role=NotebookChatMessage.ROLE_ASSISTANT,
        content=(
            'The mitochondria produces ATP through cellular respiration, providing the '
            "energy the cell needs for its activities - that's why it's called the "
            "powerhouse of the cell."
        ),
    )
    return notebook


_ALGEBRA_PDF_TEXT = (
    "Linear Equations\n\n"
    "A linear equation can be solved by isolating the variable on one side. "
    "For example, solving 2x + 4 = 10 gives x = 3. The quadratic formula solves "
    "equations of the form ax^2 + bx + c = 0."
)

_ALGEBRA_NOTES_MARKDOWN = r"""## Solving Linear Equations

- Isolate the variable: $2x + 4 = 10 \Rightarrow x = 3$
- The **quadratic formula**: $x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$
"""


def _seed_math_notebook(demo):
    """A small math-themed notebook showing off LaTeX rendering and
    symbolic (sympy) grading - questions here are answered as expressions,
    not free text, and graded instantly without an AI call."""
    notebook = _create_source_notebook(demo, 'Algebra Basics', _ALGEBRA_PDF_TEXT, _ALGEBRA_NOTES_MARKDOWN)

    _add_question(
        notebook, demo, 0,
        question_type=Question.QUESTION_TYPE_SHORT_ANSWER,
        question_text=r'Simplify: $2(x + 1)$',
        expected_answer='2x + 2',
        is_math=True,
        user_answer='2*x+2',
    )
    _add_question(
        notebook, demo, 1,
        question_type=Question.QUESTION_TYPE_SHORT_ANSWER,
        question_text=r'Solve for $x$: $2x + 4 = 10$',
        expected_answer='3',
        is_math=True,
        user_answer='5',
    )
    return notebook


def _seed_learning_path(notebook):
    topic_specs = [
        ('Cell Membrane', 1, 'The selectively permeable barrier around every cell.'),
        ('Nucleus & DNA', 2, "The cell's control center and genetic material."),
        ('Mitochondria', 2, 'The organelle that produces ATP for the cell.'),
        ('Protein Synthesis', 3, 'How ribosomes translate mRNA into proteins.'),
    ]
    topics = [
        Topic.objects.create(notebook=notebook, name=name, difficulty_level=level, description=desc, order_index=i)
        for i, (name, level, desc) in enumerate(topic_specs)
    ]
    for i in range(1, len(topics)):
        topics[i].prerequisites.add(topics[i - 1])

    LearningPath.objects.create(
        notebook=notebook,
        topic_sequence=[t.pk for t in topics],
        completed_topics=[topics[0].pk, topics[1].pk],
        current_topic_index=2,
    )


def _seed_badges_and_analytics(demo):
    badge_specs = {
        'milestone_10': ('10 Questions', 'Answered 10 practice questions.'),
        'consistent': ('Consistent Learner', 'Studied several days in a row.'),
    }
    for badge_type, (name, description) in badge_specs.items():
        badge, _ = Badge.objects.get_or_create(
            badge_type=badge_type, defaults={'name': name, 'description': description},
        )
        UserAchievement.objects.create(user=demo, badge=badge, progress=100)

    StudyAnalytics.objects.create(
        user=demo,
        total_questions_answered=6,
        total_correct=4,
        total_partial=1,
        total_incorrect=1,
        overall_accuracy=75.0,
        study_streak_days=5,
        last_study_date=timezone.now().date(),
    )

    Notification.objects.create(
        user=demo, notification_type='achievement', title='Badge earned!',
        message='You earned the "Consistent Learner" badge.', icon='bi-award',
    )
    Notification.objects.create(
        user=demo, notification_type='streak', title='5-day streak!',
        message='Keep it up - you have studied 5 days in a row.', icon='bi-fire',
    )


def _seed_friend_and_group(demo, friend):
    friend_notebook = _create_source_notebook(
        friend, 'Intro to Chemistry',
        'Atoms are made of protons, neutrons, and electrons.',
        '## Atomic Structure\n\n- Protons are positively charged\n- Electrons are negatively charged',
    )
    for i, correct in enumerate([True, True, True, False]):
        q = Question.objects.create(
            notebook=friend_notebook, order_index=i,
            question_type=Question.QUESTION_TYPE_SHORT_ANSWER,
            question_text=f'Sample chemistry question {i + 1}',
            expected_answer='Sample answer',
        )
        Answer.objects.create(
            question=q, user=friend, user_answer='An answer',
            grade=Answer.GRADE_CORRECT if correct else Answer.GRADE_INCORRECT,
            graded_at=timezone.now(),
        )

    group = StudyGroup.objects.create(
        name='Bio Study Squad', creator=demo,
        description='Studying for the cell biology midterm together.',
    )
    group.members.add(demo, friend)


def _delete_stale_demo_accounts():
    """Delete demo-prefixed users (demo AND friend accounts) older than
    `DEMO_ACCOUNT_MAX_AGE`. Deleting the User cascades to everything seeded
    for it (notebooks, questions, answers, groups, achievements, ...)."""
    cutoff = timezone.now() - DEMO_ACCOUNT_MAX_AGE
    User.objects.filter(
        username__startswith=DEMO_USERNAME_PREFIX, date_joined__lt=cutoff,
    ).delete()


def reset_demo_account():
    """Create a brand-new, uniquely-named demo account seeded with sample data,
    and return the demo `User`.

    Called both by `manage.py seed_demo_data` and by the "Try Demo" login view.

    Why a fresh account per call rather than resetting one shared 'demo' user:
    the demo is a shared, passwordless entry point, so two judges clicking
    "Try Demo" around the same time is a normal event, not an edge case. With a
    single shared username, the second login would delete and recreate the
    account the first visitor was actively using - their notebook rows would
    vanish mid-session (or come back with new PKs). Giving every call its own
    `demo_<random>` user (plus its own `demo_friend_<random>` study buddy)
    means each visitor gets an isolated sandbox that nobody else can stomp on.

    To keep `auth_user` from growing unbounded over a multi-day event, any
    demo-prefixed account whose `date_joined` is older than
    `DEMO_ACCOUNT_MAX_AGE` is deleted first (cascading to all its seeded data).
    That cleanup runs BEFORE the new pair is created, so it can never delete
    the accounts this call is about to hand back.
    """
    _delete_stale_demo_accounts()

    suffix = secrets.token_hex(4)
    demo = User.objects.create_user(
        username=f'{DEMO_USERNAME_PREFIX}{suffix}', first_name='Demo', last_name='Student',
    )
    demo.set_unusable_password()
    demo.save()
    friend = User.objects.create_user(
        username=f'{DEMO_USERNAME_PREFIX}friend_{suffix}', first_name='Study', last_name='Buddy',
    )
    friend.set_unusable_password()
    friend.save()

    notebook = _seed_notebook_and_questions(demo)
    _seed_learning_path(notebook)
    _seed_badges_and_analytics(demo)
    _seed_friend_and_group(demo, friend)
    _seed_math_notebook(demo)

    return demo
