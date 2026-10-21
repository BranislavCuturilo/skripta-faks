"""AI pregled na kraju sesije: tekstualni odgovori se ne ocenjuju jedan po jedan.

Primedba korisnika koja je napisala ovaj modul: odgovori tipa "napisi
recenicu" nisu mogli da se provere ili su javljali gresku, a poziv modelu za
svaki odgovor je skup. Dogovor: u sesiji se odgovor samo sacuva i ide se
dalje, a na kraju JEDAN poziv oceni sve sto ceka i napise zakljucak.

Ono sto ovde mora da drzi:
- u sesiji nijedan odgovor ne zove model dok se uci
- pregled je tacno jedan poziv, bez obzira koliko odgovora ceka
- pao poziv ne gubi nista: odgovori i dalje cekaju, raspored nije kaznjen
- odgovor koji ceka ne ulazi u proseke ni u strategiju
"""

import json
from unittest import mock

from app import db
from app.ai import gemini
from app.http_util import HttpError
from app.services import settings_store, strategy, study

from .base import AppTestCase

GENERATE = "app.services.ai_models.generate"


def _reply(results, conclusion="Zna definicije, mesa primenu.", **extra):
    payload = {
        "results": results,
        "conclusion": conclusion,
        "strengths": ["definicije"],
        "gaps": ["primena izvoda"],
        "next_steps": ["ponovi lekciju 3"],
        **extra,
    }
    return {"text": json.dumps(payload, ensure_ascii=False), "model": "gemini-test"}


class SessionReviewBase(AppTestCase):
    def setUp(self):
        super().setUp()
        settings_store.set_value("gemini_api_key", "lazan-kljuc")
        self.category = self.make_category()
        self.essay = self.make_question(
            self.category["id"],
            type="long_answer",
            stem="Objasni sta je izvod funkcije.",
            payload={"key_points": ["granicna vrednost", "kolicnik prirastaja"],
                     "model_answer": "Izvod je granicna vrednost kolicnika prirastaja."},
            topic="izvodi",
        )
        self.short = self.make_question(
            self.category["id"],
            type="short_answer",
            stem="Kako se zove organela u kojoj nastaje energija?",
            payload={"accepted": ["mitohondrija"], "key_points": ["mitohondrija"]},
            topic="celija",
        )
        self.blank = self.make_question(
            self.category["id"],
            type="fill_blank",
            stem="Izvod konstante je {{1}}.",
            payload={"blanks": [{"accepted": ["nula", "0"]}]},
            topic="izvodi",
        )
        self.mcq = self.make_question(self.category["id"])
        self.session_id = study.start(self.category["id"], {"length": 10})["session"]["id"]

    def answer_text_questions(self):
        """Tri tekstualna odgovora koja nisu doslovno pogodjena - sva tri cekaju."""
        study.answer(self.session_id, self.essay["id"],
                     {"answer": {"text": "Izvod pokazuje koliko se brzo funkcija menja."}})
        study.answer(self.session_id, self.short["id"], {"answer": {"text": "jezgro"}})
        study.answer(self.session_id, self.blank["id"], {"answer": {"values": {"1": "jedan"}}})

    def schedule(self, question):
        return db.query_one(
            "SELECT * FROM question_schedule WHERE question_id = ?", (question["id"],)
        ) or {"seen_count": 0}


