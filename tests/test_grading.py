"""Lokalno ocenjivanje, tip po tip.

Za svaki tip se proverava i tacan i netacan odgovor - inace bi ocenjivac koji
uvek vraca "netacno" prosao pola testova.

Poseban znacaj ima `needs_ai`: on odlucuje da li se troši AI poziv. Ako se
zapali gde ne treba, svaki odgovor kosta kvotu.
"""

from app.quiz import grading
from app.quiz import types as question_types

from .base import AppTestCase


class NormalizationTests(AppTestCase):
    def test_diacritics_and_case_are_ignored(self):
        self.assertEqual(grading.normalize("Čvrsto REŠENJE"), grading.normalize("cvrsto resenje"))

    def test_dj_is_folded(self):
        self.assertEqual(grading.normalize("đubrivo"), grading.normalize("djubrivo"))

    def test_punctuation_is_ignored(self):
        self.assertEqual(grading.normalize("izvod, funkcije."), grading.normalize("izvod funkcije"))

    def test_different_words_stay_different(self):
        self.assertNotEqual(grading.normalize("izvod"), grading.normalize("integral"))


class ChoiceGradingTests(AppTestCase):
    def test_mcq_single(self):
        payload = {"options": ["3", "4", "5"], "correct_index": 1}
        right = grading.grade({"type": "mcq_single"}, payload, {"index": 1})
        wrong = grading.grade({"type": "mcq_single"}, payload, {"index": 0})
        self.assertTrue(right.is_correct)
        self.assertEqual(right.score, 1.0)
        self.assertFalse(wrong.is_correct)
        self.assertFalse(right.needs_ai, "izbor iz ponudjenog ne sme da trosi AI poziv")
        self.assertEqual(wrong.correct_text, "4")

    def test_mcq_multi_partial_credit(self):
        payload = {"options": ["a", "b", "c", "d"], "correct_indices": [0, 2]}
        full = grading.grade({"type": "mcq_multi"}, payload, {"indices": [0, 2]})
        half = grading.grade({"type": "mcq_multi"}, payload, {"indices": [0]})
        overreach = grading.grade({"type": "mcq_multi"}, payload, {"indices": [0, 1, 2]})

        self.assertTrue(full.is_correct)
        self.assertEqual(full.score, 1.0)
        self.assertFalse(half.is_correct)
        self.assertAlmostEqual(half.score, 0.5)
        self.assertAlmostEqual(overreach.score, 0.5, msg="pogodjeno minus promaseno")

    def test_true_false(self):
        payload = {"correct": True}
        self.assertTrue(grading.grade({"type": "true_false"}, payload, {"value": True}).is_correct)
        self.assertFalse(grading.grade({"type": "true_false"}, payload, {"value": False}).is_correct)

    def test_odd_one_out(self):
        payload = {"options": ["pas", "macka", "sto"], "correct_index": 2, "rule": "zivotinje"}
        self.assertTrue(grading.grade({"type": "odd_one_out"}, payload, {"index": 2}).is_correct)
        self.assertFalse(grading.grade({"type": "odd_one_out"}, payload, {"index": 0}).is_correct)

    def test_cloze_dropdown(self):
        payload = {"blanks": [
            {"id": 1, "options": ["izvod", "integral"], "correct_index": 1},
            {"id": 2, "options": ["raste", "opada"], "correct_index": 0},
        ]}
        full = grading.grade({"type": "cloze_dropdown"}, payload, {"values": {"1": 1, "2": 0}})
        half = grading.grade({"type": "cloze_dropdown"}, payload, {"values": {"1": 1, "2": 1}})
        self.assertTrue(full.is_correct)
        self.assertAlmostEqual(half.score, 0.5)
        self.assertFalse(full.needs_ai)


