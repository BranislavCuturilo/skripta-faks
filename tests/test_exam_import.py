"""Doslovan uvoz ispitnih pitanja: parser, ugovor, provera doslovnosti, filter.

Zahtev: fiksna lista pitanja sa fakulteta ulazi u aplikaciju 1:1 - nista se ne
parafrazira, nista se ne dodaje, redosled odgovora ostaje kao u dokumentu.
"""

import json

from app import db
from app.extract import exam_parser
from app.quiz import scheduler
from app.services import exam_import, questions, study

from .base import AppTestCase
from .test_http import HttpTestCase

SAMPLE = """\
BAZA PITANJA - OBUKA

1. Koji od 4 dokumenta obuke ima za cilj da identifikuje temu i cilj procene
za svaki predmet?
a) Plan procene obučenosti polaznika obuke *
b) Program obuke
c) Plan obuke
d) Plan časa ili plan nastavnih situacija

2. Program obuke donosi:
a) direktor
*b) ministar
c) nastavnik

3. Obuka traje tri meseca.
a) Tačno
b) Netačno
Tačan odgovor: b

4. Kako se zove dokument koji propisuje sadržaj obuke?
Odgovor: Program obuke

5. Šta je f(x) ako je x = 2?
a) f(x) = 4
b) f(x) = 2

6. Koji su ciljevi obuke? (više tačnih)
a) sticanje znanja
b) zabava
c) sticanje veština

7. Pitanje bez oznacenog odgovora?
a) prvo
b) drugo

Odgovori:
5. a
6. a, c
"""


class ExamParserTests(AppTestCase):
    def test_recognises_questions_options_and_markers(self):
        report = exam_parser.parse(SAMPLE)
        self.assertEqual([question.number for question in report.questions], [1, 2, 3, 4, 5, 6, 7])

        first = report.questions[0]
        self.assertTrue(first.stem.startswith("Koji od 4 dokumenta obuke"))
        self.assertTrue(first.stem.endswith("za svaki predmet?"), "prelomljen red se lepi na pitanje")
        self.assertEqual([option.text for option in first.options][:2],
                         ["Plan procene obučenosti polaznika obuke", "Program obuke"])
        self.assertEqual([option.correct for option in first.options], [True, False, False, False])

        self.assertEqual([option.correct for option in report.questions[1].options], [False, True, False])
        self.assertEqual([option.correct for option in report.questions[2].options], [False, True])
        self.assertEqual(report.questions[3].answer_text, "Program obuke")

    def test_answer_key_at_the_end_marks_single_and_multiple(self):
        report = exam_parser.parse(SAMPLE)
        self.assertEqual(report.answer_key, {5: [0], 6: [0, 2]})
        self.assertEqual([option.correct for option in report.questions[4].options], [True, False])
        self.assertEqual([option.correct for option in report.questions[5].options], [True, False, True])

    def test_f_of_x_is_not_a_correct_marker(self):
        report = exam_parser.parse(SAMPLE)
        self.assertEqual(report.questions[4].options[1].text, "f(x) = 2")

    def test_contract_items_keep_option_order_and_types(self):
        report = exam_parser.parse(SAMPLE)
        items, skipped = exam_parser.to_contract_items(report, keep_order=True, source_ref="baza.pdf")
        by_number = {item["source_ref"].rsplit(" ", 1)[-1]: item for item in items}
        self.assertEqual(by_number["1"]["type"], "mcq_single")
        self.assertEqual(by_number["1"]["payload"]["correct_index"], 0)
        self.assertFalse(by_number["1"]["payload"]["shuffle"], "redosled kao u dokumentu")
        self.assertEqual(by_number["3"]["type"], "true_false")
        self.assertFalse(by_number["3"]["payload"]["correct"])
        self.assertEqual(by_number["4"]["type"], "short_answer")
        self.assertEqual(by_number["4"]["payload"]["accepted"], ["Program obuke"])
        self.assertEqual(by_number["6"]["type"], "mcq_multi")
        self.assertEqual(by_number["6"]["payload"]["correct_indices"], [0, 2])
        self.assertEqual([item["number"] for item in skipped], [7])
        self.assertIn("Nema oznacenog tacnog odgovora", skipped[0]["reason"])

    def test_shuffle_is_on_when_order_is_not_kept(self):
        report = exam_parser.parse(SAMPLE)
        items, _ = exam_parser.to_contract_items(report, keep_order=False)
        self.assertTrue(items[0]["payload"]["shuffle"])

    def test_cyrillic_document_and_pitanje_prefix_with_numbered_options(self):
        text = """\
Питање 1. Ко доноси програм обуке?
1) директор
2) министар *
3) наставник

Питање 2. Обука је обавезна.
а) тачно
б) нетачно
Тачан одговор: а
"""
        report = exam_parser.parse(text)
        self.assertEqual(len(report.questions), 2)
        self.assertEqual([option.correct for option in report.questions[0].options], [False, True, False])
        items, skipped = exam_parser.to_contract_items(report)
        self.assertEqual(skipped, [])
        self.assertEqual(items[1]["type"], "true_false")
        self.assertTrue(items[1]["payload"]["correct"])

    def test_star_bullets_are_a_list_when_all_options_have_them(self):
        text = "1. Pitanje?\n* prvo\n* drugo\n* trece\n"
        report = exam_parser.parse(text)
        self.assertEqual([option.correct for option in report.questions[0].options], [False, False, False])
        text = "1. Pitanje?\n- prvo\n* drugo\n- trece\n"
        report = exam_parser.parse(text)
        self.assertEqual([option.correct for option in report.questions[0].options], [False, True, False])

    def test_years_and_random_numbers_are_not_questions(self):
        text = "1. Kada je doneta uredba?\na) 2019. godine\nb) 2020. godine *\nTekst 2024. nije pitanje.\n"
        report = exam_parser.parse(text)
        self.assertEqual(len(report.questions), 1)
        self.assertEqual(len(report.questions[0].options), 2)


