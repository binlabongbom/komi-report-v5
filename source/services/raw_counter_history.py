"""Exact, report-only daily history for every Web Connection counter.

The normal KOMI reports intentionally map supported counters into billing
categories.  The Legacy report has the opposite contract: retain the source
label, canonical key and value exactly as received so operators can inspect
model-specific counters such as A5 or Fax without inventing a mapping.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime

from database import _open
from komi_snmp_profiler.models import MeterReading


@dataclass(frozen=True)
class RawCounterDailyRecord:
    device_slot: int
    record_date: date
    canonical_field: str
    label: str
    source_path: str
    subject_type: str
    subject_id: str
    subject_name: str
    opening_value: float
    closing_value: float
    delta_value: float
    reset_count: int
    sample_count: int
    first_success: str
    last_success: str
    source_name: str
    device_name_snapshot: str
    device_serial_snapshot: str
    incomplete: bool
    pending_review: bool = False
    baseline_reviewed: bool = False

    @property
    def needs_review(self) -> bool:
        return bool(self.pending_review or self.baseline_reviewed or self.reset_count)

    @property
    def is_subject(self) -> bool:
        return bool(self.subject_type)


@dataclass(frozen=True)
class UsageMeterBaseline:
    """Absolute first meter for display only; never a usage or billing row."""

    device_slot: int
    observed_on: date
    total_meter: float
    device_name_snapshot: str = ""
    device_serial_snapshot: str = ""
    source: str = "raw_counter_history"


def _non_negative_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _serial_matches(current_serial: str, candidate_serial: str) -> bool:
    current = current_serial.strip().casefold()
    return not current or current == candidate_serial.strip().casefold()


def load_usage_meter_baselines(
    slots: tuple[int, ...] | list[int] | None = None,
) -> tuple[UsageMeterBaseline, ...]:
    """Load the first absolute Total Meter for each currently known Slot.

    Exact Raw Counter history is authoritative. Older databases created before
    Raw Counter history fall back to the immutable daily opening snapshot. A
    current Serial Number match prevents a replaced printer from inheriting the
    previous printer's absolute meter.
    """

    requested = None if slots is None else {int(slot) for slot in slots}
    with _open(commit=False) as connection:
        device_rows = connection.execute(
            "SELECT slot,name,serial FROM devices ORDER BY slot"
        ).fetchall()
        raw_rows = connection.execute(
            """SELECT device_slot,record_date,opening_value,
                      device_name_snapshot,device_serial_snapshot
               FROM daily_raw_counter_records
               WHERE canonical_field='counter.total.total' AND subject_type=''
               ORDER BY record_date,first_success,id"""
        ).fetchall()
        daily_rows = connection.execute(
            """SELECT device_slot,record_date,opening_json,source_json
               FROM daily_meter_records
               ORDER BY record_date,first_success,id"""
        ).fetchall()

    devices = {
        int(slot): (str(name or ""), str(serial or ""))
        for slot, name, serial in device_rows
        if requested is None or int(slot) in requested
    }
    if requested is not None:
        for slot in requested:
            devices.setdefault(slot, ("", ""))

    baselines: dict[int, UsageMeterBaseline] = {}
    for slot, record_date, opening, name, serial in raw_rows:
        slot = int(slot)
        if slot not in devices or slot in baselines:
            continue
        current_name, current_serial = devices[slot]
        candidate_serial = str(serial or "")
        if not _serial_matches(current_serial, candidate_serial):
            continue
        total = _non_negative_number(opening)
        if total is None:
            continue
        try:
            observed_on = date.fromisoformat(str(record_date)[:10])
        except ValueError:
            continue
        baselines[slot] = UsageMeterBaseline(
            device_slot=slot,
            observed_on=observed_on,
            total_meter=total,
            device_name_snapshot=str(name or current_name),
            device_serial_snapshot=candidate_serial or current_serial,
        )

    for slot, record_date, opening_json, source_json in daily_rows:
        slot = int(slot)
        if slot not in devices or slot in baselines:
            continue
        try:
            opening = json.loads(str(opening_json or "{}"))
            source = json.loads(str(source_json or "{}"))
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(opening, dict) or not isinstance(source, dict):
            continue
        identity = source.get("device_identity")
        identity = identity if isinstance(identity, dict) else {}
        current_name, current_serial = devices[slot]
        candidate_serial = str(identity.get("serial") or "")
        if not _serial_matches(current_serial, candidate_serial):
            continue
        total = _non_negative_number(opening.get("counter.total.total"))
        if total is None:
            continue
        try:
            observed_on = date.fromisoformat(str(record_date)[:10])
        except ValueError:
            continue
        baselines[slot] = UsageMeterBaseline(
            device_slot=slot,
            observed_on=observed_on,
            total_meter=total,
            device_name_snapshot=str(identity.get("name") or current_name),
            device_serial_snapshot=candidate_serial or current_serial,
            source="daily_meter_opening",
        )

    return tuple(baselines[slot] for slot in sorted(baselines))


def _subject_identity(counter) -> tuple[str, str, str]:
    subject_type = str(counter.subject_type or "").strip().lower()
    subject_name = str(counter.subject_name or "").strip()
    subject_id = str(counter.subject_id or "").strip()
    if subject_type and not subject_id:
        subject_id = f"name:{(subject_name or 'unknown').casefold()}"
    return subject_type, subject_id, subject_name


class RawCounterHistoryStore:
    """Upsert current-day exact counters without touching billing data."""

    def update_reading(
        self,
        slot: int,
        reading: MeterReading,
        *,
        at: datetime | None = None,
    ) -> int:
        stamp = at or datetime.fromisoformat(
            reading.collected_at.replace("Z", "+00:00")
        ).astimezone()
        stamp_text = stamp.isoformat(timespec="seconds")
        day = stamp.date().isoformat()
        with _open() as connection:
            connection.execute("BEGIN IMMEDIATE")
            device = connection.execute(
                "SELECT name,serial FROM devices WHERE slot=?", (slot,)
            ).fetchone()
            device_name, device_serial = device or (f"MFP {slot + 1}", "")
            device_serial = str(device_serial or "").strip()
            if not device_serial:
                raise ValueError(
                    "Raw Counter history requires printer Serial Number identity"
                )
            changed = 0
            from services.slot_cache_bridge import approved_baseline, bridge_raw_counter
            epoch = approved_baseline(connection, slot, reading, stamp)
            for counter in reading.counters:
                bridge_raw_counter(connection, epoch, slot, day, counter)
                subject_type, subject_id, subject_name = _subject_identity(counter)
                field = str(counter.canonical_field or "").strip()
                label = str(counter.label or field or "Unknown")
                value = float(counter.count)
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Web counter must be finite and non-negative")
                existing = connection.execute(
                    """SELECT closing_value,delta_value,reset_count,sample_count,
                              last_success,counter_review_json
                       FROM daily_raw_counter_records
                       WHERE device_slot=? AND record_date=? AND canonical_field=?
                         AND source_path=? AND subject_type=? AND subject_id=?
                         AND device_serial_snapshot=?""",
                    (
                        slot,
                        day,
                        field,
                        str(counter.source_path or ""),
                        subject_type,
                        subject_id,
                        device_serial,
                    ),
                ).fetchone()
                if existing is None:
                    previous_day = connection.execute(
                        """SELECT closing_value,counter_review_json,last_success
                           FROM daily_raw_counter_records
                           WHERE device_slot=? AND record_date<? AND canonical_field=?
                             AND source_path=? AND subject_type=? AND subject_id=?
                             AND device_serial_snapshot=?
                           ORDER BY record_date DESC,last_success DESC
                           LIMIT 1""",
                        (
                            slot,
                            day,
                            field,
                            str(counter.source_path or ""),
                            subject_type,
                            subject_id,
                            device_serial,
                        ),
                    ).fetchone()
                    opening = float(previous_day[0]) if previous_day else value
                    review = json.loads(previous_day[1]) if previous_day else None
                    from services.slot_cache_bridge import raw_baseline_after_gap
                    resolved = raw_baseline_after_gap(epoch, counter, previous_day[2] if previous_day else None)
                    if resolved:
                        opening, review = float(resolved['baseline']), None
                    if review:
                        initial_delta = 0.0
                        initial_resets = 0
                    elif value >= opening:
                        initial_delta = value - opening
                        initial_resets = 0
                    else:
                        initial_delta = 0.0
                        initial_resets = 1
                        review = {"before": opening, "after": value, "at": stamp_text}
                    connection.execute(
                        """INSERT INTO daily_raw_counter_records(
                               device_slot,record_date,canonical_field,label,source_path,
                               subject_type,subject_id,subject_name,opening_value,
                               closing_value,delta_value,reset_count,sample_count,
                               first_success,last_success,source_name,
                               device_name_snapshot,device_serial_snapshot,
                               incomplete,created_at,updated_at,counter_review_json,counter_resolutions_json
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            slot,
                            day,
                            field,
                            label,
                            str(counter.source_path or ""),
                            subject_type,
                            subject_id,
                            subject_name,
                            opening,
                            value,
                            initial_delta,
                            initial_resets,
                            1,
                            stamp_text,
                            stamp_text,
                            str(reading.source or ""),
                            str(device_name or f"MFP {slot + 1}"),
                            device_serial,
                            0,
                            stamp_text,
                            stamp_text,
                            json.dumps(review, sort_keys=True),
                            json.dumps([resolved] if resolved else [], sort_keys=True),
                        ),
                    )
                    changed += 1
                    continue

                closing, delta, resets, samples, last_success, review_json = existing
                review = json.loads(review_json)
                try:
                    previous_stamp = datetime.fromisoformat(str(last_success))
                    if previous_stamp.tzinfo is None:
                        previous_stamp = previous_stamp.astimezone()
                except (TypeError, ValueError):
                    previous_stamp = stamp
                if stamp < previous_stamp:
                    continue
                previous = float(closing)
                if stamp == previous_stamp:
                    continue
                if review:
                    next_delta = float(delta)
                    next_resets = int(resets)
                elif value >= previous:
                    next_delta = float(delta) + value - previous
                    next_resets = int(resets)
                else:
                    next_delta = float(delta)
                    next_resets = int(resets) + 1
                    review = {"before": previous, "after": value, "at": stamp_text}
                connection.execute(
                    """UPDATE daily_raw_counter_records
                       SET label=?,source_path=?,subject_name=?,closing_value=?,
                           delta_value=?,reset_count=?,sample_count=?,last_success=?,
                           source_name=?,device_name_snapshot=?,device_serial_snapshot=?,
                           updated_at=?,counter_review_json=?
                       WHERE device_slot=? AND record_date=? AND canonical_field=?
                         AND source_path=? AND subject_type=? AND subject_id=?
                         AND device_serial_snapshot=?""",
                    (
                        label,
                        str(counter.source_path or ""),
                        subject_name,
                        value,
                        next_delta,
                        next_resets,
                        int(samples) + 1,
                        stamp_text,
                        str(reading.source or ""),
                        str(device_name or f"MFP {slot + 1}"),
                        device_serial,
                        stamp_text,
                        json.dumps(review, sort_keys=True),
                        slot,
                        day,
                        field,
                        str(counter.source_path or ""),
                        subject_type,
                        subject_id,
                        device_serial,
                    ),
                )
                changed += 1
        return changed

    def mark_day_incomplete(self, slot: int, day: date) -> None:
        with _open() as connection:
            connection.execute(
                """UPDATE daily_raw_counter_records SET incomplete=1,updated_at=?
                   WHERE device_slot=? AND record_date=?""",
                (datetime.now().astimezone().isoformat(timespec="seconds"), slot, day.isoformat()),
            )