class AnsweringInSessionTests(SessionReviewBase):
    def test_text_answer_in_session_waits_instead_of_calling_ai(self):
        with mock.patch(GENERATE) as generate:
            result = study.answer(self.session_id, self.essay["id"],
                                  {"answer": {"text": "Izvod je brzina promene."}})

        generate.assert_not_called()
        self.assertTrue(result["pending"])
        self.assertEqual(result["graded_by"], "pending")
        self.assertEqual(
            self.schedule(self.essay)["seen_count"], 0,
            "odgovor bez ocene ne sme da upise raspored - bio bi kaznjen kao netacan",
        )

    def test_exact_short_answer_is_still_graded_on_the_spot(self):
        """Doslovan pogodak je besplatan i siguran - ne ceka nikoga."""
        with mock.patch(GENERATE) as generate:
            result = study.answer(self.session_id, self.short["id"],
                                  {"answer": {"text": "Mitohondrija"}})

        generate.assert_not_called()
        self.assertFalse(result["pending"])
        self.assertTrue(result["is_correct"])
        self.assertEqual(self.schedule(self.short)["seen_count"], 1)

    def test_choice_answer_is_unchanged(self):
        result = study.answer(self.session_id, self.mcq["id"], {"answer": {"index": 1}})
        self.assertFalse(result["pending"])
        self.assertTrue(result["is_correct"])

    def test_answer_outside_a_session_still_asks_ai_immediately(self):
        """Provera jednog pitanja iz liste nema "kraj sesije" na koji bi cekala."""
        reply = {"text": json.dumps({"is_correct": True, "score": 0.9, "feedback": "Dobro.",
                                     "misconception": ""}), "model": "gemini-test"}
        with mock.patch(GENERATE, return_value=reply) as generate:
            result = study.answer(None, self.essay["id"], {"answer": {"text": "Brzina promene."}})

        self.assertEqual(generate.call_count, 1)
        self.assertEqual(result["graded_by"], "ai")
        self.assertTrue(result["is_correct"])

    def test_waiting_answer_is_reported_apart_from_wrong_ones(self):
        self.answer_text_questions()
        study.answer(self.session_id, self.mcq["id"], {"answer": {"index": 0}})

        summary = study.summary(self.session_id)
        self.assertEqual(summary["asked"], 4)
        self.assertEqual(summary["pending"], 3)
        self.assertEqual(summary["correct"], 0)
        self.assertEqual(len(summary["wrong"]), 1, "samo MCQ je stvarno netacan")
        self.assertEqual([item["graded_by"] for item in summary["answers"]],
                         ["pending", "pending", "pending", "local"])

    def test_waiting_answers_stay_out_of_strategy_evidence(self):
        self.answer_text_questions()
        study.answer(self.session_id, self.mcq["id"], {"answer": {"index": 1}})

        totals = strategy.evidence(self.category["id"])["totals"]
        self.assertEqual(totals["attempts"], 1, "odgovor koji ceka ne sme u proseke")
        self.assertEqual(totals["average_score"], 1.0)