class TextGradingTests(AppTestCase):
    def test_fill_blank_accepts_synonym(self):
        payload = {"blanks": [{"id": 1, "accepted": ["sume", "zbira"], "case_sensitive": False}],
                   "strict_order": True}
        result = grading.grade({"type": "fill_blank"}, payload, {"values": {"1": "ZBIRA"}})
        self.assertTrue(result.is_correct)
        self.assertFalse(result.needs_ai)

    def test_fill_blank_miss_asks_ai(self):
        """Promasena praznina moze da bude neprediviđen sinonim - to AI presudjuje."""
        payload = {"blanks": [{"id": 1, "accepted": ["sume"], "case_sensitive": False}],
                   "strict_order": True}
        result = grading.grade({"type": "fill_blank"}, payload, {"values": {"1": "sumiranja"}})
        self.assertFalse(result.is_correct)
        self.assertTrue(result.needs_ai)

    def test_short_answer_exact_match_costs_nothing(self):
        payload = {"accepted": ["izvod funkcije"], "key_points": [], "case_sensitive": False}
        result = grading.grade({"type": "short_answer"}, payload, {"text": "Izvod funkcije."})
        self.assertTrue(result.is_correct)
        self.assertFalse(result.needs_ai)

    def test_short_answer_other_wording_asks_ai(self):
        payload = {"accepted": ["izvod funkcije"], "key_points": [], "case_sensitive": False}
        result = grading.grade({"type": "short_answer"}, payload, {"text": "prvi izvod te funkcije"})
        self.assertTrue(result.needs_ai)

    def test_empty_answer_never_asks_ai(self):
        """Prazan odgovor je netacan bez razmisljanja - ne trosi kvotu."""
        for question_type, payload in (
            ("short_answer", {"accepted": ["x"], "key_points": [], "case_sensitive": False}),
            ("long_answer", {"key_points": ["a", "b"], "model_answer": "", "min_points": 1}),
            ("work_it_out", {"final_answer": "5", "expected_steps": [], "allow_photo": True, "unit": ""}),
        ):
            result = grading.grade({"type": question_type}, payload, {"text": "   "})
            self.assertFalse(result.needs_ai, question_type)
            self.assertFalse(result.is_correct, question_type)

    def test_long_answer_always_asks_ai_when_answered(self):
        payload = {"key_points": ["a", "b"], "model_answer": "", "min_points": 1}
        result = grading.grade({"type": "long_answer"}, payload, {"text": "Neki duzi odgovor."})
        self.assertTrue(result.needs_ai)


