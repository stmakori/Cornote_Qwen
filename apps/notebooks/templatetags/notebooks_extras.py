import json

from django import template
from django.utils.safestring import mark_safe

from ..services.pdf_processor import plain_text_notes_to_html

register = template.Library()


@register.filter
def notes_flow(text):
    """Turn plain-text notes into safe, structured HTML (paragraphs + lists)."""
    return plain_text_notes_to_html(text)


@register.filter
def to_json(value):
    """Serialize a Python value for embedding in an HTML attribute (e.g. data-items="{{ x|to_json }}").

    Deliberately NOT marked safe: Django's normal attribute-context autoescaping
    turns the JSON string's quotes into &quot; etc., which is exactly what an
    HTML attribute needs, and the browser/JSON.parse sees the original characters.
    """
    return json.dumps(value)
