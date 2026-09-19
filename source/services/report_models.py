"""Immutable report presentation data prepared without Qt widgets."""
from collections import defaultdict
from concurrent.futures import CancelledError
from dataclasses import dataclass
from time import sleep
from types import MappingProxyType

from services.report_operation_breakdown import breakdown_from_raw_records, raw_operation_label


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(value)
    return value


def cooperate(cancelled, index=0):
    if cancelled is not None and index % 1024 == 0:
        if cancelled.is_set():
            raise CancelledError()
        sleep(.001)


@dataclass(frozen=True)
class RawCell:
    total: float
    needs_review: bool


@dataclass(frozen=True)
class RawTable:
    headers: tuple
    rows: tuple


def raw_type_key(record):
    return tuple(str(getattr(record, name, "")) for name in ("canonical_field", "label", "source_path"))


def raw_display_label(raw_type, all_types):
    field, label, source_path = raw_type
    base = label or field or "Unknown"
    duplicate = sum((other[1] or other[0] or "Unknown") == base for other in all_types) > 1
    return f"{base} [{source_path}]" if duplicate and source_path else base


def build_legacy_raw_tables(records, devices, *, cancelled=None):
    """Index deltas once. Identity/source records remain intact in the snapshot.

    Cells intentionally sum period deltas (including a replaced printer), as
    the previous tables did. Absolute meters from different serials are never
    summed here. Missing cells remain None, distinct from a measured zero.
    """
    configured = {int(device.slot): device for device in devices}
    slots, names, types, columns, subjects, days = set(configured), {}, set(), set(), set(), set()
    machine, users, daily = {}, {}, {}
    def add(bucket, key, item):
        total, review = bucket.get(key, (0.0, False))
        bucket[key] = (total + float(getattr(item, "delta_value", 0.0)), review or bool(getattr(item, "needs_review", False)))
    for index, item in enumerate(records):
        cooperate(cancelled, index)
        slot = int(item.device_slot)
        slots.add(slot)
        name = str(getattr(item, "device_name_snapshot", "") or "").strip()
        if name:
            names.setdefault(slot, name)
        raw_type = raw_type_key(item)
        if getattr(item, "subject_type", ""):
            kind, identity = str(item.subject_type), str(item.subject_id)
            subjects.add((kind, identity, str(item.subject_name or item.subject_id)))
            columns.add((slot, *raw_type))
            add(users, (kind, identity, slot, raw_type), item)
        else:
            types.add(raw_type)
            days.add(item.record_date)
            add(machine, (slot, raw_type), item)
            add(daily, (item.record_date, slot, raw_type), item)
    slots = tuple(sorted(slots))
    names = {slot: f"Slot {slot + 1} · {names.get(slot) or getattr(configured.get(slot), 'name', '') or f'MFP {slot + 1}'}" for slot in slots}
    types = tuple(sorted(types, key=lambda item: (item[1].casefold(), item[0], item[2])))
    columns = tuple(sorted(columns, key=lambda item: (item[0], item[2].casefold(), item[1])))
    subjects = sorted(subjects, key=lambda item: (item[2].casefold(), item[0], item[1]))
    def cell(bucket, key):
        value = bucket.get(key)
        return RawCell(*value) if value is not None else None
    machine_rows = tuple((
        "—" if raw_operation_label(kind[0], kind[1]) == "ไม่พบข้อมูลแยกประเภท" else raw_operation_label(kind[0], kind[1]),
        raw_display_label(kind, types), *(cell(machine, (slot, kind)) for slot in slots)
    ) for kind in types)
    user_rows = []
    for index, (kind, identity, name) in enumerate(subjects):
        cooperate(cancelled, index)
        user_rows.append((f"{name} ({kind})", *(cell(users, (kind, identity, slot, (field, label, path))) for slot, field, label, path in columns)))
    daily_columns = tuple(sorted(machine, key=lambda item: (item[0], item[1][1].casefold(), item[1][0])))
    def headings(items):
        kinds = tuple(item[1:] for item in items)
        return tuple(f"{names[slot]} · {raw_operation_label(field, label)} · {raw_display_label((field, label, path), kinds)}" for slot, field, label, path in items)
    daily_rows = tuple((day.strftime("%d/%m/%Y"), *(cell(daily, (day, slot, kind)) for slot, kind in daily_columns)) for day in sorted(days))
    return (
        RawTable(("กลุ่มงาน", "ประเภท Counter (ชื่อจากเครื่อง)", *(names[slot] for slot in slots)), machine_rows),
        RawTable(("ผู้ใช้ / Account", *headings(columns)), tuple(user_rows)),
        RawTable(("วันที่", *headings(tuple((slot, *kind) for slot, kind in daily_columns))), daily_rows),
    )


