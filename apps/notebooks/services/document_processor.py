"""
Extract plain text from uploaded study documents (PDF, Word, plain text).
"""
from __future__ import annotations

import logging
from pathlib import Path

from .pdf_processor import extract_text_from_pdf, _clean_text

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = frozenset({'.pdf', '.docx', '.txt', '.md', '.text'})


def allowed_upload_suffix(name: str) -> str | None:
    ext = Path(name or '').suffix.lower()
    return ext if ext in ALLOWED_EXTENSIONS else None


def tesseract_ocr_available() -> bool:
    """True if Tesseract is installed and callable (for scanned PDFs)."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_text_from_docx(path: str) -> str:
    from docx import Document

    doc = Document(path)
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    raw = '\n\n'.join(parts)
    if not raw.strip():
        raise ValueError('No readable text found in this Word document.')
    return _clean_text(raw)


def extract_text_from_plain_file(path: str) -> str:
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        raw = f.read()
    if not raw.strip():
        raise ValueError('This text file appears to be empty.')
    return _clean_text(raw)


def extract_document_text(path: str, original_filename: str) -> str:
    """
    Dispatch extraction by file extension. ``path`` is the on-disk path.
    """
    ext = allowed_upload_suffix(original_filename)
    if ext is None:
        raise ValueError(
            f'Unsupported file type. Allowed: {", ".join(sorted(ALLOWED_EXTENSIONS))}'
        )

    if ext == '.pdf':
        return extract_text_from_pdf(path)
    if ext == '.docx':
        return extract_text_from_docx(path)
    if ext in ('.txt', '.md', '.text'):
        return extract_text_from_plain_file(path)
    raise ValueError(f'Unsupported extension: {ext}')
