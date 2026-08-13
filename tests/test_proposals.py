"""Predlozi za nadogradnju i mapa projekta.

Mapa je jedini razlog zbog kog AI asistent nece nagadjati, pa mora da bude
generisana iz stvarnog koda - a ne prepisana napamet. Zato se ovde proverava da
u njoj pisu fajlovi i rute koji zaista postoje.
"""

from app import config
from app.http_util import HttpError
from app.router import router
from app.services import proposals

from .base import AppTestCase


class ContextTests(AppTestCase):
    def test_context_is_generated_when_missing(self):
        config.CONTEXT_FILE.unlink(missing_ok=True)
        self.assertFalse(config.CONTEXT_FILE.is_file())

        text = proposals.context_text()
        self.assertTrue(config.CONTEXT_FILE.is_file())
        self.assertGreater(len(text), 2000)

    def test_context_lists_files_that_really_exist(self):
        text = proposals.context_text()
        for expected in ("app/db.py", "app/quiz/types.py", "web/js/render.js", "run_tests.py"):
            self.assertIn(expected, text, expected)
            if expected.endswith(".py") or expected.endswith(".js"):
                self.assertTrue((config.BASE_DIR / expected).is_file(),
                                f"mapa pominje {expected}, a fajla nema")

    def test_context_lists_real_routes(self):
        text = proposals.context_text()
        patterns = {route.pattern for route in router.entries()}
        for pattern in ("/api/health", "/api/bootstrap", "/api/network"):
            self.assertIn(pattern, patterns, "test ocekuje rutu koja ne postoji")
            self.assertIn(pattern, text, pattern)

    def test_context_carries_the_hard_rules(self):
        text = proposals.context_text()
        self.assertIn("Nula spoljnih zavisnosti", text)
        self.assertIn("AI nikad ne menja izvorni kod", text)
        self.assertIn("contract.py", text)

    def test_context_lists_every_question_type(self):
        from app.quiz import types as question_types

        text = proposals.context_text()
        for item in question_types.all_types():
            self.assertIn(item.key, text, item.key)

    def test_regenerating_overwrites(self):
        config.CONTEXT_FILE.write_text("zastarelo", "utf-8")
        self.assertTrue(proposals.regenerate_context())
        self.assertNotEqual(config.CONTEXT_FILE.read_text("utf-8"), "zastarelo")


class ManualProposalTests(AppTestCase):
    def test_written_and_listed(self):
        created = proposals.create_manual("Hoću tamniju temu", "Trenutna je presvetla noću.")
        self.assertTrue(created["slug"].startswith("predlog-0001-"))

        listed = proposals.list_all()
        self.assertEqual(len(listed), 1)
        self.assertIn("Hoću tamniju temu", listed[0]["title"])

        read = proposals.read(created["slug"])
        self.assertIn("presvetla", read["text"])

    def test_numbering_increments(self):
        first = proposals.create_manual("Prvi predlog", "telo")
        second = proposals.create_manual("Drugi predlog", "telo")
        self.assertIn("0001", first["slug"])
        self.assertIn("0002", second["slug"])

    def test_serbian_letters_become_ascii_slug(self):
        created = proposals.create_manual("Šira podešavanja za čitanje", "telo")
        self.assertIn("sira-podesavanja-za-citanje", created["slug"])

    def test_empty_title_is_refused(self):
        with self.assertRaises(HttpError):
            proposals.create_manual("   ", "telo")

    def test_delete_removes_the_file(self):
        created = proposals.create_manual("Za brisanje", "telo")
        proposals.delete(created["slug"])
        self.assertEqual(proposals.list_all(), [])
        with self.assertRaises(HttpError):
            proposals.read(created["slug"])


class PathSafetyTests(AppTestCase):
    def test_traversal_in_slug_is_refused(self):
        for slug in ("../../app/db", "..\\..\\app\\db", "predlog-0001-../../secret", "random"):
            with self.assertRaises(HttpError, msg=slug):
                proposals.read(slug)

    def test_valid_slug_still_works(self):
        """Uz svaku proveru odsustva ide i provera prisustva - inace bi test
        prosao i da je citanje potpuno pokvareno."""
        created = proposals.create_manual("Ispravan predlog", "telo")
        self.assertIn("telo", proposals.read(created["slug"])["text"])


class AiProposalTests(AppTestCase):
    def test_short_request_is_refused_before_any_call(self):
        with self.assertRaises(HttpError) as caught:
            proposals.create("kratko")
        self.assertEqual(caught.exception.status, 400)

    def test_without_api_key_it_says_so(self):
        with self.assertRaises(HttpError) as caught:
            proposals.create("Hoću da mogu da slikam rešenje i za hemiju, ne samo za matematiku.")
        self.assertEqual(caught.exception.status, 400)
        self.assertIn("ključ", caught.exception.message)


class RenderTests(AppTestCase):
    """Frontend iz predloga vadi poslednji ``` blok ispod naslova 'Nalog za AI
    asistenta'. Ako se format promeni, dugme 'Kopiraj nalog' tiho prestane da
    radi - zato je oblik ovde pinovan."""

    PAYLOAD = {
        "title": "Foto-odgovor i za hemiju",
        "understood": "Hoćeš da slikaš rešenje i kod hemije.",
        "feasible": True,
        "approach": "Tip work_it_out se već koristi; treba ga ponuditi i za te kategorije.",
        "files": [{"path": "app/quiz/types.py", "change": "bez izmene"}],
        "must_not_break": ["postojeća pitanja"],
        "questions": [],
        "effort": "mali",
        "claude_brief": "Dodaj podrsku za foto-odgovor u svim kategorijama.",
    }

    def test_brief_sits_in_a_fenced_block(self):
        text = proposals._render(7, "hoću ovo", self.PAYLOAD, "gemini-2.5-pro")
        self.assertIn("## Nalog za AI asistenta", text)

        after = text.split("Nalog za AI asistenta", 1)[1]
        start = after.index("```") + 3
        end = after.index("```", start)
        self.assertEqual(after[start:end].strip(), self.PAYLOAD["claude_brief"])

    def test_header_carries_number_and_title(self):
        text = proposals._render(7, "hoću ovo", self.PAYLOAD, "gemini-2.5-pro")
        self.assertTrue(text.startswith("# Predlog 0007 — Foto-odgovor i za hemiju"))

    def test_infeasible_request_is_flagged_at_the_top(self):
        payload = {**self.PAYLOAD, "feasible": False,
                   "breaks_rules": "Traži spoljnu biblioteku."}
        text = proposals._render(8, "hoću ovo", payload, "gemini-2.5-pro")
        self.assertIn("Pažnja", text)
        self.assertIn("Traži spoljnu biblioteku.", text)

        # A izvodljiv predlog to upozorenje NEMA - inace bi provera bila prazna.
        clean = proposals._render(9, "hoću ovo", self.PAYLOAD, "gemini-2.5-pro")
        self.assertNotIn("Pažnja", clean)

    def test_user_request_is_quoted_verbatim(self):
        text = proposals._render(1, "prvi red\ndrugi red", self.PAYLOAD, "gemini")
        self.assertIn("> prvi red", text)
        self.assertIn("> drugi red", text)
