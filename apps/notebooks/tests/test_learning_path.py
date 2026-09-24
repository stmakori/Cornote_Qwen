"""Tests for the Learning Path feature.

Before this, Topic.objects.create() was never called anywhere outside
migrations - LearningPathService.generate_learning_path read
Topic.objects.filter(notebook=notebook), which was always empty, so a
"learning path" silently did nothing. This tests the AI-backed topic
extraction that now actually populates it, and the page that drives it.
"""
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import LearningPath, Notebook, Topic
from apps.notebooks.services import ai_service
from apps.notebooks.services.features_service import LearningPathService


class ExtractTopicsTests(TestCase):
    @patch.object(ai_service, '_chat')
    def test_parses_well_formed_response(self, mock_chat):
        mock_chat.return_value = '''{"topics": [
            {"name": "Basics", "description": "Foundational ideas", "difficulty_level": 1},
            {"name": "Advanced stuff", "description": "Builds on basics", "difficulty_level": 3}
        ]}'''
        topics = ai_service.extract_topics('some course material')
        self.assertEqual(len(topics), 2)
        self.assertEqual(topics[0]['name'], 'Basics')
        self.assertEqual(topics[1]['difficulty_level'], 3)

    @patch.object(ai_service, '_chat')
    def test_drops_malformed_entries_and_fixes_bad_difficulty(self, mock_chat):
        mock_chat.return_value = '''{"topics": [
            {"name": "Good one", "difficulty_level": 99},
            {"description": "no name, should be dropped"},
            "not even a dict"
        ]}'''
        topics = ai_service.extract_topics('material')
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]['name'], 'Good one')
        self.assertEqual(topics[0]['difficulty_level'], 2)  # invalid value normalized to medium

    @patch.object(ai_service, '_chat')
    def test_empty_ai_response_returns_empty_list(self, mock_chat):
        mock_chat.return_value = '{"topics": []}'
        self.assertEqual(ai_service.extract_topics('material'), [])


class GenerateLearningPathServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pathmaker', password='pw')
        self.notebook = Notebook.objects.create(
            user=self.user, title='N', pdf_file='fake.txt', pdf_text='Some real material about X and Y.',
        )

    @patch.object(ai_service, 'extract_topics')
    def test_creates_topics_with_linear_prerequisite_chain(self, mock_extract):
        mock_extract.return_value = [
            {'name': 'A', 'description': '', 'difficulty_level': 1},
            {'name': 'B', 'description': '', 'difficulty_level': 2},
            {'name': 'C', 'description': '', 'difficulty_level': 3},
        ]
        path = LearningPathService.generate_learning_path(self.notebook)

        topics = list(Topic.objects.filter(notebook=self.notebook).order_by('order_index'))
        self.assertEqual([t.name for t in topics], ['A', 'B', 'C'])
        self.assertEqual(path.topic_sequence, [t.pk for t in topics])
        self.assertEqual(path.current_topic_index, 0)

        # B depends on A, C depends on B - a simple linear chain.
        self.assertEqual(list(topics[1].prerequisites.all()), [topics[0]])
        self.assertEqual(list(topics[2].prerequisites.all()), [topics[1]])

    @patch.object(ai_service, 'extract_topics')
    def test_does_not_recreate_topics_on_second_call(self, mock_extract):
        mock_extract.return_value = [{'name': 'Only one', 'description': '', 'difficulty_level': 1}]
        LearningPathService.generate_learning_path(self.notebook)
        LearningPathService.generate_learning_path(self.notebook)
        mock_extract.assert_called_once()
        self.assertEqual(Topic.objects.filter(notebook=self.notebook).count(), 1)

    def test_no_source_text_produces_empty_path(self):
        notebook = Notebook.objects.create(user=self.user, title='Empty', pdf_file='fake.txt')
        path = LearningPathService.generate_learning_path(notebook)
        self.assertEqual(path.topic_sequence, [])

    @patch.object(ai_service, 'extract_topics')
    def test_mark_current_topic_complete_advances_and_records_completion(self, mock_extract):
        mock_extract.return_value = [
            {'name': 'A', 'description': '', 'difficulty_level': 1},
            {'name': 'B', 'description': '', 'difficulty_level': 2},
        ]
        path = LearningPathService.generate_learning_path(self.notebook)
        first_topic = LearningPathService.get_current_topic(path)

        LearningPathService.mark_current_topic_complete(path)
        path.refresh_from_db()

        self.assertIn(first_topic.pk, path.completed_topics)
        self.assertEqual(path.current_topic_index, 1)

    @patch.object(ai_service, 'extract_topics')
    def test_marking_last_topic_complete_does_not_advance_past_the_end(self, mock_extract):
        mock_extract.return_value = [{'name': 'Only', 'description': '', 'difficulty_level': 1}]
        path = LearningPathService.generate_learning_path(self.notebook)
        LearningPathService.mark_current_topic_complete(path)
        path.refresh_from_db()
        self.assertEqual(path.current_topic_index, 0)
        self.assertEqual(len(path.completed_topics), 1)


class LearningPathPageTests(TestCase):
    def setUp(self):
        cache.clear()  # throttle.is_throttled's cache entries otherwise bleed across test methods
        self.user = User.objects.create_user(username='pathviewer', password='pw')
        self.client.force_login(self.user)
        self.notebook = Notebook.objects.create(
            user=self.user, title='N', pdf_file='fake.txt', pdf_text='Real content about topics.',
        )

    def test_shows_generate_button_when_no_path_exists(self):
        response = self.client.get(reverse('notebooks:learning_path_page', args=[self.notebook.pk]))
        self.assertContains(response, 'Generate Learning Path')

    @patch.object(ai_service, 'extract_topics')
    def test_generating_creates_topics_and_redirects(self, mock_extract):
        mock_extract.return_value = [{'name': 'Topic One', 'description': 'd', 'difficulty_level': 1}]
        response = self.client.post(
            reverse('notebooks:learning_path_page', args=[self.notebook.pk]), {'action': 'generate'},
        )
        self.assertRedirects(response, reverse('notebooks:learning_path_page', args=[self.notebook.pk]))
        self.assertTrue(Topic.objects.filter(notebook=self.notebook, name='Topic One').exists())

    @patch.object(ai_service, 'extract_topics')
    def test_page_shows_topics_after_generation(self, mock_extract):
        mock_extract.return_value = [{'name': 'Photosynthesis', 'description': '', 'difficulty_level': 1}]
        self.client.post(reverse('notebooks:learning_path_page', args=[self.notebook.pk]), {'action': 'generate'})
        response = self.client.get(reverse('notebooks:learning_path_page', args=[self.notebook.pk]))
        self.assertContains(response, 'Photosynthesis')

    def test_other_user_cannot_access_notebooks_learning_path(self):
        other = User.objects.create_user(username='not_the_owner2', password='pw')
        self.client.force_login(other)
        response = self.client.get(reverse('notebooks:learning_path_page', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)

    @patch.object(ai_service, 'extract_topics')
    def test_mark_complete_action_updates_progress(self, mock_extract):
        mock_extract.return_value = [
            {'name': 'A', 'description': '', 'difficulty_level': 1},
            {'name': 'B', 'description': '', 'difficulty_level': 2},
        ]
        self.client.post(reverse('notebooks:learning_path_page', args=[self.notebook.pk]), {'action': 'generate'})
        self.client.post(reverse('notebooks:learning_path_page', args=[self.notebook.pk]), {'action': 'mark_complete'})

        path = LearningPath.objects.get(notebook=self.notebook)
        self.assertEqual(path.current_topic_index, 1)
        self.assertEqual(len(path.completed_topics), 1)
