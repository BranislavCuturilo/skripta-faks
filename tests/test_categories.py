"""Stablo kategorija: dubina, ciklusi, nasledjivanje uputstva."""

from app.http_util import HttpError
from app.services import categories

from .base import AppTestCase


class TreeTests(AppTestCase):
    def test_tree_has_no_depth_limit(self):
        node = self.make_category("Matematika 2")
        chain = [node["id"]]
        for level in range(6):
            node = categories.create(name=f"Nivo {level}", parent_id=node["id"])
            chain.append(node["id"])

        self.assertEqual(categories.subtree_ids(chain[0]), chain)
        self.assertEqual(len(categories.ancestors(chain[-1])), len(chain) - 1)

    def test_subtree_includes_every_descendant(self):
        root = self.make_category("Predmet")
        first = categories.create(name="Kolokvijum 1", parent_id=root["id"])
        second = categories.create(name="Kolokvijum 2", parent_id=root["id"])
        deep = categories.create(name="Oblast", parent_id=first["id"])

        found = set(categories.subtree_ids(root["id"]))
        self.assertEqual(found, {root["id"], first["id"], second["id"], deep["id"]})
        self.assertNotIn(second["id"], categories.subtree_ids(first["id"]))

    def test_moving_into_own_subtree_is_refused(self):
        root = self.make_category("Predmet")
        child = categories.create(name="Kolokvijum", parent_id=root["id"])
        grandchild = categories.create(name="Oblast", parent_id=child["id"])

        with self.assertRaises(HttpError):
            categories.move(root["id"], grandchild["id"])
        with self.assertRaises(HttpError):
            categories.move(root["id"], root["id"])

        # Dozvoljen premestaj i dalje radi - inace bi test prosao i da je sve zabranjeno.
        other = self.make_category("Drugi predmet")
        moved = categories.move(child["id"], other["id"])
        self.assertEqual(moved["parent_id"], other["id"])

    def test_slug_is_unique_per_parent_only(self):
        first = self.make_category("Analiza")
        second = self.make_category("Analiza")
        self.assertNotEqual(first["slug"], second["slug"])

        child_a = categories.create(name="Deo", parent_id=first["id"])
        child_b = categories.create(name="Deo", parent_id=second["id"])
        self.assertEqual(child_a["slug"], child_b["slug"])

    def test_slug_transliterates_serbian_letters(self):
        node = self.make_category("Čvrsto Đubrivo Šuma Žito Ćup")
        self.assertEqual(node["slug"], "cvrsto-djubrivo-suma-zito-cup")


class StudyPromptTests(AppTestCase):
    def test_prompt_is_inherited_down_the_chain(self):
        root = self.make_category("Matematika 2", study_prompt="Oznake iz skripte.")
        colloquium = categories.create(
            name="Kolokvijum 1", parent_id=root["id"], study_prompt="Samo lekcije 1-5."
        )
        area = categories.create(name="Integrali", parent_id=colloquium["id"])

        effective = categories.effective_study_prompt(area["id"])
        self.assertIn("Oznake iz skripte.", effective)
        self.assertIn("Samo lekcije 1-5.", effective)
        self.assertLess(
            effective.index("Oznake iz skripte."),
            effective.index("Samo lekcije 1-5."),
            "roditeljsko uputstvo mora da stoji pre detetovog",
        )

    def test_empty_prompts_are_skipped(self):
        root = self.make_category("Predmet")
        child = categories.create(name="Kolokvijum", parent_id=root["id"], study_prompt="Do 5.")
        self.assertEqual(categories.effective_study_prompt(child["id"]), "[Kolokvijum] Do 5.")


class CountersTests(AppTestCase):
    def test_parent_totals_roll_up_from_children(self):
        root = self.make_category("Predmet")
        child = categories.create(name="Kolokvijum", parent_id=root["id"])
        self.make_question(child["id"])
        self.make_question(child["id"], stem="Koliko je 3 + 3?",
                           payload={"options": ["5", "6"], "correct_index": 1})

        tree = categories.tree()
        root_node = next(node for node in tree if node["id"] == root["id"])
        self.assertEqual(root_node["own_questions"], 0)
        self.assertEqual(root_node["total_questions"], 2)
        self.assertEqual(root_node["children"][0]["own_questions"], 2)
