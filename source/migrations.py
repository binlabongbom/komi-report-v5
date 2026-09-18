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

CURRENT_SCHEMA_VERSION = 20


class UnsupportedSchemaVersionError(RuntimeError):
    """Raised when a database was created by a newer KOMI Report version."""


class SchemaDriftError(RuntimeError):
    """Raised when a current-version database is missing required schema."""


_REQUIRED_SCHEMA: dict[str, frozenset[str]] = {
    "readings": frozenset({"id", "slot", "data_json", "read_date_iso", "billing_month"}),
    "settings": frozenset({"key", "value"}),
    "devices": frozenset(
        {"slot", "host", "password", "credential_ref", "tls_mode", "tls_fingerprint", "connection_status"}
    ),
    "daily_meter_records": frozenset({"id", "device_slot", "record_date", "source_json"}),
    "billing_ledger": frozenset({"id", "entry_kind", "source_hash", "idempotency_key"}),
    "daily_subject_records": frozenset({"id", "device_slot", "subject_type", "subject_id"}),
    "daily_raw_counter_records": frozenset(
        {
            "id",
            "device_slot",
            "record_date",
            "canonical_field",
            "label",
            "subject_type",
            "subject_id",
            "opening_value",
            "closing_value",
            "delta_value",
        }
    ),
    "parser_mapping_overrides": frozenset(
        {
            "device_serial",
            "raw_key",
            "source_field",
            "source_path",
            "target_field",
            "updated_at",
        }
    ),
    "parser_mapping_change_log": frozenset(
        {
            "id",
            "device_serial",
            "raw_key",
            "old_target",
            "new_target",
            "changed_at",
        }
    ),
    "legacy_history_imports": frozenset({"id", "source_sha256", "imported_rows"}),
    "legacy_history_items": frozenset({"id", "reading_id", "row_fingerprint"}),
    "registration_profile": frozenset(
        {
            "singleton_id",
            "installation_id",
            "company_name",
            "client_first_started_at",
            "notice_version",
            "notice_accepted_at",
            "token_ref",
            "status",
            "registered_at",
            "last_heartbeat_at",
            "next_heartbeat_at",
            "last_error_code",
            "updated_at",
        }
    ),
    "registration_outbox": frozenset(
        {
            "operation_id",
            "event_type",
            "idempotency_key",
            "request_fingerprint",
            "payload_json",
            "state",
            "attempt_count",
            "next_attempt_at",
            "last_error_code",
            "created_at",
            "updated_at",
            "completed_at",
        }
    ),
    "registration_attempt_history": frozenset(
        {
            "id",
            "operation_id",
            "attempted_at",
            "outcome",
            "http_status",
            "error_code",
            "retryable",
            "retry_after_seconds",
            "duration_ms",
        }
    ),
    "v52_telemetry_outbox": frozenset(
        {
            "operation_id",
            "event_type",
            "idempotency_key",
            "request_fingerprint",
            "payload_json",
            "state",
            "attempt_count",
            "next_attempt_at",
            "last_error_code",
            "created_at",
            "updated_at",
            "completed_at",
        }
    ),
    "v52_telemetry_success": frozenset({"event_type", "last_successful_at"}),
    "v52_runtime_state": frozenset(
        {
            "singleton_id",
            "mode",
            "company_name",
            "installation_id",
            "first_started_at",
            "notice_version",
            "notice_accepted_at",
            "status",
            "last_sent_at",
            "next_status_at",
            "next_meter_at",
            "last_error_code",
            "offline_request_json",
            "offline_license_id",
            "offline_license_expires_at",
            "offline_license_kid",
            "offline_bound_devices_json",
            "registration_inventory_json",
            "last_registered_inventory_json",
            "last_registration_terminal_inventory_json",
            "updated_at",
        }
    ),
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


def _migration_010_credential_reference(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(devices)")}
    if not columns:
        return
    if "credential_ref" not in columns:
        connection.execute("ALTER TABLE devices ADD COLUMN credential_ref TEXT NOT NULL DEFAULT ''")


def _migration_011_printer_tls_policy(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(devices)")}
    if not columns:
        return
    if "tls_mode" not in columns:
        connection.execute("ALTER TABLE devices ADD COLUMN tls_mode TEXT NOT NULL DEFAULT 'system'")
    if "tls_fingerprint" not in columns:
        connection.execute("ALTER TABLE devices ADD COLUMN tls_fingerprint TEXT NOT NULL DEFAULT ''")


def _migration_012_registration_outbox(connection: sqlite3.Connection) -> None:
    """Add durable registration state without touching meter or billing data."""

    connection.execute(
        """CREATE TABLE IF NOT EXISTS registration_profile(
               singleton_id            INTEGER PRIMARY KEY CHECK(singleton_id = 1),
               installation_id         TEXT NOT NULL UNIQUE,
               company_name            TEXT NOT NULL,
               client_first_started_at TEXT NOT NULL,
               notice_version          TEXT NOT NULL DEFAULT '',
               notice_accepted_at      TEXT NOT NULL DEFAULT '',
               token_ref               TEXT NOT NULL DEFAULT '',
               status                  TEXT NOT NULL DEFAULT 'pending',
               registered_at           TEXT NOT NULL DEFAULT '',
               last_heartbeat_at       TEXT NOT NULL DEFAULT '',
               next_heartbeat_at       TEXT NOT NULL DEFAULT '',
               last_error_code         TEXT NOT NULL DEFAULT '',
               updated_at              TEXT NOT NULL
           )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS registration_outbox(
               operation_id       TEXT PRIMARY KEY,
               event_type         TEXT NOT NULL CHECK(event_type IN ('register','heartbeat')),
               idempotency_key    TEXT NOT NULL UNIQUE,
               request_fingerprint TEXT NOT NULL,
               payload_json       TEXT NOT NULL,
               state              TEXT NOT NULL DEFAULT 'pending'
                                  CHECK(state IN ('pending','in_flight','retry','succeeded','action_required','superseded')),
               attempt_count      INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
               next_attempt_at    TEXT NOT NULL,
               last_error_code    TEXT NOT NULL DEFAULT '',
               created_at         TEXT NOT NULL,
               updated_at         TEXT NOT NULL,
               completed_at       TEXT NOT NULL DEFAULT '',
               UNIQUE(event_type, request_fingerprint)
           )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS registration_attempt_history(
               id                  INTEGER PRIMARY KEY AUTOINCREMENT,
               operation_id        TEXT NOT NULL,
               attempted_at        TEXT NOT NULL,
               outcome             TEXT NOT NULL,
               http_status         INTEGER,
               error_code          TEXT NOT NULL DEFAULT '',
               retryable           INTEGER NOT NULL DEFAULT 0,
               retry_after_seconds INTEGER,
               duration_ms         INTEGER NOT NULL DEFAULT 0,
               FOREIGN KEY(operation_id) REFERENCES registration_outbox(operation_id) ON DELETE CASCADE
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_registration_outbox_due
           ON registration_outbox(state, next_attempt_at)"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_registration_attempt_operation
           ON registration_attempt_history(operation_id, id DESC)"""
    )


def _migration_013_v52_telemetry_outbox(connection: sqlite3.Connection) -> None:
    """Add V5.2 Status/Meter coalescing without rewriting V5.1 data."""

    connection.execute(
        """CREATE TABLE IF NOT EXISTS v52_telemetry_outbox(
               operation_id        TEXT PRIMARY KEY,
               event_type          TEXT NOT NULL CHECK(event_type IN ('register','status','meter')),
               idempotency_key     TEXT NOT NULL UNIQUE,
               request_fingerprint TEXT NOT NULL,
               payload_json        TEXT NOT NULL,
               state               TEXT NOT NULL
                                   CHECK(state IN ('pending','in_flight','retry','terminal','succeeded')),
               attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
               next_attempt_at     TEXT NOT NULL,
               last_error_code     TEXT NOT NULL DEFAULT '',
               created_at          TEXT NOT NULL,
               updated_at          TEXT NOT NULL,
               completed_at        TEXT NOT NULL DEFAULT ''
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_v52_telemetry_due
           ON v52_telemetry_outbox(state,next_attempt_at)"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS v52_telemetry_success(
               event_type       TEXT PRIMARY KEY CHECK(event_type IN ('register','status','meter')),
               last_successful_at TEXT NOT NULL
           )"""
    )


def _migration_014_v52_runtime_state(connection: sqlite3.Connection) -> None:
    """Persist only public/redacted V5.2 lifecycle and Offline License state."""

    connection.execute(
        """CREATE TABLE IF NOT EXISTS v52_runtime_state(
               singleton_id                    INTEGER PRIMARY KEY CHECK(singleton_id = 1),
               mode                            TEXT NOT NULL DEFAULT 'online'
                                               CHECK(mode IN ('online','offline')),
               company_name                    TEXT NOT NULL DEFAULT '',
               installation_id                 TEXT NOT NULL DEFAULT '',
               first_started_at                TEXT NOT NULL DEFAULT '',
               notice_version                  TEXT NOT NULL DEFAULT '',
               notice_accepted_at              TEXT NOT NULL DEFAULT '',
               status                          TEXT NOT NULL DEFAULT 'not_configured',
               last_sent_at                    TEXT NOT NULL DEFAULT '',
               next_status_at                  TEXT NOT NULL DEFAULT '',
               next_meter_at                   TEXT NOT NULL DEFAULT '',
               last_error_code                 TEXT NOT NULL DEFAULT '',
               offline_request_json            TEXT NOT NULL DEFAULT '',
               offline_license_id              TEXT NOT NULL DEFAULT '',
               offline_license_expires_at      TEXT NOT NULL DEFAULT '',
               offline_license_kid             TEXT NOT NULL DEFAULT '',
               offline_bound_devices_json      TEXT NOT NULL DEFAULT '[]',
               updated_at                      TEXT NOT NULL
           )"""
    )


def _migration_015_v52_registration_inventory(connection: sqlite3.Connection) -> None:
    """Keep the complete redacted discovery inventory separate from selected devices."""

    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(v52_runtime_state)")
    }
    if "registration_inventory_json" not in columns:
        connection.execute(
            "ALTER TABLE v52_runtime_state "
            "ADD COLUMN registration_inventory_json TEXT NOT NULL DEFAULT '[]'"
        )


def _migration_019_v52_registration_inventory_baseline(
    connection: sqlite3.Connection,
) -> None:
    """Remember accepted and terminal inventories for safe re-registration.

    The current discovery inventory remains separate from these baselines.  A
    changed inventory can therefore create one new signed register operation,
    while an unchanged terminal response (including HTTP 409) is not retried on
    every scheduler tick.
    """

    columns = {
        str(row[1]) for row in connection.execute("PRAGMA table_info(v52_runtime_state)")
    }
    if not columns:
        # A deliberately partial legacy fixture is allowed to advance its
        # recorded history; the normal schema validator still rejects a
        # production database that is missing the runtime table.
        return
    if "last_registered_inventory_json" not in columns:
        connection.execute(
            "ALTER TABLE v52_runtime_state "
            "ADD COLUMN last_registered_inventory_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "last_registration_terminal_inventory_json" not in columns:
        connection.execute(
            "ALTER TABLE v52_runtime_state "
            "ADD COLUMN last_registration_terminal_inventory_json "
            "TEXT NOT NULL DEFAULT '[]'"
        )


def _migration_016_daily_raw_counter_history(connection: sqlite3.Connection) -> None:
    """Persist exact Web counter names and values for the Legacy report.

    This table is deliberately report-only.  It does not replace normalized
    daily meter rows, subject totals, pricing, or the append-only billing
    ledger.
    """

    connection.execute(
        """CREATE TABLE IF NOT EXISTS daily_raw_counter_records(
               id                     INTEGER PRIMARY KEY AUTOINCREMENT,
               device_slot            INTEGER NOT NULL,
               record_date            TEXT NOT NULL,
               canonical_field        TEXT NOT NULL,
               label                  TEXT NOT NULL,
               source_path            TEXT NOT NULL DEFAULT '',
               subject_type           TEXT NOT NULL DEFAULT '',
               subject_id             TEXT NOT NULL DEFAULT '',
               subject_name           TEXT NOT NULL DEFAULT '',
               opening_value          REAL NOT NULL,
               closing_value          REAL NOT NULL,
               delta_value            REAL NOT NULL DEFAULT 0,
               reset_count            INTEGER NOT NULL DEFAULT 0,
               sample_count           INTEGER NOT NULL DEFAULT 0,
               first_success          TEXT NOT NULL DEFAULT '',
               last_success           TEXT NOT NULL DEFAULT '',
               source_name            TEXT NOT NULL DEFAULT '',
               device_name_snapshot   TEXT NOT NULL DEFAULT '',
               device_serial_snapshot TEXT NOT NULL DEFAULT '',
               incomplete             INTEGER NOT NULL DEFAULT 0,
               created_at             TEXT NOT NULL,
               updated_at             TEXT NOT NULL,
               UNIQUE(
                   device_slot,device_serial_snapshot,record_date,
                   canonical_field,source_path,
                   subject_type,subject_id
               )
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_daily_raw_counter_period
           ON daily_raw_counter_records(
               record_date,device_slot,device_serial_snapshot,
               subject_type,subject_id,canonical_field
           )"""
    )


def _migration_017_parser_mapping_overrides(connection: sqlite3.Connection) -> None:
    """Add reversible, per-device parser overrides without rewriting history.

    Overrides are keyed by printer Serial Number plus the exact raw source
    identity.  They are applied only to future normalized reads; the exact
    Legacy counter table and append-only Billing Ledger remain untouched.
    """

    connection.execute(
        """CREATE TABLE IF NOT EXISTS parser_mapping_overrides(
               device_serial TEXT NOT NULL,
               raw_key       TEXT NOT NULL,
               source_field  TEXT NOT NULL,
               source_path   TEXT NOT NULL DEFAULT '',
               target_field  TEXT NOT NULL,
               updated_at    TEXT NOT NULL,
               PRIMARY KEY(device_serial,raw_key)
           )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS parser_mapping_change_log(
               id            INTEGER PRIMARY KEY AUTOINCREMENT,
               device_serial TEXT NOT NULL,
               raw_key       TEXT NOT NULL,
               old_target    TEXT NOT NULL DEFAULT '',
               new_target    TEXT NOT NULL DEFAULT '',
               changed_at    TEXT NOT NULL
           )"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_parser_mapping_log_serial
           ON parser_mapping_change_log(device_serial,id DESC)"""
    )


def _migration_018_raw_counter_device_identity(connection: sqlite3.Connection) -> None:
    """Make printer Serial Number part of every Raw Counter daily identity.

    A Slot is a customer location, not a permanent printer identity.  Reusing
    a Slot for a replacement printer must create a new zero-delta baseline;
    otherwise the replacement's absolute meter could be recorded as usage.
    SQLite cannot alter a UNIQUE constraint in place, so rebuild this
    report-only table transactionally while preserving every existing row/id.
    """

    connection.execute("DROP TABLE IF EXISTS daily_raw_counter_records_v18")
    connection.execute(
        """CREATE TABLE daily_raw_counter_records_v18(
               id                     INTEGER PRIMARY KEY AUTOINCREMENT,
               device_slot            INTEGER NOT NULL,
               record_date            TEXT NOT NULL,
               canonical_field        TEXT NOT NULL,
               label                  TEXT NOT NULL,
               source_path            TEXT NOT NULL DEFAULT '',
               subject_type           TEXT NOT NULL DEFAULT '',
               subject_id             TEXT NOT NULL DEFAULT '',
               subject_name           TEXT NOT NULL DEFAULT '',
               opening_value          REAL NOT NULL,
               closing_value          REAL NOT NULL,
               delta_value            REAL NOT NULL DEFAULT 0,
               reset_count            INTEGER NOT NULL DEFAULT 0,
               sample_count           INTEGER NOT NULL DEFAULT 0,
               first_success          TEXT NOT NULL DEFAULT '',
               last_success           TEXT NOT NULL DEFAULT '',
               source_name            TEXT NOT NULL DEFAULT '',
               device_name_snapshot   TEXT NOT NULL DEFAULT '',
               device_serial_snapshot TEXT NOT NULL DEFAULT '',
               incomplete             INTEGER NOT NULL DEFAULT 0,
               created_at             TEXT NOT NULL,
               updated_at             TEXT NOT NULL,
               UNIQUE(
                   device_slot,device_serial_snapshot,record_date,
                   canonical_field,source_path,subject_type,subject_id
               )
           )"""
    )
    connection.execute(
        """INSERT INTO daily_raw_counter_records_v18(
               id,device_slot,record_date,canonical_field,label,source_path,
               subject_type,subject_id,subject_name,opening_value,closing_value,
               delta_value,reset_count,sample_count,first_success,last_success,
               source_name,device_name_snapshot,device_serial_snapshot,
               incomplete,created_at,updated_at
           )
           SELECT id,device_slot,record_date,canonical_field,label,source_path,
                  subject_type,subject_id,subject_name,opening_value,closing_value,
                  delta_value,reset_count,sample_count,first_success,last_success,
                  source_name,device_name_snapshot,device_serial_snapshot,
                  incomplete,created_at,updated_at
           FROM daily_raw_counter_records"""
    )
    connection.execute("DROP TABLE daily_raw_counter_records")
    connection.execute(
        "ALTER TABLE daily_raw_counter_records_v18 RENAME TO daily_raw_counter_records"
    )
    connection.execute(
        """CREATE INDEX idx_daily_raw_counter_period
           ON daily_raw_counter_records(
               record_date,device_slot,device_serial_snapshot,
               subject_type,subject_id,canonical_field
           )"""
    )


def _migration_020_peer_settings_history(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE peer_settings_revisions(
        revision TEXT PRIMARY KEY, document_json TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE peer_settings_state(
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")


MIGRATIONS: tuple[tuple[int, str, object], ...] = (
    (8, "record_schema_history_and_reporting_indexes", _migration_008_record_schema_history),
    (9, "add_legacy_usage_history_import_provenance", _migration_009_legacy_history_import),
    (10, "add_os_vault_credential_reference", _migration_010_credential_reference),
    (11, "add_verified_or_pinned_printer_tls_policy", _migration_011_printer_tls_policy),
    (12, "add_durable_registration_outbox", _migration_012_registration_outbox),
    (13, "add_v52_status_meter_coalescing_outbox", _migration_013_v52_telemetry_outbox),
    (14, "add_v52_runtime_state", _migration_014_v52_runtime_state),
    (15, "add_v52_registration_inventory", _migration_015_v52_registration_inventory),
    (16, "add_exact_daily_raw_counter_history", _migration_016_daily_raw_counter_history),
    (17, "add_per_serial_parser_mapping_overrides", _migration_017_parser_mapping_overrides),
    (18, "separate_raw_counter_history_by_printer_serial", _migration_018_raw_counter_device_identity),
    (19, "add_v52_registration_inventory_baselines", _migration_019_v52_registration_inventory_baseline),
    (20, "add_peer_settings_revision_history", _migration_020_peer_settings_history),
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