def _record_identity(record) -> str:
    identity = str(getattr(record, "device_identity", "") or "").strip()
    return identity or f"slot:{int(getattr(record, 'device_slot', 0))}"


def build_user_rows(subjects, raw_counter_records, *, cancelled=None):
    grouped: dict[str, dict] = {}
    subject_group_keys: dict[tuple[str, str, int], str] = {}
    for item in subjects:
        subject_name = str(item.subject_name or "").strip()
        slot = int(item.device_slot)
        key = (
            f"{item.subject_type}:name:{subject_name.casefold()}"
            if subject_name and subject_name != str(item.subject_id)
            else f"{item.subject_type}:slot:{slot}:id:{item.subject_id}"
        )
        subject_group_keys[(str(item.subject_type), str(item.subject_id), slot)] = key
        row = grouped.setdefault(
            key,
            {
                "key": key,
                "name": subject_name or str(item.subject_id),
                "type": item.subject_type,
                "usage": 0.0,
                "print": 0.0,
                "copy": 0.0,
                "print_available": False,
                "copy_available": False,
                "latest": 0.0,
                "printers": defaultdict(float),
                "by_slot": defaultdict(
                    lambda: {
                        "print_a3_color": 0.0,
                        "print_a3_bw": 0.0,
                        "print_a4_color": 0.0,
                        "print_a4_bw": 0.0,
                        "print_other": 0.0,
                        "copy_a3_color": 0.0,
                        "copy_a3_bw": 0.0,
                        "copy_a4_color": 0.0,
                        "copy_a4_bw": 0.0,
                        "copy_other": 0.0,
                        "scan": 0.0,
                        "total": 0.0,
                        "cost": 0.0,
                        "print_available": False,
                        "copy_available": False,
                        "scan_available": False,
                        "cost_available": False,
                    }
                ),
                "review": False,
            },
        )
        identity = _record_identity(item)
        row["usage"] += float(item.period_usage)
        if item.latest_total is not None:
            row["latest"] = max(row["latest"], float(item.latest_total))
        row["printers"][identity] += float(item.period_usage)
        row["by_slot"][slot]["total"] += float(item.period_usage)
        row["review"] = row["review"] or bool(item.needs_review)

    raw_groups: dict[tuple[str, str, int, str], list[object]] = defaultdict(list)
    for index, item in enumerate(raw_counter_records):
        cooperate(cancelled, index)
        subject_type = str(getattr(item, "subject_type", "") or "")
        subject_id = str(getattr(item, "subject_id", "") or "")
        if not subject_type or not subject_id:
            continue
        serial = str(getattr(item, "device_serial_snapshot", "") or "").strip()
        slot = int(item.device_slot)
        identity = f"serial:{serial}" if serial else f"slot:{slot}"
        raw_groups[(subject_type, subject_id, slot, identity)].append(item)
    for (subject_type, subject_id, slot, identity), raw_records in raw_groups.items():
        key = subject_group_keys.get((subject_type, subject_id, slot))
        if key is None:
            raw_name = str(getattr(raw_records[0], "subject_name", "") or "").strip()
            key = (
                f"{subject_type}:name:{raw_name.casefold()}"
                if raw_name and raw_name != subject_id
                else f"{subject_type}:slot:{slot}:id:{subject_id}"
            )
        row = grouped.get(key)
        if row is None:
            continue
        breakdown = breakdown_from_raw_records(raw_records)
        slot_row = row["by_slot"][slot]
        slot_row.setdefault("available_fields", set()).update(breakdown.available_fields)
        for field in (
            "print_a3_color",
            "print_a3_bw",
            "print_a4_color",
            "print_a4_bw",
            "print_other",
            "copy_a3_color",
            "copy_a3_bw",
            "copy_a4_color",
            "copy_a4_bw",
            "copy_other",
            "scan",
        ):
            slot_row[field] += float(getattr(breakdown, field))
        slot_row["print_available"] = (
            slot_row["print_available"] or breakdown.print_available
        )
        slot_row["copy_available"] = (
            slot_row["copy_available"] or breakdown.copy_available
        )
        slot_row["scan_available"] = (
            slot_row["scan_available"] or breakdown.scan_available
        )
        row["print"] += breakdown.print_total
        row["copy"] += breakdown.copy_total
        row["print_available"] = row["print_available"] or breakdown.print_available
        row["copy_available"] = row["copy_available"] or breakdown.copy_available
        if breakdown.print_available or breakdown.copy_available:
            row["printers"][identity] = max(
                row["printers"].get(identity, 0.0),
                breakdown.print_total + breakdown.copy_total,
            )
    return freeze(sorted(grouped.values(), key=lambda item: item["usage"], reverse=True))