def load_raw_counter_history(
    slots: tuple[int, ...] | list[int] | None = None,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
) -> tuple[RawCounterDailyRecord, ...]:
    clauses: list[str] = []
    parameters: list[object] = []
    if slots:
        placeholders = ",".join("?" for _ in slots)
        clauses.append(f"device_slot IN ({placeholders})")
        parameters.extend(int(slot) for slot in slots)
    if period_start is not None:
        clauses.append("record_date>=?")
        parameters.append(period_start.isoformat())
    if period_end is not None:
        clauses.append("record_date<=?")
        parameters.append(period_end.isoformat())
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    columns = ("device_slot", "record_date", "canonical_field", "label", "source_path",
        "subject_type", "subject_id", "subject_name", "opening_value", "closing_value", "delta_value",
        "reset_count", "sample_count", "first_success", "last_success", "source_name", "device_name_snapshot",
        "device_serial_snapshot", "incomplete", "counter_review_json", "counter_resolutions_json")
    with _open(commit=False) as connection:
        connection.execute("BEGIN")
        rows = connection.execute("SELECT " + ",".join(columns) + " FROM daily_raw_counter_records" + where,
            tuple(parameters)).fetchall()
        from services.report_detail_archive import ReportDetailArchive
        rows.extend(tuple(item["row"][key] for key in columns) for item in ReportDetailArchive().details(
            connection, "raw", slots, start=period_start, end=period_end))
    rows.sort(key=lambda row: (row[1], row[0], row[5], row[7], row[2]))
    return tuple(
        RawCounterDailyRecord(
            device_slot=int(row[0]),
            record_date=date.fromisoformat(str(row[1])),
            canonical_field=str(row[2]),
            label=str(row[3]),
            source_path=str(row[4]),
            subject_type=str(row[5]),
            subject_id=str(row[6]),
            subject_name=str(row[7]),
            opening_value=float(row[8]),
            closing_value=float(row[9]),
            delta_value=float(row[10]),
            reset_count=int(row[11]),
            sample_count=int(row[12]),
            first_success=str(row[13]),
            last_success=str(row[14]),
            source_name=str(row[15]),
            device_name_snapshot=str(row[16]),
            device_serial_snapshot=str(row[17]),
            incomplete=bool(row[18]),
            pending_review=json.loads(row[19]) is not None,
            baseline_reviewed=bool(json.loads(row[20])),
        )
        for row in rows
    )
