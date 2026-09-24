"""Tests for the seeded demo account (used by the management command and
the 'Try Demo' login button).

Each call to `reset_demo_account()` creates a brand-new, uniquely-named
`demo_<hex>` user (plus a `demo_friend_<hex>` study buddy), so concurrent
visitors never share or reset each other's sandbox. Stale demo accounts
(older than an hour) are cleaned up on the next call.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.notebooks.models import (
    Answer, LearningPath, Notebook, Question, StudyAnalytics, StudyGroup, UserAchievement,
)
from apps.notebooks.services.demo_data import DEMO_USERNAME_PREFIX, reset_demo_account


def _demo_users():
    """All demo (non-friend) accounts currently in the DB."""
    return User.objects.filter(username__startswith=DEMO_USERNAME_PREFIX).exclude(username__contains='friend')


class ResetDemoAccountTests(TestCase):
    def test_creates_demo_user_with_unusable_password(self):
        demo = reset_demo_account()
        self.assertTrue(demo.username.startswith(DEMO_USERNAME_PREFIX))
        self.assertNotIn('friend', demo.username)
        self.assertFalse(demo.has_usable_password())

    def test_friend_account_also_uses_demo_prefix_and_unusable_password(self):
        demo = reset_demo_account()
        group = StudyGroup.objects.get(creator=demo)
        friend = group.members.exclude(pk=demo.pk).get()
        self.assertTrue(friend.username.startswith(DEMO_USERNAME_PREFIX))
        self.assertIn('friend', friend.username)
        self.assertFalse(friend.has_usable_password())

    def test_creates_notebook_with_all_seven_question_types(self):
        demo = reset_demo_account()
        notebook = Notebook.objects.get(user=demo, title='Cell Biology Basics')
        types = set(notebook.questions.values_list('question_type', flat=True))
        self.assertEqual(types, {
            'short_answer', 'multiple_choice', 'true_false',
            'fill_blank', 'multiple_select', 'matching', 'ordering',
        })

    def test_structured_answers_are_graded_via_real_grading_logic(self):
        demo = reset_demo_account()
        notebook = Notebook.objects.get(user=demo, title='Cell Biology Basics')
        mc_question = notebook.questions.get(question_type=Question.QUESTION_TYPE_MULTIPLE_CHOICE)
        self.assertEqual(mc_question.answer.grade, Answer.GRADE_CORRECT)
        tf_question = notebook.questions.get(question_type=Question.QUESTION_TYPE_TRUE_FALSE)
        self.assertEqual(tf_question.answer.grade, Answer.GRADE_INCORRECT)

    def test_one_question_left_ungraded_to_show_that_state(self):
        demo = reset_demo_account()
        notebook = Notebook.objects.get(user=demo, title='Cell Biology Basics')
        select_question = notebook.questions.get(question_type=Question.QUESTION_TYPE_MULTIPLE_SELECT)
        self.assertEqual(select_question.answer.grade, Answer.GRADE_UNGRADED)

    def test_seeds_learning_path_with_some_progress(self):
        demo = reset_demo_account()
        notebook = Notebook.objects.get(user=demo, title='Cell Biology Basics')
        path = LearningPath.objects.get(notebook=notebook)
        self.assertEqual(len(path.completed_topics), 2)
        self.assertEqual(path.current_topic_index, 2)

    def test_seeds_math_notebook_with_symbolic_grading(self):
        demo = reset_demo_account()
        notebook = Notebook.objects.get(user=demo, title='Algebra Basics')
        questions = list(notebook.questions.order_by('order_index'))
        self.assertTrue(all(q.is_math for q in questions))
        self.assertEqual(questions[0].answer.grade, Answer.GRADE_CORRECT)  # 2*x+2 == 2x+2
        self.assertEqual(questions[1].answer.grade, Answer.GRADE_INCORRECT)  # 5 != 3

    def test_seeds_badges_and_analytics(self):
        demo = reset_demo_account()
        self.assertEqual(UserAchievement.objects.filter(user=demo).count(), 2)
        analytics = StudyAnalytics.objects.get(user=demo)
        self.assertGreater(analytics.overall_accuracy, 0)

    def test_seeds_friend_and_shared_study_group(self):
        demo = reset_demo_account()
        group = StudyGroup.objects.get(creator=demo)
        self.assertEqual(group.members.count(), 2)
        self.assertIn(demo, group.members.all())
        friend = group.members.exclude(pk=demo.pk).get()
        self.assertNotEqual(friend.pk, demo.pk)

    def test_calling_twice_creates_two_independent_accounts(self):
        first = reset_demo_account()
        second = reset_demo_account()

        self.assertNotEqual(first.pk, second.pk)
        self.assertNotEqual(first.username, second.username)
        self.assertEqual(_demo_users().count(), 2)
        # Each account has its own full set of seeded notebooks.
        for demo in (first, second):
            self.assertEqual(Notebook.objects.filter(user=demo).count(), 2)
            self.assertTrue(Notebook.objects.filter(user=demo, title='Cell Biology Basics').exists())
        # ...and its own friend + study group, not a shared one.
        first_friend = StudyGroup.objects.get(creator=first).members.exclude(pk=first.pk).get()
        second_friend = StudyGroup.objects.get(creator=second).members.exclude(pk=second.pk).get()
        self.assertNotEqual(first_friend.pk, second_friend.pk)

    def test_stale_demo_accounts_are_cleaned_up_on_next_call(self):
        old_demo = reset_demo_account()
        old_friend = StudyGroup.objects.get(creator=old_demo).members.exclude(pk=old_demo.pk).get()
        old_notebook_pks = list(Notebook.objects.filter(user__in=[old_demo, old_friend]).values_list('pk', flat=True))
        self.assertTrue(old_notebook_pks)

        User.objects.filter(username__startswith=DEMO_USERNAME_PREFIX).update(
            date_joined=timezone.now() - timedelta(hours=2),
        )

        fresh_demo = reset_demo_account()

        self.assertFalse(User.objects.filter(pk=old_demo.pk).exists())
        self.assertFalse(User.objects.filter(pk=old_friend.pk).exists())
        self.assertFalse(Notebook.objects.filter(pk__in=old_notebook_pks).exists())
        self.assertTrue(User.objects.filter(pk=fresh_demo.pk).exists())
        self.assertEqual(_demo_users().count(), 1)

    def test_recent_demo_accounts_are_not_cleaned_up(self):
        recent = reset_demo_account()
        reset_demo_account()
        self.assertTrue(User.objects.filter(pk=recent.pk).exists())
        self.assertEqual(_demo_users().count(), 2)

    def test_pdf_file_is_a_real_readable_file(self):
        demo = reset_demo_account()
        notebook = Notebook.objects.get(user=demo, title='Cell Biology Basics')
        content = notebook.pdf_file.read()
        self.assertTrue(content.startswith(b'%PDF'))


class DemoLoginViewTests(TestCase):
    def test_get_is_not_allowed(self):
        response = self.client.get(reverse('users:demo_login'))
        self.assertEqual(response.status_code, 405)

    def test_post_logs_in_as_demo_and_redirects_to_dashboard(self):
        response = self.client.post(reverse('users:demo_login'))
        self.assertRedirects(response, reverse('notebooks:dashboard'))
        # Fresh test DB + one login = exactly one demo user (plus one friend).
        demo = User.objects.exclude(username__contains='friend').get(username__startswith='demo_')
        self.assertEqual(self.client.session['_auth_user_id'], str(demo.pk))

    def test_second_login_creates_independent_account_first_is_untouched(self):
        self.client.post(reverse('users:demo_login'))
        first_demo = User.objects.exclude(username__contains='friend').get(username__startswith='demo_')
        first_notebook = Notebook.objects.get(user=first_demo, title='Cell Biology Basics')
        first_notebook.title = 'Something a visitor changed'
        first_notebook.save()

        # A second visitor clicks "Try Demo" while the first is still mid-session.
        self.client.post(reverse('users:demo_login'))

        # (a) A genuinely different demo user now exists and is the one logged in.
        second_demo = (
            User.objects.exclude(username__contains='friend')
            .filter(username__startswith='demo_')
            .exclude(pk=first_demo.pk)
            .get()
        )
        self.assertNotEqual(second_demo.pk, first_demo.pk)
        self.assertEqual(self.client.session['_auth_user_id'], str(second_demo.pk))

        # (b) The first visitor's account and edits are completely untouched.
        self.assertTrue(User.objects.filter(pk=first_demo.pk).exists())
        first_notebook.refresh_from_db()
        self.assertEqual(first_notebook.title, 'Something a visitor changed')
        self.assertEqual(first_notebook.user_id, first_demo.pk)
        self.assertFalse(Notebook.objects.filter(user=first_demo, title='Cell Biology Basics').exists())

        # (c) The second visitor gets their own fresh seeded notebook.
        self.assertTrue(Notebook.objects.filter(user=second_demo, title='Cell Biology Basics').exists())
