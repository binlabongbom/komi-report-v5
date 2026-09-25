"""Transactional day tokens invalidate cached projections for direct SQL writes."""
import re
import sqlite3

import pytest

import database
from migrations import MIGRATIONS, SchemaDriftError, apply_migrations, validate_current_schema
from services.device_config import DeviceConfig, DeviceConfigRepository


TABLES = {"subject": "daily_subject_records", "raw": "daily_raw_counter_records"}
STAMP = "2026-09-01T10:00:00+00:00"


def insert(conn, kind, *, slot=0, day="2026-09-01", key="u-1"):
    if kind == "subject":
        return conn.execute("""INSERT INTO daily_subject_records(
            device_slot,record_date,subject_type,subject_id,subject_name,
            opening_total,closing_total,delta_total,created_at)
            VALUES(?,?,'user',?,?,0,10,10,?)""", (slot, day, key, key, STAMP)).lastrowid
    return conn.execute("""INSERT INTO daily_raw_counter_records(
        device_slot,record_date,canonical_field,label,opening_value,closing_value,
        delta_value,created_at,updated_at) VALUES(?,?,?,?,0,10,10,?,?)""",
        (slot, day, "counter." + key, key, STAMP, STAMP)).lastrowid


def token(conn, kind, slot=0, day="2026-09-01"):
    row = conn.execute("""SELECT token FROM report_day_revisions
        WHERE kind=? AND device_slot=? AND record_date=?""", (kind, slot, day)).fetchone()
    return row[0] if row else None


@pytest.fixture
def devices():
    DeviceConfigRepository().replace_all([
        DeviceConfig(slot, f"Printer {slot}", f"192.0.2.{10 + slot}", serial=f"SER-{slot}")
        for slot in (0, 1)
    ])


def test_v34_backfills_distinct_existing_days_without_changing_source_rows(tmp_path):
    with sqlite3.connect(tmp_path / "v33.sqlite3") as conn:
        conn.execute("CREATE TABLE daily_meter_records(record_date TEXT,device_slot INTEGER)")
        conn.execute("""CREATE TABLE daily_subject_records(id INTEGER PRIMARY KEY,device_slot INTEGER,
            record_date TEXT,subject_type TEXT,subject_id TEXT,subject_name TEXT,
            opening_total REAL,closing_total REAL,delta_total REAL,created_at TEXT)""")
        for version, name, migration in MIGRATIONS:
            if version < 34:
                migration(conn)
                conn.execute("INSERT INTO schema_migrations VALUES(?,?,?)", (version, name, STAMP))
        conn.execute("PRAGMA user_version=33")
        for kind in TABLES:
            insert(conn, kind)
            insert(conn, kind, key="u-2")
            insert(conn, kind, slot=1, day="2026-09-02")
        before = {kind: conn.execute("SELECT * FROM " + table).fetchall() for kind, table in TABLES.items()}
        assert apply_migrations(conn) == [34]
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 34
        revisions = conn.execute("SELECT kind,device_slot,record_date,token FROM report_day_revisions").fetchall()
        assert {(kind, slot, day) for kind, slot, day, _ in revisions} == {
            (kind, slot, day) for kind in TABLES for slot, day in ((0, "2026-09-01"), (1, "2026-09-02"))}
        assert len(revisions) == 4
        assert all(re.fullmatch("[0-9a-f]{32}", revision) for *_, revision in revisions)
        generation = conn.execute("SELECT singleton,token FROM report_projection_generation").fetchone()
        assert generation[0] == 1 and re.fullmatch("[0-9a-f]{32}", generation[1])
        assert apply_migrations(conn) == []
        assert conn.execute("SELECT singleton,token FROM report_projection_generation").fetchone() == generation
        assert conn.execute("SELECT kind,device_slot,record_date,token FROM report_day_revisions").fetchall() == revisions
        assert {kind: conn.execute("SELECT * FROM " + table).fetchall() for kind, table in TABLES.items()} == before
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT token FROM report_projection_generation").fetchone()[0] != generation[1]


@pytest.mark.parametrize("kind", TABLES)
def test_direct_updates_change_only_the_day_token_without_timestamp_changes(kind, devices):
    with database._open() as conn:
        row_id = insert(conn, kind)
        insert(conn, kind, day="2026-09-02")
        insert(conn, "raw" if kind == "subject" else "subject")
        before = conn.execute("SELECT kind,device_slot,record_date,token FROM report_day_revisions").fetchall()
        initial = token(conn, kind)
        value = "delta_total" if kind == "subject" else "delta_value"
        timestamp = "created_at" if kind == "subject" else "updated_at"
        conn.execute(f"UPDATE {TABLES[kind]} SET {value}={value}+1 WHERE id=?", (row_id,))
        assert token(conn, kind) != initial
        assert conn.execute(f"SELECT {timestamp} FROM {TABLES[kind]} WHERE id=?", (row_id,)).fetchone()[0] == STAMP
        after = conn.execute("SELECT kind,device_slot,record_date,token FROM report_day_revisions").fetchall()
        assert [(k, s, d, t) for k, s, d, t in after if (k, s, d) != (kind, 0, "2026-09-01")] == [
            (k, s, d, t) for k, s, d, t in before if (k, s, d) != (kind, 0, "2026-09-01")]


