from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from database import _open, get_billing_day, get_cfg, get_db_path
from komi_snmp_profiler.models import MeterReading, WebCounterValue
from services.billing_periods import billing_month_range
from services.daily_cache import DailyCacheStore


def _timestamp(value: str) -> float:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.timestamp()


def _device_identity_snapshot(slot: int) -> dict[str, str]:
    with _open(commit=False) as conn:
        row = conn.execute("SELECT name,serial,host FROM devices WHERE slot=?", (slot,)).fetchone()
    name, serial, host = row or ("", "", "")
    return {"name": name or "", "serial": serial or "", "host": host or ""}


def _identity_matches(captured: dict, current: dict) -> bool:
    old_serial = str(captured.get("serial") or "").strip()
    new_serial = str(current.get("serial") or "").strip()
    if old_serial and new_serial:
        return old_serial == new_serial
    old_host = str(captured.get("host") or "").strip()
    new_host = str(current.get("host") or "").strip()
    return bool(old_host and new_host and old_host == new_host)


def _identity_snapshot(value: object, slot: int) -> tuple[str, str, str]:
    """Extract a stable identity from cache/source JSON without using current slot data."""

    source = value if isinstance(value, dict) else {}
    captured = source.get("device_identity") if isinstance(source, dict) else None
    if not isinstance(captured, dict):
        captured = {}
    name = str(captured.get("name") or "")
    serial = str(captured.get("serial") or "").strip()
    host = str(captured.get("host") or "").strip()
    identity = f"serial:{serial}" if serial else (f"host:{host}" if host else f"unattributed:slot:{slot}")
    return identity, name, serial


def _source_identity(source_json: object, slot: int) -> tuple[str, str, str]:
    try:
        source = json.loads(source_json) if isinstance(source_json, str) else source_json
    except json.JSONDecodeError:
        source = {}
    return _identity_snapshot(source, slot)


@dataclass(frozen=True)
class SubjectCounter:
    subject_type: str
    subject_id: str
    subject_name: str
    total_counter: float
    canonical_field: str
    source_path: str
    warnings: tuple[str, ...] = ()

    @property
    def identity_key(self) -> str:
        return f"{self.subject_type}:{self.subject_id}"


@dataclass(frozen=True)
class SubjectDailyRecord:
    device_slot: int
    record_date: date
    subject_type: str
    subject_id: str
    subject_name: str
    opening_total: float
    closing_total: float
    delta_total: float
    reset_count: int
    missing_baseline: bool
    sample_count: int
    first_success: str | None
    last_success: str | None
    incomplete: bool
    warnings: tuple[str, ...]
    device_identity: str = ""
    device_name_snapshot: str = ""
    device_serial_snapshot: str = ""


@dataclass(frozen=True)
class SubjectPeriodUsage:
    device_slot: int
    period_start: date
    period_end: date
    subject_type: str
    subject_id: str
    subject_name: str
    latest_total: float
    period_usage: float
    reset_count: int
    missing_baseline_days: int
    incomplete_days: int
    sample_count: int
    latest_at: str | None
    warnings: tuple[str, ...]
    device_identity: str = ""
    device_name_snapshot: str = ""
    device_serial_snapshot: str = ""

    @property
    def needs_review(self) -> bool:
        return bool(self.reset_count or self.missing_baseline_days or self.warnings)


def _number(value: int | float) -> float:
    if isinstance(value, bool):
        return 0.0
    return float(value)


def extract_subject_totals(reading: MeterReading) -> tuple[SubjectCounter, ...]:
    """Return exact User/Account total counters without estimating size or color."""

    grouped: dict[tuple[str, str, str], list[WebCounterValue]] = {}
    for counter in reading.counters:
        subject_type = (counter.subject_type or "").strip().lower()
        if subject_type not in {"user", "track", "account"}:
            continue
        expected = f"counter.{subject_type}.total.total"
        if counter.canonical_field != expected:
            continue
        name = (counter.subject_name or counter.subject_id or "Unknown").strip() or "Unknown"
        raw_id = (counter.subject_id or "").strip()
        subject_id = raw_id or f"name:{name.casefold()}"
        grouped.setdefault((subject_type, subject_id, name), []).append(counter)

    result: list[SubjectCounter] = []
    for (subject_type, subject_id, name), counters in sorted(grouped.items()):
        values = {_number(counter.count) for counter in counters}
        warnings: list[str] = []
        if subject_id.startswith("name:"):
            warnings.append("missing_subject_id")
        if len(values) > 1:
            warnings.append("conflicting_total_fields")
        selected = counters[-1]
        result.append(
            SubjectCounter(
                subject_type=subject_type,
                subject_id=subject_id,
                subject_name=name,
                total_counter=_number(selected.count),
                canonical_field=selected.canonical_field,
                source_path=selected.source_path,
                warnings=tuple(warnings),
            )
        )
    return tuple(result)


