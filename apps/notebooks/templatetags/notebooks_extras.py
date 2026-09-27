import json

from django import template
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

from ..services.pdf_processor import plain_text_notes_to_html

register = template.Library()

# html=False makes markdown-it-py HTML-escape any raw tags in the source
# instead of passing them through - notes_content is AI-generated or
# freely user-edited text rendered on the public (unauthenticated) share
# page, so treat it as untrusted input rather than trusted markup.
_markdown = MarkdownIt('commonmark', {'html': False})


@register.filter
def notes_flow(text):
    """Turn plain-text notes into safe, structured HTML (paragraphs + lists)."""
    return plain_text_notes_to_html(text)


@register.filter
def markdown_safe(text):
    """Render notes_content (Markdown, as produced by format_notes_as_markdown)
    to safe HTML. Used on the public shared-notebook page, which has no
    client-side marked.js rendering - without this, notes with ## headings and
    **bold** rendered as literal, unformatted markdown syntax."""
    return mark_safe(_markdown.render(text or ''))


@register.filter
def to_json(value):
    """Serialize a Python value for embedding in an HTML attribute (e.g. data-items="{{ x|to_json }}").

    Deliberately NOT marked safe: Django's normal attribute-context autoescaping
    turns the JSON string's quotes into &quot; etc., which is exactly what an
    HTML attribute needs, and the browser/JSON.parse sees the original characters.
    """
    return json.dumps(value)
