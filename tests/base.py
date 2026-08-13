"""Osnova za testove.

Dva nezavisna predohrana, oba obavezna:

1. `config.use_data_dir` na privremeni folder - baza je fizicki drugi fajl, ne
   ista baza sa drugim redovima
2. `_assert_safe` proverava ZIVU putanju na svakom setUp - ako neko sutra
   promeni redosled uvoza, test padne odmah umesto da obrise necije gradivo

Prvi je konfiguracija i moze da se pregazi; drugi gleda u ono sto je stvarno
podeseno i ne moze.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from app import config, db

PROJECT_DATA_DIR = (Path(__file__).resolve().parent.parent / "data").resolve()

_TABLES = (
    "attempt", "session_skip", "study_session", "explanation_cache",
    "question_schedule", "question_meta", "question", "generation_run",
    "material_chunk", "material", "material_note", "misconception",
    "strategy", "category", "setting", "ai_call_log",
)


def _assert_safe() -> None:
    if config.DATA_DIR.resolve() == PROJECT_DATA_DIR:
        raise AssertionError(
            "Testovi pokazuju na pravi data/ folder. Prekidam pre nego sto obrisem podatke."
        )


class AppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp_dir = tempfile.mkdtemp(prefix="skripta-test-")
        db.close_thread_connection()
        config.use_data_dir(cls._temp_dir)
        _assert_safe()
        db.init_db()

    @classmethod
    def tearDownClass(cls) -> None:
        db.close_thread_connection()
        shutil.rmtree(cls._temp_dir, ignore_errors=True)

    def setUp(self) -> None:
        _assert_safe()
        for table in _TABLES:
            db.execute(f"DELETE FROM {table}")

    # -------------------------------------------------------------- fixtures

    def make_category(self, name="Matematika 2", parent_id=None, study_prompt=""):
        from app.services import categories

        return categories.create(name=name, parent_id=parent_id, study_prompt=study_prompt)

    def make_question(self, category_id, **overrides):
        """Pitanje ide kroz isti ugovor kao AI izlaz - fixture ne sme da zaobidje
        provere koje stiti produkcioni put."""
        from app.ai import contract
        from app.services import questions

        item = {
            "type": "mcq_single",
            "stem": "Koliko je 2 + 2?",
            "payload": {"options": ["3", "4", "5"], "correct_index": 1},
            "explanation": "Zbir dva i dva je cetiri.",
            "difficulty": 1,
            "topic": "sabiranje",
        }
        item.update(overrides)
        validated = contract.validate_one(item)
        result = questions.insert_many(category_id, None, [validated])
        self.assertEqual(result["inserted_count"], 1, "fixture nije upisan")
        return questions.get(result["inserted"][0])
