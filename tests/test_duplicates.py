"""Isto pitanje dvaput.

Primedba korisnika: "cesto se desava da se ponavlja apsolutno isto pitanje".
Dogovoreno pravilo: isto pitanje = isti nacin odgovaranja + isti tacan odgovor
+ skoro isti tekst. Isto gradivo pitano drugim tipom (jednom zaokruzi, drugi
put dopuni) NIJE duplikat.

Tri mesta drze to pravilo:
1. upis iz generisanja ne pusta duplikat (ni iz iste serije)
2. sesija nikad ne da isto pitanje ni varijaciju vec odgovorenog
3. "Ukloni duplikate" cisti ono sto je uslo pre nego sto je provera postojala
"""

import json

from app import db
from app.ai import contract
from app.quiz import duplicates
from app.quiz import types as question_types
from app.services import categories, questions, study

from .base import AppTestCase


def mcq(stem, options, correct=0, **extra):
    return {"type": "mcq_single", "stem": stem,
            "payload": {"options": options, "correct_index": correct}, **extra}


INSULIN = mcq("Koji organ proizvodi insulin?", ["pankreas", "jetra", "bubreg"])


def same(first, second):
    return duplicates.Index([first]).match(second) is not None


class SameQuestionTests(AppTestCase):
    def test_identical_question_is_the_same(self):
        self.assertTrue(same(INSULIN, dict(INSULIN)))

    def test_case_punctuation_and_one_extra_word_do_not_make_it_new(self):
        other = mcq("koji organ proizvodi hormon insulin", ["Pankreas", "jetra", "bubreg"])
        self.assertTrue(same(INSULIN, other))

    def test_other_wrong_options_and_order_do_not_make_it_new(self):
        """Studentu je isto pitanje sa istim tacnim odgovorom isto pitanje."""
        other = mcq("Koji organ proizvodi insulin?", ["slezina", "pankreas", "srce"], correct=1)
        self.assertTrue(same(INSULIN, other))

    def test_another_way_of_answering_is_a_different_question(self):
        """Dogovor sa korisnikom: jednom zaokruzi, drugi put dopuni - u redu je."""
        blank = {"type": "fill_blank", "stem": "Insulin proizvodi {{1}}.",
                 "payload": {"blanks": [{"accepted": ["pankreas"]}]}}
        short = {"type": "short_answer", "stem": "Koji organ proizvodi insulin?",
                 "payload": {"accepted": ["pankreas"]}}
        self.assertFalse(same(INSULIN, blank))
        self.assertFalse(same(INSULIN, short))

    def test_another_correct_answer_is_a_different_question(self):
        other = mcq("Koji organ proizvodi insulin?", ["pankreas", "jetra", "bubreg"], correct=1)
        self.assertFalse(same(INSULIN, other))

    def test_other_numbers_make_another_exercise(self):
        """Isti odgovor (4) i skoro isti tekst, a drugi zadatak."""
        first = {"type": "numeric", "stem": "Izracunaj 2 + 2.", "payload": {"value": 4}}
        second = {"type": "numeric", "stem": "Izracunaj 1 + 3.", "payload": {"value": 4}}
        self.assertFalse(same(first, second))

    def test_same_answer_but_other_question_is_kept(self):
        spider = {"type": "numeric", "stem": "Koliko nogu ima pauk?", "payload": {"value": 8}}
        octopus = {"type": "numeric", "stem": "Koliko krakova ima hobotnica?", "payload": {"value": 8}}
        self.assertFalse(same(spider, octopus))

    def test_negated_statement_is_not_the_same(self):
        true = {"type": "true_false", "stem": "Mitohondrija proizvodi ATP.", "payload": {"correct": True}}
        false = {"type": "true_false", "stem": "Mitohondrija ne proizvodi ATP.", "payload": {"correct": False}}
        self.assertFalse(same(true, false))

    def test_cyrillic_copy_is_the_same(self):
        cyrillic = mcq("Који орган производи инсулин?", ["панкреас", "јетра", "бубрег"])
        self.assertTrue(same(INSULIN, cyrillic))

    def test_broken_payload_is_never_a_duplicate(self):
        broken = {"type": "mcq_single", "stem": INSULIN["stem"], "payload": {"options": []}}
        self.assertIsNone(duplicates.answer_key("mcq_single", broken["payload"]))
        self.assertFalse(same(INSULIN, broken))

    def test_every_question_type_has_an_answer_key(self):
        """Nov tip bez kljuca se nikad ne bi prepoznao kao duplikat."""
        missing = set(question_types.keys()) - set(duplicates._ANSWER_KEYS)
        self.assertEqual(missing, set(), f"tipovi bez kljuca za duplikate: {missing}")


class InsertTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.subject = self.make_category("Biologija")

    def insert(self, category_id, *items, origin="ai"):
        validated = [contract.validate_one(item) for item in items]
        return questions.insert_many(category_id, None, validated, origin=origin)

    def test_generated_copy_of_an_existing_question_is_not_written(self):
        self.insert(self.subject["id"], INSULIN)
        copy = mcq("Koji organ proizvodi hormon insulin?", ["srce", "pankreas", "jetra"], correct=1)
        result = self.insert(self.subject["id"], copy)
        self.assertEqual(result["inserted_count"], 0)
        self.assertEqual(result["duplicates"], 1)

    def test_same_question_twice_in_one_batch_is_written_once(self):
        result = self.insert(self.subject["id"], INSULIN, mcq("Koji organ proizvodi insulin", ["pankreas", "srce"]))
        self.assertEqual(result["inserted_count"], 1)
        self.assertEqual(result["duplicates"], 1)

    def test_other_type_on_the_same_topic_is_written(self):
        self.insert(self.subject["id"], INSULIN)
        blank = {"type": "fill_blank", "stem": "Insulin proizvodi {{1}}.",
                 "payload": {"blanks": [{"accepted": ["pankreas"]}]}}
        self.assertEqual(self.insert(self.subject["id"], blank)["inserted_count"], 1)

    def test_question_already_in_a_subcategory_is_not_written_to_the_parent(self):
        child = self.make_category("Kolokvijum 1", parent_id=self.subject["id"])
        self.insert(child["id"], INSULIN)
        self.assertEqual(self.insert(self.subject["id"], INSULIN)["inserted_count"], 0)

    def test_question_in_the_parent_is_still_written_to_a_subcategory(self):
        """Sesija samo te podkategorije bi ga inace izgubila. Da se ne pojavi
        dvaput u sesiji celog predmeta, brine raspored."""
        child = self.make_category("Kolokvijum 1", parent_id=self.subject["id"])
        self.insert(self.subject["id"], INSULIN)
        self.assertEqual(self.insert(child["id"], INSULIN)["inserted_count"], 1)

    def test_ignored_question_does_not_come_back_as_new(self):
        first = self.insert(self.subject["id"], INSULIN)["inserted"][0]
        questions.set_meta(first, {"ignored": True})
        copy = mcq("Koji organ proizvodi insulin?!", ["pankreas", "jetra"])
        self.assertEqual(self.insert(self.subject["id"], copy)["inserted_count"], 0)

    def test_exam_questions_go_in_literally(self):
        """Ispitna lista je 1:1 kao u dokumentu - i kad ima dva skoro ista."""
        result = self.insert(self.subject["id"], INSULIN,
                             mcq("Koji organ proizvodi insulin!", ["pankreas", "srce"]), origin="exam")
        self.assertEqual(result["inserted_count"], 2)


class SessionTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.subject = self.make_category("Biologija")

    def _ids(self, session_id, count):
        picked = []
        for _ in range(count):
            step = study.next_question(session_id)
            if step["done"]:
                break
            picked.append(step["question"]["id"])
            study.answer(session_id, step["question"]["id"], {"answer": {"index": 0}})
        return picked

    def test_variant_of_an_answered_question_does_not_come_next(self):
        """Sledece pitanje se bira posebno; ranije nije znalo za grupu varijacija
        upravo odgovorenog pitanja i varijacija je dolazila odmah posle njega."""
        original = self.make_question(self.subject["id"], **mcq(
            "Koji organ proizvodi insulin?", ["pankreas", "jetra"], variant_group="insulin"))
        variant = self.make_question(self.subject["id"], **mcq(
            "Insulin se stvara u kom organu?", ["pankreas", "srce"], variant_group="insulin",
            variant_index=1))
        session_id = study.start(self.subject["id"], {"length": 1})["session"]["id"]
        db.execute("UPDATE study_session SET planned_count = 5 WHERE id = ?", (session_id,))

        picked = self._ids(session_id, 2)
        self.assertEqual(len(picked), 1, f"varijacija u istoj sesiji: {picked}")
        self.assertIn(picked[0], (original["id"], variant["id"]))

    def test_same_question_from_two_subcategories_is_asked_once(self):
        first = self.make_category("Kolokvijum 1", parent_id=self.subject["id"])
        second = self.make_category("Kolokvijum 2", parent_id=self.subject["id"])
        self.make_question(first["id"], **INSULIN)
        self.make_question(second["id"], **INSULIN)
        session_id = study.start(self.subject["id"], {"length": 5})["session"]["id"]

        self.assertEqual(len(self._ids(session_id, 5)), 1)


