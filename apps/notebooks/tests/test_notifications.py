"""Tests for the streak/review-reminder notifications wired into check_achievements.

Both NotificationService.create_streak_notification and .create_review_reminder
existed but were never called from anywhere before this change. The dedup
guards added alongside them are the important behavior to lock down: without
them, polling this endpoint (it's called on every achievements-page load)
would spam a new notification every time.

Note: AchievementService.check_and_award_achievements recalculates
study_streak_days from real StudySession history on every call (via
AnalyticsService.update_user_analytics), overwriting anything hand-set on
StudyAnalytics - so these tests build actual consecutive-day sessions rather
than writing the streak count directly.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.notebooks.models import Notebook, Notification, Question, QuestionReview, StudySession


class StreakAndReminderNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='streaker', password='pw')
        self.client.force_login(self.user)
        self.notebook = Notebook.objects.create(user=self.user, title='N', pdf_file='fake.txt')

    def _check(self):
        return self.client.post(reverse('notebooks:check_achievements'))

    def _give_streak(self, days):
        """Create real StudySessions on `days` consecutive calendar days ending today,
        matching how AnalyticsService.update_user_analytics actually computes a streak."""
        now = timezone.now()
        for days_ago in range(days):
            session = StudySession.objects.create(notebook=self.notebook, ended_at=now)
            StudySession.objects.filter(pk=session.pk).update(started_at=now - timedelta(days=days_ago))

    def test_no_streak_notification_with_no_study_history(self):
        self._check()
        self.assertFalse(Notification.objects.filter(user=self.user, notification_type='streak').exists())

    def test_streak_notification_created_once_per_day(self):
        self._give_streak(3)
        self._check()
        self.assertEqual(Notification.objects.filter(user=self.user, notification_type='streak').count(), 1)

        # Calling again the same day must not create a second one.
        self._check()
        self.assertEqual(Notification.objects.filter(user=self.user, notification_type='streak').count(), 1)

    def test_streak_notification_can_fire_again_a_new_day(self):
        self._give_streak(3)
        self._check()
        notif = Notification.objects.get(user=self.user, notification_type='streak')
        # Backdate it to yesterday so today's check is allowed to create a new one.
        Notification.objects.filter(pk=notif.pk).update(created_at=timezone.now() - timedelta(days=1))

        self._check()
        self.assertEqual(Notification.objects.filter(user=self.user, notification_type='streak').count(), 2)

    def test_no_review_reminder_when_nothing_due(self):
        self._check()
        self.assertFalse(Notification.objects.filter(user=self.user, notification_type='reminder').exists())

    def test_review_reminder_created_when_reviews_due(self):
        question = Question.objects.create(notebook=self.notebook, order_index=1, question_text='Q?')
        QuestionReview.objects.create(question=question, user=self.user)  # next_review defaults to now

        self._check()
        self.assertEqual(Notification.objects.filter(user=self.user, notification_type='reminder').count(), 1)

    def test_review_reminder_does_not_duplicate_while_unread(self):
        question = Question.objects.create(notebook=self.notebook, order_index=1, question_text='Q?')
        QuestionReview.objects.create(question=question, user=self.user)

        self._check()
        self._check()
        self.assertEqual(Notification.objects.filter(user=self.user, notification_type='reminder').count(), 1)

    def test_review_reminder_can_fire_again_after_being_read(self):
        question = Question.objects.create(notebook=self.notebook, order_index=1, question_text='Q?')
        QuestionReview.objects.create(question=question, user=self.user)

        self._check()
        Notification.objects.filter(user=self.user, notification_type='reminder').update(is_read=True)
        self._check()

        self.assertEqual(Notification.objects.filter(user=self.user, notification_type='reminder').count(), 2)
