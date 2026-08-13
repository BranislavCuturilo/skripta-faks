"""Baza: deljenje SQL skripte, migracije, i dokaz da predohran ume da padne."""

from app import config, db

from .base import PROJECT_DATA_DIR, AppTestCase, _assert_safe


class StatementSplitTests(AppTestCase):
    def test_splits_on_top_level_semicolons(self):
        parts = db.statements("CREATE TABLE a (id INT); CREATE INDEX i ON a(id);")
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].startswith("CREATE TABLE"))
        self.assertTrue(parts[1].startswith("CREATE INDEX"))

    def test_semicolon_inside_string_does_not_split(self):
        parts = db.statements("INSERT INTO t (v) VALUES ('a;b'); SELECT 1;")
        self.assertEqual(len(parts), 2)
        self.assertIn("'a;b'", parts[0])

    def test_escaped_quote_inside_string(self):
        parts = db.statements("INSERT INTO t (v) VALUES ('it''s; fine'); SELECT 1;")
        self.assertEqual(len(parts), 2)
        self.assertIn("it''s; fine", parts[0])

    def test_line_comment_is_dropped(self):
        parts = db.statements("-- komentar sa ; unutra\nSELECT 1;")
        self.assertEqual(parts, ["SELECT 1"])


class MigrationTests(AppTestCase):
    def test_schema_is_fully_applied(self):
        self.assertEqual(db.scalar("PRAGMA user_version"), len(db.MIGRATIONS))

    def test_running_again_applies_nothing(self):
        self.assertEqual(db.init_db(), 0)

    def test_every_migration_table_exists(self):
        names = {
            row["name"]
            for row in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        for expected in ("category", "material", "question", "question_meta", "attempt",
                         "question_schedule", "strategy", "misconception"):
            self.assertIn(expected, names)

    def test_foreign_keys_are_enforced(self):
        with self.assertRaises(Exception):
            db.execute("INSERT INTO material (category_id, filename, stored_name, rel_path) "
                       "VALUES (99999, 'x', 'x', 'x')")


class SafetyGuardTests(AppTestCase):
    def test_guard_passes_while_pointed_at_temp_dir(self):
        _assert_safe()
        self.assertNotEqual(config.DATA_DIR.resolve(), PROJECT_DATA_DIR)

    def test_guard_actually_fails_when_pointed_at_real_data(self):
        """Provera koja nikad nije pala nije provera - ovde je namerno rusimo."""
        original = config.DATA_DIR
        config.DATA_DIR = PROJECT_DATA_DIR
        try:
            with self.assertRaises(AssertionError):
                _assert_safe()
        finally:
            config.DATA_DIR = original
        _assert_safe()
