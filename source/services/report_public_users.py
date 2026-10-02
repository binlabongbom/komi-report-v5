"""Group printer usage without named subjects into one virtual report user.

"Public User" is a presentation group, not a claim about the printer's
authentication settings, public-login support, or the success of a user read.
"""

from collections import defaultdict

from services.report_models import (
    _combined,
    _operation_available,
    _operation_total,
    _record_total,
    cooperate,
    freeze,
)

_DETAIL_FIELDS = tuple(
    f"{operation}_{suffix}"
    for operation in ("print", "copy")
    for suffix in ("a3_color", "a3_bw", "a4_color", "a4_bw", "other")
)


def _identity(record):
    identity = str(getattr(record, "device_identity", "") or "").strip()
    serial = str(getattr(record, "device_serial_snapshot", "") or "").strip()
    if not identity or identity in {f"slot:{record.device_slot}", f"unattributed:slot:{record.device_slot}"}:
        identity = f"serial:{serial}" if serial else ""
    return identity.casefold() if identity.casefold().startswith("serial:") else identity


def _subject_intervals(subjects, cancelled):
    intervals = defaultdict(set)
    for index, subject in enumerate(subjects):
        cooperate(cancelled, index)
        if getattr(subject, "subject_type", "") not in {"user", "account", "track"}:
            continue
        identity = _identity(subject)
        intervals[(int(subject.device_slot), identity)].add(
            (subject.period_start, subject.period_end)
        )
    return intervals


def build_public_user_rows(daily_records, devices, *, subjects=(), cancelled=None):
    """Return one Public User for daily printer usage without overlapping subjects.

    Existing daily history is sufficient; no authentication history is required.
    This row groups unattributed usage, regardless of why named-user data is
    absent. Multi-day buckets are never apportioned, and overlapping subject
    periods (including zero-use subjects) suppress public usage to avoid double
    counting. Totals remain separated by slot within the row, while physical
    identity contributions remain available in ``printers``. Authentication/read
    errors remain separate from this display model. ``devices`` remains in the
    public signature for report callers; the row name never depends on a device.
    """
    subject_intervals = _subject_intervals(subjects, cancelled)
    row = None
    for index, record in enumerate(daily_records):
        cooperate(cancelled, index)
        slot = int(record.device_slot)
        identity = _identity(record)
        day = record.period_start
        if record.period_end != day:
            continue
        intervals = subject_intervals.get((slot, identity), ())
        # Unattributed subject evidence cannot safely be assigned to a different
        # physical printer that happened to occupy the same slot that day.
        unknown_intervals = subject_intervals.get((slot, ""), ()) if identity else tuple(
            interval
            for (subject_slot, subject_identity), values in subject_intervals.items()
            if subject_slot == slot and subject_identity
            for interval in values
        )
        if any(start <= day <= end for start, end in (*intervals, *unknown_intervals)):
            continue
        if not (record.day_count or record.provisional_days):
            continue  # A held-only bucket does not establish a measured zero.

        if row is None:
            row = {
                "key": "public:all",
                "name": "Public User",
                "type": "public",
                "virtual": True,
                "usage_source": "printer_daily_usage",
                "usage": 0.0,
                "print": 0.0,
                "copy": 0.0,
                "print_available": False,
                "copy_available": False,
                "latest": 0.0,
                "printers": {},
                "by_slot": {},
                "review": False,
            }
        slot_row = row["by_slot"].setdefault(slot, {
            **dict.fromkeys((*_DETAIL_FIELDS, "scan", "total", "cost", "gross_cost", "net_cost"), 0.0),
            "available_fields": None,
            "print_available": True,
            "copy_available": True,
            "scan_available": True,
            "cost_available": True,
        })
        total = _record_total(record)
        row["usage"] += total
        printer_identity = identity or f"slot:{slot}"
        row["printers"][printer_identity] = row["printers"].get(printer_identity, 0.0) + total
        slot_row["total"] += total
        slot_row["scan"] += _combined(record, "scan")
        slot_row["cost"] += _combined(record, "net_cost")
        slot_row["gross_cost"] += _combined(record, "gross_cost")
        slot_row["net_cost"] += _combined(record, "net_cost")
        fields = set()
        for operation in ("print", "copy"):
            available = _operation_available(record, operation)
            slot_row[f"{operation}_available"] &= available
            row[f"{operation}_available"] |= available
            row[operation] += _operation_total(record, operation)
            for field in _DETAIL_FIELDS:
                if field.startswith(operation + "_"):
                    slot_row[field] += _combined(record, field)
                    if available:
                        fields.add(field)
        existing_fields = slot_row["available_fields"]
        slot_row["available_fields"] = fields if existing_fields is None else existing_fields & fields
        cost_available = not record.provisional_days or record.provisional_cost_available
        slot_row["cost_available"] &= cost_available
        row["review"] |= bool(record.held_days or record.incomplete_days) or not cost_available

    if row is None:
        return ()
    for slot_row in row["by_slot"].values():
        for field in ("cost", "gross_cost", "net_cost"):
            slot_row[field] = round(slot_row[field], 2)
    return freeze((row,))
