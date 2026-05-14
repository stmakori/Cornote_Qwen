from django import template
from django.utils.safestring import mark_safe

from ..services.pdf_processor import plain_text_notes_to_html

register = template.Library()


@register.filter
def notes_flow(text):
    """Turn plain-text notes into safe, structured HTML (paragraphs + lists)."""
    return plain_text_notes_to_html(text)
