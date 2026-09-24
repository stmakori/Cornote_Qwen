"""Unit tests for the exact-match structured grading module (apps.notebooks.services.grading).

These types are graded without any AI call, so correctness here is pure Python
logic - no mocking needed. Short answer / fill blank intentionally fall back
to AI grading (grade_structured_answer returns None for them).
"""
from types import SimpleNamespace

from django.test import TestCase

from apps.notebooks.services import grading


def _question(question_type, **fields):
    defaults = dict(
        expected_answer='',
        choices=[],
        correct_choices=[],
        matching_pairs=[],
        correct_order=[],
        is_math=False,
    )
    defaults.update(fields)
    return SimpleNamespace(question_type=question_type, **defaults)


class TrueFalseGradingTests(TestCase):
    def test_correct_true(self):
        q = _question('true_false', expected_answer='True')
        result = grading.grade_structured_answer(q, 'True')
        self.assertEqual(result['grade'], 'correct')

    def test_correct_false_case_insensitive(self):
        q = _question('true_false', expected_answer='False')
        result = grading.grade_structured_answer(q, 'false')
        self.assertEqual(result['grade'], 'correct')

    def test_incorrect(self):
        q = _question('true_false', expected_answer='True')
        result = grading.grade_structured_answer(q, 'False')
        self.assertEqual(result['grade'], 'incorrect')

    def test_malformed_expected_answer_falls_back_to_ai(self):
        q = _question('true_false', expected_answer='')
        self.assertIsNone(grading.grade_structured_answer(q, 'True'))


class MultipleChoiceGradingTests(TestCase):
    def test_correct(self):
        q = _question('multiple_choice', correct_choices=['Paris'], expected_answer='Paris')
        result = grading.grade_structured_answer(q, 'Paris')
        self.assertEqual(result['grade'], 'correct')

    def test_incorrect(self):
        q = _question('multiple_choice', correct_choices=['Paris'], expected_answer='Paris')
        result = grading.grade_structured_answer(q, 'London')
        self.assertEqual(result['grade'], 'incorrect')

    def test_falls_back_to_expected_answer_when_no_correct_choices(self):
        q = _question('multiple_choice', correct_choices=[], expected_answer='Paris')
        result = grading.grade_structured_answer(q, 'Paris')
        self.assertEqual(result['grade'], 'correct')

    def test_no_data_falls_back_to_ai(self):
        q = _question('multiple_choice', correct_choices=[], expected_answer='')
        self.assertIsNone(grading.grade_structured_answer(q, 'Paris'))


class MultipleSelectGradingTests(TestCase):
    def test_correct_full_match(self):
        q = _question('multiple_select', correct_choices=['Glucose', 'Oxygen'])
        result = grading.grade_structured_answer(q, 'Glucose | Oxygen')
        self.assertEqual(result['grade'], 'correct')

    def test_correct_regardless_of_order(self):
        q = _question('multiple_select', correct_choices=['Glucose', 'Oxygen'])
        result = grading.grade_structured_answer(q, 'Oxygen | Glucose')
        self.assertEqual(result['grade'], 'correct')

    def test_partial_when_some_but_not_all_selected(self):
        q = _question('multiple_select', correct_choices=['Glucose', 'Oxygen'])
        result = grading.grade_structured_answer(q, 'Glucose')
        self.assertEqual(result['grade'], 'partial')

    def test_incorrect_when_no_overlap(self):
        q = _question('multiple_select', correct_choices=['Glucose', 'Oxygen'])
        result = grading.grade_structured_answer(q, 'Carbon dioxide | Water')
        self.assertEqual(result['grade'], 'incorrect')

    def test_no_data_falls_back_to_ai(self):
        q = _question('multiple_select', correct_choices=[])
        self.assertIsNone(grading.grade_structured_answer(q, 'Glucose'))


class OrderingGradingTests(TestCase):
    def test_correct_order(self):
        q = _question('ordering', correct_order=['A', 'B', 'C'])
        result = grading.grade_structured_answer(q, 'A → B → C')
        self.assertEqual(result['grade'], 'correct')

    def test_wrong_order_is_partial_when_some_positions_match(self):
        q = _question('ordering', correct_order=['A', 'B', 'C'])
        result = grading.grade_structured_answer(q, 'A → C → B')
        self.assertEqual(result['grade'], 'partial')

    def test_completely_wrong_order_is_incorrect(self):
        q = _question('ordering', correct_order=['A', 'B', 'C'])
        result = grading.grade_structured_answer(q, 'C → A → B')
        self.assertEqual(result['grade'], 'incorrect')

    def test_no_data_falls_back_to_ai(self):
        q = _question('ordering', correct_order=[])
        self.assertIsNone(grading.grade_structured_answer(q, 'A → B'))


