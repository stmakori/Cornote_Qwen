"""Tests for the gated file-serving views and the notebook sharing feature.

Before this, notebook.pdf_file.url / summary.audio_file.url were plain Django
media URLs with no access control at all - anyone with the URL could download
another user's uploaded PDF or generated audio. These tests lock down the
replacement (owner / public-with-token / shared_with) access rules, and the
public share view itself.
"""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.notebooks.models import Notebook, Question, Summary


class _MediaTestCase(TestCase):
    """Points MEDIA_ROOT at a scratch temp dir so FileResponse has a real file
    to open, and cleans it up afterwards."""

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


class NotebookPdfFileAccessTests(_MediaTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='fileowner', password='pw')
        self.other = User.objects.create_user(username='filestranger', password='pw')
        self.notebook = Notebook.objects.create(user=self.owner, title='Private Notes')
        self.notebook.pdf_file.save('test.txt', ContentFile(b'hello world'), save=True)

    def test_owner_can_access_their_own_file(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('notebooks:notebook_pdf_file', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)

    def test_stranger_cannot_access_private_notebook_file(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('notebooks:notebook_pdf_file', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_cannot_access_private_notebook_file(self):
        response = self.client.get(reverse('notebooks:notebook_pdf_file', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_can_access_public_notebook_file_with_correct_token(self):
        self.notebook.is_public = True
        self.notebook.save()
        url = reverse('notebooks:notebook_pdf_file', args=[self.notebook.pk])
        response = self.client.get(url, {'token': self.notebook.share_token})
        self.assertEqual(response.status_code, 200)

    def test_anonymous_cannot_access_public_notebook_file_with_wrong_token(self):
        self.notebook.is_public = True
        self.notebook.save()
        url = reverse('notebooks:notebook_pdf_file', args=[self.notebook.pk])
        response = self.client.get(url, {'token': 'not-the-real-token'})
        self.assertEqual(response.status_code, 404)

    def test_shared_with_user_can_access_private_file_without_token(self):
        self.notebook.shared_with.add(self.other)
        self.client.force_login(self.other)
        response = self.client.get(reverse('notebooks:notebook_pdf_file', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)


class SummaryAudioFileAccessTests(_MediaTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='audioowner', password='pw')
        self.other = User.objects.create_user(username='audiostranger', password='pw')
        self.notebook = Notebook.objects.create(user=self.owner, title='N')
        self.notebook.pdf_file.save('fake.txt', ContentFile(b'x'), save=True)
        self.summary = Summary.objects.create(notebook=self.notebook)
        self.summary.audio_file.save('test.mp3', ContentFile(b'fake-mp3-bytes'), save=True)

    def test_owner_can_access_their_audio(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('notebooks:summary_audio_file', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)

    def test_stranger_cannot_access_audio_even_if_notebook_is_public(self):
        # Audio is intentionally owner-only for now, unlike the PDF/notes.
        self.notebook.is_public = True
        self.notebook.save()
        self.client.force_login(self.other)
        response = self.client.get(reverse('notebooks:summary_audio_file', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_cannot_access_audio(self):
        response = self.client.get(reverse('notebooks:summary_audio_file', args=[self.notebook.pk]))
        self.assertIn(response.status_code, (302, 404))  # redirected to login (login_required)

    def test_404_when_no_audio_generated_yet(self):
        Summary.objects.filter(pk=self.summary.pk).update(audio_file='')
        self.client.force_login(self.owner)
        response = self.client.get(reverse('notebooks:summary_audio_file', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)


class NotebookSharingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='sharer', password='pw')
        self.client.force_login(self.owner)
        self.notebook = Notebook.objects.create(user=self.owner, title='Shareable', pdf_file='fake.txt')

    def test_toggle_on_mints_a_share_token_and_url(self):
        response = self.client.post(
            reverse('notebooks:toggle_sharing', args=[self.notebook.pk]), {'is_public': 'true'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['is_public'])
        self.assertIsNotNone(data['share_url'])

        self.notebook.refresh_from_db()
        self.assertTrue(self.notebook.is_public)
        self.assertTrue(self.notebook.share_token)
        self.assertIn(self.notebook.share_token, data['share_url'])

    def test_toggle_off_clears_public_flag(self):
        self.notebook.is_public = True
        self.notebook.save()
        response = self.client.post(
            reverse('notebooks:toggle_sharing', args=[self.notebook.pk]), {'is_public': 'false'},
        )
        data = response.json()
        self.assertFalse(data['is_public'])
        self.assertIsNone(data['share_url'])

    def test_other_user_cannot_toggle_sharing_on_someone_elses_notebook(self):
        other = User.objects.create_user(username='not_the_owner', password='pw')
        self.client.force_login(other)
        response = self.client.post(
            reverse('notebooks:toggle_sharing', args=[self.notebook.pk]), {'is_public': 'true'},
        )
        self.assertEqual(response.status_code, 404)


class SharedNotebookViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='study_sharer', password='pw')
        self.notebook = Notebook.objects.create(
            user=self.owner, title='Public Study Guide', pdf_file='fake.txt',
            notes_content='Some notes here.', is_public=True,
        )
        self.notebook.save()  # mints the share_token
        Question.objects.create(
            notebook=self.notebook, order_index=1,
            question_text='What is X?', expected_answer='X is Y.',
        )

    def test_anonymous_can_view_public_shared_notebook(self):
        response = self.client.get(reverse('notebooks:shared_notebook', args=[self.notebook.share_token]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Study Guide')
        self.assertContains(response, 'What is X?')
        self.assertContains(response, 'X is Y.')

    def test_wrong_token_returns_404(self):
        response = self.client.get(reverse('notebooks:shared_notebook', args=['bogus-token']))
        self.assertEqual(response.status_code, 404)

    def test_notebook_made_private_again_is_no_longer_shareable(self):
        token = self.notebook.share_token
        self.notebook.is_public = False
        self.notebook.save()
        response = self.client.get(reverse('notebooks:shared_notebook', args=[token]))
        self.assertEqual(response.status_code, 404)