class RemoveExistingTests(AppTestCase):
    """Pitanja koja su usla pre provere - upisuju se mimo `insert_many`."""

    def setUp(self):
        super().setUp()
        self.subject = self.make_category("Biologija")

    def legacy(self, category_id, item, origin="ai", seen=0):
        validated = contract.validate_one(item)
        question_id = db.insert("question", {
            "category_id": category_id, "type": validated["type"], "stem": validated["stem"],
            "payload": json.dumps(validated["payload"], ensure_ascii=False),
            "content_hash": validated["content_hash"], "origin": origin,
        })
        db.execute("INSERT INTO question_meta (question_id) VALUES (?)", (question_id,))
        db.execute("INSERT INTO question_schedule (question_id, category_id, seen_count) VALUES (?, ?, ?)",
                   (question_id, category_id, seen))
        return question_id

    def deleted(self, question_id):
        return bool(db.scalar("SELECT deleted_at FROM question_meta WHERE question_id = ?", (question_id,)))

    def test_keeps_the_one_with_progress_and_removes_the_rest(self):
        fresh = self.legacy(self.subject["id"], INSULIN)
        practised = self.legacy(self.subject["id"], mcq("Koji organ proizvodi insulin", ["pankreas", "srce"]), seen=6)
        third = self.legacy(self.subject["id"], mcq("Koji organ proizvodi insulin?", ["pankreas"] * 1 + ["jetra"]))

        result = questions.remove_duplicates(self.subject["id"])
        self.assertEqual(result["removed"], 2)
        self.assertFalse(self.deleted(practised), "ostaje ono na kome je napredak")
        self.assertTrue(self.deleted(fresh))
        self.assertTrue(self.deleted(third))

    def test_never_removes_a_question_with_a_note_or_an_exam_question(self):
        kept = self.legacy(self.subject["id"], INSULIN, seen=3)
        noted = self.legacy(self.subject["id"], dict(INSULIN, stem="Koji organ proizvodi insulin!"))
        questions.set_meta(noted, {"note": "proveri u skripti"})
        exam = self.legacy(self.subject["id"], dict(INSULIN, stem="Koji organ proizvodi insulin??"), origin="exam")

        self.assertEqual(questions.remove_duplicates(self.subject["id"])["removed"], 1)
        self.assertFalse(self.deleted(noted))
        self.assertFalse(self.deleted(exam))
        self.assertTrue(self.deleted(kept), "ispitno pitanje je vrednije od AI kopije")

    def test_twin_in_a_sibling_category_is_left_alone(self):
        first = self.make_category("Kolokvijum 1", parent_id=self.subject["id"])
        second = self.make_category("Kolokvijum 2", parent_id=self.subject["id"])
        one = self.legacy(first["id"], INSULIN, seen=2)
        two = self.legacy(second["id"], INSULIN)

        self.assertEqual(questions.remove_duplicates(self.subject["id"])["removed"], 0)
        self.assertFalse(self.deleted(one) or self.deleted(two))

    def test_removed_question_leaves_the_session(self):
        self.legacy(self.subject["id"], INSULIN, seen=2)
        self.legacy(self.subject["id"], dict(INSULIN, stem="Koji organ proizvodi insulin."))
        questions.remove_duplicates(self.subject["id"])
        ids = categories.subtree_ids(self.subject["id"])
        self.assertEqual(questions.type_counts(ids), {"mcq_single": 1})