class MatchingGradingTests(TestCase):
    def _pairs(self):
        return [
            {'left': 'Term A', 'right': 'Def A'},
            {'left': 'Term B', 'right': 'Def B'},
        ]

    def test_all_pairs_correct(self):
        q = _question('matching', matching_pairs=self._pairs())
        answer = 'Term A => Def A ~ Term B => Def B'
        result = grading.grade_structured_answer(q, answer)
        self.assertEqual(result['grade'], 'correct')

    def test_one_pair_correct_is_partial(self):
        q = _question('matching', matching_pairs=self._pairs())
        answer = 'Term A => Def A ~ Term B => Def A'
        result = grading.grade_structured_answer(q, answer)
        self.assertEqual(result['grade'], 'partial')

    def test_no_correct_pairs_is_incorrect(self):
        q = _question('matching', matching_pairs=self._pairs())
        answer = 'Term A => Def B ~ Term B => Def A'
        result = grading.grade_structured_answer(q, answer)
        self.assertEqual(result['grade'], 'incorrect')

    def test_no_data_falls_back_to_ai(self):
        q = _question('matching', matching_pairs=[])
        self.assertIsNone(grading.grade_structured_answer(q, 'Term A => Def A'))


class FreeTextTypesDelegateToAI(TestCase):
    def test_short_answer_returns_none(self):
        q = _question('short_answer', expected_answer='Some free text answer')
        self.assertIsNone(grading.grade_structured_answer(q, 'anything'))

    def test_fill_blank_returns_none(self):
        q = _question('fill_blank', expected_answer='photolysis')
        self.assertIsNone(grading.grade_structured_answer(q, 'photolysis'))

    def test_empty_user_answer_does_not_crash(self):
        q = _question('true_false', expected_answer='True')
        result = grading.grade_structured_answer(q, '')
        self.assertEqual(result['grade'], 'incorrect')


class MathGradingTests(TestCase):
    def test_exact_match_is_correct(self):
        q = _question('short_answer', expected_answer='4', is_math=True)
        result = grading.grade_structured_answer(q, '4')
        self.assertEqual(result['grade'], 'correct')

    def test_algebraically_equivalent_expression_is_correct(self):
        q = _question('short_answer', expected_answer='2x + 2', is_math=True)
        result = grading.grade_structured_answer(q, '2*(x+1)')
        self.assertEqual(result['grade'], 'correct')

    def test_decimal_vs_fraction_is_correct(self):
        q = _question('short_answer', expected_answer='1/2', is_math=True)
        result = grading.grade_structured_answer(q, '0.5')
        self.assertEqual(result['grade'], 'correct')

    def test_latex_fraction_expected_answer_is_parsed(self):
        q = _question('short_answer', expected_answer=r'\frac{1}{2}', is_math=True)
        result = grading.grade_structured_answer(q, '0.5')
        self.assertEqual(result['grade'], 'correct')

    def test_wrong_answer_is_incorrect(self):
        q = _question('short_answer', expected_answer='4', is_math=True)
        result = grading.grade_structured_answer(q, '5')
        self.assertEqual(result['grade'], 'incorrect')

    def test_caret_exponent_is_parsed(self):
        q = _question('short_answer', expected_answer='x**2', is_math=True)
        result = grading.grade_structured_answer(q, 'x^2')
        self.assertEqual(result['grade'], 'correct')

    def test_unparseable_answer_falls_back_to_ai(self):
        q = _question('short_answer', expected_answer='4', is_math=True)
        self.assertIsNone(grading.grade_structured_answer(q, 'because two plus two equals four'))

    def test_word_problem_expected_answer_falls_back_to_ai(self):
        q = _question(
            'short_answer',
            expected_answer='The train travels 4 hours because 240/60=4',
            is_math=True,
        )
        self.assertIsNone(grading.grade_structured_answer(q, 'It takes 4 hours.'))

    def test_blank_answer_falls_back_to_ai(self):
        q = _question('short_answer', expected_answer='4', is_math=True)
        self.assertIsNone(grading.grade_structured_answer(q, ''))

    def test_non_math_question_is_unaffected_by_is_math_false(self):
        q = _question('true_false', expected_answer='True', is_math=False)
        result = grading.grade_structured_answer(q, 'True')
        self.assertEqual(result['grade'], 'correct')
