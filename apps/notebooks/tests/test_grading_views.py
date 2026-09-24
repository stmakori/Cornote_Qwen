"""Integration tests for the grading views (Grade All / exam finalize) with a
mix of structured and free-text question types.

The core claim under test: structured types (true_false, multiple_choice,
multiple_select, ordering, matching) must be graded WITHOUT ever calling the
AI - so these tests patch ai_service._chat to raise if it's called for those,
which would fail loudly if a regression routed them back through the AI path.
Only short_answer/fill_blank should reach the (mocked) AI.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import Answer, ExamSession, Notebook, Question, QuestionReview
from apps.notebooks.services import ai_service


def _unexpected_ai_call(*args, **kwargs):
    raise AssertionError(
        'ai_service._chat was called - a structured-type question should never reach the AI grader'
    )


class GradeAnswersViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='grader', password='pw')
        self.client.force_login(self.user)
        self.notebook = Notebook.objects.create(
            user=self.user,
            title='Mixed Types',
            pdf_file='fake/path.txt',
            status=Notebook.STATUS_READY,
            processing_stage=Notebook.STAGE_READY,
        )

    def _add_question(self, order_index, **fields):
        question = Question.objects.create(notebook=self.notebook, order_index=order_index, **fields)
        Answer.objects.create(question=question)
        return question

    def _set_answer(self, question, text):
        answer = question.answer
        answer.user_answer = text
        answer.save()
        return answer

    @patch.object(ai_service, '_chat', side_effect=_unexpected_ai_call)
    def test_structured_types_grade_without_any_ai_call(self, mock_chat):
        tf = self._add_question(1, question_type='true_false', expected_answer='True')
        mc = self._add_question(
            2, question_type='multiple_choice',
            choices=['Paris', 'London'], correct_choices=['Paris'], expected_answer='Paris',
        )
        ms = self._add_question(
            3, question_type='multiple_select',
            choices=['A', 'B', 'C'], correct_choices=['A', 'B'],
        )
        order = self._add_question(4, question_type='ordering', correct_order=['First', 'Second'])
        match = self._add_question(
            5, question_type='matching',
            matching_pairs=[{'left': 'X', 'right': 'Y'}],
        )

        self._set_answer(tf, 'True')
        self._set_answer(mc, 'Paris')
        self._set_answer(ms, 'A | B')
        self._set_answer(order, 'First → Second')
        self._set_answer(match, 'X => Y')

        response = self.client.post(reverse('notebooks:grade_answers', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        mock_chat.assert_not_called()

        for q in (tf, mc, ms, order, match):
            q.answer.refresh_from_db()
            self.assertEqual(q.answer.grade, Answer.GRADE_CORRECT, msg=f'{q.question_type} should be correct')

    @patch.object(ai_service, '_chat', side_effect=_unexpected_ai_call)
    def test_structured_incorrect_answer_is_graded_incorrect_without_ai(self, mock_chat):
        tf = self._add_question(1, question_type='true_false', expected_answer='True')
        self._set_answer(tf, 'False')

        response = self.client.post(reverse('notebooks:grade_answers', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        mock_chat.assert_not_called()
        tf.answer.refresh_from_db()
        self.assertEqual(tf.answer.grade, Answer.GRADE_INCORRECT)

    @patch.object(ai_service, '_chat')
    def test_short_answer_still_goes_through_ai(self, mock_chat):
        mock_chat.return_value = '{"grade": "correct", "feedback": "Nicely explained."}'
        short = self._add_question(
            1, question_type='short_answer',
            expected_answer='Because photosynthesis produces oxygen.',
            expected_keywords=['oxygen'],
        )
        self._set_answer(short, 'It produces oxygen for other organisms to breathe.')

        response = self.client.post(reverse('notebooks:grade_answers', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        mock_chat.assert_called_once()
        short.answer.refresh_from_db()
        self.assertEqual(short.answer.grade, Answer.GRADE_CORRECT)
        self.assertEqual(short.answer.feedback, 'Nicely explained.')

    def test_blank_answer_is_incorrect_without_any_grading_call(self):
        short = self._add_question(1, question_type='short_answer', expected_keywords=['x'])
        # answer.user_answer left blank
        response = self.client.post(reverse('notebooks:grade_answers', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        short.answer.refresh_from_db()
        self.assertEqual(short.answer.grade, Answer.GRADE_INCORRECT)
        self.assertIn('No answer provided', short.answer.feedback)

    @patch.object(ai_service, '_chat', side_effect=_unexpected_ai_call)
    def test_missed_structured_question_feeds_spaced_repetition_queue(self, mock_chat):
        tf = self._add_question(1, question_type='true_false', expected_answer='True')
        self._set_answer(tf, 'False')

        self.client.post(reverse('notebooks:grade_answers', args=[self.notebook.pk]))

        self.assertTrue(QuestionReview.objects.filter(question=tf, user=self.user).exists())

    @patch.object(ai_service, '_chat', side_effect=_unexpected_ai_call)
    def test_graded_results_preserve_original_question_order(self, mock_chat):
        # short_answer (AI path, but blank -> no AI call) interleaved with a
        # structured type, to prove the two grading passes don't scramble order.
        q1 = self._add_question(1, question_type='true_false', expected_answer='True')
        q2 = self._add_question(2, question_type='short_answer')  # left blank
        q3 = self._add_question(3, question_type='multiple_choice', correct_choices=['A'])
        self._set_answer(q1, 'True')
        self._set_answer(q3, 'A')

        response = self.client.post(reverse('notebooks:grade_answers', args=[self.notebook.pk]))
        graded = response.context['graded']
        self.assertEqual([q.pk for q, _ in graded], [q1.pk, q2.pk, q3.pk])


class ExamGradingViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='examtaker', password='pw')
        self.client.force_login(self.user)
        self.notebook = Notebook.objects.create(
            user=self.user,
            title='Exam Notebook',
            pdf_file='fake/path.txt',
            status=Notebook.STATUS_READY,
            processing_stage=Notebook.STAGE_READY,
        )
        self.tf = Question.objects.create(
            notebook=self.notebook, order_index=1,
            question_type='true_false', expected_answer='True',
        )
        self.short = Question.objects.create(
            notebook=self.notebook, order_index=2,
            question_type='short_answer', expected_answer='An answer', expected_keywords=['answer'],
        )
        self.exam = ExamSession.objects.create(
            notebook=self.notebook, user=self.user, time_limit_minutes=60,
            total_questions=self.notebook.questions.count(),
        )

    def _save_answer(self, question, text):
        return self.client.post(
            reverse('notebooks:save_answer', args=[question.pk]),
            {'user_answer': text, 'exam_session_id': self.exam.pk},
        )

    @patch.object(ai_service, '_chat')
    def test_exam_links_answers_and_grades_structured_without_ai(self, mock_chat):
        mock_chat.return_value = '{"grade": "correct", "feedback": "Good."}'

        self._save_answer(self.tf, 'True')
        self._save_answer(self.short, 'A correct answer')

        response = self.client.post(reverse('notebooks:end_exam', args=[self.exam.pk]))
        self.assertEqual(response.status_code, 200)

        # Structured question graded with zero AI calls, free-text question used exactly one.
        mock_chat.assert_called_once()

        self.assertEqual(self.exam.answers.count(), 2)
        self.tf.answer.refresh_from_db()
        self.short.answer.refresh_from_db()
        self.assertEqual(self.tf.answer.grade, Answer.GRADE_CORRECT)
        self.assertEqual(self.short.answer.grade, Answer.GRADE_CORRECT)

        report = response.json()
        self.assertEqual(report['correct_answers'], 2)
        self.assertEqual(report['score_percentage'], 100.0)

    def test_answer_not_linked_without_matching_exam_session_ownership(self):
        other_user = User.objects.create_user(username='other', password='pw')
        other_exam = ExamSession.objects.create(
            notebook=self.notebook, user=other_user, time_limit_minutes=60, total_questions=1,
        )
        self.client.post(
            reverse('notebooks:save_answer', args=[self.tf.pk]),
            {'user_answer': 'True', 'exam_session_id': other_exam.pk},
        )
        self.tf.answer.refresh_from_db()
        self.assertIsNone(self.tf.answer.exam_session)

    def test_skipped_question_counts_against_score_not_excluded_from_it(self):
        """A question the student never touches at all never gets an Answer
        linked to this exam_session, so the denominator must be
        total_questions (captured at exam start), not answers.count() -
        otherwise skipping a question silently inflates the score instead of
        counting it as wrong."""
        self._save_answer(self.tf, 'True')  # correct
        # self.short is left completely untouched - never saved, never linked

        response = self.client.post(reverse('notebooks:end_exam', args=[self.exam.pk]))
        report = response.json()

        self.assertEqual(self.exam.total_questions, 2)
        self.assertEqual(report['correct_answers'], 1)
        self.assertEqual(report['score_percentage'], 50.0)
