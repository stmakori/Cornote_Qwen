"""Tests for the accuracy leaderboard."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import Answer, Badge, Notebook, Question, StudyGroup, UserAchievement


def _make_graded_question(notebook, grade, order_index=0):
    question = Question.objects.create(notebook=notebook, question_text=f'Q{order_index}', order_index=order_index)
    return Answer.objects.create(question=question, user=notebook.user, user_answer='x', grade=grade)


class LeaderboardPageTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(username='viewer', password='pw')
        self.client.force_login(self.viewer)

    def test_users_below_minimum_answered_are_excluded(self):
        low = User.objects.create_user(username='low_activity', password='pw')
        notebook = Notebook.objects.create(user=low, title='N', pdf_file='fake.txt')
        _make_graded_question(notebook, Answer.GRADE_CORRECT, 0)
        _make_graded_question(notebook, Answer.GRADE_CORRECT, 1)  # only 2, below MIN_ANSWERED=3

        response = self.client.get(reverse('notebooks:leaderboard_page'))
        usernames = [row['user'].username for row in response.context['rows']]
        self.assertNotIn('low_activity', usernames)

    def test_ranks_by_accuracy_then_badge_count(self):
        strong = User.objects.create_user(username='strong', password='pw')
        weak = User.objects.create_user(username='weak', password='pw')

        strong_notebook = Notebook.objects.create(user=strong, title='N', pdf_file='fake.txt')
        for i in range(3):
            _make_graded_question(strong_notebook, Answer.GRADE_CORRECT, i)

        weak_notebook = Notebook.objects.create(user=weak, title='N', pdf_file='fake.txt')
        for i in range(3):
            _make_graded_question(weak_notebook, Answer.GRADE_INCORRECT, i)

        response = self.client.get(reverse('notebooks:leaderboard_page'))
        rows = response.context['rows']
        usernames_in_order = [row['user'].username for row in rows]
        self.assertLess(usernames_in_order.index('strong'), usernames_in_order.index('weak'))
        strong_row = next(r for r in rows if r['user'].username == 'strong')
        self.assertEqual(strong_row['accuracy'], 100.0)
        self.assertEqual(strong_row['rank'], 1)

    def test_partial_grades_count_as_half_credit(self):
        user = User.objects.create_user(username='partial_scorer', password='pw')
        notebook = Notebook.objects.create(user=user, title='N', pdf_file='fake.txt')
        _make_graded_question(notebook, Answer.GRADE_PARTIAL, 0)
        _make_graded_question(notebook, Answer.GRADE_PARTIAL, 1)
        _make_graded_question(notebook, Answer.GRADE_PARTIAL, 2)

        response = self.client.get(reverse('notebooks:leaderboard_page'))
        row = next(r for r in response.context['rows'] if r['user'].username == 'partial_scorer')
        self.assertEqual(row['accuracy'], 50.0)

    def test_badge_count_reflected_in_row(self):
        user = User.objects.create_user(username='badged', password='pw')
        notebook = Notebook.objects.create(user=user, title='N', pdf_file='fake.txt')
        for i in range(3):
            _make_graded_question(notebook, Answer.GRADE_CORRECT, i)
        badge = Badge.objects.create(name='Speedy', badge_type='speed_learner', description='d')
        UserAchievement.objects.create(user=user, badge=badge)

        response = self.client.get(reverse('notebooks:leaderboard_page'))
        row = next(r for r in response.context['rows'] if r['user'].username == 'badged')
        self.assertEqual(row['badge_count'], 1)

    def test_group_leaderboard_only_shows_members(self):
        member = User.objects.create_user(username='groupmate', password='pw')
        outsider = User.objects.create_user(username='outsider', password='pw')
        group = StudyGroup.objects.create(name='Bio Study Group', creator=self.viewer)
        group.members.add(self.viewer, member)

        member_notebook = Notebook.objects.create(user=member, title='N', pdf_file='fake.txt')
        for i in range(3):
            _make_graded_question(member_notebook, Answer.GRADE_CORRECT, i)
        outsider_notebook = Notebook.objects.create(user=outsider, title='N', pdf_file='fake.txt')
        for i in range(3):
            _make_graded_question(outsider_notebook, Answer.GRADE_CORRECT, i)

        response = self.client.get(reverse('notebooks:leaderboard_page'))
        group_leaderboards = response.context['group_leaderboards']
        self.assertEqual(len(group_leaderboards), 1)
        group_usernames = [row['user'].username for row in group_leaderboards[0]['rows']]
        self.assertIn('groupmate', group_usernames)
        self.assertNotIn('outsider', group_usernames)
