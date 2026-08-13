"""Kroz pravi HTTP server, od zahteva do baze.

Ovo je jedini test koji vozi pravi ulaz aplikacije - ruter, parsiranje tela,
multipart upload, JSON odgovore. Sve ostalo ide oko servera, pa greska u
serveru ne bi bila vidljiva nigde drugde.
"""

import json
import threading
import time
import urllib.error
import urllib.request
import uuid

from app import server
from app.services import jobs

from .base import AppTestCase


class HttpTestCase(AppTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.port = server.find_free_port(8791, 40)
        cls.httpd = server.build(cls.port, host="127.0.0.1")
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)
        super().tearDownClass()

    # ------------------------------------------------------------------ client

    def call(self, method, path, payload=None, expect=200, raw_body=None, content_type=None):
        data = None
        headers = {}
        if raw_body is not None:
            data = raw_body
            headers["Content-Type"] = content_type or "application/octet-stream"
        elif payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(self.base + path, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status, body, ctype = response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            status, body, ctype = exc.code, exc.read(), exc.headers.get("Content-Type", "")

        self.assertEqual(status, expect, f"{method} {path} -> {status}: {body[:300]}")
        if "application/json" in ctype:
            return json.loads(body.decode("utf-8"))
        return body

    def upload(self, path, filename, content: bytes, fields=None, expect=201):
        """expect=201 kad se nesto novo sacuva, 200 kad je sve duplikat ili odbijeno."""
        boundary = f"----test{uuid.uuid4().hex}"
        parts = []
        for key, value in (fields or {}).items():
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n".encode()
        )
        parts.append(content)
        parts.append(f"\r\n--{boundary}--\r\n".encode())
        return self.call(
            "POST", path, expect=expect, raw_body=b"".join(parts),
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def wait_for_job(self, job_id, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = jobs.snapshot(job_id)
            if record and record["status"] != "running":
                return record
            time.sleep(0.05)
        self.fail(f"posao {job_id} nije zavrsio u {timeout}s")


class BasicRoutingTests(HttpTestCase):
    def test_health(self):
        payload = self.call("GET", "/api/health")
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["version"])

    def test_bootstrap_carries_everything_the_first_screen_needs(self):
        payload = self.call("GET", "/api/bootstrap")
        self.assertTrue(payload["ok"])
        self.assertIn("settings", payload)
        self.assertIn("tree", payload)
        self.assertEqual(len(payload["question_types"]), 15)

    def test_unknown_api_route_is_404(self):
        body = self.call("GET", "/api/nema-ovoga", expect=404)
        self.assertFalse(body["ok"])

    def test_wrong_method_is_405(self):
        self.call("DELETE", "/api/health", expect=405)

    def test_broken_json_body_is_400_not_500(self):
        body = self.call("POST", "/api/categories", expect=400,
                         raw_body=b"{ ovo nije json", content_type="application/json")
        self.assertFalse(body["ok"])

    def test_json_array_body_is_400_not_500(self):
        """Validan JSON koji nije objekat je greska klijenta, ne pad servera."""
        body = self.call("POST", "/api/categories", expect=400,
                         raw_body=b"[1, 2, 3]", content_type="application/json")
        self.assertFalse(body["ok"])

    def test_media_path_traversal_is_refused(self):
        self.call("GET", "/media/../../app/config.py", expect=404)
        self.call("GET", "/media/..%2f..%2fapp%2fconfig.py", expect=404)

    def test_index_page_is_served(self):
        body = self.call("GET", "/")
        self.assertIn(b"<", body[:200], "index.html mora da se servira sa korena")


class CategoryApiTests(HttpTestCase):
    def test_create_read_move_delete(self):
        created = self.call("POST", "/api/categories",
                            {"name": "Matematika 2", "study_prompt": "Oznake iz skripte."},
                            expect=201)
        root_id = created["category"]["id"]

        child = self.call("POST", "/api/categories",
                          {"name": "Kolokvijum 1", "parent_id": root_id,
                           "study_prompt": "Samo lekcije 1-5."},
                          expect=201)["category"]

        detail = self.call("GET", f"/api/categories/{child['id']}")
        self.assertIn("Oznake iz skripte.", detail["effective_prompt"])
        self.assertIn("Samo lekcije 1-5.", detail["effective_prompt"])
        self.assertEqual(len(detail["breadcrumb"]), 2)

        tree = self.call("GET", "/api/categories")["tree"]
        self.assertEqual(len(tree), 1)
        self.assertEqual(len(tree[0]["children"]), 1)

        moved = self.call("POST", f"/api/categories/{child['id']}/move", {"parent_id": None})
        self.assertIsNone(moved["category"]["parent_id"])

        self.call("DELETE", f"/api/categories/{root_id}", expect=400)
        self.call("DELETE", f"/api/categories/{root_id}?confirm=1")
        self.assertEqual(len(self.call("GET", "/api/categories")["tree"]), 1)

    def test_cycle_move_is_refused_over_http(self):
        root = self.call("POST", "/api/categories", {"name": "Predmet"}, expect=201)["category"]
        child = self.call("POST", "/api/categories",
                          {"name": "Deo", "parent_id": root["id"]}, expect=201)["category"]
        self.call("POST", f"/api/categories/{root['id']}/move",
                  {"parent_id": child["id"]}, expect=400)

    def test_missing_name_is_refused(self):
        self.call("POST", "/api/categories", {"name": "   "}, expect=400)


class MaterialApiTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.category = self.call("POST", "/api/categories", {"name": "Predmet"},
                                  expect=201)["category"]

    def test_upload_extracts_and_chunks(self):
        text = "Lekcija 1\n\n" + ("Integral je granicna vrednost sume proizvoda. " * 30)
        response = self.upload(
            f"/api/categories/{self.category['id']}/materials", "skripta.txt",
            text.encode("utf-8"), {"note": "glavna skripta"},
        )
        self.assertEqual(len(response["stored"]), 1)
        self.wait_for_job(response["job"]["id"])

        material_id = response["stored"][0]["id"]
        detail = self.call("GET", f"/api/materials/{material_id}")
        self.assertEqual(detail["material"]["extraction_status"], "local_ok")
        self.assertGreater(detail["material"]["char_count"], 100)
        self.assertIn("Integral", detail["preview"])
        self.assertIn("Lekcija 1", detail["outline"])

    def test_same_file_twice_is_recognised_as_duplicate(self):
        content = b"Neki sadrzaj skripte za proveru duplikata."
        first = self.upload(f"/api/categories/{self.category['id']}/materials", "a.txt", content)
        self.wait_for_job(first["job"]["id"])
        second = self.upload(f"/api/categories/{self.category['id']}/materials", "a.txt",
                             content, expect=200)
        self.assertEqual(len(second["stored"]), 0)
        self.assertEqual(len(second["duplicates"]), 1)

    def test_unsupported_extension_is_refused(self):
        response = self.upload(
            f"/api/categories/{self.category['id']}/materials", "virus.exe", b"MZ\x00\x00",
            expect=200,
        )
        self.assertEqual(len(response["stored"]), 0)
        self.assertEqual(len(response["failures"]), 1)
        self.assertIn("nije podržan", response["failures"][0]["error"])

    def test_uploaded_file_is_served_as_attachment(self):
        response = self.upload(f"/api/categories/{self.category['id']}/materials",
                               "beleske.txt", b"sadrzaj")
        self.wait_for_job(response["job"]["id"])
        material = self.call("GET", f"/api/materials/{response['stored'][0]['id']}")["material"]

        request = urllib.request.Request(self.base + "/media/" + material["rel_path"])
        with urllib.request.urlopen(request, timeout=10) as http_response:
            disposition = http_response.headers.get("Content-Disposition", "")
            self.assertIn("attachment", disposition,
                          "tekst i HTML se nikad ne serviraju inline - to bi bio XSS")


class StudyFlowTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.category = self.call("POST", "/api/categories", {"name": "Statistika"},
                                  expect=201)["category"]
        self.import_questions()

    def import_questions(self):
        payload = {"questions": [
            {"type": "mcq_single", "stem": "Koliko je 2 + 2?",
             "payload": {"options": ["3", "4", "5"], "correct_index": 1},
             "explanation": "Dva i dva je cetiri.", "topic": "sabiranje"},
            {"type": "true_false", "stem": "Verovatnoca je uvek izmedju 0 i 1.",
             "payload": {"correct": True}, "explanation": "Po definiciji.", "topic": "osnove"},
            {"type": "numeric", "stem": "Koliko je 10 podeljeno sa 4?",
             "payload": {"value": 2.5, "tolerance": 0.01}, "explanation": "2.5",
             "topic": "deljenje"},
        ]}
        result = self.call("POST", f"/api/categories/{self.category['id']}/generate/import",
                           {"text": json.dumps(payload)})
        self.assertEqual(result["inserted"], 3)
        self.assertEqual(result["rejected"], [])

    def test_import_rejects_bad_questions_but_keeps_good_ones(self):
        payload = {"questions": [
            {"type": "mcq_single", "stem": "Novo ispravno pitanje o medijani?",
             "payload": {"options": ["a", "b"], "correct_index": 0}},
            {"type": "mcq_single", "stem": "Pitanje bez opcija?", "payload": {}},
        ]}
        result = self.call("POST", f"/api/categories/{self.category['id']}/generate/import",
                           {"text": json.dumps(payload)})
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(result["rejected"]), 1)

    def test_import_of_the_same_batch_is_deduplicated(self):
        before = self.call("GET", f"/api/categories/{self.category['id']}/questions")["total"]
        payload = {"questions": [
            {"type": "mcq_single", "stem": "Koliko je 2 + 2?",
             "payload": {"options": ["5", "3", "4"], "correct_index": 2},
             "explanation": "Isto pitanje, izmesane opcije."},
        ]}
        result = self.call("POST", f"/api/categories/{self.category['id']}/generate/import",
                           {"text": json.dumps(payload)})
        self.assertEqual(result["inserted"], 0)
        self.assertEqual(result["duplicates"], 1)
        after = self.call("GET", f"/api/categories/{self.category['id']}/questions")["total"]
        self.assertEqual(before, after)

    def test_full_session_answer_and_summary(self):
        started = self.call("POST", "/api/study/start",
                            {"category_id": self.category["id"], "length": 3})
        session_id = started["session"]["id"]
        self.assertEqual(started["planned"], 3)

        answered = 0
        while True:
            step = self.call("GET", f"/api/study/{session_id}/next")
            if step["done"]:
                break
            question = step["question"]
            self.assertNotIn("payload", question, "tacan odgovor ne sme da stigne pre odgovora")
            self.assertNotIn("correct_text", question)

            answer = _correct_answer(question)
            result = self.call("POST", f"/api/study/{session_id}/answer",
                               {"question_id": question["id"], "answer": answer})
            self.assertTrue(result["is_correct"], f"{question['type']}: {result}")
            self.assertEqual(result["graded_by"], "local")
            self.assertTrue(result["feedback"])
            answered += 1

        self.assertEqual(answered, 3)
        summary = self.call("POST", f"/api/study/{session_id}/end")["summary"]
        self.assertEqual(summary["asked"], 3)
        self.assertEqual(summary["correct"], 3)
        self.assertEqual(summary["wrong"], [])

    def test_wrong_answer_returns_explanation_without_ai(self):
        started = self.call("POST", "/api/study/start",
                            {"category_id": self.category["id"], "length": 5,
                             "type_filter": ["mcq_single"]})
        step = self.call("GET", f"/api/study/{started['session']['id']}/next")
        question = step["question"]

        result = self.call("POST", f"/api/study/{started['session']['id']}/answer",
                           {"question_id": question["id"], "answer": {"index": 0}})
        self.assertFalse(result["is_correct"])
        self.assertEqual(result["graded_by"], "local")
        self.assertIn("cetiri", result["feedback"])
        self.assertEqual(result["correct_text"], "4")

    def test_skip_removes_question_from_this_session_only(self):
        started = self.call("POST", "/api/study/start",
                            {"category_id": self.category["id"], "length": 3})
        session_id = started["session"]["id"]
        first = self.call("GET", f"/api/study/{session_id}/next")["question"]

        self.call("POST", f"/api/study/{session_id}/skip",
                  {"question_id": first["id"], "reason": "skip"})
        following = self.call("GET", f"/api/study/{session_id}/next")["question"]
        self.assertNotEqual(following["id"], first["id"])

        other = self.call("POST", "/api/study/start",
                          {"category_id": self.category["id"], "length": 3})
        self.assertEqual(other["planned"], 3, "preskakanje vazi samo za tu sesiju")

    def test_ignore_forever_survives_the_session(self):
        started = self.call("POST", "/api/study/start",
                            {"category_id": self.category["id"], "length": 3})
        first = self.call("GET", f"/api/study/{started['session']['id']}/next")["question"]
        self.call("POST", f"/api/study/{started['session']['id']}/skip",
                  {"question_id": first["id"], "reason": "ignore_forever"})

        later = self.call("POST", "/api/study/start",
                          {"category_id": self.category["id"], "length": 5})
        self.assertEqual(later["planned"], 2)

    def test_unknown_skip_reason_is_refused(self):
        started = self.call("POST", "/api/study/start", {"category_id": self.category["id"]})
        question = self.call("GET", f"/api/study/{started['session']['id']}/next")["question"]
        self.call("POST", f"/api/study/{started['session']['id']}/skip",
                  {"question_id": question["id"], "reason": "izmisljeno"}, expect=400)


