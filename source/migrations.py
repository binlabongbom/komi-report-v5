"""Versioned, additive SQLite migrations for KOMI Report V5.

The existing schema creation remains deliberately compatible with older V4/V5
installations.  New migrations are small, named and recorded so an upgrade can
be inspected and backed up without rewriting the billing tables.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

CURRENT_SCHEMA_VERSION = 9


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when a database was created by a newer KOMI Report version."""


class SchemaDriftError(RuntimeError):
    """Raised when a current-version database is missing required schema."""


_REQUIRED_SCHEMA: dict[str, frozenset[str]] = {
    "readings": frozenset({"id", "slot", "data_json", "read_date_iso", "billing_month"}),
    "settings": frozenset({"key", "value"}),
    "devices": frozenset({"slot", "host", "password", "connection_status"}),
    "daily_meter_records": frozenset({"id", "device_slot", "record_date", "source_json"}),
    "billing_ledger": frozenset({"id", "entry_kind", "source_hash", "idempotency_key"}),
    "daily_subject_records": frozenset({"id", "device_slot", "subject_type", "subject_id"}),
    "legacy_history_imports": frozenset({"id", "source_sha256", "imported_rows"}),
    "legacy_history_items": frozenset({"id", "reading_id", "row_fingerprint"}),
}


def require_supported_schema_version(version: int) -> None:
    """Fail closed instead of silently downgrading a newer database."""

    if version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersionError(
            "Database นี้สร้างด้วย KOMI Report รุ่นใหม่กว่า "
            f"(schema {version}; โปรแกรมนี้รองรับถึง {CURRENT_SCHEMA_VERSION})"
        )


def validate_current_schema(connection: sqlite3.Connection) -> None:
    """Verify the minimum production schema before committing initialization."""

    missing: list[str] = []
    for table_name, required_columns in _REQUIRED_SCHEMA.items():
        columns = {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table_name}")')
        }
        if not columns:
            missing.append(f"table {table_name}")
            continue
        absent = sorted(required_columns - columns)
        if absent:
            missing.append(f"{table_name} columns: {', '.join(absent)}")
    if missing:
        raise SchemaDriftError("Database schema ไม่ครบ: " + "; ".join(missing))


def schema_version(path: Path) -> int:
    """Return zero for a database that has not been created yet."""

    if not path.is_file():
        return 0
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def backup_before_migration(path: Path, *, from_version: int) -> Path | None:
    """Create a SQLite-consistent backup before a non-empty database changes."""

    if not path.is_file() or from_version >= CURRENT_SCHEMA_VERSION:
        return None
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.stem}.pre-v{CURRENT_SCHEMA_VERSION}-{stamp}{path.suffix}")
    with closing(sqlite3.connect(path)) as source, closing(
        sqlite3.connect(backup_path)
    ) as destination:
        source.backup(destination)
        destination.commit()
    return backup_path


def _migration_008_record_schema_history(connection: sqlite3.Connection) -> None:
    """Record schema history and add indexes used by period/identity reporting."""

    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations(
               version INTEGER PRIMARY KEY,
               name TEXT NOT NULL,
               applied_at TEXT NOT NULL
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_daily_meter_period_slot
           ON daily_meter_records(record_date, device_slot)"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_daily_subject_identity
           ON daily_subject_records(device_slot, subject_type, subject_id, record_date)"""
    )


def ensure_legacy_history_import_schema(connection: sqlite3.Connection) -> None:
    """Create provenance tables for read-only V4.6 usage-history imports."""

    connection.execute(
        """CREATE TABLE IF NOT EXISTS legacy_history_imports(
               id                    INTEGER PRIMARY KEY AUTOINCREMENT,
               source_file_name      TEXT NOT NULL,
               source_sha256         TEXT NOT NULL,
               source_schema_version INTEGER NOT NULL DEFAULT 0,
               date_min              TEXT NOT NULL DEFAULT '',
               date_max              TEXT NOT NULL DEFAULT '',
               total_rows            INTEGER NOT NULL,
               imported_rows         INTEGER NOT NULL,
               duplicate_rows        INTEGER NOT NULL,
               rejected_rows         INTEGER NOT NULL,
               imported_at           TEXT NOT NULL
           )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS legacy_history_items(
               id              INTEGER PRIMARY KEY AUTOINCREMENT,
               import_id       INTEGER NOT NULL,
               reading_id      INTEGER NOT NULL UNIQUE,
               source_row_id   TEXT NOT NULL,
               row_fingerprint TEXT NOT NULL UNIQUE,
               FOREIGN KEY(import_id) REFERENCES legacy_history_imports(id) ON DELETE CASCADE,
               FOREIGN KEY(reading_id) REFERENCES readings(id) ON DELETE CASCADE
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_legacy_history_imported_at
           ON legacy_history_imports(imported_at DESC)"""
    )


def _migration_009_legacy_history_import(connection: sqlite3.Connection) -> None:
    ensure_legacy_history_import_schema(connection)


MIGRATIONS: tuple[tuple[int, str, object], ...] = (
    (8, "record_schema_history_and_reporting_indexes", _migration_008_record_schema_history),
    (9, "add_legacy_usage_history_import_provenance", _migration_009_legacy_history_import),
)


def apply_migrations(connection: sqlite3.Connection) -> list[int]:
    """Apply each missing additive migration inside the caller transaction."""

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    require_supported_schema_version(version)

    connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations(
               version INTEGER PRIMARY KEY,
               name TEXT NOT NULL,
               applied_at TEXT NOT NULL
           )"""
    )
    applied: list[int] = []
    for version, name, migration in MIGRATIONS:
        exists = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (version,)
        ).fetchone()
        if exists:
            continue
        migration(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
            (version, name, datetime.now().astimezone().isoformat(timespec="seconds")),
        )
        applied.append(version)
    connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
    return applied
