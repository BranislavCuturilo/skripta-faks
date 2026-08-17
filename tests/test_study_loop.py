"""Petlja sesije: sta se desi POSLE netacnog odgovora, i kako radi kartica.

Dve primedbe korisnika su napisale ovaj modul:

1. "kada netacno se odgovori na pitanje ponavlja pitanje sto puta dok tacno ga
   ne odgovoris" - netacan odgovor gura pitanje na `due_at = +10 minuta` i obara
   mu mastery na dno, a adaptivni redosled bas to stavlja prvo. `next_question`
   zato vrati isto pitanje odmah. Ponavljanje pripada SLEDECOJ sesiji.
2. "kod kartica kad se okrene ne pise odgovor" - poledjina kartice nije stizala
   do frontenda pre ocenjivanja, pa se korisnik ocenjivao naslepo.
"""

from app.services import study

from .base import AppTestCase


class NoImmediateRepeatTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.category = self.make_category()
        self.questions = [
            self.make_question(
                self.category["id"],
                stem=f"Pitanje broj {index} o integralima?",
                payload={"options": ["a", "b", "c"], "correct_index": 0},
            )
            for index in range(4)
        ]

    def _start(self, length=4):
        started = study.start(self.category["id"], {"length": length, "aggressiveness": 3})
        return started["session"]["id"]

    def _answer_wrong(self, session_id, question):
        """`correct_index` je 0 u svim fixture pitanjima, pa je 1 uvek promasaj."""
        return study.answer(session_id, question["id"], {"answer": {"index": 1}})

    def test_wrong_answer_does_not_come_back_immediately(self):
        session_id = self._start()
        first = study.next_question(session_id)["question"]
        result = self._answer_wrong(session_id, first)
        self.assertFalse(result["is_correct"], "test trazi bas netacan odgovor")

        second = study.next_question(session_id)
        self.assertFalse(second["done"])
        self.assertNotEqual(
            second["question"]["id"],
            first["id"],
            "netacno odgovoreno pitanje se vratilo odmah - to je petlja koju je korisnik prijavio",
        )

    def test_session_walks_through_every_question_once(self):
        session_id = self._start(length=4)
        seen = []
        for _ in range(len(self.questions)):
            step = study.next_question(session_id)
            self.assertFalse(step["done"], f"sesija se zavrsila prerano, videno: {seen}")
            seen.append(step["question"]["id"])
            self._answer_wrong(session_id, step["question"])

        self.assertEqual(
            len(seen), len(set(seen)), f"isto pitanje se ponovilo u istoj sesiji: {seen}"
        )
        self.assertEqual(sorted(seen), sorted(item["id"] for item in self.questions))

    def test_session_ends_instead_of_repeating_when_pool_runs_out(self):
        """Sesija duza od broja pitanja se zavrsava, ne vrti u krug."""
        session_id = self._start(length=20)
        for _ in range(len(self.questions)):
            step = study.next_question(session_id)
            self.assertFalse(step["done"])
            self._answer_wrong(session_id, step["question"])

        step = study.next_question(session_id)
        self.assertTrue(step["done"], "nema vise novih pitanja - sesija mora da se zavrsi")

    def test_answered_question_returns_in_the_next_session(self):
        """Ne sme da se ponavlja SADA, ali mora da se vrati posle - inace bi
        popravka petlje ubila samo ponavljanje."""
        first_session = self._start()
        step = study.next_question(first_session)
        wrong_id = step["question"]["id"]
        self._answer_wrong(first_session, step["question"])
        study.end(first_session)

        second_session = self._start()
        picked = []
        for _ in range(len(self.questions)):
            step = study.next_question(second_session)
            if step["done"]:
                break
            picked.append(step["question"]["id"])
            study.answer(second_session, step["question"]["id"], {"answer": {"index": 0}})

        self.assertIn(wrong_id, picked, "pogresno odgovoreno mora da se vrati u sledecoj sesiji")

    def test_skipped_question_is_also_not_repeated(self):
        session_id = self._start()
        first = study.next_question(session_id)["question"]
        study.skip(session_id, first["id"], "skip")

        second = study.next_question(session_id)
        self.assertFalse(second["done"])
        self.assertNotEqual(second["question"]["id"], first["id"])


class FlashcardFlowTests(AppTestCase):
    """Kartica: poledjina mora da stigne PRE ocenjivanja, jer se korisnik
    ocenjuje sam - "znao sam / nisam znao" nema smisla ako odgovor ne vidi."""

    def setUp(self):
        super().setUp()
        self.category = self.make_category()
        self.card = self.make_question(
            self.category["id"],
            type="flashcard",
            stem="Sta je izvod funkcije?",
            payload={"back": "Granicna vrednost kolicnika prirastaja."},
            explanation="Definicija izvoda.",
        )

    def test_back_of_the_card_is_sent_before_the_answer(self):
        session_id = study.start(self.category["id"], {"length": 1})["session"]["id"]
        step = study.next_question(session_id)
        self.assertEqual(
            step["question"]["presentation"].get("back"),
            "Granicna vrednost kolicnika prirastaja.",
            "poledjina kartice mora da stigne uz pitanje - korisnik je vidi kad okrene",
        )

    def test_other_types_still_hide_their_answer(self):
        """Poledjina kartice sme napolje; tacan odgovor ostalih tipova ne sme.
        Bez ovog para, gornji test bi prosao i da smo poslali ceo payload."""
        mcq = self.make_question(
            self.category["id"],
            stem="Koliko je 7 + 1?",
            payload={"options": ["7", "8"], "correct_index": 1},
        )
        session_id = study.start(
            self.category["id"], {"length": 5, "type_filter": ["mcq_single"]}
        )["session"]["id"]
        step = study.next_question(session_id)

        self.assertEqual(step["question"]["id"], mcq["id"])
        presentation = step["question"]["presentation"]
        self.assertIn("options", presentation, "ponudjeni odgovori moraju da stignu")
        self.assertNotIn("correct_index", presentation, "tacan odgovor ne sme napolje")
        self.assertNotIn("payload", step["question"])
        self.assertNotIn("back", presentation)
