"""Pismo: model vrati pola latinicom, pola cirilicom - u bazu ulazi jedno pismo.

Prijava korisnika: pitanje na ekranu "Koji od 4 dokumenta obuke ima za cilj da
identifikuje temu i cilj процене за сваки предмет..." - pola-pola. Uputstvo u
promptu nije dovoljno; pismo se namece pri upisu.
"""

import unittest

from app import db, translit
from app.ai import contract
from app.quiz import grading

from .base import AppTestCase


class TransliterationTests(unittest.TestCase):
    def test_cyrillic_to_latin_is_complete(self):
        self.assertEqual(
            translit.to_latin("Који од 4 документа обуке има за циљ Ђурђевдан, џеп, њива, љубав?"),
            "Koji od 4 dokumenta obuke ima za cilj Đurđevdan, džep, njiva, ljubav?",
        )

    def test_uppercase_digraphs_follow_neighbours(self):
        self.assertEqual(translit.to_latin("ЉУБАВ"), "LJUBAV")
        self.assertEqual(translit.to_latin("Љубав"), "Ljubav")
        self.assertEqual(translit.to_latin("ШЉ"), "ŠLJ")

    def test_mixed_sentence_becomes_one_script(self):
        mixed = "Koji od 4 dokumenta obuke ima za cilj da identifikuje temu i cilj процене за сваки предмет?"
        self.assertTrue(translit.is_mixed(mixed))
        fixed = translit.to_latin(mixed)
        self.assertFalse(translit.has_cyrillic(fixed))
        self.assertIn("procene za svaki predmet", fixed)

    def test_latin_to_cyrillic_keeps_formulas_units_and_foreign_words(self):
        result = translit.to_cyrillic("Plan časa ili plan nastavnih situacija, H2O, Windows, PDF, x = 2, ljubav")
        self.assertEqual(
            result, "План часа или план наставних ситуација, H2O, Windows, PDF, x = 2, љубав"
        )

    def test_enforce_none_is_identity(self):
        self.assertEqual(translit.enforce("ћирилица i latinica", None), "ћирилица i latinica")

    def test_enforce_deep_walks_payload(self):
        payload = {"options": ["Plan обуке", "Program"], "correct_index": 1, "blanks": [{"accepted": ["ћао"]}]}
        self.assertEqual(
            translit.enforce_deep(payload, "latin"),
            {"options": ["Plan obuke", "Program"], "correct_index": 1, "blanks": [{"accepted": ["ćao"]}]},
        )

    def test_script_for_language(self):
        self.assertEqual(translit.script_for_language("sr"), "latin")
        self.assertEqual(translit.script_for_language("sr-cyrl"), "cyrillic")
        self.assertIsNone(translit.script_for_language("en"))


class ContractScriptTests(unittest.TestCase):
    def _item(self, **overrides):
        item = {
            "type": "mcq_single",
            "stem": "Koji od 4 dokumenta obuke predstavlja osnovnu referencu за учинак полазника?",
            "payload": {"options": ["Plan процене", "Program obuke", "План обуке"], "correct_index": 0},
            "explanation": "Зато што је тако.",
            "topic": "документа обуке",
        }
        item.update(overrides)
        return item

    def test_latin_script_is_enforced_in_every_field(self):
        validated = contract.validate_one(self._item(), script="latin")
        for text in [validated["stem"], validated["explanation"], validated["topic"], *validated["payload"]["options"]]:
            self.assertFalse(translit.has_cyrillic(text), text)
        self.assertIn("za učinak polaznika", validated["stem"])
        self.assertEqual(validated["payload"]["options"][2], "Plan obuke")
        self.assertEqual(validated["explanation"], "Zato što je tako.")
        self.assertEqual(validated["type"], "mcq_single")

    def test_cyrillic_script_leaves_contract_keys_alone(self):
        validated = contract.validate_one(self._item(), script="cyrillic")
        self.assertEqual(validated["type"], "mcq_single")
        self.assertEqual(validated["payload"]["options"][1], "Програм обуке")
        self.assertIn("Који од 4 документа обуке представља", validated["stem"])
        self.assertNotIn("obuke", validated["stem"])

    def test_no_script_keeps_text_as_is(self):
        validated = contract.validate_one(self._item())
        self.assertTrue(translit.is_mixed(validated["stem"]))

    def test_same_question_in_two_scripts_hashes_the_same(self):
        latin = contract.validate_one(self._item(), script="latin")
        cyrillic = contract.validate_one(self._item(), script="cyrillic")
        self.assertEqual(latin["content_hash"], cyrillic["content_hash"])

    def test_two_different_cyrillic_questions_do_not_collide(self):
        # Pre popravke: otisak je bacao sva ne-ASCII slova, pa su dva razlicita
        # cirilicna pitanja bila "duplikat" i drugo je tiho nestajalo.
        first = contract.validate_one(self._item(stem="Шта је процена обучености полазника?"))
        second = contract.validate_one(self._item(stem="Шта је програм обуке за полазнике?"))
        self.assertNotEqual(first["content_hash"], second["content_hash"])

    def test_validate_all_passes_script_through(self):
        accepted, rejected = contract.validate_all([self._item()], script="latin")
        self.assertEqual(rejected, [])
        self.assertFalse(translit.has_cyrillic(accepted[0]["stem"]))
        self.assertIn("polaznika", accepted[0]["stem"])