class QuestionMetaTests(HttpTestCase):
    def setUp(self):
        super().setUp()
        self.category = self.make_category("Predmet")
        self.question = self.make_question(self.category["id"])

    def test_note_and_flags_are_saved(self):
        result = self.call("POST", f"/api/questions/{self.question['id']}/meta", {
            "note": "Proveriti u skripti na strani 40.",
            "flag_review": True,
            "flag_check_source": True,
        })["question"]
        self.assertEqual(result["note"], "Proveriti u skripti na strani 40.")
        self.assertTrue(result["flags"]["flag_review"])
        self.assertTrue(result["flags"]["flag_check_source"])
        self.assertFalse(result["flags"]["flag_irrelevant"])

    def test_note_survives_editing_the_question(self):
        """Beleska zivi u question_meta bas zato da bi prezivela izmenu pitanja."""
        self.call("POST", f"/api/questions/{self.question['id']}/meta",
                  {"note": "Moja beleska."})
        self.call("PATCH", f"/api/questions/{self.question['id']}",
                  {"stem": "Koliko je dva plus dva?"})

        after = self.call("GET", f"/api/questions/{self.question['id']}")["question"]
        self.assertEqual(after["stem"], "Koliko je dva plus dva?")
        self.assertEqual(after["note"], "Moja beleska.")

    def test_invalid_edit_is_refused(self):
        self.call("PATCH", f"/api/questions/{self.question['id']}",
                  {"payload": {"options": ["a"], "correct_index": 5}}, expect=400)
        unchanged = self.call("GET", f"/api/questions/{self.question['id']}")["question"]
        self.assertEqual(unchanged["payload"]["correct_index"], 1)

    def test_filtering_by_flag(self):
        other = self.make_question(self.category["id"], stem="Drugo pitanje o zbiru?")
        self.call("POST", f"/api/questions/{other['id']}/meta", {"flag_review": True})

        flagged = self.call(
            "GET", f"/api/categories/{self.category['id']}/questions?flag=flag_review"
        )
        self.assertEqual(flagged["total"], 1)
        self.assertEqual(flagged["items"][0]["id"], other["id"])

        everything = self.call("GET", f"/api/categories/{self.category['id']}/questions")
        self.assertEqual(everything["total"], 2)

    def test_purge_removes_it_for_good(self):
        self.call("DELETE", f"/api/questions/{self.question['id']}")
        self.call("GET", f"/api/questions/{self.question['id']}", expect=404)


