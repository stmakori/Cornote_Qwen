"""Regression test for a script-breakout bug in spaced_review.html.

The page used to embed question data as `const questions = {{ questions_json|safe }};`
where questions_json was plain json.dumps() output marked |safe. json.dumps()
does not escape "</script>", so a notebook title or question text containing
that literal string would prematurely close the inline <script> tag and let
whatever followed run as raw HTML/script - a stored XSS via something as
simple as naming your own notebook `</script><script>...`.

Fixed by switching to Django's json_script filter, which HTML-escapes for
exactly this context. This test renders a due review whose notebook title
contains a script-breakout payload and asserts it never appears as a literal,
unescaped "</script>" in the response.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.notebooks.models import Notebook, Question, QuestionReview


class SpacedReviewScriptBreakoutTests(TestCase):
    def test_malicious_notebook_title_cannot_break_out_of_script_tag(self):
        user = User.objects.create_user(username='xss_tester', password='pw')
        self.client.force_login(user)

        payload = '</script><script>window.__pwned__=true;</script>'
        notebook = Notebook.objects.create(user=user, title=payload, pdf_file='fake.txt')
        question = Question.objects.create(
            notebook=notebook, order_index=1, question_text='Q?', expected_answer='A',
        )
        QuestionReview.objects.create(question=question, user=user)  # next_review defaults to due-now

        response = self.client.get(reverse('notebooks:spaced_review_page'))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode()
        self.assertNotIn('</script><script>window.__pwned__', content)
        # json_script's payload should be present, but HTML-escaped (the raw
        # "</script>" substring must not appear literally in the page).
        self.assertIn('spaced-review-questions', content)