class GradingScriptTests(unittest.TestCase):
    def test_answer_in_other_script_still_matches(self):
        payload = {"accepted": ["План обуке"], "key_points": [], "case_sensitive": False}
        result = grading.grade({"type": "short_answer"}, payload, {"text": "plan obuke"})
        self.assertTrue(result.is_correct)
        wrong = grading.grade({"type": "short_answer"}, payload, {"text": "program obuke"})
        self.assertFalse(wrong.is_correct)

    def test_fill_blank_accepts_cyrillic_typing(self):
        payload = {
            "blanks": [{"id": 1, "accepted": ["program obuke"], "case_sensitive": False, "hint": ""}],
            "strict_order": True,
        }
        result = grading.grade({"type": "fill_blank"}, payload, {"values": {"1": "програм обуке"}})
        self.assertTrue(result.is_correct)


class NormalizeExistingQuestionsTests(AppTestCase):
    """Pitanja upisana pre popravke (pola-pola) se ujednacuju na zahtev."""

    def test_mixed_questions_are_rewritten_and_rehashed(self):
        from app.services import questions

        category = self.make_category()
        # Fixture prolazi kroz ugovor BEZ pisma - tacno kao stari upis.
        mixed = self.make_question(
            category["id"],
            stem="Koji dokument ima za cilj da identifikuje temu i cilj процене?",
            payload={"options": ["Plan процене", "Program obuke", "План обуке"], "correct_index": 0},
        )
        clean = self.make_question(category["id"], stem="Koliko je 3 + 3?",
                                   payload={"options": ["5", "6"], "correct_index": 1})
        old_hash = db.scalar("SELECT content_hash FROM question WHERE id = ?", (mixed["id"],))

        result = questions.normalize_script("latin")
        self.assertEqual(result, {"checked": 2, "changed": 1})

        fixed = questions.get(mixed["id"])
        self.assertEqual(fixed["stem"], "Koji dokument ima za cilj da identifikuje temu i cilj procene?")
        self.assertEqual(fixed["payload"]["options"], ["Plan procene", "Program obuke", "Plan obuke"])
        self.assertEqual(fixed["payload"]["correct_index"], 0)
        # Otisak ne zavisi od pisma: isto pitanje pre i posle popravke je isto
        # pitanje, pa ponovni uvoz iz drugog modela ne sme da ga duplira.
        new_hash = db.scalar("SELECT content_hash FROM question WHERE id = ?", (mixed["id"],))
        self.assertEqual(old_hash, new_hash)
        self.assertEqual(questions.get(clean["id"])["stem"], "Koliko je 3 + 3?")

    def test_unknown_script_is_refused(self):
        from app.http_util import HttpError
        from app.services import questions

        with self.assertRaises(HttpError):
            questions.normalize_script("glagoljica")
