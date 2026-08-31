"""Read-only V4.6 usage-history import with preview and rollback safety."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterable
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import database
from migrations import apply_migrations, ensure_legacy_history_import_schema

log = logging.getLogger(__name__)

_REQUIRED_SOURCE_COLUMNS = frozenset({"slot", "data_json"})
_OPTIONAL_SOURCE_COLUMNS = (
    "machine_name",
    "serial",
    "read_date",
    "read_date_iso",
    "billing_month",
    "mode",
    "imported_at",
    "file_name",
    "parser_name",
)
_USAGE_PAYLOAD_KEYS = frozenset(
    {
        "date",
        "machine_name",
        "serial",
        "mode",
        "total_counter",
        "summary",
        "paper_size",
        "paper_color",
        "detail",
        "meters",
        "warnings",
        "parser_name",
        "profile_mode",
        "report_type",
        "parse_strategy",
    }
)


class LegacyHistoryImportError(ValueError):
    """A source database cannot be previewed or imported safely."""


@dataclass(frozen=True)
class LegacyDeviceSummary:
    slot: int
    machine_name: str
    serial: str
    reading_count: int


@dataclass(frozen=True)
class LegacyHistoryPreview:
    source_path: Path
    source_sha256: str
    source_schema_version: int
    total_rows: int
    valid_rows: int
    new_rows: int
    duplicate_rows: int
    rejected_rows: int
    date_min: str
    date_max: str
    devices: tuple[LegacyDeviceSummary, ...]


@dataclass(frozen=True)
class LegacyHistoryImportResult:
    import_id: int
    imported_rows: int
    duplicate_rows: int
    rejected_rows: int
    backup_path: Path
    source_sha256: str


@dataclass(frozen=True)
class LegacyUsageSnapshot:
    read_date: str
    billing_month: str
    slot: int
    machine_name: str
    serial: str
    total: float
    color: float
    bw: float
    a3_color: float
    a3_bw: float
    a4_color: float
    a4_bw: float


@dataclass(frozen=True)
class LegacyUsageInterval:
    """A V4.6 usage interval attached to a logical installation Slot."""

    device_slot: int
    period_start: date
    period_end: date
    billing_month: str
    total: float
    a3_color: float
    a3_bw: float
    a4_color: float
    a4_bw: float
    scan: float
    gross_cost: float
    net_cost: float
    device_identity: str
    device_name_snapshot: str
    device_serial_snapshot: str
    source: str = "legacy_v4.6"
    cost_available: bool = False


@dataclass(frozen=True)
class _HistoryCandidate:
    source_row_id: str
    slot: int
    machine_name: str
    serial: str
    read_date: str
    read_date_iso: str
    billing_month: str
    mode: str
    data_json: str
    parser_name: str
    fingerprint: str


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


@contextmanager
def _consistent_source_snapshot(path: Path):
    """Yield a read-only, WAL-inclusive snapshot whose bytes match the scan."""

    with tempfile.TemporaryDirectory(prefix="komi-v46-preview-") as temp_dir:
        snapshot = Path(temp_dir) / "source-snapshot.sqlite3"
        try:
            with closing(_open_readonly(path)) as source, closing(
                sqlite3.connect(snapshot)
            ) as destination:
                source.backup(destination)
        except sqlite3.Error as err:
            raise LegacyHistoryImportError(
                f"สร้างสำเนา Database V4.6 สำหรับตรวจสอบไม่ได้: {err}"
            ) from err
        yield snapshot


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        ).fetchone()
        is not None
    )


def _source_columns(connection: sqlite3.Connection) -> set[str]:
    if not _table_exists(connection, "readings"):
        raise LegacyHistoryImportError("ไม่พบตารางประวัติ readings ใน Database ที่เลือก")
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(readings)")}
    missing = sorted(_REQUIRED_SOURCE_COLUMNS - columns)
    if missing:
        raise LegacyHistoryImportError(
            "Database นี้ไม่ใช่รูปแบบ V4.6 ที่รองรับ (ขาด: " + ", ".join(missing) + ")"
        )
    return columns


def detect_legacy_history_sources(
    extra_paths: Iterable[str | Path] = (),
    *,
    include_known_locations: bool = True,
) -> tuple[Path, ...]:
    """Return confirmed V4.6 databases from known, read-only locations.

    Detection is intentionally conservative.  The onboarding wizard should not
    advertise migration to every new customer, and it must never treat the
    active V5 database as a legacy source.
    """

    candidates: list[Path] = []
    configured = os.environ.get("KOMI_V46_DATABASE", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(Path(value).expanduser() for value in extra_paths)
    if include_known_locations:
        candidates.extend(
            (
                Path.home() / "KOMI Reader" / "KOMI_Reader_data.db",
                Path.home() / "Documents" / "KOMI Reader" / "KOMI_Reader_data.db",
            )
        )

    active = Path(database.get_db_path()).expanduser().resolve(strict=False)
    confirmed: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen or resolved == active or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            with closing(_open_readonly(resolved)) as connection:
                _source_columns(connection)
                # device_configs is owned by V5.  A file containing it is not
                # offered as a V4.6 migration source even if it has readings.
                if _table_exists(connection, "device_configs"):
                    continue
        except (OSError, sqlite3.Error, LegacyHistoryImportError):
            continue
        confirmed.append(resolved)
    return tuple(confirmed)


def _sanitize_payload(raw_json: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(raw_json or ""))
    except (TypeError, json.JSONDecodeError) as err:
        raise LegacyHistoryImportError("ข้อมูลประวัติเป็น JSON ที่อ่านไม่ได้") from err
    if not isinstance(decoded, dict):
        raise LegacyHistoryImportError("ข้อมูลประวัติต้องเป็น JSON object")
    return {key: decoded[key] for key in _USAGE_PAYLOAD_KEYS if key in decoded}


def _row_value(row: sqlite3.Row, key: str, fallback: Any = "") -> Any:
    value = row[key] if key in row.keys() else None
    return fallback if value is None else value


def _candidate_from_row(row: sqlite3.Row) -> _HistoryCandidate:
    payload = _sanitize_payload(row["data_json"])
    try:
        slot = int(row["slot"])
    except (TypeError, ValueError) as err:
        raise LegacyHistoryImportError("Slot ของประวัติไม่ถูกต้อง") from err
    if slot not in (0, 1, 2):
        raise LegacyHistoryImportError("รองรับประวัติเครื่อง Slot 1–3 เท่านั้น")

    read_date = str(_row_value(row, "read_date", payload.get("date", ""))).strip()
    read_date_iso = str(_row_value(row, "read_date_iso", "")).strip()
    read_date_iso = database._date_to_iso(read_date_iso or read_date)
    if not read_date_iso:
        raise LegacyHistoryImportError("วันที่ของประวัติอ่านไม่ได้")

    machine_name = str(
        _row_value(row, "machine_name", payload.get("machine_name", ""))
    ).strip()
    serial = str(_row_value(row, "serial", payload.get("serial", ""))).strip()
    mode = str(_row_value(row, "mode", payload.get("mode", "summary"))).strip() or "summary"
    billing_month = str(_row_value(row, "billing_month", "")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}", billing_month):
        billing_month = read_date_iso[:7]
    parser_name = str(_row_value(row, "parser_name", "legacy_v4.6_database")).strip()
    parser_name = parser_name or "legacy_v4.6_database"

    payload.setdefault("date", read_date)
    payload.setdefault("machine_name", machine_name)
    payload.setdefault("serial", serial)
    payload.setdefault("mode", mode)
    normalized_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint_payload = json.dumps(
        {
            "slot": slot,
            "serial": serial,
            "read_date_iso": read_date_iso,
            "mode": mode,
            "usage": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest()
    return _HistoryCandidate(
        source_row_id=str(row["_source_row_id"]),
        slot=slot,
        machine_name=machine_name,
        serial=serial,
        read_date=read_date,
        read_date_iso=read_date_iso,
        billing_month=billing_month,
        mode=mode,
        data_json=normalized_json,
        parser_name=parser_name,
        fingerprint=fingerprint,
    )


def _load_source_candidates(path: Path) -> tuple[int, list[_HistoryCandidate], int]:
    try:
        with closing(_open_readonly(path)) as source:
            integrity = source.execute("PRAGMA quick_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise LegacyHistoryImportError("Database V4.6 ไม่สมบูรณ์ กรุณาเลือกสำเนาใหม่")
            columns = _source_columns(source)
            schema_version = int(source.execute("PRAGMA user_version").fetchone()[0])
            source_id = "id" if "id" in columns else "rowid"
            optional = [
                f'"{column}"' if column in columns else f"NULL AS \"{column}\""
                for column in _OPTIONAL_SOURCE_COLUMNS
            ]
            query = (
                f'SELECT "{source_id}" AS _source_row_id, "slot", "data_json", '
                + ", ".join(optional)
                + ' FROM "readings" ORDER BY "slot", _source_row_id'
            )
            rows = source.execute(query).fetchall()
    except LegacyHistoryImportError:
        raise
    except sqlite3.Error as err:
        raise LegacyHistoryImportError(f"เปิด Database V4.6 ไม่ได้: {err}") from err

    candidates: list[_HistoryCandidate] = []
    rejected = 0
    for row in rows:
        try:
            candidates.append(_candidate_from_row(row))
        except LegacyHistoryImportError:
            rejected += 1
    return schema_version, candidates, rejected


def _existing_fingerprints(destination_path: Path) -> set[str]:
    fingerprints: set[str] = set()
    try:
        with closing(sqlite3.connect(destination_path)) as destination:
            destination.row_factory = sqlite3.Row
            if _table_exists(destination, "legacy_history_items"):
                fingerprints.update(
                    str(row[0])
                    for row in destination.execute("SELECT row_fingerprint FROM legacy_history_items")
                )
            if not _table_exists(destination, "readings"):
                return fingerprints
            columns = {str(row[1]) for row in destination.execute("PRAGMA table_info(readings)")}
            optional = [
                f'"{column}"' if column in columns else f"NULL AS \"{column}\""
                for column in _OPTIONAL_SOURCE_COLUMNS
            ]
            query = (
                'SELECT "id" AS _source_row_id, "slot", "data_json", '
                + ", ".join(optional)
                + ' FROM "readings" ORDER BY "id"'
            )
            for row in destination.execute(query):
                try:
                    fingerprints.add(_candidate_from_row(row).fingerprint)
                except LegacyHistoryImportError:
                    continue
    except sqlite3.Error as err:
        raise LegacyHistoryImportError(f"อ่าน Database V5 ไม่ได้: {err}") from err
    return fingerprints


def _scan(
    source_path: Path, destination_path: Path
) -> tuple[LegacyHistoryPreview, list[_HistoryCandidate]]:
    source = source_path.expanduser().resolve()
    destination = destination_path.expanduser().resolve()
    if not source.is_file():
        raise LegacyHistoryImportError("ไม่พบไฟล์ Database ที่เลือก")
    if source == destination:
        raise LegacyHistoryImportError("กรุณาเลือกสำเนา Database V4.6 ไม่ใช่ Database V5 ที่กำลังใช้งาน")
    if not destination.is_file():
        raise LegacyHistoryImportError("ไม่พบ Database V5 ปัจจุบัน")

    # Hash and read the same SQLite-consistent snapshot. This includes rows
    # committed in a WAL file without modifying or checkpointing the source.
    with _consistent_source_snapshot(source) as snapshot:
        source_hash = _file_sha256(snapshot)
        schema_version, candidates, rejected = _load_source_candidates(snapshot)
    existing = _existing_fingerprints(destination)
    seen = set(existing)
    new_candidates: list[_HistoryCandidate] = []
    duplicates = 0
    for candidate in candidates:
        if candidate.fingerprint in seen:
            duplicates += 1
            continue
        seen.add(candidate.fingerprint)
        new_candidates.append(candidate)

    counts: Counter[tuple[int, str, str]] = Counter(
        (candidate.slot, candidate.machine_name, candidate.serial) for candidate in candidates
    )
    devices = tuple(
        LegacyDeviceSummary(slot=slot, machine_name=name, serial=serial, reading_count=count)
        for (slot, name, serial), count in sorted(counts.items())
    )
    dates = [candidate.read_date_iso for candidate in candidates]
    preview = LegacyHistoryPreview(
        source_path=source,
        source_sha256=source_hash,
        source_schema_version=schema_version,
        total_rows=len(candidates) + rejected,
        valid_rows=len(candidates),
        new_rows=len(new_candidates),
        duplicate_rows=duplicates,
        rejected_rows=rejected,
        date_min=min(dates) if dates else "",
        date_max=max(dates) if dates else "",
        devices=devices,
    )
    return preview, new_candidates


def preview_legacy_history(
    source_path: str | Path, *, destination_path: str | Path | None = None
) -> LegacyHistoryPreview:
    """Inspect a V4.6 database without writing to either database."""

    destination = Path(destination_path) if destination_path is not None else database.get_db_path()
    preview, _ = _scan(Path(source_path), Path(destination))
    return preview


def _backup_path(destination: Path) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    candidate = destination.with_name(
        f"{destination.stem}.before-v46-history-import-{stamp}{destination.suffix}"
    )
    counter = 2
    while candidate.exists():
        candidate = destination.with_name(
            f"{destination.stem}.before-v46-history-import-{stamp}-{counter}{destination.suffix}"
        )
        counter += 1
    return candidate


def import_legacy_history(
    preview: LegacyHistoryPreview, *, destination_path: str | Path | None = None
) -> LegacyHistoryImportResult:
    """Back up V5, then atomically import only sanitized usage-history rows."""

    destination = (
        Path(destination_path).expanduser().resolve()
        if destination_path is not None
        else database.get_db_path().expanduser().resolve()
    )
    current, candidates = _scan(preview.source_path, destination)
    if current.source_sha256 != preview.source_sha256:
        raise LegacyHistoryImportError("Database V4.6 เปลี่ยนระหว่างตรวจสอบ กรุณา Preview ใหม่")
    if not candidates:
        raise LegacyHistoryImportError("ไม่มีประวัติการใช้งานใหม่สำหรับนำเข้า")

    backup_path = _backup_path(destination)
    with closing(sqlite3.connect(destination)) as source, closing(sqlite3.connect(backup_path)) as backup:
        source.backup(backup)

    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        with closing(sqlite3.connect(destination, timeout=30)) as connection:
            with connection:
                connection.execute("PRAGMA foreign_keys = ON")
                ensure_legacy_history_import_schema(connection)
                apply_migrations(connection)
                cursor = connection.execute(
                    """INSERT INTO legacy_history_imports(
                           source_file_name,source_sha256,source_schema_version,date_min,date_max,
                           total_rows,imported_rows,duplicate_rows,rejected_rows,imported_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        preview.source_path.name,
                        preview.source_sha256,
                        preview.source_schema_version,
                        current.date_min,
                        current.date_max,
                        current.total_rows,
                        len(candidates),
                        current.duplicate_rows,
                        current.rejected_rows,
                        imported_at,
                    ),
                )
                import_id = int(cursor.lastrowid)
                for candidate in candidates:
                    reading = connection.execute(
                        """INSERT INTO readings(
                               slot,machine_name,serial,read_date,read_date_iso,billing_month,
                               mode,data_json,imported_at,file_name,parser_name
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            candidate.slot,
                            candidate.machine_name,
                            candidate.serial,
                            candidate.read_date,
                            candidate.read_date_iso,
                            candidate.billing_month,
                            candidate.mode,
                            candidate.data_json,
                            imported_at,
                            preview.source_path.name,
                            "legacy_v4.6_database",
                        ),
                    )
                    connection.execute(
                        """INSERT INTO legacy_history_items(
                               import_id,reading_id,source_row_id,row_fingerprint
                           ) VALUES(?,?,?,?)""",
                        (
                            import_id,
                            int(reading.lastrowid),
                            candidate.source_row_id,
                            candidate.fingerprint,
                        ),
                    )
    except Exception as err:
        log.exception("V4.6 usage-history import failed")
        raise LegacyHistoryImportError(f"นำเข้าประวัติไม่สำเร็จ: {err}") from err

    database._clear_read_caches()
    return LegacyHistoryImportResult(
        import_id=import_id,
        imported_rows=len(candidates),
        duplicate_rows=current.duplicate_rows,
        rejected_rows=current.rejected_rows,
        backup_path=backup_path,
        source_sha256=preview.source_sha256,
    )


def _counter_value(payload: dict[str, Any], group: str, key: str) -> float:
    try:
        return float((payload.get(group, {}) or {}).get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _same_legacy_meter_lineage(
    previous: LegacyUsageSnapshot,
    current: LegacyUsageSnapshot,
) -> bool:
    """Return False at a physical-printer replacement or meter reset boundary."""

    old_serial = previous.serial.strip()
    new_serial = current.serial.strip()
    if old_serial and new_serial and old_serial != new_serial:
        return False
    return current.total >= previous.total


def build_legacy_usage_intervals(
    snapshots: tuple[LegacyUsageSnapshot, ...] | list[LegacyUsageSnapshot],
) -> tuple[LegacyUsageInterval, ...]:
    """Convert V4.6 meter snapshots into Slot-based usage without crossing printers."""

    ordered = sorted(snapshots, key=lambda item: (item.slot, item.read_date, item.serial))
    previous_by_slot: dict[int, LegacyUsageSnapshot] = {}
    intervals: list[LegacyUsageInterval] = []
    counter_names = ("total", "a3_color", "a3_bw", "a4_color", "a4_bw")

    for snapshot in ordered:
        try:
            read_day = date.fromisoformat(snapshot.read_date[:10])
        except ValueError:
            continue
        previous = previous_by_slot.get(snapshot.slot)
        previous_by_slot[snapshot.slot] = snapshot
        if previous is None:
            # The first absolute meter is a display-only baseline. It must not
            # become usage, cost, or a chart point.
            continue
        if previous is not None and not _same_legacy_meter_lineage(previous, snapshot):
            # The first snapshot of a replacement printer is its baseline.  It
            # remains visible in V4.6 History but never becomes usage.
            continue

        values = {
            name: max(
                0.0,
                float(getattr(snapshot, name))
                - (float(getattr(previous, name)) if previous is not None else 0.0),
            )
            for name in counter_names
        }
        if not any(values.values()):
            continue
        intervals.append(
            LegacyUsageInterval(
                device_slot=snapshot.slot,
                period_start=read_day,
                period_end=read_day,
                billing_month=snapshot.billing_month or read_day.strftime("%Y-%m"),
                total=values["total"],
                a3_color=values["a3_color"],
                a3_bw=values["a3_bw"],
                a4_color=values["a4_color"],
                a4_bw=values["a4_bw"],
                scan=0.0,
                gross_cost=0.0,
                net_cost=0.0,
                device_identity=f"slot:{snapshot.slot}",
                device_name_snapshot=snapshot.machine_name,
                device_serial_snapshot=snapshot.serial,
            )
        )
    return tuple(intervals)


def load_imported_legacy_history(
    *, destination_path: str | Path | None = None
) -> tuple[LegacyUsageSnapshot, ...]:
    """Return imported V4.6 meter snapshots for the read-only Reports tab."""

    destination = (
        Path(destination_path).expanduser().resolve()
        if destination_path is not None
        else database.get_db_path().expanduser().resolve()
    )
    if not destination.is_file():
        return ()
    try:
        with closing(sqlite3.connect(destination)) as connection:
            connection.row_factory = sqlite3.Row
            if not _table_exists(connection, "legacy_history_items"):
                return ()
            rows = connection.execute(
                """SELECT r.read_date_iso,r.read_date,r.billing_month,r.slot,
                          r.machine_name,r.serial,r.data_json
                   FROM legacy_history_items AS item
                   JOIN readings AS r ON r.id=item.reading_id
                   ORDER BY r.read_date_iso DESC,r.id DESC"""
            ).fetchall()
    except sqlite3.Error as err:
        log.warning("cannot load imported V4.6 history: %s", err)
        return ()

    snapshots: list[LegacyUsageSnapshot] = []
    for row in rows:
        try:
            payload = json.loads(str(row["data_json"] or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        color = _counter_value(payload, "summary", "total_color")
        bw = _counter_value(payload, "summary", "total_bw")
        if color == 0 and bw == 0:
            color = _counter_value(payload, "meters", "color_meter")
            bw = _counter_value(payload, "meters", "bw_meter")
        total = _counter_value(payload, "summary", "total") or color + bw
        snapshots.append(
            LegacyUsageSnapshot(
                read_date=str(row["read_date_iso"] or row["read_date"] or ""),
                billing_month=str(row["billing_month"] or ""),
                slot=int(row["slot"]),
                machine_name=str(row["machine_name"] or ""),
                serial=str(row["serial"] or ""),
                total=total,
                color=color,
                bw=bw,
                a3_color=_counter_value(payload, "paper_color", "a3_color"),
                a3_bw=_counter_value(payload, "paper_color", "a3_bw"),
                a4_color=_counter_value(payload, "paper_color", "a4_color"),
                a4_bw=_counter_value(payload, "paper_color", "a4_bw"),
            )
        )
    return tuple(snapshots)