class StructuredGradingTests(AppTestCase):
    def test_numeric_within_tolerance(self):
        payload = {"value": 3.14, "tolerance": 0.01, "relative_tolerance": False, "unit": ""}
        self.assertTrue(grading.grade({"type": "numeric"}, payload, {"value": "3.145"}).is_correct)
        self.assertTrue(grading.grade({"type": "numeric"}, payload, {"value": "3,14"}).is_correct)
        self.assertFalse(grading.grade({"type": "numeric"}, payload, {"value": "3.2"}).is_correct)

    def test_numeric_rejects_non_number(self):
        payload = {"value": 5, "tolerance": 0, "relative_tolerance": False, "unit": ""}
        result = grading.grade({"type": "numeric"}, payload, {"value": "pet"})
        self.assertFalse(result.is_correct)
        self.assertFalse(result.needs_ai)

    def test_match_pairs_partial(self):
        payload = {"left": ["a", "b"], "right": ["1", "2", "3"], "mapping": [0, 1]}
        full = grading.grade({"type": "match_pairs"}, payload, {"mapping": [0, 1]})
        half = grading.grade({"type": "match_pairs"}, payload, {"mapping": [0, 2]})
        self.assertTrue(full.is_correct)
        self.assertAlmostEqual(half.score, 0.5)

    def test_order_sequence_partial_credit(self):
        payload = {"items": ["a", "b", "c", "d"], "correct_order": [0, 1, 2, 3]}
        exact = grading.grade({"type": "order_sequence"}, payload, {"order": [0, 1, 2, 3]})
        near = grading.grade({"type": "order_sequence"}, payload, {"order": [0, 1, 3, 2]})
        reversed_order = grading.grade({"type": "order_sequence"}, payload, {"order": [3, 2, 1, 0]})

        self.assertTrue(exact.is_correct)
        self.assertFalse(near.is_correct)
        self.assertGreater(near.score, reversed_order.score, "blizu tacnog mora da vredi vise")
        self.assertEqual(reversed_order.score, 0.0)

    def test_image_label_hits_within_radius(self):
        payload = {"image": {"path": "materials/x.png"},
                   "targets": [{"id": 1, "label": "jezgro", "x": 0.5, "y": 0.5, "radius": 0.1}]}
        near = grading.grade({"type": "image_label"}, payload, {"marks": [{"id": 1, "x": 0.55, "y": 0.52}]})
        far = grading.grade({"type": "image_label"}, payload, {"marks": [{"id": 1, "x": 0.9, "y": 0.1}]})
        self.assertTrue(near.is_correct)
        self.assertFalse(far.is_correct)

    def test_flashcard_is_self_graded(self):
        payload = {"back": "Granicna vrednost sume."}
        self.assertTrue(grading.grade({"type": "flashcard"}, payload, {"known": True}).is_correct)
        self.assertFalse(grading.grade({"type": "flashcard"}, payload, {"known": False}).is_correct)

    def test_work_it_out_with_photo_asks_ai(self):
        payload = {"final_answer": "5", "expected_steps": [], "allow_photo": True, "unit": ""}
        result = grading.grade({"type": "work_it_out"}, payload,
                               {"photo_path": "answers/q1-abc.jpg"})
        self.assertTrue(result.needs_ai)


class CoverageTests(AppTestCase):
    def test_every_registered_type_has_a_grader(self):
        for item in question_types.all_types():
            result = grading.grade({"type": item.key}, _minimal_payload(item.key), {})
            self.assertIsNotNone(result, item.key)
            self.assertFalse(result.is_correct, f"{item.key}: prazan odgovor ne sme biti tacan")

    def test_describe_answer_is_readable(self):
        text = grading.describe_answer(
            "mcq_single", {"options": ["3", "4"], "correct_index": 1}, {"index": 1}
        )
        self.assertEqual(text, "4")


def _minimal_payload(key: str) -> dict:
    return {
        "mcq_single": {"options": ["a", "b"], "correct_index": 0},
        "mcq_multi": {"options": ["a", "b", "c"], "correct_indices": [0]},
        "true_false": {"correct": True},
        "fill_blank": {"blanks": [{"id": 1, "accepted": ["x"], "case_sensitive": False}]},
        "cloze_dropdown": {"blanks": [{"id": 1, "options": ["a", "b"], "correct_index": 0}]},
        "short_answer": {"accepted": ["x"], "key_points": [], "case_sensitive": False},
        "long_answer": {"key_points": ["a"], "model_answer": "", "min_points": 1},
        "numeric": {"value": 1, "tolerance": 0, "relative_tolerance": False, "unit": ""},
        "match_pairs": {"left": ["a"], "right": ["1"], "mapping": [0]},
        "order_sequence": {"items": ["a", "b", "c"], "correct_order": [0, 1, 2]},
        "odd_one_out": {"options": ["a", "b", "c"], "correct_index": 0, "rule": ""},
        "image_match": {"image": {"path": "x"}, "options": ["a", "b"], "correct_index": 0},
        "image_label": {"image": {"path": "x"},
                        "targets": [{"id": 1, "label": "a", "x": 0.5, "y": 0.5, "radius": 0.1}]},
        "work_it_out": {"final_answer": "1", "expected_steps": [], "allow_photo": True, "unit": ""},
        "flashcard": {"back": "x"},
    }[key]
