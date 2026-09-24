"""
Exact-match grading for structured question types.

Multiple choice, true/false, multiple select, ordering, and matching questions
carry enough structured data on the Question model (choices/correct_choices/
correct_order/matching_pairs) to be graded instantly and deterministically -
no AI call needed, no risk of the model misreading a well-formed selection.

Short answer and fill-in-the-blank stay AI-graded (ai_service.grade_answer):
free text needs semantic judgment this module doesn't attempt. Math questions
(Question.is_math) get their own symbolic grader below, and only fall back to
AI grading when the answer can't be parsed as an expression (e.g. a word
problem answered in prose).

The serialization formats parsed here (" | ", " -> ", " => ", " ~ ") are the
same delimiters static/js/question-widgets.js writes into the answer textarea
- keep the two in sync if either changes.
"""
import re

_LATEX_STRIP = [
    (re.compile(r'\\left|\\right'), ''),
    (re.compile(r'\\cdot|\\times'), '*'),
    (re.compile(r'\\div'), '/'),
    (re.compile(r'\\sqrt\{([^{}]+)\}'), r'sqrt(\1)'),
    (re.compile(r'\\frac\{([^{}]+)\}\{([^{}]+)\}'), r'((\1)/(\2))'),
    (re.compile(r'\\pi\b'), 'pi'),
    (re.compile(r'\$+'), ''),
]


def _strip_latex(text: str) -> str:
    """Convert a handful of common LaTeX math constructs into something
    sympy's parser can read. Not a full LaTeX parser - just enough for the
    simple expected-answer strings the AI is asked to produce (see
    ai_service._QUESTION_TYPE_SPEC's math entry) and typical student input."""
    text = (text or '').strip()
    for pattern, repl in _LATEX_STRIP:
        text = pattern.sub(repl, text)
    return text.strip()


_MATH_FUNCTION_WHITELIST = {
    'sqrt', 'sin', 'cos', 'tan', 'sec', 'csc', 'cot', 'asin', 'acos', 'atan',
    'log', 'ln', 'exp', 'abs', 'pi', 'e', 'oo', 'mod', 'min', 'max',
}
_WORD_RE = re.compile(r'[a-zA-Z]{3,}')


def _contains_prose(text: str) -> bool:
    """sympy's implicit-multiplication parser will happily accept "because
    two plus two" as a product of single-letter symbols (b*e*c*a*u*s*e*...) -
    a successful parse, but not a math expression. Reject any 3+ letter word
    that isn't a recognized math function/constant name before we even try
    parsing, so word problems and prose answers fall through to AI grading
    instead of being "graded" against a nonsense symbolic comparison."""
    return any(w.lower() not in _MATH_FUNCTION_WHITELIST for w in _WORD_RE.findall(text))


def _grade_math(question, user_answer):
    """Symbolic/numeric equivalence check via sympy, so "2x+2" and "2*(x+1)"
    (or "1/2" and "0.5") both grade as correct instead of requiring an exact
    string match. Returns None (fall back to AI grading) when either side
    can't be parsed as an expression - word problems, multi-step "show your
    work" answers, or a blank submission."""
    if not question.expected_answer or not (user_answer or '').strip():
        return None

    expected_clean = _strip_latex(question.expected_answer)
    got_clean = _strip_latex(user_answer)
    if _contains_prose(expected_clean) or _contains_prose(got_clean):
        return None

    try:
        import sympy
        from sympy.parsing.sympy_parser import (
            parse_expr, standard_transformations,
            implicit_multiplication_application, convert_xor,
        )

        transformations = standard_transformations + (implicit_multiplication_application, convert_xor)
        expected_expr = parse_expr(expected_clean, transformations=transformations)
        got_expr = parse_expr(got_clean, transformations=transformations)
    except Exception:
        return None  # not a clean expression - let AI take a shot

    try:
        if sympy.simplify(expected_expr - got_expr) == 0:
            return _result('correct', 'Correct!')
    except Exception:
        pass

    try:
        if abs(complex(expected_expr.evalf()) - complex(got_expr.evalf())) < 1e-6:
            return _result('correct', 'Correct!')
    except Exception:
        pass

    return _result('incorrect', f'Not quite - the correct answer is {question.expected_answer}.')


def _norm(value):
    return (value or '').strip().casefold()