def _combined(record, name: str) -> float:
    return float(getattr(record, name, 0) or 0) + float(
        getattr(record, f"provisional_{name}", 0) or 0
    )


def _record_total(record) -> float:
    explicit = _combined(record, "total")
    if explicit:
        return explicit
    return sum(
        _combined(record, name)
        for name in ("a3_color", "a4_color", "a3_bw", "a4_bw")
    )


def _operation_total(record, operation: str) -> float:
    return sum(
        _combined(record, f"{operation}_{suffix}")
        for suffix in ("a3_color", "a3_bw", "a4_color", "a4_bw", "other")
    )


def _operation_available(record, operation: str) -> bool:
    return bool(getattr(record, f"{operation}_available", False)) or any(
        _combined(record, f"{operation}_{suffix}")
        for suffix in ("a3_color", "a3_bw", "a4_color", "a4_bw", "other")
    )


def _record_name(record, devices_by_slot: dict[int, object]) -> str:
    snapshot = str(getattr(record, "device_name_snapshot", "") or "").strip()
    slot = int(getattr(record, "device_slot", 0))
    device = devices_by_slot.get(slot)
    return snapshot or str(getattr(device, "name", "") or f"MFP {slot + 1}")


def build_printer_rows(records, devices):
    devices_by_slot = {int(device.slot): device for device in devices}
    grouped: dict[str, dict] = {}
    for record in records:
        key = _record_identity(record)
        slot = int(record.device_slot)
        device = devices_by_slot.get(slot)
        row = grouped.setdefault(
            key,
            {
                "key": key,
                "slot": slot,
                "name": _record_name(record, devices_by_slot),
                "device": device,
                "color": 0.0,
                "bw": 0.0,
                "print": 0.0,
                "copy": 0.0,
                "print_available": False,
                "copy_available": False,
                "scan": 0.0,
                "total": 0.0,
                "net_cost": 0.0,
                "gross_cost": 0.0,
                "review": False,
            },
        )
        row["color"] += sum(_combined(record, name) for name in ("a3_color", "a4_color"))
        row["bw"] += sum(_combined(record, name) for name in ("a3_bw", "a4_bw"))
        row["print"] += _operation_total(record, "print")
        row["copy"] += _operation_total(record, "copy")
        row["print_available"] = row["print_available"] or _operation_available(
            record, "print"
        )
        row["copy_available"] = row["copy_available"] or _operation_available(
            record, "copy"
        )
        row["scan"] += _combined(record, "scan")
        row["total"] += _record_total(record)
        row["net_cost"] += _combined(record, "net_cost")
        row["gross_cost"] += _combined(record, "gross_cost")
        row["review"] = row["review"] or bool(record.held_days or record.incomplete_days)
    return freeze(sorted(grouped.values(), key=lambda item: item["total"], reverse=True))
