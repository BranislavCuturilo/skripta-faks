"""Raspored ponavljanja: forsiranje gresaka, agresivnost, izbor pitanja."""

from app import db
from app.quiz import scheduler
from app.services import questions

from .base import AppTestCase


class RecordTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.category = self.make_category()
        self.question = self.make_question(self.category["id"])

    def _schedule(self):
        return db.query_one(
            "SELECT * FROM question_schedule WHERE question_id = ?", (self.question["id"],)
        )

    def test_wrong_answer_comes_back_within_minutes(self):
        scheduler.record(self.question["id"], 0.0)
        row = self._schedule()
        soon = db.scalar(
            "SELECT CASE WHEN ? <= datetime('now', '+20 minutes') THEN 1 ELSE 0 END",
            (row["due_at"],),
        )
        self.assertEqual(soon, 1, f"promasaj mora brzo nazad, a due_at je {row['due_at']}")
        self.assertEqual(row["lapses"], 1)
        self.assertEqual(row["streak"], 0)

    def test_correct_answers_push_the_interval_out(self):
        intervals = []
        for _ in range(4):
            scheduler.record(self.question["id"], 1.0)
            intervals.append(self._schedule()["interval_days"])
        self.assertEqual(intervals, sorted(intervals), f"interval mora da raste: {intervals}")
        self.assertGreater(intervals[-1], intervals[0])
        self.assertEqual(self._schedule()["streak"], 4)

    def test_mastery_rises_with_success_and_falls_with_failure(self):
        for _ in range(5):
            scheduler.record(self.question["id"], 1.0)
        high = self._schedule()["mastery"]
        self.assertGreater(high, 0.7)

        scheduler.record(self.question["id"], 0.0)
        self.assertLess(self._schedule()["mastery"], high)

    def test_partial_score_is_neither_success_nor_lapse(self):
        scheduler.record(self.question["id"], 0.6)
        row = self._schedule()
        self.assertEqual(row["lapses"], 0)
        self.assertEqual(row["streak"], 0)

    def test_aggressiveness_shortens_intervals(self):
        second = self.make_question(self.category["id"], stem="Koliko je 5 + 5?",
                                    payload={"options": ["9", "10"], "correct_index": 1})
        for _ in range(3):
            scheduler.record(self.question["id"], 1.0, aggressiveness=1)
            scheduler.record(second["id"], 1.0, aggressiveness=5)

        relaxed = self._schedule()["interval_days"]
        strict = db.query_one(
            "SELECT interval_days FROM question_schedule WHERE question_id = ?", (second["id"],)
        )["interval_days"]
        self.assertLess(strict, relaxed, "moram-sve-da-znam mora da vraca cesce")

    def test_profile_thresholds_are_ordered(self):
        relaxed, _, relaxed_share = scheduler.profile(1)
        strict, _, strict_share = scheduler.profile(5)
        self.assertLess(relaxed, strict)
        self.assertGreater(relaxed_share, strict_share)


class PickTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.category = self.make_category()
        self.ids = [self.category["id"]]

    def _make(self, stem, **overrides):
        return self.make_question(
            self.category["id"],
            stem=stem,
            payload=overrides.pop("payload", {"options": ["a", "b"], "correct_index": 0}),
            **overrides,
        )

    def test_weak_questions_come_before_mastered_ones(self):
        weak = self._make("Slabo pitanje o integralima?")
        strong = self._make("Dobro pitanje o izvodima?")
        for _ in range(6):
            scheduler.record(strong["id"], 1.0, aggressiveness=3)
        scheduler.record(weak["id"], 0.0, aggressiveness=3)

        picked = scheduler.pick(self.ids, limit=2, aggressiveness=3)
        self.assertEqual(picked[0]["id"], weak["id"], "ono sto se gresi mora prvo")

    def test_mastered_questions_still_appear_sometimes(self):
        """'Provlaci tek povremeno' znaci povremeno, ne nikad."""
        mastered = self._make("Savladano pitanje?")
        for _ in range(8):
            scheduler.record(mastered["id"], 1.0, aggressiveness=1)

        picked = scheduler.pick(self.ids, limit=10, aggressiveness=1)
        self.assertIn(mastered["id"], [row["id"] for row in picked])

    def test_only_one_variant_per_group_per_session(self):
        for index in range(3):
            self._make(f"Varijanta broj {index} istog pitanja?", variant_group="grupa-1",
                       variant_index=index)
        self._make("Sasvim drugo pitanje?")

        picked = scheduler.pick(self.ids, limit=10, aggressiveness=3)
        groups = [row["variant_group"] for row in picked if row["variant_group"]]
        self.assertEqual(len(groups), len(set(groups)))
        self.assertEqual(len(picked), 2, "3 varijante + 1 drugo = 2 pitanja u sesiji")

    def test_ignored_and_deleted_are_excluded(self):
        kept = self._make("Pitanje koje ostaje?")
        ignored = self._make("Pitanje koje se zanemaruje?")
        deleted = self._make("Pitanje koje se brise?")
        questions.set_meta(ignored["id"], {"ignored": True})
        questions.set_meta(deleted["id"], {"deleted": True})

        picked = [row["id"] for row in scheduler.pick(self.ids, limit=10)]
        self.assertIn(kept["id"], picked)
        self.assertNotIn(ignored["id"], picked)
        self.assertNotIn(deleted["id"], picked)

    def test_type_filter_narrows_the_pool(self):
        self._make("Pitanje sa ponudjenim odgovorima?")
        self._make("Tvrdnja koju treba oceniti.", type="true_false", payload={"correct": True})

        only_tf = scheduler.pick(self.ids, limit=10, type_filter=["true_false"])
        self.assertEqual(len(only_tf), 1)
        self.assertEqual(only_tf[0]["type"], "true_false")

    def test_empty_category_returns_nothing(self):
        self.assertEqual(scheduler.pick([self.category["id"]], limit=5), [])
        self.assertEqual(scheduler.pick([], limit=5), [])

    def test_stats_count_the_buckets(self):
        unseen = self._make("Novo pitanje?")
        weak = self._make("Pitanje koje gresim?")
        scheduler.record(weak["id"], 0.0, aggressiveness=3)

        stats = scheduler.stats(self.ids, aggressiveness=3)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["unseen"], 1)
        self.assertEqual(stats["weak"], 1)
        self.assertEqual(stats["mastered"], 0)
        self.assertIn(unseen["id"], [row["id"] for row in scheduler.pick(self.ids, limit=5)])
