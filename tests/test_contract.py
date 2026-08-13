"""Ugovor sa modelom: parsiranje, spasavanje odsecenog, odbijanje neispravnog.

Ovo je jedini put kojim pitanja ulaze u bazu - i za Gemini i za rucno nalepljen
odgovor iz Claude-a. Zato se ovde proverava i sta prolazi i sta NE prolazi.
"""

import json

from app.ai import contract
from app.quiz import types as question_types

from .base import AppTestCase


def _mcq(stem="Koliko je 2 + 2?", options=None, correct=1):
    return {
        "type": "mcq_single",
        "stem": stem,
        "payload": {"options": options or ["3", "4", "5"], "correct_index": correct},
        "explanation": "Zato.",
    }


class ParseTests(AppTestCase):
    def test_plain_json_object(self):
        parsed = contract.parse(json.dumps({"questions": [_mcq()]}))
        self.assertEqual(len(parsed["questions"]), 1)
        self.assertFalse(parsed["salvaged"])

    def test_markdown_fences_are_removed(self):
        raw = "```json\n" + json.dumps({"questions": [_mcq()]}) + "\n```"
        parsed = contract.parse(raw)
        self.assertEqual(len(parsed["questions"]), 1)

    def test_bare_list_is_accepted(self):
        parsed = contract.parse(json.dumps([_mcq(), _mcq("Koliko je 3 + 3?")]))
        self.assertEqual(len(parsed["questions"]), 2)

    def test_serbian_key_is_accepted(self):
        parsed = contract.parse(json.dumps({"pitanja": [_mcq()]}))
        self.assertEqual(len(parsed["questions"]), 1)

    def test_truncated_response_is_salvaged(self):
        """Odsecen odgovor (MAX_TOKENS) - 2 cela pitanja su bolja od nijednog."""
        full = json.dumps({"questions": [_mcq("Prvo pitanje?"), _mcq("Drugo pitanje?"),
                                         _mcq("Trece pitanje?")]})
        truncated = full[: full.rindex("Trece") + 20]
        parsed = contract.parse(truncated)
        self.assertTrue(parsed["salvaged"])
        self.assertEqual(len(parsed["questions"]), 2)
        self.assertEqual(parsed["questions"][0]["stem"], "Prvo pitanje?")

    def test_empty_response_is_rejected(self):
        with self.assertRaises(contract.ContractError):
            contract.parse("")

    def test_prose_without_json_is_rejected(self):
        with self.assertRaises(contract.ContractError):
            contract.parse("Izvini, ne mogu da napravim pitanja iz ovog materijala.")


class ValidationTests(AppTestCase):
    def test_valid_question_passes(self):
        item = contract.validate_one(_mcq())
        self.assertEqual(item["type"], "mcq_single")
        self.assertEqual(item["payload"]["correct_index"], 1)
        self.assertTrue(item["content_hash"])

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(contract.ContractError):
            contract.validate_one({**_mcq(), "type": "nepostojeci_tip"})

    def test_correct_index_out_of_range_is_rejected(self):
        with self.assertRaises(question_types.InvalidQuestion):
            contract.validate_one(_mcq(correct=9))

    def test_empty_stem_is_rejected(self):
        with self.assertRaises(contract.ContractError):
            contract.validate_one(_mcq(stem="?"))

    def test_fill_blank_without_marker_is_rejected(self):
        with self.assertRaises(contract.ContractError):
            contract.validate_one({
                "type": "fill_blank",
                "stem": "Integral je granicna vrednost sume.",
                "payload": {"blanks": [{"id": 1, "accepted": ["sume"]}]},
            })

    def test_fill_blank_with_marker_passes(self):
        item = contract.validate_one({
            "type": "fill_blank",
            "stem": "Integral je granicna vrednost {{1}}.",
            "payload": {"blanks": [{"id": 1, "accepted": ["sume", "zbira"]}]},
        })
        self.assertEqual(len(item["payload"]["blanks"][0]["accepted"]), 2)

    def test_flat_payload_is_accepted(self):
        """Neki modeli razliju polja po korenu umesto u payload."""
        item = contract.validate_one({
            "type": "true_false",
            "stem": "Integral je uvek pozitivan.",
            "correct": False,
            "explanation": "Zavisi od funkcije.",
        })
        self.assertFalse(item["payload"]["correct"])

    def test_one_bad_item_does_not_kill_the_batch(self):
        accepted, rejected = contract.validate_all([
            _mcq("Prvo pitanje?"),
            {"type": "mcq_single", "stem": "Bez opcija?", "payload": {}},
            _mcq("Trece pitanje?"),
        ])
        self.assertEqual(len(accepted), 2)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["position"], 2)
        self.assertTrue(rejected[0]["reason"])

    def test_order_sequence_must_be_a_permutation(self):
        with self.assertRaises(question_types.InvalidQuestion):
            contract.validate_one({
                "type": "order_sequence",
                "stem": "Poredjaj korake resavanja.",
                "payload": {"items": ["a", "b", "c"], "correct_order": [0, 0, 1]},
            })
        item = contract.validate_one({
            "type": "order_sequence",
            "stem": "Poredjaj korake resavanja.",
            "payload": {"items": ["a", "b", "c"], "correct_order": [2, 0, 1]},
        })
        self.assertEqual(item["payload"]["correct_order"], [2, 0, 1])


class ContentHashTests(AppTestCase):
    def test_same_question_with_shuffled_options_hashes_the_same(self):
        first = contract.validate_one(_mcq(options=["3", "4", "5"], correct=1))
        second = contract.validate_one(_mcq(options=["5", "3", "4"], correct=2))
        self.assertEqual(first["content_hash"], second["content_hash"])

    def test_different_question_hashes_differently(self):
        first = contract.validate_one(_mcq("Koliko je 2 + 2?"))
        second = contract.validate_one(_mcq("Koliko je 3 + 3?"))
        self.assertNotEqual(first["content_hash"], second["content_hash"])

    def test_punctuation_and_case_do_not_matter(self):
        first = contract.validate_one(_mcq("Koliko je 2 + 2?"))
        second = contract.validate_one(_mcq("koliko je 2 + 2"))
        self.assertEqual(first["content_hash"], second["content_hash"])