class SubjectDailyCacheStore:
    """Persistent daily working state for User/Auth and Account Track totals."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_db_path().parent / "runtime-cache" / "subjects"

    def path(self, slot: int, day: date) -> Path:
        return self.root / f"device-{slot + 1}" / f"{day.isoformat()}.json"

    def load(self, slot: int, day: date) -> dict | None:
        path = self.path(slot, day)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _previous_total(slot: int, subject_type: str, subject_id: str, day: date) -> tuple[float | None, dict, dict | None]:
        with _open(commit=False) as conn:
            row = conn.execute(
                """SELECT closing_total,source_json FROM daily_subject_records
                   WHERE device_slot=? AND subject_type=? AND subject_id=? AND record_date<?
                   ORDER BY record_date DESC LIMIT 1""",
                (slot, subject_type, subject_id, day.isoformat()),
            ).fetchone()
        if row is None:
            return None, {}, None
        try:
            source = json.loads(row[1])
        except (TypeError, json.JSONDecodeError):
            source = {}
        identity = source.get("device_identity", {}) if isinstance(source, dict) else {}
        review = source.get("counter_review") if isinstance(source, dict) else None
        if isinstance(source, dict) and not review and source.get("resets") and not source.get("counter_resolutions"):
            review = {**source["resets"][-1], "reason": "legacy_reset_requires_review"}
        return float(row[0]), identity if isinstance(identity, dict) else {}, review

    def update_reading(self, slot: int, reading: MeterReading, *, at: datetime | None = None) -> dict:
        stamp = at or datetime.fromisoformat(reading.collected_at.replace("Z", "+00:00")).astimezone()
        with DailyCacheStore._path_lock(self.path(slot, stamp.date())):
            return self._update_reading(slot, reading, at=stamp)

    def _update_reading(self, slot: int, reading: MeterReading, *, at: datetime) -> dict:
        stamp = at
        day = stamp.date()
        loaded = self.load(slot, day)
        state = loaded or {
            "schema_version": "komi.subject.daily.cache.v1",
            "device_slot": slot,
            "record_date": day.isoformat(),
            "subjects": {},
            "sample_count": 0,
            "device_identity": _device_identity_snapshot(slot),
        }
        current_identity = _device_identity_snapshot(slot)
        if not isinstance(state.get("device_identity"), dict):
            state["device_identity"] = current_identity
        captured_identity = state["device_identity"]
        if loaded is not None and not _identity_matches(captured_identity, current_identity):
            issue = {
                "at": stamp.isoformat(timespec="seconds"),
                "reason": "device_identity_changed_during_day",
                "captured": captured_identity,
                "current": current_identity,
            }
            state["identity_conflict"] = issue
            state["rejected_sample_count"] = int(state.get("rejected_sample_count", 0)) + 1
            for item in state.get("subjects", {}).values():
                item["warnings"] = sorted(
                    set(item.get("warnings", ())) | {"device_identity_changed_during_day"}
                )
            self._atomic_write(self.path(slot, day), state)
            return state
        subjects = state.setdefault("subjects", {})
        for item in subjects.values():
            if item.get("resets") and not item.get("counter_review") and not item.get("counter_resolutions"):
                item["counter_review"] = {**item["resets"][-1], "reason": "legacy_reset_requires_review"}
                item["warnings"] = sorted(set(item.get("warnings", ())) | {"counter_baseline_review"})
        counters = extract_subject_totals(reading)
        incoming_stamp = stamp.isoformat(timespec="seconds")
        previous_stamp = state.get("last_success")
        if loaded is not None and previous_stamp:
            try:
                ordering = (_timestamp(incoming_stamp) > _timestamp(previous_stamp)) - (
                    _timestamp(incoming_stamp) < _timestamp(previous_stamp)
                )
            except (TypeError, ValueError):
                ordering = -1
            same_values = all(
                counter.identity_key in subjects
                and float(subjects[counter.identity_key].get("latest_total", 0.0)) == counter.total_counter
                for counter in counters
            )
            if ordering < 0 or (ordering == 0 and not same_values):
                issue = {
                    "at": incoming_stamp,
                    "last_success": previous_stamp,
                    "reason": "late_sample" if ordering < 0 else "same_timestamp_conflict",
                }
                state.setdefault("ordering_issues", []).append(issue)
                state["rejected_sample_count"] = int(state.get("rejected_sample_count", 0)) + 1
                for counter in counters:
                    item = subjects.get(counter.identity_key)
                    if item is not None:
                        item["warnings"] = sorted(set(item.get("warnings", ())) | {"out_of_order_sample"})
                self._atomic_write(self.path(slot, day), state)
                return state
            if ordering == 0:
                state["duplicate_sample_count"] = int(state.get("duplicate_sample_count", 0)) + 1
                self._atomic_write(self.path(slot, day), state)
                return state

        for counter in counters:
            item = subjects.get(counter.identity_key)
            if item is None:
                previous_total, previous_identity, previous_review = self._previous_total(
                    slot, counter.subject_type, counter.subject_id, day
                )
                has_baseline = previous_total is not None and _identity_matches(previous_identity, current_identity)
                opening = previous_total if has_baseline else counter.total_counter
                warnings = list(counter.warnings)
                if previous_total is not None and not has_baseline:
                    warnings.append("device_identity_baseline_mismatch")
                item = {
                    "subject_type": counter.subject_type,
                    "subject_id": counter.subject_id,
                    "subject_name": counter.subject_name,
                    "opening_total": opening,
                    "latest_total": opening,
                    "delta_total": 0.0,
                    "reset_count": 0,
                    "resets": [],
                    "missing_baseline": not has_baseline,
                    "sample_count": 0,
                    "first_success": incoming_stamp,
                    "last_success": incoming_stamp,
                    "canonical_field": counter.canonical_field,
                    "source_path": counter.source_path,
                    "source": reading.source,
                    "warnings": warnings,
                }
                subjects[counter.identity_key] = item
                if has_baseline and previous_review:
                    item["counter_review"] = previous_review
                    item["warnings"].append("counter_baseline_review")

            previous = float(item.get("latest_total", counter.total_counter))
            current = counter.total_counter
            if item.get("counter_review"):
                pass  # Keep observing while usage is held for a reviewed baseline.
            elif current >= previous:
                item["delta_total"] = float(item.get("delta_total", 0.0)) + current - previous
            else:
                item["counter_review"] = {"before": previous, "after": current, "at": incoming_stamp}
                item["warnings"].append("counter_baseline_review")
                item["reset_count"] = int(item.get("reset_count", 0)) + 1
                item.setdefault("resets", []).append(
                    {
                        "before": previous,
                        "after": current,
                        "at": incoming_stamp,
                    }
                )
            item["subject_name"] = counter.subject_name
            item["latest_total"] = current
            item["last_success"] = incoming_stamp
            item["sample_count"] = int(item.get("sample_count", 0)) + 1
            item["warnings"] = sorted(set(item.get("warnings", ())) | set(counter.warnings))

        state["sample_count"] = int(state.get("sample_count", 0)) + 1
        state["last_success"] = incoming_stamp
        self._atomic_write(self.path(slot, day), state)
        return state

    def finalize(self, slot: int, day: date, *, incomplete: bool = False) -> tuple[SubjectDailyRecord, ...]:
        with DailyCacheStore._path_lock(self.path(slot, day)):
            return self._finalize(slot, day, incomplete=incomplete)

    def _finalize(self, slot: int, day: date, *, incomplete: bool) -> tuple[SubjectDailyRecord, ...]:
        state = self.load(slot, day)
        if not state:
            return ()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        records: list[SubjectDailyRecord] = []
        expected = {
            (item["subject_type"], item["subject_id"]): (
                item["subject_name"],
                float(item.get("opening_total", 0.0)),
                float(item.get("latest_total", 0.0)),
                float(item.get("delta_total", 0.0)),
                int(item.get("reset_count", 0)),
                int(bool(item.get("missing_baseline"))),
                int(item.get("sample_count", 0)),
                item.get("first_success"),
                item.get("last_success"),
                int(incomplete),
                tuple(item.get("warnings", ())),
            )
            for item in state.get("subjects", {}).values()
        }
        with _open() as conn:
            existing_rows = conn.execute(
                """SELECT subject_type,subject_id,subject_name,opening_total,closing_total,delta_total,
                          reset_count,missing_baseline,sample_count,first_success,last_success,incomplete,warnings_json
                   FROM daily_subject_records WHERE device_slot=? AND record_date=?""",
                (slot, day.isoformat()),
            ).fetchall()
            existing = {
                (row[0], row[1]): (*row[2:12], tuple(json.loads(row[12] or "[]")))
                for row in existing_rows
            }
            if existing:
                if existing == expected:
                    self.path(slot, day).unlink(missing_ok=True)
                else:
                    state["finalization_conflict"] = {
                        "detected_at": now,
                        "reason": "same_day_subject_evidence_differs",
                    }
                    self._atomic_write(self.path(slot, day), state)
                return ()
            for item in state.get("subjects", {}).values():
                warnings = tuple(item.get("warnings", ()))
                cursor = conn.execute(
                    """INSERT INTO daily_subject_records(
                           device_slot,record_date,subject_type,subject_id,subject_name,
                           opening_total,closing_total,delta_total,reset_count,missing_baseline,
                           sample_count,first_success,last_success,incomplete,warnings_json,source_json,created_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(device_slot,record_date,subject_type,subject_id) DO NOTHING""",
                    (
                        slot,
                        day.isoformat(),
                        item["subject_type"],
                        item["subject_id"],
                        item["subject_name"],
                        float(item.get("opening_total", 0.0)),
                        float(item.get("latest_total", 0.0)),
                        float(item.get("delta_total", 0.0)),
                        int(item.get("reset_count", 0)),
                        int(bool(item.get("missing_baseline"))),
                        int(item.get("sample_count", 0)),
                        item.get("first_success"),
                        item.get("last_success"),
                        int(incomplete),
                        json.dumps(warnings, ensure_ascii=False),
                        json.dumps(
                            {
                                "canonical_field": item.get("canonical_field"),
                                "source_path": item.get("source_path"),
                                "source": item.get("source"),
                                "device_identity": state.get("device_identity", {}),
                                "resets": item.get("resets", []),
                                "counter_review": item.get("counter_review"),
                                "counter_resolutions": item.get("counter_resolutions", []),
                                "ordering_issues": state.get("ordering_issues", []),
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now,
                    ),
                )
                if cursor.rowcount:
                    records.append(
                        _daily_record_from_cache(
                            slot,
                            day,
                            item,
                            incomplete,
                            identity_source=state,
                        )
                    )
        self.path(slot, day).unlink(missing_ok=True)
        return tuple(records)

    def _review_candidate(self, slot: int, day: date, key: str) -> tuple[dict, dict, dict]:
        with _open(commit=False) as conn:
            if conn.execute("SELECT 1 FROM daily_subject_records WHERE device_slot=? AND record_date=?",
                            (slot, day.isoformat())).fetchone():
                raise ValueError("Finalized days require an amended-report workflow")
        state = self.load(slot, day) or {}
        item = state.get("subjects", {}).get(key, {})
        identity = _device_identity_snapshot(slot)
        captured = state.get("device_identity", {})
        if (not item.get("counter_review") or not item.get("sample_count")
                or state.get("identity_conflict") or not identity.get("serial")
                or captured.get("serial") != identity["serial"]):
            raise ValueError("A pending review and current serial-bound Web observation are required")
        return state, item, identity

    def preview_counter_baseline(self, slot: int, day: date, key: str) -> dict:
        with DailyCacheStore._path_lock(self.path(slot, day)):
            state, item, identity = self._review_candidate(slot, day, key)
            issue = item["counter_review"]
            return {"revision": DailyCacheStore._review_revision(state), "device_identity": identity,
                    "label": f"{item['subject_type']} · {item['subject_name']} ({item['subject_id']})",
                    "key": key, "before": issue["before"], "detected_at": issue["at"],
                    "baseline": item["latest_total"], "observed_at": item["last_success"],
                    "preserved_delta": item["delta_total"]}

    def confirm_counter_baseline(self, slot: int, day: date, key: str, *,
                                 expected_revision: str, actor: str, reason: str,
                                 at: datetime | None = None) -> dict:
        stamp = at or datetime.now().astimezone()
        if stamp.date() != day or not actor.strip() or not reason.strip():
            raise ValueError("Resolution needs today's observation, actor and reason")
        with DailyCacheStore._path_lock(self.path(slot, day)):
            state, item, identity = self._review_candidate(slot, day, key)
            if DailyCacheStore._review_revision(state) != expected_revision:
                raise ValueError("Counter changed after preview; review again")
            if _timestamp(stamp.isoformat()) < _timestamp(item["last_success"]):
                raise ValueError("Resolution cannot precede its observation")
            issue = item["counter_review"]
            resolution = {"id": str(uuid.uuid4()), "key": key, "review_at": issue["at"],
                          "previous_counter": issue["before"], "baseline": item["latest_total"],
                          "observed_at": item["last_success"], "resolved_at": stamp.isoformat(),
                          "actor": actor.strip(), "reason": reason.strip(), "device_identity": identity,
                          "preserved_delta": item["delta_total"]}
            item.setdefault("counter_resolutions", []).append(resolution)
            del item["counter_review"]
            self._atomic_write(self.path(slot, day), state)
            return resolution

    def finalize_before(self, today: date) -> tuple[SubjectDailyRecord, ...]:
        records: list[SubjectDailyRecord] = []
        if not self.root.exists():
            return ()
        for path in self.root.glob("device-*/*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
                day = date.fromisoformat(state["record_date"])
                slot = int(state["device_slot"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if day < today:
                complete = False
                try:
                    last_success = datetime.fromisoformat(state["last_success"])
                    hour, minute = (int(part) for part in get_cfg("work_end", "17:00").split(":", 1))
                    complete = (last_success.hour, last_success.minute) >= (hour, minute)
                except (KeyError, TypeError, ValueError):
                    pass
                records.extend(self.finalize(slot, day, incomplete=not complete))
        return tuple(records)

    @staticmethod
    def _atomic_write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)


def _daily_record_from_cache(
    slot: int,
    day: date,
    item: dict,
    incomplete: bool,
    *,
    identity_source: object | None = None,
) -> SubjectDailyRecord:
    device_identity, device_name, device_serial = _identity_snapshot(identity_source, slot)
    return SubjectDailyRecord(
        device_slot=slot,
        record_date=day,
        subject_type=item["subject_type"],
        subject_id=item["subject_id"],
        subject_name=item["subject_name"],
        opening_total=float(item.get("opening_total", 0.0)),
        closing_total=float(item.get("latest_total", 0.0)),
        delta_total=float(item.get("delta_total", 0.0)),
        reset_count=int(item.get("reset_count", 0)),
        missing_baseline=bool(item.get("missing_baseline")),
        sample_count=int(item.get("sample_count", 0)),
        first_success=item.get("first_success"),
        last_success=item.get("last_success"),
        incomplete=incomplete,
        warnings=tuple(item.get("warnings", ())),
        device_identity=device_identity,
        device_name_snapshot=device_name,
        device_serial_snapshot=device_serial,
    )


def _latest_device_ledger_periods(slots: list[int]) -> dict[tuple[int, date], tuple[date, date]]:
    """Return each device day's immutable period without changing legacy rows."""

    if not slots:
        return {}
    placeholders = ",".join("?" for _ in slots)
    with _open(commit=False) as conn:
        rows = conn.execute(
            f"""SELECT device_slot,record_date,period_start,period_end
                FROM billing_ledger
                WHERE device_slot IN ({placeholders})
                ORDER BY id""",
            slots,
        ).fetchall()

    periods: dict[tuple[int, date], tuple[date, date]] = {}
    for slot, record_day, period_start, period_end in rows:
        try:
            key = (int(slot), date.fromisoformat(record_day))
            periods[key] = (date.fromisoformat(period_start), date.fromisoformat(period_end))
        except (TypeError, ValueError):
            continue
    return periods


def load_subject_history(
    slots: list[int],
    *,
    today: date | None = None,
    cache: SubjectDailyCacheStore | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> tuple[SubjectPeriodUsage, ...]:
    current = today or date.today()
    billing_day = get_billing_day()
    frozen_periods = _latest_device_ledger_periods(slots)
    daily: list[tuple[SubjectDailyRecord, tuple[date, date] | None]] = []
    if slots:
        placeholders = ",".join("?" for _ in slots)
        with _open(commit=False) as conn:
            rows = conn.execute(
                f"""SELECT device_slot,record_date,subject_type,subject_id,subject_name,
                           opening_total,closing_total,delta_total,reset_count,missing_baseline,
                           sample_count,first_success,last_success,incomplete,warnings_json,source_json
                    FROM daily_subject_records WHERE device_slot IN ({placeholders})
                    ORDER BY record_date,device_slot,subject_type,subject_id""",
                slots,
            ).fetchall()
        for row in rows:
            device_identity, device_name, device_serial = _source_identity(row[15], int(row[0]))
            record = SubjectDailyRecord(
                device_slot=int(row[0]),
                record_date=date.fromisoformat(row[1]),
                subject_type=row[2],
                subject_id=row[3],
                subject_name=row[4],
                opening_total=float(row[5]),
                closing_total=float(row[6]),
                delta_total=float(row[7]),
                reset_count=int(row[8]),
                missing_baseline=bool(row[9]),
                sample_count=int(row[10]),
                first_success=row[11],
                last_success=row[12],
                incomplete=bool(row[13]),
                warnings=tuple(json.loads(row[14] or "[]")),
                device_identity=device_identity,
                device_name_snapshot=device_name,
                device_serial_snapshot=device_serial,
            )
            daily.append(
                (record, frozen_periods.get((record.device_slot, record.record_date)))
            )

    cache_store = cache or SubjectDailyCacheStore()
    for slot in slots:
        state = cache_store.load(slot, current)
        if not state:
            continue
        daily.extend(
            (
                _daily_record_from_cache(
                    slot,
                    current,
                    item,
                    False,
                    identity_source=state,
                ),
                None,
            )
            for item in state.get("subjects", {}).values()
        )

    buckets: dict[tuple[date, date, int, str, str, str], dict] = {}
    for record, frozen_period in daily:
        if period_start is not None and record.record_date < period_start:
            continue
        if period_end is not None and record.record_date > period_end:
            continue
        start, end = (
            (period_start, period_end)
            if period_start is not None and period_end is not None
            else frozen_period or billing_month_range(record.record_date, billing_day)
        )
        key = (
            start,
            end,
            record.device_slot,
            record.device_identity,
            record.subject_type,
            record.subject_id,
        )
        bucket = buckets.setdefault(
            key,
            {
                "name": record.subject_name,
                "device_name_snapshot": record.device_name_snapshot,
                "device_serial_snapshot": record.device_serial_snapshot,
                "latest_total": record.closing_total,
                "period_usage": 0.0,
                "reset_count": 0,
                "missing_baseline_days": 0,
                "incomplete_days": 0,
                "sample_count": 0,
                "latest_at": record.last_success,
                "warnings": set(),
                "latest_date": record.record_date,
            },
        )
        bucket["period_usage"] += record.delta_total
        bucket["reset_count"] += record.reset_count
        bucket["missing_baseline_days"] += int(record.missing_baseline)
        bucket["incomplete_days"] += int(record.incomplete)
        bucket["sample_count"] += record.sample_count
        bucket["warnings"].update(record.warnings)
        if record.record_date >= bucket["latest_date"]:
            bucket["latest_date"] = record.record_date
            bucket["latest_total"] = record.closing_total
            bucket["latest_at"] = record.last_success
            bucket["name"] = record.subject_name
            bucket["device_name_snapshot"] = record.device_name_snapshot
            bucket["device_serial_snapshot"] = record.device_serial_snapshot

    result = [
        SubjectPeriodUsage(
            device_slot=slot,
            period_start=start,
            period_end=end,
            subject_type=subject_type,
            subject_id=subject_id,
            subject_name=bucket["name"],
            latest_total=bucket["latest_total"],
            period_usage=bucket["period_usage"],
            reset_count=bucket["reset_count"],
            missing_baseline_days=bucket["missing_baseline_days"],
            incomplete_days=bucket["incomplete_days"],
            sample_count=bucket["sample_count"],
            latest_at=bucket["latest_at"],
            warnings=tuple(sorted(bucket["warnings"])),
            device_identity=device_identity,
            device_name_snapshot=bucket["device_name_snapshot"],
            device_serial_snapshot=bucket["device_serial_snapshot"],
        )
        for (
            start,
            end,
            slot,
            device_identity,
            subject_type,
            subject_id,
        ), bucket in buckets.items()
    ]
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.period_start,
                item.period_usage,
                item.device_identity,
                item.subject_name.casefold(),
            ),
            reverse=True,
        )
    )
