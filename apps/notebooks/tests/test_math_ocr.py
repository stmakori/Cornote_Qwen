"""Tests for AI-vision transcription of scanned pages (used so scanned math
notes/problems come through as LaTeX instead of Tesseract's garbled plain
text) and the OCR fallback chain that wires it in."""
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.notebooks.services import ai_service, pdf_processor


class TranscribeScannedPageImageTests(TestCase):
    @patch('apps.notebooks.services.ai_service.Anthropic')
    def test_returns_transcribed_text_from_vision_response(self, mock_anthropic):
        response = mock_anthropic.return_value.messages.create.return_value
        response.content = [type('Block', (), {'type': 'text', 'text': r'The area is $\pi r^2$.'})()]

        with override_settings(ANTHROPIC_API_KEY='test-key'):
            image = MagicMock()
            result = ai_service.transcribe_scanned_page_image(image)

        self.assertEqual(result, r'The area is $\pi r^2$.')
        image.save.assert_called_once()  # saved to a PNG buffer for base64 encoding

    @patch('apps.notebooks.services.ai_service.Anthropic')
    def test_sends_image_as_base64_content_block(self, mock_anthropic):
        create_mock = mock_anthropic.return_value.messages.create
        create_mock.return_value.content = [type('Block', (), {'type': 'text', 'text': 'ok'})()]

        with override_settings(ANTHROPIC_API_KEY='test-key'):
            image = MagicMock()
            image.save.side_effect = lambda buf, format: buf.write(b'fake-png-bytes')
            ai_service.transcribe_scanned_page_image(image)

        sent_content = create_mock.call_args.kwargs['messages'][0]['content']
        image_block = next(b for b in sent_content if b['type'] == 'image')
        self.assertEqual(image_block['source']['media_type'], 'image/png')
        text_block = next(b for b in sent_content if b['type'] == 'text')
        self.assertIn('LaTeX', text_block['text'])

    @patch('apps.notebooks.services.ai_service.Anthropic')
    def test_empty_response_raises_and_is_not_silently_returned(self, mock_anthropic):
        mock_anthropic.return_value.messages.create.return_value.content = []
        with override_settings(ANTHROPIC_API_KEY='test-key', AI_MAX_RETRIES=1):
            with self.assertRaises(ValueError):
                ai_service.transcribe_scanned_page_image(MagicMock())


class OcrPageFallbackTests(TestCase):
    def _fake_page(self):
        page = MagicMock()
        page.to_image.return_value.original = MagicMock()
        return page

    @patch.object(ai_service, 'transcribe_scanned_page_image')
    def test_uses_ai_vision_transcription_when_available(self, mock_transcribe):
        mock_transcribe.return_value = r'$\frac{1}{2}$'
        result = pdf_processor._ocr_page(self._fake_page())
        self.assertEqual(result, r'$\frac{1}{2}$')

    @patch('pytesseract.image_to_string')
    @patch.object(ai_service, 'transcribe_scanned_page_image')
    def test_falls_back_to_tesseract_when_ai_vision_fails(self, mock_transcribe, mock_tesseract):
        mock_transcribe.side_effect = ValueError('AI unavailable')
        mock_tesseract.return_value = 'plain ocr text'
        result = pdf_processor._ocr_page(self._fake_page())
        self.assertEqual(result, 'plain ocr text')

    @patch.object(ai_service, 'transcribe_scanned_page_image')
    def test_returns_empty_string_when_page_image_cannot_be_rendered(self, mock_transcribe):
        page = MagicMock()
        page.to_image.side_effect = Exception('render failed')
        result = pdf_processor._ocr_page(page)
        self.assertEqual(result, '')
        mock_transcribe.assert_not_called()