class ReviewTests(SessionReviewBase):
    def test_review_grades_every_waiting_answer_with_one_call(self):
        self.answer_text_questions()
        study.answer(self.session_id, self.mcq["id"], {"answer": {"index": 1}})

        reply = _reply([
            {"n": 1, "score": 0.5, "is_correct": False, "feedback": "Fali granicna vrednost.",
             "misconception": "izvod kao brzina bez granice"},
            {"n": 2, "score": 0.0, "is_correct": False, "feedback": "Jezgro cuva DNK."},
            {"n": 3, "score": 1.0, "is_correct": True, "feedback": "Tacno, nula."},
        ])
        with mock.patch(GENERATE, return_value=reply) as generate:
            summary = study.review(self.session_id)

        self.assertEqual(generate.call_count, 1, "pregled cele sesije je JEDAN poziv")
        self.assertEqual(generate.call_args.kwargs["thinking"], "low",
                         "student ceka na rezimeu - bez dugog razmisljanja")
        self.assertEqual(generate.call_args.kwargs["timeout_s"], study.REVIEW_TIMEOUT_S)
        self.assertNotIn("max_output_tokens", generate.call_args.kwargs,
                         "ocena svih odgovora ne sme da bude odsecena tesnim limitom")
        prompt = generate.call_args.args[1]
        for text in ("Izvod pokazuje koliko se brzo", "jezgro", "jedan", "Objasni sta je izvod"):
            self.assertIn(text, prompt)

        self.assertEqual(summary["pending"], 0)
        self.assertEqual(summary["correct"], 2, "MCQ + dopuna koju je AI priznao")
        by_question = {item["question_id"]: item for item in summary["answers"]}
        self.assertEqual(by_question[self.essay["id"]]["score"], 0.5)
        self.assertEqual(by_question[self.essay["id"]]["graded_by"], "ai")
        self.assertEqual(by_question[self.essay["id"]]["feedback"], "Fali granicna vrednost.")
        self.assertTrue(by_question[self.blank["id"]]["is_correct"])
        self.assertEqual(summary["review"]["conclusion"], "Zna definicije, mesa primenu.")
        self.assertEqual(summary["review"]["gaps"], ["primena izvoda"])

        session = db.query_one("SELECT * FROM study_session WHERE id = ?", (self.session_id,))
        self.assertEqual(session["correct_count"], 2)
        for question in (self.essay, self.short, self.blank):
            self.assertEqual(self.schedule(question)["seen_count"], 1,
                             "raspored se upisuje tacno jednom, kad stigne ocena")
        self.assertEqual(db.scalar("SELECT COUNT(*) FROM explanation_cache"), 3)
        self.assertEqual(
            db.scalar("SELECT evidence_count FROM misconception WHERE label = ?",
                      ("izvod kao brzina bez granice",)),
            1,
        )

    def test_failed_call_keeps_every_answer_waiting(self):
        self.answer_text_questions()
        with mock.patch(GENERATE, side_effect=gemini.AiError("Kvota je potrosena.", status=429)):
            with self.assertRaises(HttpError) as caught:
                study.review(self.session_id)

        self.assertIn("Kvota je potrosena.", caught.exception.message)
        self.assertIn("čekaju", caught.exception.message)
        self.assertEqual(study.summary(self.session_id)["pending"], 3)
        self.assertEqual(self.schedule(self.essay)["seen_count"], 0)

        reply = _reply([{"n": n, "score": 1.0, "is_correct": True, "feedback": "ok"} for n in (1, 2, 3)])
        with mock.patch(GENERATE, return_value=reply):
            summary = study.review(self.session_id)
        self.assertEqual(summary["pending"], 0, "drugi pokusaj ocenjuje ono sto je cekalo")

    def test_unreadable_reply_keeps_every_answer_waiting(self):
        self.answer_text_questions()
        with mock.patch(GENERATE, return_value={"text": "", "model": "gemini-test"}):
            with self.assertRaises(HttpError) as caught:
                study.review(self.session_id)
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(study.summary(self.session_id)["pending"], 3)

    def test_answer_the_model_skipped_waits_for_the_next_review(self):
        self.answer_text_questions()
        with mock.patch(GENERATE, return_value=_reply(
                [{"n": 1, "score": 1.0, "is_correct": True, "feedback": "ok"}])):
            summary = study.review(self.session_id)
        self.assertEqual(summary["pending"], 2)

        reply = _reply([{"n": n, "score": 0.0, "is_correct": False, "feedback": "ne"} for n in (1, 2)])
        with mock.patch(GENERATE, return_value=reply) as generate:
            summary = study.review(self.session_id)

        # Ocenjen odgovor sme da stoji medju "ostalima" (ulazi u zakljucak),
        # ali ne u bloku koji se ocenjuje.
        to_grade = generate.call_args.args[1].split("OSTALI ODGOVORI")[0]
        self.assertNotIn("Izvod pokazuje koliko se brzo", to_grade,
                         "vec ocenjen odgovor ne sme ponovo na ocenu")
        self.assertIn("jezgro", to_grade)
        self.assertEqual(summary["pending"], 0)
        self.assertEqual(self.schedule(self.essay)["seen_count"], 1)

    def test_truncated_reply_still_saves_the_complete_grades(self):
        self.answer_text_questions()
        full = _reply([{"n": n, "score": 1.0, "is_correct": True, "feedback": "ok"} for n in (1, 2, 3)])
        cut = full["text"][: full["text"].index('"conclusion"') - 2]
        with mock.patch(GENERATE, return_value={"text": cut, "model": "gemini-test"}):
            summary = study.review(self.session_id)

        self.assertEqual(summary["pending"], 0)
        self.assertIsNone(summary["review"], "zakljucak je presecen - nema ga, ne izmislja se")

    def test_second_review_without_waiting_answers_costs_nothing(self):
        self.answer_text_questions()
        reply = _reply([{"n": n, "score": 1.0, "is_correct": True, "feedback": "ok"} for n in (1, 2, 3)])
        with mock.patch(GENERATE, return_value=reply):
            study.review(self.session_id)

        with mock.patch(GENERATE) as generate:
            summary = study.review(self.session_id)
        generate.assert_not_called()
        self.assertEqual(summary["review"]["conclusion"], "Zna definicije, mesa primenu.")

    def test_fully_graded_session_can_still_ask_for_a_conclusion(self):
        """Dugme "AI zakljucak" kad nista ne ceka: jedan poziv, samo zakljucak."""
        study.answer(self.session_id, self.mcq["id"], {"answer": {"index": 0}})
        with mock.patch(GENERATE, return_value=_reply([])) as generate:
            summary = study.review(self.session_id)

        self.assertEqual(generate.call_count, 1)
        self.assertIn("nema ih", generate.call_args.args[1])
        self.assertEqual(summary["review"]["conclusion"], "Zna definicije, mesa primenu.")
        self.assertEqual(self.schedule(self.mcq)["seen_count"], 1, "lokalna ocena se ne dira")

    def test_review_without_key_says_so_and_keeps_answers(self):
        self.answer_text_questions()
        settings_store.set_value("gemini_api_key", "")
        with mock.patch(GENERATE) as generate:
            with self.assertRaises(HttpError) as caught:
                study.review(self.session_id)
        generate.assert_not_called()
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(study.summary(self.session_id)["pending"], 3)

    def test_review_is_measured_against_the_source_material(self):
        """"Proveri na osnovu skripte": u prompt ide izvod iz kog je pitanje pravljeno."""
        material_id = db.insert("material", {
            "category_id": self.category["id"], "filename": "skripta.pdf",
            "stored_name": "skripta.pdf", "rel_path": "materials/skripta.pdf",
        })
        chunk_id = db.insert("material_chunk", {
            "material_id": material_id, "ordinal": 0, "label": "strana 12",
            "text": "Izvod funkcije je granicna vrednost kolicnika prirastaja.",
        })
        run_id = db.insert("generation_run", {
            "category_id": self.category["id"], "chunk_ids": json.dumps([chunk_id]),
        })
        db.execute("UPDATE question SET generation_run_id = ? WHERE id = ?", (run_id, self.essay["id"]))

        study.answer(self.session_id, self.essay["id"], {"answer": {"text": "Brzina promene."}})
        with mock.patch(GENERATE, return_value=_reply(
                [{"n": 1, "score": 0.4, "is_correct": False, "feedback": "Fali granica."}])) as generate:
            study.review(self.session_id)

        prompt = generate.call_args.args[1]
        self.assertIn("granicna vrednost kolicnika prirastaja", prompt)
        self.assertIn("skripta.pdf - strana 12", prompt)

    def test_concurrent_review_of_the_same_session_is_refused(self):
        """Dupli klik ne sme da oceni iste odgovore dvaput."""
        self.answer_text_questions()
        study._reviewing.add(self.session_id)
        try:
            with mock.patch(GENERATE) as generate:
                with self.assertRaises(HttpError) as caught:
                    study.review(self.session_id)
            generate.assert_not_called()
            self.assertEqual(caught.exception.status, 409)
        finally:
            study._reviewing.discard(self.session_id)