class SettingsApiTests(HttpTestCase):
    def test_api_key_is_never_returned_in_full(self):
        secret = "AIzaSyTAJNIKLJUC1234567890abc"
        self.call("PATCH", "/api/settings", {"gemini_api_key": secret})

        payload = self.call("GET", "/api/settings")["settings"]
        self.assertEqual(payload["gemini_api_key"], "")
        self.assertTrue(payload["gemini_api_key_set"])
        self.assertNotIn(secret, json.dumps(payload))
        self.assertIn("AIza", payload["gemini_api_key_hint"])

    def test_empty_string_does_not_wipe_the_key(self):
        self.call("PATCH", "/api/settings", {"gemini_api_key": "AIzaSyNESTO1234567890abc"})
        self.call("PATCH", "/api/settings", {"aggressiveness": 5, "gemini_api_key": ""})
        payload = self.call("GET", "/api/settings")["settings"]
        self.assertTrue(payload["gemini_api_key_set"])
        self.assertEqual(payload["aggressiveness"], 5)

    def test_delete_clears_the_key(self):
        self.call("PATCH", "/api/settings", {"gemini_api_key": "AIzaSyNESTO1234567890abc"})
        payload = self.call("DELETE", "/api/settings/api-key")["settings"]
        self.assertFalse(payload["gemini_api_key_set"])

    def test_types_are_preserved(self):
        self.call("PATCH", "/api/settings", {"aggressiveness": 4, "tts_enabled": True,
                                             "tts_rate": 1.25})
        payload = self.call("GET", "/api/settings")["settings"]
        self.assertIsInstance(payload["aggressiveness"], int)
        self.assertIs(payload["tts_enabled"], True)
        self.assertAlmostEqual(payload["tts_rate"], 1.25)


class NetworkGuardTests(HttpTestCase):
    def test_ai_calls_are_blocked_during_tests(self):
        """Predohran koji nikad nije pao nije predohran - ovde ga namerno gadjamo."""
        self.call("PATCH", "/api/settings", {"gemini_api_key": "AIzaSyLAZAN1234567890abc"})
        body = self.call("POST", "/api/settings/test-key", {})
        self.assertFalse(body["ok"])
        self.assertIn("blokirani", body.get("error", ""))


def _correct_answer(question: dict) -> dict:
    """Tacan odgovor izveden iz onoga sto klijent VIDI, ne iz baze."""
    kind = question["presentation"]["answer_kind"]
    if question["type"] == "true_false":
        return {"value": True}
    if question["type"] == "numeric":
        return {"value": 2.5}
    if kind == "choice":
        options = question["presentation"]["options"]
        return {"index": options.index("4")}
    raise AssertionError(f"test ne zna da odgovori na tip {question['type']}")
