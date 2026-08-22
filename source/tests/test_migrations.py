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

    assert applied == [8, 9, 10, 11, CURRENT_SCHEMA_VERSION]
    assert versions == [(8,), (9,), (10,), (11,), (CURRENT_SCHEMA_VERSION,)]
    assert version == CURRENT_SCHEMA_VERSION
    assert ("idx_daily_meter_period_slot",) in indexes
    assert ("idx_daily_subject_identity",) in indexes
    assert ("legacy_history_imports",) in tables
    assert ("legacy_history_items",) in tables
    assert ("registration_profile",) in tables
    assert ("registration_outbox",) in tables
    assert ("registration_attempt_history",) in tables


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
