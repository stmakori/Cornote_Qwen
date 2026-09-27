"""Tests for PDF upload limits, text extraction, notes rendering, and AI helpers (mocked)."""
import os
import tempfile
from unittest.mock import patch

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.notebooks.forms import PDFUploadForm
from apps.notebooks.services import ai_service
from apps.notebooks.services.pdf_processor import extract_text_from_pdf, plain_text_notes_to_html


class PDFUploadFormTests(TestCase):
    def test_accepts_pdf_up_to_3mb(self):
        size = 3 * 1024 * 1024
        payload = b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n' + b'0' * (size - 20)
        pdf = SimpleUploadedFile('chapter.pdf', payload, content_type='application/pdf')
        form = PDFUploadForm(data={'title': 'Test chapter'}, files={'pdf_file': pdf})
        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_over_max_bytes(self):
        max_bytes = getattr(settings, 'MAX_UPLOAD_MB', settings.MAX_PDF_SIZE_MB) * 1024 * 1024
        pdf = SimpleUploadedFile(
            'huge.pdf',
            b'x' * (max_bytes + 1),
            content_type='application/pdf',
        )
        form = PDFUploadForm(data={'title': 'Big'}, files={'pdf_file': pdf})
        self.assertFalse(form.is_valid())
        self.assertIn('pdf_file', form.errors)

    def test_rejects_bad_extension(self):
        pdf = SimpleUploadedFile('notes.exe', b'hello', content_type='application/octet-stream')
        form = PDFUploadForm(data={'title': 'Nope'}, files={'pdf_file': pdf})
        self.assertFalse(form.is_valid())

    def test_accepts_txt(self):
        pdf = SimpleUploadedFile('notes.txt', b'Hello plain text.', content_type='text/plain')
        form = PDFUploadForm(data={'title': 'Txt'}, files={'pdf_file': pdf})
        self.assertTrue(form.is_valid(), form.errors)

    def test_accepts_docx_extension(self):
        pdf = SimpleUploadedFile('notes.docx', b'PK\x03\x04' + b'0' * 200, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        form = PDFUploadForm(data={'title': 'Word notes'}, files={'pdf_file': pdf})
        self.assertTrue(form.is_valid(), form.errors)


class DocumentExtractTests(TestCase):
    def test_extract_text_from_minimal_pdf(self):
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.pdfgen import canvas
        except ImportError:
            self.skipTest('reportlab not installed')

        fd, path = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        c = canvas.Canvas(path, pagesize=letter)
        c.drawString(100, 750, 'Cornote PDF extraction smoke test. Second sentence.')
        c.showPage()
        c.save()
        try:
            text = extract_text_from_pdf(path)
        finally:
            os.unlink(path)

        self.assertIn('Cornote', text)
        self.assertIn('extraction', text.lower())


class PlainTextNotesHtmlTests(TestCase):
    def test_empty_notes(self):
        html = plain_text_notes_to_html('')
        self.assertIn('notes-placeholder', html)

    def test_escapes_html(self):
        html = plain_text_notes_to_html('<script>x</script>')
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_bullet_list_block(self):
        raw = 'Intro\n\n- one\n- two\n\nOutro'
        html = plain_text_notes_to_html(raw)
        self.assertIn('notes-ul', html)
        self.assertIn('one', html)
        self.assertIn('Outro', html)

    def test_numbered_list_block(self):
        raw = '1) first\n2) second'
        html = plain_text_notes_to_html(raw)
        self.assertIn('notes-ol', html)
        self.assertIn('first', html)


class AIServiceMockedTests(TestCase):
    @patch.object(ai_service, '_chat')
    def test_generate_questions_parses_json(self, mock_chat):
        mock_chat.return_value = (
            '{"questions":[{"question_text":"What is X?","expected_answer":"X is ...",'
            '"expected_keywords":["a","b"]}]}'
        )
        out = ai_service.generate_questions('Some course text about X.')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['question_text'], 'What is X?')

    @patch.object(ai_service, '_chat')
    def test_generate_questions_normalizes_is_math_true(self, mock_chat):
        mock_chat.return_value = (
            '{"questions":[{"question_text":"Solve $2x+2=4$","expected_answer":"1",'
            '"is_math":true}]}'
        )
        out = ai_service.generate_questions('Some algebra text.')
        self.assertTrue(out[0]['is_math'])

    @patch.object(ai_service, '_chat')
    def test_generate_questions_defaults_is_math_false_when_missing(self, mock_chat):
        mock_chat.return_value = '{"questions":[{"question_text":"What is X?","expected_answer":"X"}]}'
        out = ai_service.generate_questions('Some course text about X.')
        self.assertFalse(out[0]['is_math'])

    @patch.object(ai_service, '_chat')
    def test_generate_questions_uses_requested_count(self, mock_chat):
        mock_chat.return_value = '{"questions":[]}'
        with self.assertRaises(ValueError):
            ai_service.generate_questions('Some course text about X.', count=7)
        prompt = mock_chat.call_args.args[0][0]['content']
        self.assertIn('exactly 7 questions', prompt)

    @patch('apps.notebooks.services.ai_service.Anthropic')
    def test_get_client_uses_anthropic_auth_token(self, mock_anthropic):
        with override_settings(
            ANTHROPIC_API_KEY='test-api-key',
            ANTHROPIC_BASE_URL='https://aws-external-anthropic.us-east-2.api.aws',
            ANTHROPIC_WORKSPACE_ID='workspace-123',
        ):
            ai_service._get_client()

        mock_anthropic.assert_called_once()
        kwargs = mock_anthropic.call_args.kwargs
        self.assertEqual(kwargs['api_key'].__class__.__name__, 'Omit')
        self.assertEqual(kwargs['auth_token'], 'test-api-key')
        self.assertEqual(kwargs['base_url'], 'https://aws-external-anthropic.us-east-2.api.aws')
        self.assertEqual(kwargs['default_headers']['anthropic-workspace-id'], 'workspace-123')

    @patch('apps.notebooks.services.ai_service.Anthropic')
    def test_chat_once_uses_auth_token_and_workspace_header(self, mock_anthropic):
        response = mock_anthropic.return_value.messages.create.return_value
        response.content = [type('Block', (), {'type': 'text', 'text': 'pong'})()]

        with override_settings(
            ANTHROPIC_BASE_URL='https://aws-external-anthropic.us-east-2.api.aws',
            ANTHROPIC_WORKSPACE_ID='workspace-123',
            ANTHROPIC_MODEL_ID='claude-sonnet-4-20250514',
            ANTHROPIC_API_KEY='test-api-key',
        ):
            content = ai_service._chat_once([{'role': 'user', 'content': 'Hello'}], max_tokens=10)

        self.assertEqual(content, 'pong')
        mock_anthropic.assert_called_once()
        kwargs = mock_anthropic.call_args.kwargs
        self.assertEqual(kwargs['base_url'], 'https://aws-external-anthropic.us-east-2.api.aws')
        self.assertEqual(kwargs['default_headers']['anthropic-workspace-id'], 'workspace-123')
        self.assertEqual(kwargs['auth_token'], 'test-api-key')
        mock_anthropic.return_value.messages.create.assert_called_once()
        called_kwargs = mock_anthropic.return_value.messages.create.call_args.kwargs
        self.assertEqual(called_kwargs['model'], 'claude-sonnet-4-20250514')
        self.assertEqual(called_kwargs['max_tokens'], 10)
        self.assertNotIn('extra_headers', called_kwargs)

    @patch('apps.notebooks.services.ai_service.gTTS')
    def test_generate_audio_summary_uses_gtts_fallback(self, mock_gtts):
        mock_gtts.return_value.write_to_fp.side_effect = lambda buffer: buffer.write(b'mp3-bytes')

        with override_settings():
            audio = ai_service.generate_audio_summary('Hello world')

        self.assertEqual(audio[1:], ('mp3', 'audio/mpeg'))
        self.assertEqual(audio[0], b'mp3-bytes')
        mock_gtts.assert_called_once()


class DocxExtractTests(TestCase):
    def test_extract_docx_paragraph(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest('python-docx not installed')

        from apps.notebooks.services.document_processor import extract_document_text

        fd, path = tempfile.mkstemp(suffix='.docx')
        os.close(fd)
        doc = Document()
        doc.add_paragraph('Cornote DOCX extraction line.')
        doc.save(path)
        try:
            text = extract_document_text(path, 'unit.docx')
        finally:
            os.unlink(path)
        self.assertIn('Cornote', text)
