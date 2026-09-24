"""Tests for the per-user AI-endpoint cooldown (apps.notebooks.services.throttle)
and its wiring into get_hint / reformat_notes / summary_feedback / notes_summary /
audio_summary."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import Notebook, Question
from apps.notebooks.services import ai_service, throttle


class IsThrottledUnitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='throttleme', password='pw')

    def test_first_call_is_not_throttled(self):
        self.assertFalse(throttle.is_throttled(self.user, 'k', seconds=5))

    def test_second_call_within_window_is_throttled(self):
        throttle.is_throttled(self.user, 'k', seconds=5)
        self.assertTrue(throttle.is_throttled(self.user, 'k', seconds=5))

    def test_different_keys_do_not_interfere(self):
        throttle.is_throttled(self.user, 'k1', seconds=5)
        self.assertFalse(throttle.is_throttled(self.user, 'k2', seconds=5))

    def test_different_users_do_not_interfere(self):
        other = User.objects.create_user(username='other_throttle', password='pw')
        throttle.is_throttled(self.user, 'k', seconds=5)
        self.assertFalse(throttle.is_throttled(other, 'k', seconds=5))

    def test_anonymous_user_is_never_throttled(self):
        class Anon:
            is_authenticated = False
        self.assertFalse(throttle.is_throttled(Anon(), 'k', seconds=5))
        self.assertFalse(throttle.is_throttled(Anon(), 'k', seconds=5))


class HintThrottleViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='hinter', password='pw')
        self.client.force_login(self.user)
        notebook = Notebook.objects.create(user=self.user, title='N', pdf_file='fake.txt')
        self.question = Question.objects.create(
            notebook=notebook, order_index=1, question_text='Q?', expected_answer='A',
        )

    @patch.object(ai_service, 'generate_hint', return_value='A gentle nudge.')
    def test_second_rapid_hint_request_is_throttled(self, mock_hint):
        r1 = self.client.post(reverse('notebooks:get_hint', args=[self.question.pk]))
        self.assertEqual(r1.status_code, 200)
        mock_hint.assert_called_once()

        r2 = self.client.post(reverse('notebooks:get_hint', args=[self.question.pk]))
        self.assertEqual(r2.status_code, 200)
        # Still only called once - the second request was throttled before reaching the AI.
        mock_hint.assert_called_once()
        self.assertIn(b'Slow down', r2.content)
