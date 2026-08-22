import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import database
from migrations import CURRENT_SCHEMA_VERSION, UnsupportedSchemaVersionError


def _reading(date: str, *, total: int, a4_color: int, a4_bw: int) -> dict:
    return {
        "machine_name": "Test Machine",
        "serial": "SN-001",
        "date": date,
        "mode": "summary",
        "total_counter": total,
        "summary": {
            "total_color": a4_color,
            "total_bw": a4_bw,
            "total": total,
        },
        "paper_color": {
            "a4_color": a4_color,
            "a4_bw": a4_bw,
            "a3_color": 0,
            "a3_bw": 0,
        },
        "detail": {},
        "warnings": [],
    }


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.original_path = database.get_db_path()
        self.tmp = tempfile.TemporaryDirectory()
        database.set_db_path(Path(self.tmp.name) / "test.sqlite3")
        database.init_db()

    def tearDown(self):
        database.set_db_path(self.original_path)
        self.tmp.cleanup()

    def test_billing_month_uses_configured_cutoff(self):
        database.set_cfg("billing_day", "25")

        self.assertEqual(database.calc_billing_month("2026/07/25"), "2026-07")
        self.assertEqual(database.calc_billing_month("2026/07/26"), "2026-08")

    def test_monthly_summary_uses_deltas_and_cache_invalidation(self):
        database.save_reading(0, _reading("2026/07/20", total=100, a4_color=40, a4_bw=60), "first.txt")
        first = database.get_monthly_summary(0)

        database.save_reading(0, _reading("2026/07/21", total=130, a4_color=55, a4_bw=75), "second.txt")
        second = database.get_monthly_summary(0)

        self.assertEqual(first["2026-07"]["total"], 100)
        self.assertEqual(second["2026-07"]["total"], 130)
        self.assertEqual(second["2026-07"]["a4_color"], 55)
        self.assertEqual(second["2026-07"]["a4_bw"], 75)

    def test_duplicate_detection(self):
        data = _reading("2026/07/20", total=100, a4_color=40, a4_bw=60)
        database.save_reading(1, data, "first.txt")

        self.assertTrue(database.check_duplicate(1, "SN-001", "2026/07/20"))
        self.assertFalse(database.check_duplicate(2, "SN-001", "2026/07/20"))

    def test_current_schema_records_additive_migration_history(self):
        with database._open(commit=False) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_subject_records'"
            ).fetchone()
            sql = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='daily_subject_records'"
            ).fetchone()[0]
            migrations = conn.execute("SELECT version FROM schema_migrations").fetchall()
            legacy_tables = conn.execute(
                """SELECT name FROM sqlite_master
                   WHERE type='table' AND name IN ('legacy_history_imports','legacy_history_items')
                   ORDER BY name"""
            ).fetchall()

        self.assertEqual(version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(table[0], "daily_subject_records")
        self.assertIn("UNIQUE(device_slot, record_date, subject_type, subject_id)", sql)
        self.assertIn((8,), migrations)
        self.assertIn((CURRENT_SCHEMA_VERSION,), migrations)
        self.assertEqual(
            legacy_tables,
            [("legacy_history_imports",), ("legacy_history_items",)],
        )

    def test_init_db_refuses_future_schema_without_mutating_it(self):
        future_path = Path(self.tmp.name) / "future.sqlite3"
        with closing(sqlite3.connect(future_path)) as connection:
            connection.execute("CREATE TABLE future_data(value TEXT)")
            connection.execute("INSERT INTO future_data VALUES ('keep-me')")
            connection.execute("PRAGMA user_version = 99")
            connection.commit()
        database.set_db_path(future_path)

        with self.assertRaises(UnsupportedSchemaVersionError):
            database.init_db()

        with closing(sqlite3.connect(future_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 99)
            self.assertEqual(
                connection.execute("SELECT value FROM future_data").fetchone(),
                ("keep-me",),
            )

    def test_init_db_rolls_back_all_schema_edits_when_migration_fails(self):
        old_path = Path(self.tmp.name) / "old.sqlite3"
        with closing(sqlite3.connect(database.get_db_path())) as source, closing(
            sqlite3.connect(old_path)
        ) as connection:
            source.backup(connection)
            connection.execute("DROP INDEX idx_readings_imported")
            connection.execute("PRAGMA user_version = 7")
            connection.commit()
        database.set_db_path(old_path)

        with patch("database.apply_migrations", side_effect=RuntimeError("stop")):
            with self.assertRaisesRegex(RuntimeError, "stop"):
                database.init_db()

        with closing(sqlite3.connect(old_path)) as connection:
            restored_index = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_readings_imported'"
            ).fetchone()
            self.assertIsNone(restored_index)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)

    def test_first_run_database_copy_is_verified_and_never_overwrites(self):
        database.set_cfg("company_name", "Original Company")
        destination = Path(self.tmp.name) / "customer-data" / "KOMI_Report_V5.db"

        copied = database.copy_database_for_first_run(destination)

        self.assertEqual(copied, destination.resolve())
        with closing(sqlite3.connect(copied)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone(), ("ok",))
            self.assertEqual(
                connection.execute(
                    "SELECT value FROM settings WHERE key='company_name'"
                ).fetchone(),
                ("Original Company",),
            )

        with self.assertRaises(FileExistsError):
            database.copy_database_for_first_run(destination)


if __name__ == "__main__":
    unittest.main()
