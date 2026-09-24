"""Tests for the teacher/assignment flow: previously a teacher could create an
Assignment (with no way to attach questions to it) but there was no
student-facing view to complete one, and ClassStatistics was modeled/registered
in admin but never computed. This also proves the core reason a new
AssignmentSubmission model was needed: Answer is a OneToOneField(Question) - one
answer per question, globally - so two students answering the same assigned
question could never have both worked with the old model.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.notebooks.models import (
    Assignment, AssignmentSubmission, ClassStatistics, Notebook, Question, StudentClass,
)
from apps.notebooks.services import ai_service


def _unexpected_ai_call(*args, **kwargs):
    raise AssertionError('ai_service._chat was called for a structured-type question')


class AssignmentCreationTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='teacher1', password='pw')
        self.client.force_login(self.teacher)
        self.cls = StudentClass.objects.create(teacher=self.teacher, name='Bio 101', subject='Biology')
        notebook = Notebook.objects.create(user=self.teacher, title='Teacher Notebook', pdf_file='fake.txt')
        self.q1 = Question.objects.create(notebook=notebook, order_index=1, question_text='Q1?', expected_answer='A1')
        self.q2 = Question.objects.create(notebook=notebook, order_index=2, question_text='Q2?', expected_answer='A2')

    def test_create_assignment_attaches_selected_questions(self):
        response = self.client.post(reverse('notebooks:teacher_class_detail', args=[self.cls.id]), {
            'action': 'create_assignment',
            'title': 'Homework 1',
            'description': 'Read chapter 1',
            'due_date': '2026-12-01T00:00',
            'question_ids': [self.q1.pk, self.q2.pk],
        })
        self.assertEqual(response.status_code, 302)
        assignment = Assignment.objects.get(title='Homework 1')
        self.assertEqual(set(assignment.questions.values_list('pk', flat=True)), {self.q1.pk, self.q2.pk})

    def test_cannot_attach_another_teachers_question(self):
        other_teacher = User.objects.create_user(username='teacher2', password='pw')
        other_notebook = Notebook.objects.create(user=other_teacher, title='Not yours', pdf_file='fake.txt')
        foreign_question = Question.objects.create(notebook=other_notebook, order_index=1, question_text='Foreign?')

        self.client.post(reverse('notebooks:teacher_class_detail', args=[self.cls.id]), {
            'action': 'create_assignment',
            'title': 'Sneaky',
            'due_date': '2026-12-01T00:00',
            'question_ids': [foreign_question.pk],
        })
        assignment = Assignment.objects.get(title='Sneaky')
        self.assertEqual(assignment.questions.count(), 0)

    def test_student_cannot_create_assignment(self):
        student = User.objects.create_user(username='sneaky_student', password='pw')
        self.cls.students.add(student)
        self.client.force_login(student)
        response = self.client.post(reverse('notebooks:teacher_class_detail', args=[self.cls.id]), {
            'action': 'create_assignment', 'title': 'Should not exist', 'due_date': '2026-12-01T00:00',
        })
        self.assertFalse(Assignment.objects.filter(title='Should not exist').exists())


class ClassAccessTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='teacher3', password='pw')
        self.student = User.objects.create_user(username='enrolled_student', password='pw')
        self.stranger = User.objects.create_user(username='not_in_class', password='pw')
        self.cls = StudentClass.objects.create(teacher=self.teacher, name='Chem', subject='Chemistry')
        self.cls.students.add(self.student)

    def test_teacher_can_view_class(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('notebooks:teacher_class_detail', args=[self.cls.id]))
        self.assertEqual(response.status_code, 200)

    def test_assignment_count_renders_correctly_in_header(self):
        # Regression: `assignments` is built as a plain list (so per-student
        # progress can be annotated onto each item), and `{{ assignments.count }}`
        # in a template silently renders empty for a list (list.count needs an
        # argument, unlike a QuerySet) rather than erroring - easy to miss without
        # actually checking rendered content.
        Assignment.objects.create(
            student_class=self.cls, created_by=self.teacher, title='Some HW',
            due_date=timezone.now() + timezone.timedelta(days=1),
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('notebooks:teacher_class_detail', args=[self.cls.id]))
        self.assertContains(response, 'Assignments (1)')

    def test_enrolled_student_can_view_class(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('notebooks:teacher_class_detail', args=[self.cls.id]))
        self.assertEqual(response.status_code, 200)

    def test_stranger_cannot_view_class(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('notebooks:teacher_class_detail', args=[self.cls.id]))
        self.assertEqual(response.status_code, 404)

    def test_joining_lands_on_class_detail_not_a_dead_end(self):
        self.client.force_login(self.stranger)
        response = self.client.post(reverse('notebooks:join_class'), {'invite_code': self.cls.invite_code})
        self.assertRedirects(response, reverse('notebooks:teacher_class_detail', args=[self.cls.id]))

    def test_enrolled_class_shows_on_dashboard(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('notebooks:teacher_dashboard_page'))
        self.assertContains(response, 'Chem')


class TakeAssignmentTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='teacher4', password='pw')
        self.student = User.objects.create_user(username='taker', password='pw')
        self.stranger = User.objects.create_user(username='not_enrolled', password='pw')
        self.cls = StudentClass.objects.create(teacher=self.teacher, name='Physics', subject='Physics')
        self.cls.students.add(self.student)

        notebook = Notebook.objects.create(user=self.teacher, title='Physics Notebook', pdf_file='fake.txt')
        self.tf_question = Question.objects.create(
            notebook=notebook, order_index=1, question_type='true_false',
            question_text='Is F=ma?', expected_answer='True',
        )
        self.short_question = Question.objects.create(
            notebook=notebook, order_index=2, question_type='short_answer',
            question_text='Explain inertia.', expected_answer='Objects resist changes in motion.',
            expected_keywords=['resist', 'motion'],
        )
        self.assignment = Assignment.objects.create(
            student_class=self.cls, created_by=self.teacher, title='HW1',
            description='', due_date=timezone.now() + timezone.timedelta(days=7),
        )
        self.assignment.questions.set([self.tf_question, self.short_question])

    def test_non_enrolled_user_cannot_open_assignment(self):
        self.client.force_login(self.stranger)
        response = self.client.get(reverse('notebooks:take_assignment', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 404)

    def test_opening_assignment_creates_blank_submissions(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('notebooks:take_assignment', args=[self.assignment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            AssignmentSubmission.objects.filter(assignment=self.assignment, student=self.student).count(), 2,
        )

    @patch.object(ai_service, '_chat', side_effect=_unexpected_ai_call)
    def test_structured_question_graded_without_ai(self, mock_chat):
        self.client.force_login(self.student)
        self.client.post(
            reverse('notebooks:save_assignment_answer', args=[self.assignment.pk, self.tf_question.pk]),
            {'user_answer': 'True'},
        )
        # Leave short_question blank so no AI call is needed at all here.
        self.client.post(reverse('notebooks:submit_assignment', args=[self.assignment.pk]))

        submission = AssignmentSubmission.objects.get(
            assignment=self.assignment, student=self.student, question=self.tf_question,
        )
        self.assertEqual(submission.grade, 'correct')
        mock_chat.assert_not_called()

    @patch.object(ai_service, '_chat')
    def test_free_text_question_goes_through_ai(self, mock_chat):
        mock_chat.return_value = '{"grade": "correct", "feedback": "Well explained."}'
        self.client.force_login(self.student)
        self.client.post(
            reverse('notebooks:save_assignment_answer', args=[self.assignment.pk, self.short_question.pk]),
            {'user_answer': 'Objects resist changes to their motion.'},
        )
        self.client.post(reverse('notebooks:submit_assignment', args=[self.assignment.pk]))

        submission = AssignmentSubmission.objects.get(
            assignment=self.assignment, student=self.student, question=self.short_question,
        )
        self.assertEqual(submission.grade, 'correct')
        mock_chat.assert_called_once()

    def test_two_students_answering_the_same_question_dont_collide(self):
        student2 = User.objects.create_user(username='taker2', password='pw')
        self.cls.students.add(student2)

        self.client.force_login(self.student)
        self.client.post(
            reverse('notebooks:save_assignment_answer', args=[self.assignment.pk, self.tf_question.pk]),
            {'user_answer': 'True'},
        )
        self.client.force_login(student2)
        self.client.post(
            reverse('notebooks:save_assignment_answer', args=[self.assignment.pk, self.tf_question.pk]),
            {'user_answer': 'False'},
        )

        sub1 = AssignmentSubmission.objects.get(assignment=self.assignment, student=self.student, question=self.tf_question)
        sub2 = AssignmentSubmission.objects.get(assignment=self.assignment, student=student2, question=self.tf_question)
        self.assertEqual(sub1.user_answer, 'True')
        self.assertEqual(sub2.user_answer, 'False')

    def test_cannot_save_answer_to_unassigned_question(self):
        other_notebook = Notebook.objects.create(user=self.teacher, title='Other', pdf_file='fake.txt')
        unassigned_question = Question.objects.create(notebook=other_notebook, order_index=1, question_text='Not in this assignment')
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('notebooks:save_assignment_answer', args=[self.assignment.pk, unassigned_question.pk]),
            {'user_answer': 'x'},
        )
        self.assertEqual(response.status_code, 404)


class ClassStatisticsTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(username='teacher5', password='pw')
        self.student = User.objects.create_user(username='stats_student', password='pw')
        self.cls = StudentClass.objects.create(teacher=self.teacher, name='Stats Class', subject='Math')
        self.cls.students.add(self.student)
        notebook = Notebook.objects.create(user=self.teacher, title='N', pdf_file='fake.txt')
        self.q_easy = Question.objects.create(
            notebook=notebook, order_index=1, question_type='true_false',
            question_text='Easy one', expected_answer='True',
        )
        self.q_hard = Question.objects.create(
            notebook=notebook, order_index=2, question_type='true_false',
            question_text='Hard one', expected_answer='True',
        )
        self.assignment = Assignment.objects.create(
            student_class=self.cls, created_by=self.teacher, title='Quiz',
            due_date=timezone.now() + timezone.timedelta(days=1),
        )
        self.assignment.questions.set([self.q_easy, self.q_hard])

    def test_statistics_computed_after_submission(self):
        self.client.force_login(self.student)
        self.client.get(reverse('notebooks:take_assignment', args=[self.assignment.pk]))  # creates blank submissions
        self.client.post(
            reverse('notebooks:save_assignment_answer', args=[self.assignment.pk, self.q_easy.pk]),
            {'user_answer': 'True'},  # correct
        )
        self.client.post(
            reverse('notebooks:save_assignment_answer', args=[self.assignment.pk, self.q_hard.pk]),
            {'user_answer': 'False'},  # incorrect
        )
        self.client.post(reverse('notebooks:submit_assignment', args=[self.assignment.pk]))

        stats = ClassStatistics.objects.get(student_class=self.cls)
        self.assertEqual(stats.total_students, 1)
        self.assertEqual(stats.average_accuracy, 50.0)
        self.assertIn('Hard one', stats.most_difficult_topics)