class ExamImportServiceTests(AppTestCase):
    def test_local_import_writes_verbatim_questions_with_exam_origin(self):
        category = self.make_category("Obuka")
        result = exam_import.import_local(category["id"], {"text": SAMPLE})
        self.assertEqual(result["inserted"], 6)
        self.assertEqual(result["rejected"], [])
        self.assertEqual([item["number"] for item in result["skipped"]], [7])

        rows = questions.list_for([category["id"]])["items"]
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["origin"] == "exam" for row in rows))
        stems = {row["stem"] for row in rows}
        self.assertIn("Program obuke donosi:", stems)
        first = next(row for row in rows if row["stem"].startswith("Koji od 4"))
        self.assertEqual(first["payload"]["options"][0], "Plan procene obučenosti polaznika obuke")
        self.assertFalse(first["presentation"]["shuffle"])

    def test_second_import_of_the_same_text_is_all_duplicates(self):
        category = self.make_category("Obuka")
        exam_import.import_local(category["id"], {"text": SAMPLE})
        again = exam_import.import_local(category["id"], {"text": SAMPLE})
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(again["duplicates"], 6)

    def test_preview_writes_nothing(self):
        category = self.make_category("Obuka")
        preview = exam_import.preview(category["id"], {"text": SAMPLE})
        self.assertEqual(preview["stats"]["total"], 7)
        self.assertEqual(preview["importable"], 6)
        self.assertEqual(preview["recommendation"], "local")
        self.assertEqual(questions.list_for([category["id"]])["total"], 0)

    def test_empty_source_is_refused(self):
        category = self.make_category("Obuka")
        from app.http_util import HttpError

        with self.assertRaises(HttpError):
            exam_import.preview(category["id"], {"text": "   "})

    def test_transcribed_questions_must_exist_verbatim_in_the_source(self):
        haystack = SAMPLE
        model_output = [
            {
                "type": "mcq_single",
                "stem": "Program obuke donosi:",
                "payload": {"options": ["direktor", "ministar", "nastavnik"], "correct_index": 1},
                "answer_source": "document",
            },
            {
                # Model je "popravio" formulaciju - to nije doslovno.
                "type": "mcq_single",
                "stem": "Ko donosi program obuke?",
                "payload": {"options": ["direktor", "ministar", "nastavnik"], "correct_index": 1},
                "answer_source": "document",
            },
            {
                # Model je izmislio opciju.
                "type": "mcq_single",
                "stem": "Program obuke donosi:",
                "payload": {"options": ["direktor", "ministar", "rektor"], "correct_index": 1},
                "answer_source": "document",
            },
            {
                # Odgovor je odredio model - prolazi, ali sa flagom.
                "type": "mcq_single",
                "stem": "Pitanje bez oznacenog odgovora?",
                "payload": {"options": ["prvo", "drugo"], "correct_index": 0},
                "answer_source": "model",
            },
            {"type": "flashcard", "stem": "Nesto sto nije dozvoljeno", "payload": {"back": "x"}},
        ]
        accepted, rejected = exam_import.prepare_transcribed(model_output, haystack=haystack)
        self.assertEqual([item["stem"] for item in accepted],
                         ["Program obuke donosi:", "Pitanje bez oznacenog odgovora?"])
        self.assertEqual(accepted[0]["flags"], {"flag_check_source": False})
        self.assertEqual(accepted[1]["flags"], {"flag_check_source": True})
        self.assertFalse(accepted[0]["payload"]["shuffle"])
        reasons = [item["reason"] for item in rejected]
        self.assertEqual(len(reasons), 3)
        self.assertIn("nije nadjen doslovno", reasons[0])
        self.assertIn("rektor", reasons[1])
        self.assertIn("nije dozvoljen", reasons[2])

    def test_verbatim_check_survives_line_breaks_case_and_script(self):
        haystack = "1. Koji od 4 dokumenta obuke ima za cilj da\nidentifikuje temu?\na) Plan obuke\n"
        model_output = [{
            "type": "mcq_single",
            "stem": "Који од 4 документа обуке има за циљ да идентификује тему?",
            "payload": {"options": ["PLAN OBUKE", "Program"], "correct_index": 0},
            "answer_source": "document",
        }]
        accepted, rejected = exam_import.prepare_transcribed(model_output, haystack=haystack, strict=False)
        self.assertEqual(len(accepted), 1)
        accepted, rejected = exam_import.prepare_transcribed(model_output, haystack=haystack, strict=True)
        self.assertEqual(accepted, [])
        self.assertIn("Program", rejected[0]["reason"], "opcija koje nema u izvoru se odbija")

    def test_scan_without_text_flags_everything_for_review(self):
        model_output = [{
            "type": "true_false", "stem": "Obuka traje tri meseca.",
            "payload": {"correct": False}, "answer_source": "document",
        }]
        accepted, _ = exam_import.prepare_transcribed(model_output, haystack=None)
        self.assertTrue(accepted[0]["flags"]["flag_check_source"])

    def test_flags_are_written_on_insert(self):
        category = self.make_category("Obuka")
        accepted, _ = exam_import.prepare_transcribed(
            [{"type": "true_false", "stem": "Obuka traje tri meseca.", "payload": {"correct": False},
              "answer_source": "model"}],
            haystack=SAMPLE,
        )
        result = questions.insert_many(category["id"], None, accepted, origin="exam")
        row = questions.get(result["inserted"][0])
        self.assertTrue(row["flags"]["flag_check_source"])
        self.assertEqual(row["origin"], "exam")


