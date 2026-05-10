import pdfplumber
import re


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract and clean text from a PDF.
    For scanned/image-only PDFs, falls back to OCR via pytesseract if available.
    """
    pages_text = []
    is_scanned = False

    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) == 0:
            raise ValueError('PDF has no pages.')
        for page in pdf.pages:
            text = page.extract_text()
            if text and text.strip():
                pages_text.append(text.strip())
            else:
                # Page has no selectable text - probably scanned
                is_scanned = True
                ocr_text = _ocr_page(page)
                if ocr_text:
                    pages_text.append(ocr_text)

    if not pages_text:
        raise ValueError(
            'Could not extract any text from this PDF. '
            'If it is a scanned document, please ensure Tesseract OCR is installed.'
        )

    full_text = '\n\n'.join(pages_text)
    return _clean_text(full_text)


def _ocr_page(page) -> str:
    """Run OCR on a single pdfplumber page. Returns empty string if unavailable."""
    try:
        import pytesseract
        from PIL import Image
        import io
        img = page.to_image(resolution=200).original
        text = pytesseract.image_to_string(img)
        return text.strip()
    except ImportError:
        return ''
    except Exception:
        return ''


def _clean_text(text: str) -> str:
    """Normalize whitespace and join PDF-imposed line breaks within paragraphs."""
    text = re.sub(r'[ \t]+', ' ', text)
    # Split into paragraphs (two or more blank lines)
    paragraphs = re.split(r'\n{2,}', text)
    cleaned = []
    for para in paragraphs:
        lines = [l.strip() for l in para.splitlines() if l.strip()]
        if not lines:
            continue
        # Join short lines (≤ 120 chars) into flowing text; keep long lines as-is
        joined = ' '.join(lines)
        cleaned.append(joined)
    return '\n\n'.join(cleaned).strip()


def format_notes_for_display(text: str) -> str:
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    return '\n\n'.join(paragraphs)


def truncate_for_ai(text: str, max_chars: int = 12000) -> str:
    """Truncate text to fit within AI prompt limits while keeping whole sentences."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = truncated.rfind('.')
    if last_period > max_chars * 0.8:
        truncated = truncated[:last_period + 1]
    return truncated + '\n\n[Text truncated for processing...]'
