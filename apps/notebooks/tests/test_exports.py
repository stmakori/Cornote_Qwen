"""Smoke tests for the PDF (reportlab) and Anki (genanki) export endpoints -
neither had been exercised anywhere in the test suite before this."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import Answer, Notebook, Question


class ExportPDFTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='exporter', password='pw')
        self.client.force_login(self.user)
        self.notebook = Notebook.objects.create(
            user=self.user, title='Export Me', pdf_file='fake.txt',
            status=Notebook.STATUS_READY, processing_stage=Notebook.STAGE_READY,
        )

    def test_export_pdf_smoke(self):
        q = Question.objects.create(
            notebook=self.notebook, order_index=1,
            question_text='What is photosynthesis?', expected_answer='A process.',
        )
        Answer.objects.create(question=q, user_answer='It makes food.', grade='correct')

        response = self.client.get(reverse('notebooks:export_pdf', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_export_pdf_rejects_special_xml_characters(self):
        # reportlab's Paragraph interprets a subset of markup (&, <, >) as XML -
        # unescaped question/answer text containing these can break PDF generation.
        q = Question.objects.create(
            notebook=self.notebook, order_index=1,
            question_text='Is 5 < 10 & is AT&T a company?',
            expected_answer='Yes, 5 < 10 and AT&T is a company.',
        )
        Answer.objects.create(question=q, user_answer='Yes < that & more', grade='correct', feedback='A & B')

        response = self.client.get(reverse('notebooks:export_pdf', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_export_pdf_not_ready_notebook_rejected(self):
        self.notebook.status = Notebook.STATUS_PROCESSING
        self.notebook.save(update_fields=['status'])
        response = self.client.get(reverse('notebooks:export_pdf', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 400)

    def test_export_pdf_requires_ownership(self):
        other = User.objects.create_user(username='not_owner', password='pw')
        self.client.force_login(other)
        response = self.client.get(reverse('notebooks:export_pdf', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)


class ExportAnkiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='ankiexporter', password='pw')
        self.client.force_login(self.user)
        self.notebook = Notebook.objects.create(
            user=self.user, title='Anki Deck', pdf_file='fake.txt',
            status=Notebook.STATUS_READY, processing_stage=Notebook.STAGE_READY,
        )

    def test_export_anki_smoke(self):
        Question.objects.create(
            notebook=self.notebook, order_index=1,
            question_text='Capital of France?', expected_answer='Paris',
        )
        response = self.client.get(reverse('notebooks:export_anki', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/octet-stream')
        # .apkg is a zip file under the hood
        self.assertEqual(response.content[:2], b'PK')

    def test_export_anki_handles_special_characters(self):
        Question.objects.create(
            notebook=self.notebook, order_index=1,
            question_text='AT&T <vs> 5 < 10?', expected_answer='Yes & no',
        )
        response = self.client.get(reverse('notebooks:export_anki', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 200)

    def test_export_anki_requires_ownership(self):
        other = User.objects.create_user(username='not_anki_owner', password='pw')
        self.client.force_login(other)
        response = self.client.get(reverse('notebooks:export_anki', args=[self.notebook.pk]))
        self.assertEqual(response.status_code, 404)
