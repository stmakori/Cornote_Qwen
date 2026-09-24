"""Tests for ai_service.grade_answer_batch: concurrent AI grading of free-text answers."""
import time
from unittest.mock import patch

from django.test import TestCase

from apps.notebooks.services import ai_service


class GradeAnswerBatchTests(TestCase):
    def test_empty_input_returns_empty_list(self):
        self.assertEqual(ai_service.grade_answer_batch([]), [])

    @patch.object(ai_service, '_chat')
    def test_results_preserve_input_order(self, mock_chat):
        # Each call's response encodes which item it was for, so we can prove
        # the batch result list lines up with the input list even though the
        # underlying calls run concurrently (and could finish in any order).
        def fake_chat(messages, **kwargs):
            prompt = messages[0]['content']
            for i in range(5):
                if f'Q{i}' in prompt:
                    return f'{{"grade": "correct", "feedback": "answer {i}"}}'
            raise AssertionError('unexpected prompt')

        mock_chat.side_effect = fake_chat
        items = [
            {
                'question_text': f'Q{i}',
                'expected_answer': 'x',
                'expected_keywords': [],
                'user_answer': 'x',
            }
            for i in range(5)
        ]
        results = ai_service.grade_answer_batch(items)
        self.assertEqual(len(results), 5)
        for i, result in enumerate(results):
            self.assertTrue(result['ok'])
            self.assertEqual(result['feedback'], f'answer {i}')

    @patch.object(ai_service, '_chat')
    def test_runs_concurrently_not_sequentially(self, mock_chat):
        # Each fake call sleeps 0.2s; if grade_answer_batch ran them one at a
        # time, 6 items would take >= 1.2s. Concurrently, it should take well
        # under that - proving this is actually a speedup, not just an API shape.
        def slow_chat(messages, **kwargs):
            time.sleep(0.2)
            return '{"grade": "correct", "feedback": "ok"}'

        mock_chat.side_effect = slow_chat
        items = [
            {'question_text': f'Q{i}', 'expected_answer': 'x', 'expected_keywords': [], 'user_answer': 'x'}
            for i in range(6)
        ]
        start = time.monotonic()
        results = ai_service.grade_answer_batch(items, max_workers=6)
        elapsed = time.monotonic() - start
        self.assertEqual(len(results), 6)
        self.assertLess(elapsed, 1.0, 'batch grading did not appear to run concurrently')

    @patch.object(ai_service, '_chat')
    def test_per_item_failure_does_not_break_the_batch(self, mock_chat):
        def flaky_chat(messages, **kwargs):
            prompt = messages[0]['content']
            if 'Q1' in prompt:
                raise RuntimeError('simulated network error')
            return '{"grade": "correct", "feedback": "fine"}'

        mock_chat.side_effect = flaky_chat
        items = [
            {'question_text': 'Q0', 'expected_answer': 'x', 'expected_keywords': [], 'user_answer': 'x'},
            {'question_text': 'Q1', 'expected_answer': 'x', 'expected_keywords': [], 'user_answer': 'x'},
            {'question_text': 'Q2', 'expected_answer': 'x', 'expected_keywords': [], 'user_answer': 'x'},
        ]
        results = ai_service.grade_answer_batch(items)
        self.assertTrue(results[0]['ok'])
        self.assertFalse(results[1]['ok'])
        self.assertIn('error', results[1])
        self.assertTrue(results[2]['ok'])
