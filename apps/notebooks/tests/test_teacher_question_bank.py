"""Tests for the teacher question bank: hand-authoring a Question without
uploading a PDF first. Previously the assignment question-picker could only
offer questions AI-generated from a notebook the teacher personally uploaded.
"""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.notebooks.models import Assignment, Notebook, Question, StudentClass
from apps.notebooks.services import question_bank


class _MediaTestCase(TestCase):
    """The bank notebook saves a placeholder PDF, so point MEDIA_ROOT at a
    scratch dir and clean it up afterwards."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_root = tempfile.mkdtemp(prefix='cornote_test_media_')
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()


class TeacherQuestionBankTests(_MediaTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='bank_teacher', password='pw')
        self.cls = StudentClass.objects.create(teacher=self.teacher, name='Bio 101', subject='Biology')
        self.url = reverse('notebooks:create_teacher_question')
        self.detail_url = reverse('notebooks:teacher_class_detail', args=[self.cls.id])
        self.client.force_login(self.teacher)

    # ── happy paths ──────────────────────────────────────────────

    def test_short_answer_question_lands_in_bank_and_picker(self):
        self.assertEqual(Question.objects.filter(notebook__user=self.teacher).count(), 0)

        response = self.client.post(self.url, {
            'class_id': self.cls.id,
            'question_type': 'short_answer',
            'question_text': 'What organelle produces ATP?',
            'expected_answer': 'Mitochondria',
            'expected_keywords': 'mitochondria, ATP , respiration',
        })
        self.assertRedirects(response, self.detail_url)

        question = Question.objects.get(notebook__user=self.teacher)
        self.assertEqual(question.question_type, 'short_answer')
        self.assertEqual(question.expected_answer, 'Mitochondria')
        self.assertEqual(question.expected_keywords, ['mitochondria', 'ATP', 'respiration'])
        self.assertFalse(question.is_math)
        self.assertEqual(question.notebook.title, question_bank.BANK_TITLE)
        self.assertEqual(question.notebook.status, Notebook.STATUS_READY)
        self.assertTrue(question.notebook.pdf_file.name)  # placeholder file was saved

        # It is immediately offered in the assignment question-picker.
        page = self.client.get(self.detail_url)
        self.assertContains(page, 'What organelle produces ATP?')
        self.assertContains(page, f'value="{question.pk}"')

    def test_multiple_choice_question_stores_choices_and_correct_one(self):
        response = self.client.post(self.url, {
            'class_id': self.cls.id,
            'question_type': 'multiple_choice',
            'question_text': 'Which organelle builds proteins?',
            'choices': 'Mitochondria\nRibosome\nNucleus',
            'correct_choice': '2',
        })
        self.assertRedirects(response, self.detail_url)

        question = Question.objects.get(notebook__user=self.teacher)
        self.assertEqual(question.question_type, 'multiple_choice')
        self.assertEqual(question.choices, ['Mitochondria', 'Ribosome', 'Nucleus'])
        self.assertEqual(question.correct_choices, ['Ribosome'])
        self.assertEqual(question.expected_answer, 'Ribosome')

    def test_true_false_and_math_questions(self):
        self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'true_false',
            'question_text': 'Mitosis produces two identical cells.', 'expected_answer': 'true',
        })
        self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'short_answer',
            'question_text': 'Simplify $x + x$.', 'expected_answer': '2x', 'is_math': 'on',
        })
        tf = Question.objects.get(question_type='true_false', notebook__user=self.teacher)
        self.assertEqual(tf.expected_answer, 'True')  # normalised for the exact-match grader
        math_q = Question.objects.get(is_math=True, notebook__user=self.teacher)
        self.assertEqual(math_q.expected_answer, '2x')

    def test_bank_notebook_is_reused_and_order_index_increments(self):
        for i in range(3):
            self.client.post(self.url, {
                'class_id': self.cls.id, 'question_type': 'short_answer',
                'question_text': f'Q{i}', 'expected_answer': f'A{i}',
            })
        banks = Notebook.objects.filter(user=self.teacher, title=question_bank.BANK_TITLE)
        self.assertEqual(banks.count(), 1)
        self.assertEqual(
            list(banks.first().questions.values_list('order_index', flat=True)), [1, 2, 3],
        )

    def test_bank_question_is_assignable(self):
        self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'short_answer',
            'question_text': 'Define osmosis.', 'expected_answer': 'Diffusion of water across a membrane.',
        })
        question = Question.objects.get(notebook__user=self.teacher)

        self.client.post(self.detail_url, {
            'action': 'create_assignment', 'title': 'HW from bank',
            'due_date': '2026-12-01T00:00', 'question_ids': [question.pk],
        })
        assignment = Assignment.objects.get(title='HW from bank')
        self.assertEqual(list(assignment.questions.all()), [question])

    def test_class_detail_shows_new_question_button_for_teacher_only(self):
        self.assertContains(self.client.get(self.detail_url), 'New Question')
        student = User.objects.create_user(username='bank_student', password='pw')
        self.cls.students.add(student)
        self.client.force_login(student)
        self.assertNotContains(self.client.get(self.detail_url), 'New Question')

    # ── validation ───────────────────────────────────────────────

    def test_missing_question_text_flashes_error_and_creates_nothing(self):
        response = self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'short_answer',
            'question_text': '   ', 'expected_answer': 'x',
        }, follow=True)
        self.assertEqual(Question.objects.filter(notebook__user=self.teacher).count(), 0)
        self.assertContains(response, 'Question text is required.')

    def test_short_answer_without_expected_answer_is_rejected(self):
        response = self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'short_answer', 'question_text': 'Why?',
        }, follow=True)
        self.assertEqual(Question.objects.count(), 0)
        self.assertContains(response, 'expected answer is required')

    def test_multiple_choice_needs_two_choices_and_a_valid_correct_index(self):
        self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'multiple_choice',
            'question_text': 'Pick one', 'choices': 'Only one', 'correct_choice': '1',
        })
        self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'multiple_choice',
            'question_text': 'Pick one', 'choices': 'A\nB', 'correct_choice': '5',
        })
        self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'multiple_choice',
            'question_text': 'Pick one', 'choices': 'A\nB', 'correct_choice': '',
        })
        self.assertEqual(Question.objects.count(), 0)
        # No bank notebook is created for a failed submission either.
        self.assertFalse(Notebook.objects.filter(user=self.teacher).exists())

    def test_unsupported_question_type_is_rejected(self):
        self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'matching',
            'question_text': 'Match these', 'expected_answer': 'x',
        })
        self.assertEqual(Question.objects.count(), 0)

    # ── access control ───────────────────────────────────────────

    def test_user_without_a_class_gets_403(self):
        nobody = User.objects.create_user(username='no_class', password='pw')
        self.client.force_login(nobody)
        response = self.client.post(self.url, {
            'question_type': 'short_answer', 'question_text': 'Injected?', 'expected_answer': 'x',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Question.objects.count(), 0)

    def test_enrolled_student_gets_403(self):
        student = User.objects.create_user(username='enrolled', password='pw')
        self.cls.students.add(student)
        self.client.force_login(student)
        response = self.client.post(self.url, {
            'class_id': self.cls.id, 'question_type': 'short_answer',
            'question_text': 'Injected?', 'expected_answer': 'x',
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Question.objects.count(), 0)

    def test_anonymous_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(self.url, {'question_text': 'x'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_redirects_to_dashboard_when_class_id_is_not_yours(self):
        other = User.objects.create_user(username='other_teacher', password='pw')
        other_cls = StudentClass.objects.create(teacher=other, name='Not mine', subject='x')
        response = self.client.post(self.url, {
            'class_id': other_cls.id, 'question_type': 'short_answer',
            'question_text': 'Q', 'expected_answer': 'A',
        })
        self.assertRedirects(response, reverse('notebooks:teacher_dashboard_page'))
        # The question still lands in *my* bank, never in the other teacher's.
        self.assertEqual(Question.objects.get().notebook.user, self.teacher)
