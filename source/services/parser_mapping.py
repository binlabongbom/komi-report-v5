"""Reversible per-printer mappings from exact Web counters to KOMI fields.

The Legacy counter history is written before this adapter is called.  These
overrides therefore affect only future normalized cache/report rows; they do
not rewrite raw history, the Billing Ledger, or previously posted totals.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime

from database import _open
from komi_snmp_profiler.models import MeterReading, WebCounterValue

DEFAULT_TARGET = "default"
NO_MAPPING_TARGET = "none"
LEGACY_ONLY_TARGET = "legacy_only"


TARGET_OPTIONS: tuple[tuple[str, str], ...] = (
    (DEFAULT_TARGET, "ใช้ Mapping เดิมของระบบ"),
    ("mapped.print.a3.color", "Print A3 Color"),
    ("mapped.print.a3.bw", "Print A3 B&W"),
    ("mapped.print.a4.color", "Print A4 Color"),
    ("mapped.print.a4.bw", "Print A4 B&W"),
    ("mapped.print.other.total", "Print Other Size"),
    ("mapped.copy.a3.color", "Copy A3 Color"),
    ("mapped.copy.a3.bw", "Copy A3 B&W"),
    ("mapped.copy.a4.color", "Copy A4 Color"),
    ("mapped.copy.a4.bw", "Copy A4 B&W"),
    ("mapped.copy.other.total", "Copy Other Size"),
    ("counter.scan_fax.document_read_total", "Scan / Document Read"),
    ("counter.total.total", "Total Meter"),
    ("counter.duplex.total", "Duplex"),
    ("counter.original.total", "Originals"),
    (NO_MAPPING_TARGET, "No Mapping"),
    (LEGACY_ONLY_TARGET, "Legacy only (เก็บ Raw เท่านั้น)"),
)

ALLOWED_TARGETS = frozenset(value for value, _label in TARGET_OPTIONS)


def raw_counter_key(canonical_field: object, source_path: object) -> str:
    """Return a stable identity without exposing values or credentials."""

    return json.dumps(
        [str(canonical_field or "").strip(), str(source_path or "").strip()],
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class ParserMappingOverride:
    device_serial: str
    raw_key: str
    source_field: str
    source_path: str
    target_field: str
    updated_at: str


class ParserMappingRepository:
    def load(self, device_serial: str) -> dict[str, ParserMappingOverride]:
        serial = str(device_serial or "").strip()
        if not serial:
            return {}
        with _open(commit=False) as connection:
            rows = connection.execute(
                """SELECT device_serial,raw_key,source_field,source_path,
                          target_field,updated_at
                   FROM parser_mapping_overrides
                   WHERE device_serial=? ORDER BY source_field,source_path""",
                (serial,),
            ).fetchall()
        return {
            str(row[1]): ParserMappingOverride(
                device_serial=str(row[0]),
                raw_key=str(row[1]),
                source_field=str(row[2]),
                source_path=str(row[3]),
                target_field=str(row[4]),
                updated_at=str(row[5]),
            )
            for row in rows
        }

    def replace_all(
        self,
        device_serial: str,
        mappings: dict[tuple[str, str], str],
    ) -> int:
        """Replace explicit overrides for one serial and append an audit trail."""

        serial = str(device_serial or "").strip()
        if not serial:
            raise ValueError("ต้องมี Serial Number ก่อนบันทึก Mapping")
        normalized: dict[str, tuple[str, str, str]] = {}
        for (source_field, source_path), target in mappings.items():
            target_field = str(target or DEFAULT_TARGET).strip()
            if target_field not in ALLOWED_TARGETS:
                raise ValueError(f"ไม่รองรับ Mapping target: {target_field}")
            if target_field == DEFAULT_TARGET:
                continue
            field = str(source_field or "").strip()
            path = str(source_path or "").strip()
            normalized[raw_counter_key(field, path)] = (field, path, target_field)

        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with _open() as connection:
            existing_rows = connection.execute(
                """SELECT raw_key,target_field FROM parser_mapping_overrides
                   WHERE device_serial=?""",
                (serial,),
            ).fetchall()
            existing = {str(key): str(target) for key, target in existing_rows}
            next_targets = {key: item[2] for key, item in normalized.items()}
            changed_keys = sorted(set(existing) | set(next_targets))
            changed_keys = [
                key for key in changed_keys if existing.get(key, "") != next_targets.get(key, "")
            ]
            connection.execute(
                "DELETE FROM parser_mapping_overrides WHERE device_serial=?",
                (serial,),
            )
            for key, (field, path, target) in normalized.items():
                connection.execute(
                    """INSERT INTO parser_mapping_overrides(
                           device_serial,raw_key,source_field,source_path,target_field,updated_at
                       ) VALUES(?,?,?,?,?,?)""",
                    (serial, key, field, path, target, stamp),
                )
            for key in changed_keys:
                connection.execute(
                    """INSERT INTO parser_mapping_change_log(
                           device_serial,raw_key,old_target,new_target,changed_at
                       ) VALUES(?,?,?,?,?)""",
                    (serial, key, existing.get(key, ""), next_targets.get(key, ""), stamp),
                )
        return len(changed_keys)


def _category_for_target(target: str) -> str:
    if target.startswith("mapped.print."):
        return "Print"
    if target.startswith("mapped.copy."):
        return "Copy"
    if "scan" in target:
        return "Scan"
    return "Mapped"


def apply_parser_mapping_overrides(
    reading: MeterReading,
    device_serial: str,
    *,
    repository: ParserMappingRepository | None = None,
) -> MeterReading:
    """Apply explicit mappings to a copy of ``reading`` for normalized storage.

    Subject/User counters remain exact because an administrator mapping a
    device-level row must never silently change per-user evidence.
    """

    overrides = (repository or ParserMappingRepository()).load(device_serial)
    if not overrides:
        return reading

    # The normalized counter set is a different evidence set from the exact
    # Web snapshot.  Encode the effective rules in the reading identity so the
    # daily cache can rebaseline (and hold billing) if an operator changes a
    # mapping during the same day.  ``updated_at`` is intentionally excluded:
    # saving the same effective rules must not create a false schema change.
    revision_payload = [
        (raw_key, override.target_field)
        for raw_key, override in sorted(overrides.items())
    ]
    revision = hashlib.sha256(
        json.dumps(
            revision_payload,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]

    passthrough: list[WebCounterValue] = []
    mapped: dict[
        tuple[str, str | None, str | None],
        list[WebCounterValue],
    ] = {}
    for counter in reading.counters:
        if counter.subject_type:
            passthrough.append(counter)
            continue
        override = overrides.get(raw_counter_key(counter.canonical_field, counter.source_path))
        if override is None:
            passthrough.append(counter)
            continue
        target = override.target_field
        if target in {NO_MAPPING_TARGET, LEGACY_ONLY_TARGET}:
            continue
        identity = (target, counter.subject_type, counter.subject_id)
        mapped.setdefault(identity, []).append(counter)

    for (target, _subject_type, _subject_id), counters in mapped.items():
        first = counters[0]
        label = " + ".join(dict.fromkeys(str(item.label or item.canonical_field) for item in counters))
        source_path = " + ".join(dict.fromkeys(str(item.source_path or "") for item in counters))
        passthrough.append(
            replace(
                first,
                canonical_field=target,
                label=f"Mapped: {label}",
                count=sum(float(item.count) for item in counters),
                category=_category_for_target(target),
                source_path=source_path,
            )
        )
    return replace(
        reading,
        counters=tuple(passthrough),
        schema_version=f"{reading.schema_version}+parser.{revision}",
    )