@pytest.mark.parametrize("kind", TABLES)
def test_rolled_back_update_and_delete_leave_token_and_rows_unchanged(kind, devices):
    with database._open() as conn:
        row_id = insert(conn, kind)
        initial = token(conn, kind)
    with database._open(commit=False) as conn:
        conn.execute("BEGIN")
        conn.execute(f"UPDATE {TABLES[kind]} SET device_slot=1,record_date='2026-09-02' WHERE id=?", (row_id,))
        assert token(conn, kind) != initial
        assert token(conn, kind, 1, "2026-09-02")
        conn.execute(f"DELETE FROM {TABLES[kind]} WHERE id=?", (row_id,))
        conn.rollback()
        assert token(conn, kind) == initial
        assert token(conn, kind, 1, "2026-09-02") is None
        assert conn.execute(f"SELECT device_slot,record_date FROM {TABLES[kind]} WHERE id=?", (row_id,)).fetchone() == (0, "2026-09-01")


@pytest.mark.parametrize("kind", TABLES)
def test_delete_keeps_a_tombstone_and_reinsert_changes_it_again(kind, devices):
    with database._open() as conn:
        row_id = insert(conn, kind)
        initial = token(conn, kind)
        conn.execute(f"DELETE FROM {TABLES[kind]} WHERE id=?", (row_id,))
        deleted = token(conn, kind)
        assert deleted and deleted != initial
        assert conn.execute(f"SELECT COUNT(*) FROM {TABLES[kind]}").fetchone()[0] == 0
        insert(conn, kind)
        assert token(conn, kind) not in (initial, deleted)


@pytest.mark.parametrize("kind", TABLES)
def test_slot_and_date_move_invalidates_both_old_and_existing_new_scope(kind, devices):
    with database._open() as conn:
        row_id = insert(conn, kind)
        insert(conn, kind, slot=1, day="2026-09-02", key="other")
        old, new = token(conn, kind), token(conn, kind, 1, "2026-09-02")
        conn.execute(f"UPDATE {TABLES[kind]} SET device_slot=1,record_date='2026-09-02' WHERE id=?", (row_id,))
        assert token(conn, kind) != old
        assert token(conn, kind, 1, "2026-09-02") != new


@pytest.mark.parametrize("kind", TABLES)
@pytest.mark.parametrize("operation", ["insert", "update", "delete"])
def test_missing_invalidation_trigger_fails_schema_validation(kind, operation):
    with database._open() as conn:
        validate_current_schema(conn)
        name = f"report_day_revision_{kind}_{operation}"
        conn.execute(f"DROP TRIGGER {name}")
        with pytest.raises(SchemaDriftError, match=name):
            validate_current_schema(conn)


@pytest.mark.parametrize("table", ["report_projection_generation", "report_day_revisions"])
def test_missing_projection_table_fails_schema_validation(table):
    with database._open() as conn:
        conn.execute(f"DROP TABLE {table}")
        with pytest.raises(SchemaDriftError, match=table):
            validate_current_schema(conn)


@pytest.mark.parametrize("reset", [database.reset_usage_data, database.factory_reset_v5])
def test_resets_retain_generation_and_invalidate_deleted_days(reset, devices):
    with database._open() as conn:
        for kind in TABLES:
            insert(conn, kind)
        before = {kind: token(conn, kind) for kind in TABLES}
        generation = conn.execute("SELECT token FROM report_projection_generation").fetchone()[0]
    reset()
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT token FROM report_projection_generation").fetchone()[0] == generation
        for kind, table in TABLES.items():
            assert conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == 0
            assert token(conn, kind) and token(conn, kind) != before[kind]
        validate_current_schema(conn)


def test_raw_day_index_serves_slot_and_date_range_queries(devices):
    with database._open() as conn:
        insert(conn, "raw")
        plan = conn.execute("""EXPLAIN QUERY PLAN SELECT canonical_field,delta_value
            FROM daily_raw_counter_records WHERE device_slot=? AND record_date>=? AND record_date<=?""",
            (0, "2026-09-01", "2026-09-02")).fetchall()
        assert any("idx_report_raw_day" in row[3] for row in plan)
