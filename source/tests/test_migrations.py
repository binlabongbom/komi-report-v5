import sqlite3
from pathlib import Path

import pytest

from migrations import (
    CURRENT_SCHEMA_VERSION,
    UnsupportedSchemaVersionError,
    apply_migrations,
    backup_before_migration,
)


def test_migration_records_history_and_reporting_indexes(tmp_path):
    path = tmp_path / "komi.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE daily_meter_records(record_date TEXT, device_slot INTEGER)")
        connection.execute(
            "CREATE TABLE daily_subject_records(device_slot INTEGER, subject_type TEXT, subject_id TEXT, record_date TEXT)"
        )
        applied = apply_migrations(connection)

        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
        indexes = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ).fetchall()
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert applied == list(range(8, CURRENT_SCHEMA_VERSION + 1))
    assert versions == [(version,) for version in range(8, CURRENT_SCHEMA_VERSION + 1)]
    assert version == CURRENT_SCHEMA_VERSION
    assert ("idx_daily_meter_period_slot",) in indexes
    assert ("idx_daily_subject_identity",) in indexes
    assert ("legacy_history_imports",) in tables
    assert ("legacy_history_items",) in tables
    assert ("registration_profile",) in tables
    assert ("registration_outbox",) in tables
    assert ("registration_attempt_history",) in tables
    assert ("v52_telemetry_outbox",) in tables
    assert ("v52_telemetry_success",) in tables
    assert ("v52_runtime_state",) in tables
    assert ("daily_raw_counter_records",) in tables
    assert ("idx_daily_raw_counter_period",) in indexes

    with sqlite3.connect(path) as connection:
        runtime_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(v52_runtime_state)")
        }
    assert "registration_inventory_json" in runtime_columns
    assert "last_registered_inventory_json" in runtime_columns
    assert "last_registration_terminal_inventory_json" in runtime_columns

    with sqlite3.connect(path) as connection:
        raw_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(daily_raw_counter_records)")
        }
    assert {
        "canonical_field",
        "label",
        "source_path",
        "subject_type",
        "subject_id",
        "opening_value",
        "closing_value",
        "delta_value",
    } <= raw_columns


def test_registration_migration_is_additive_and_does_not_change_billing_table(tmp_path):
    path = tmp_path / "komi.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE daily_meter_records(record_date TEXT, device_slot INTEGER)")
        connection.execute(
            "CREATE TABLE daily_subject_records(device_slot INTEGER, subject_type TEXT, subject_id TEXT, record_date TEXT)"
        )
        connection.execute(
            "CREATE TABLE billing_ledger(id INTEGER PRIMARY KEY, source_hash TEXT, amount TEXT)"
        )
        connection.execute("INSERT INTO billing_ledger VALUES(1, 'immutable-source', '42.00')")
        before_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='billing_ledger'"
        ).fetchone()[0]
        apply_migrations(connection)
        after_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='billing_ledger'"
        ).fetchone()[0]
        row = connection.execute("SELECT * FROM billing_ledger").fetchone()

    assert after_sql == before_sql
    assert row == (1, "immutable-source", "42.00")


def test_raw_history_identity_migration_preserves_rows_and_allows_slot_replacement(tmp_path):
    path = tmp_path / "komi-v17.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, name TEXT, applied_at TEXT)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES(?,?,?)",
            [(version, f"migration-{version}", "2026-08-26T00:00:00+07:00") for version in range(8, 18)],
        )
        connection.execute("PRAGMA user_version = 17")
        connection.execute(
            """CREATE TABLE daily_raw_counter_records(
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   device_slot INTEGER NOT NULL,
                   record_date TEXT NOT NULL,
                   canonical_field TEXT NOT NULL,
                   label TEXT NOT NULL,
                   source_path TEXT NOT NULL DEFAULT '',
                   subject_type TEXT NOT NULL DEFAULT '',
                   subject_id TEXT NOT NULL DEFAULT '',
                   subject_name TEXT NOT NULL DEFAULT '',
                   opening_value REAL NOT NULL,
                   closing_value REAL NOT NULL,
                   delta_value REAL NOT NULL DEFAULT 0,
                   reset_count INTEGER NOT NULL DEFAULT 0,
                   sample_count INTEGER NOT NULL DEFAULT 0,
                   first_success TEXT NOT NULL DEFAULT '',
                   last_success TEXT NOT NULL DEFAULT '',
                   source_name TEXT NOT NULL DEFAULT '',
                   device_name_snapshot TEXT NOT NULL DEFAULT '',
                   device_serial_snapshot TEXT NOT NULL DEFAULT '',
                   incomplete INTEGER NOT NULL DEFAULT 0,
                   created_at TEXT NOT NULL,
                   updated_at TEXT NOT NULL,
                   UNIQUE(device_slot,record_date,canonical_field,source_path,subject_type,subject_id)
               )"""
        )
        row = (
            0,
            "2026-08-26",
            "paper.a5",
            "A5",
            "/counter.xml",
            "",
            "",
            "",
            100,
            110,
            10,
            0,
            2,
            "2026-08-26T08:00:00+07:00",
            "2026-08-26T09:00:00+07:00",
            "legacy_xml",
            "Old Printer",
            "OLD-001",
            0,
            "2026-08-26T08:00:00+07:00",
            "2026-08-26T09:00:00+07:00",
        )
        connection.execute(
            """INSERT INTO daily_raw_counter_records(
                   device_slot,record_date,canonical_field,label,source_path,
                   subject_type,subject_id,subject_name,opening_value,closing_value,
                   delta_value,reset_count,sample_count,first_success,last_success,
                   source_name,device_name_snapshot,device_serial_snapshot,
                   incomplete,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )

        assert apply_migrations(connection) == [18, 19]
        connection.execute(
            """INSERT INTO daily_raw_counter_records(
                   device_slot,record_date,canonical_field,label,source_path,
                   subject_type,subject_id,subject_name,opening_value,closing_value,
                   delta_value,reset_count,sample_count,first_success,last_success,
                   source_name,device_name_snapshot,device_serial_snapshot,
                   incomplete,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*row[:17], "NEW-002", *row[18:]),
        )
        rows = connection.execute(
            "SELECT device_serial_snapshot,delta_value FROM daily_raw_counter_records ORDER BY id"
        ).fetchall()

    assert rows == [("OLD-001", 10.0), ("NEW-002", 10.0)]


def test_backup_before_migration_is_consistent_copy(tmp_path):
    path = Path(tmp_path) / "komi.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample(value) VALUES ('before')")
        connection.execute("PRAGMA user_version = 7")

    backup = backup_before_migration(path, from_version=7)

    assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("before",)


def test_migration_refuses_a_database_from_a_newer_app(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE future_data(value TEXT)")
        connection.execute("INSERT INTO future_data VALUES ('keep-me')")
        connection.execute("PRAGMA user_version = 99")

    with sqlite3.connect(path) as connection, pytest.raises(UnsupportedSchemaVersionError):
        apply_migrations(connection)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
        assert connection.execute("SELECT value FROM future_data").fetchone() == ("keep-me",)