def _result(grade, feedback):
    return {'grade': grade, 'feedback': feedback}


def _grade_true_false(question, user_answer):
    expected = _norm(question.expected_answer)
    if expected not in ('true', 'false'):
        return None  # question wasn't populated correctly - let AI take a shot
    got = _norm(user_answer)
    if got not in ('true', 'false'):
        return _result('incorrect', f"That isn't True or False. Expected: {question.expected_answer}.")
    if got == expected:
        return _result('correct', 'Correct!')
    return _result('incorrect', f'Not quite - the correct answer is {question.expected_answer}.')


def _grade_multiple_choice(question, user_answer):
    correct_choices = question.correct_choices or (
        [question.expected_answer] if question.expected_answer else []
    )
    if not correct_choices:
        return None
    correct = correct_choices[0]
    if _norm(user_answer) == _norm(correct):
        return _result('correct', 'Correct!')
    return _result('incorrect', f'Not quite - the correct answer is "{correct}".')


def _grade_multiple_select(question, user_answer):
    if not question.correct_choices:
        return None
    got = {s.strip() for s in user_answer.split(' | ') if s.strip()}
    expected = {c.strip() for c in question.correct_choices}
    got_norm = {_norm(x) for x in got}
    expected_norm = {_norm(x) for x in expected}

    if got_norm == expected_norm:
        return _result('correct', 'Correct - you selected exactly the right choices!')
    if got_norm & expected_norm:
        return _result(
            'partial',
            f'Partially correct. The full set of correct choices is: {", ".join(sorted(expected))}.',
        )
    return _result('incorrect', f'Not quite - the correct choices are: {", ".join(sorted(expected))}.')


def _grade_ordering(question, user_answer):
    if not question.correct_order:
        return None
    got = [s.strip() for s in user_answer.split(' → ') if s.strip()]
    expected = list(question.correct_order)
    if not got:
        return _result('incorrect', f'No order given. Correct order: {" → ".join(expected)}.')

    got_norm = [_norm(x) for x in got]
    expected_norm = [_norm(x) for x in expected]

    if got_norm == expected_norm:
        return _result('correct', 'Correct order!')
    if len(got_norm) == len(expected_norm):
        matches = sum(1 for a, b in zip(got_norm, expected_norm) if a == b)
        if matches > 0:
            return _result(
                'partial',
                f'{matches}/{len(expected_norm)} in the right position. '
                f'Correct order: {" → ".join(expected)}.',
            )
    return _result('incorrect', f'Not quite - the correct order is: {" → ".join(expected)}.')


def _grade_matching(question, user_answer):
    if not question.matching_pairs:
        return None
    expected_pairs = {
        (_norm(p.get('left', '')), _norm(p.get('right', '')))
        for p in question.matching_pairs
    }
    got_pairs = set()
    for chunk in user_answer.split(' ~ '):
        parts = chunk.split(' => ')
        if len(parts) == 2:
            got_pairs.add((_norm(parts[0]), _norm(parts[1])))

    total = len(expected_pairs)
    expected_display = ', '.join(f"{p['left']} → {p['right']}" for p in question.matching_pairs)

    if not got_pairs:
        return _result('incorrect', f'No pairs matched. Correct pairing: {expected_display}.')

    correct_count = len(got_pairs & expected_pairs)
    if correct_count == total and len(got_pairs) == total:
        return _result('correct', 'All pairs matched correctly!')
    if correct_count > 0:
        return _result(
            'partial',
            f'{correct_count}/{total} pairs correct. Correct pairing: {expected_display}.',
        )
    return _result('incorrect', f'Not quite - the correct pairing is: {expected_display}.')


_GRADERS = {
    'true_false': _grade_true_false,
    'multiple_choice': _grade_multiple_choice,
    'multiple_select': _grade_multiple_select,
    'ordering': _grade_ordering,
    'matching': _grade_matching,
}


def grade_structured_answer(question, user_answer):
    """Return {'grade', 'feedback'} for question types with unambiguous structured
    data, or None to signal "fall back to AI grading" (short_answer, fill_blank,
    or a structured type whose data wasn't populated for some reason)."""
    if question.is_math:
        return _grade_math(question, user_answer or '')
    grader = _GRADERS.get(question.question_type)
    if grader is None:
        return None
    return grader(question, user_answer or '')