class ExamStudyFilterTests(AppTestCase):
    def test_session_can_be_limited_to_exam_questions(self):
        category = self.make_category("Obuka")
        self.make_question(category["id"], stem="AI pitanje broj jedan?")
        exam_import.import_local(category["id"], {"text": SAMPLE})

        only_exam = scheduler.pick([category["id"]], limit=50, origin="exam")
        self.assertEqual(len(only_exam), 6)
        everything = scheduler.pick([category["id"]], limit=50)
        self.assertEqual(len(everything), 7)

        session = study.start(category["id"], {"origin_filter": "exam", "length": 50})
        self.assertEqual(session["planned"], 6)
        step = study.next_question(session["session"]["id"])
        self.assertEqual(step["question"]["origin"], "exam")

        counts = questions.origin_counts([category["id"]])
        self.assertEqual(counts, {"ai": 1, "exam": 6})

    def test_unknown_origin_filter_is_refused(self):
        from app.http_util import HttpError

        category = self.make_category("Obuka")
        self.make_question(category["id"])
        with self.assertRaises(HttpError):
            study.start(category["id"], {"origin_filter": "nesto"})


class ExamApiTests(HttpTestCase):
    def test_preview_and_local_import_over_http(self):
        category = self.call("POST", "/api/categories", {"name": "Obuka"}, expect=201)["category"]
        preview = self.call("POST", f"/api/categories/{category['id']}/exam/preview", {"text": SAMPLE})
        self.assertEqual(preview["importable"], 6)
        self.assertEqual(preview["questions"][0]["correct"], "Plan procene obučenosti polaznika obuke")

        result = self.call("POST", f"/api/categories/{category['id']}/exam/import",
                           {"text": SAMPLE, "mode": "local"})
        self.assertEqual(result["inserted"], 6)

        listing = self.call("GET", f"/api/categories/{category['id']}/questions?origin=exam")
        self.assertEqual(listing["total"], 6)
        self.assertEqual(listing["origin_counts"], {"exam": 6})

        runs = self.call("GET", f"/api/categories/{category['id']}/runs")["runs"]
        self.assertEqual(runs[0]["source_kind"], "exam_local")

    def test_ai_mode_without_key_fails_inside_the_job(self):
        category = self.call("POST", "/api/categories", {"name": "Obuka"}, expect=201)["category"]
        response = self.call("POST", f"/api/categories/{category['id']}/exam/import",
                             {"text": SAMPLE, "mode": "ai"}, expect=202)
        import time

        from app.services import jobs

        for _ in range(50):
            record = jobs.snapshot(response["job"]["id"])
            if record["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(record["status"], "failed")
        self.assertIn("Gemini API", record["error"])
