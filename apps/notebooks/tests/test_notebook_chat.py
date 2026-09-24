"""Tests for the AI tutor chat feature."""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import Notebook, NotebookChatMessage
from apps.notebooks.services import ai_service


class AnswerNotebookQuestionTests(TestCase):
    @patch.object(ai_service, '_chat')
    def test_grounds_answer_in_pdf_text_and_history(self, mock_chat):
        mock_chat.return_value = 'Mitochondria are the powerhouse of the cell.'
        answer = ai_service.answer_notebook_question(
            pdf_text='Notes about cell biology.',
            history=[{'role': 'user', 'content': 'Hi'}, {'role': 'assistant', 'content': 'Hello!'}],
            question='What do mitochondria do?',
        )
        self.assertEqual(answer, 'Mitochondria are the powerhouse of the cell.')
        sent_messages = mock_chat.call_args[0][0]
        self.assertEqual(sent_messages[0]['role'], 'system')
        self.assertIn('Notes about cell biology.', sent_messages[0]['content'])
        self.assertEqual(sent_messages[-1], {'role': 'user', 'content': 'What do mitochondria do?'})


class NotebookChatViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='chatuser', password='pw')
        self.client.force_login(self.user)
        self.notebook = Notebook.objects.create(
            user=self.user, title='Bio Notes', pdf_file='fake.txt', pdf_text='Mitochondria are organelles.',
        )

    @patch.object(ai_service, 'answer_notebook_question')
    def test_sends_message_and_stores_both_turns(self, mock_answer):
        mock_answer.return_value = 'They produce ATP.'
        response = self.client.post(
            reverse('notebooks:notebook_chat', args=[self.notebook.pk]),
            {'message': 'What do mitochondria do?'},
        )
        self.assertEqual(response.status_code, 200)
        messages = list(NotebookChatMessage.objects.filter(notebook=self.notebook).order_by('created_at'))
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, NotebookChatMessage.ROLE_USER)
        self.assertEqual(messages[0].content, 'What do mitochondria do?')
        self.assertEqual(messages[1].role, NotebookChatMessage.ROLE_ASSISTANT)
        self.assertEqual(messages[1].content, 'They produce ATP.')
        self.assertContains(response, 'They produce ATP.')

    def test_empty_message_is_rejected_without_ai_call(self):
        response = self.client.post(reverse('notebooks:notebook_chat', args=[self.notebook.pk]), {'message': '  '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(NotebookChatMessage.objects.count(), 0)
        self.assertContains(response, 'Type a question first.')

    @patch.object(ai_service, 'answer_notebook_question')
    def test_ai_failure_still_keeps_the_user_message_and_shows_error(self, mock_answer):
        mock_answer.side_effect = ValueError('boom')
        response = self.client.post(
            reverse('notebooks:notebook_chat', args=[self.notebook.pk]),
            {'message': 'Explain everything'},
        )
        self.assertEqual(response.status_code, 200)
        messages = list(NotebookChatMessage.objects.filter(notebook=self.notebook))
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].role, NotebookChatMessage.ROLE_USER)
        self.assertContains(response, 'boom')

    def test_other_user_cannot_chat_on_notebook_they_do_not_own(self):
        other = User.objects.create_user(username='not_the_owner3', password='pw')
        self.client.force_login(other)
        response = self.client.post(
            reverse('notebooks:notebook_chat', args=[self.notebook.pk]), {'message': 'Hi'},
        )
        self.assertEqual(response.status_code, 404)

    @patch.object(ai_service, 'answer_notebook_question')
    def test_chat_page_shows_prior_history(self, mock_answer):
        NotebookChatMessage.objects.create(
            notebook=self.notebook, user=self.user, role=NotebookChatMessage.ROLE_USER, content='Earlier question',
        )
        response = self.client.get(reverse('notebooks:notebook_chat_page', args=[self.notebook.pk]))
        self.assertContains(response, 'Earlier question')

    def test_throttled_second_message_shows_slow_down_error(self):
        with patch.object(ai_service, 'answer_notebook_question', return_value='ok'):
            self.client.post(reverse('notebooks:notebook_chat', args=[self.notebook.pk]), {'message': 'first'})
            response = self.client.post(reverse('notebooks:notebook_chat', args=[self.notebook.pk]), {'message': 'second'})
        self.assertContains(response, 'Slow down')
        self.assertEqual(NotebookChatMessage.objects.count(), 2)  # second message never got created
