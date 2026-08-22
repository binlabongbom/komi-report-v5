from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from database import _open, get_billing_day
from services.billing_periods import billing_month_range
from services.daily_cache import DailyCacheStore
from services.pricing import recognized_paper_size

DEFAULT_USAGE_LABELS = (
    "A3 Color (Print)",
    "A3 B&W (Print)",
    "A4 Color (Print)",
    "A4 B&W (Print)",
    "A3 Color (Copy)",
    "A3 B&W (Copy)",
    "A4 Color (Copy)",
    "A4 B&W (Copy)",
    "Other size (Print)",
    "Other size (Copy)",
    "SCAN",
)


@dataclass(frozen=True)
class IdentityPeriodCounters:
    """Frozen current-period counters for one physical device identity."""

    device_identity: str
    device_name_snapshot: str
    device_serial_snapshot: str
    counters: dict[str, float]


def _identity(serial: object, host: object) -> str:
    serial_text = str(serial or "").strip()
    host_text = str(host or "").strip()
    if serial_text:
        return f"serial:{serial_text}"
    if host_text:
        return f"host:{host_text}"
    return ""


def current_device_identity(slot: int) -> str:
    """Return the configured physical identity for a slot, never its display name."""

    with _open(commit=False) as conn:
        row = conn.execute(
            "SELECT serial,host FROM devices WHERE slot=? AND enabled=1",
            (slot,),
        ).fetchone()
    return _identity(*row) if row else ""


def _source_identity(source_json: object) -> str:
    try:
        source = json.loads(source_json) if isinstance(source_json, str) else source_json
    except json.JSONDecodeError:
        return ""
    if not isinstance(source, dict):
        return ""
    captured = source.get("device_identity")
    if not isinstance(captured, dict):
        return ""
    return _identity(captured.get("serial"), captured.get("host"))


def billing_period(today: date | None = None) -> tuple[date, date]:
    current = today or date.today()
    billing_day = get_billing_day()
    start, _period_end = billing_month_range(current, billing_day)
    return start, current


def current_period_counters_by_identity(
    slot: int,
    *,
    today: date | None = None,
) -> tuple[IdentityPeriodCounters, ...]:
    _start, end = billing_period(today)
    with _open(commit=False) as conn:
        rows = conn.execute(
            """SELECT latest.device_identity,latest.device_name_snapshot,
                      latest.device_serial_snapshot,latest.delta_json
               FROM daily_meter_records d
               JOIN billing_ledger latest ON latest.id=(
                   SELECT MAX(l.id) FROM billing_ledger l WHERE l.source_daily_record_id=d.id
               )
               WHERE d.device_slot=? AND d.record_date<=?
                 AND latest.period_start<=? AND latest.period_end>=?
                 AND latest.entry_kind IN ('posting','replacement')""",
            (slot, end.isoformat(), end.isoformat(), end.isoformat()),
        ).fetchall()
    grouped: dict[str, dict] = {}
    for device_identity, device_name, device_serial, payload in rows:
        try:
            counters = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(counters, dict):
            continue
        bucket = grouped.setdefault(
            str(device_identity),
            {
                "name": str(device_name or ""),
                "serial": str(device_serial or ""),
                "counters": {},
            },
        )
        for key, value in counters.items():
            totals = bucket["counters"]
            totals[key] = totals.get(key, 0.0) + float(value)
    return tuple(
        IdentityPeriodCounters(
            device_identity=device_identity,
            device_name_snapshot=bucket["name"],
            device_serial_snapshot=bucket["serial"],
            counters=bucket["counters"],
        )
        for device_identity, bucket in sorted(grouped.items())
    )


def current_period_counters(slot: int, *, today: date | None = None) -> dict[str, float]:
    """Return only counters belonging to the physical device now in ``slot``."""

    configured_identity = current_device_identity(slot)
    if not configured_identity:
        return {}
    return next(
        (
            dict(item.counters)
            for item in current_period_counters_by_identity(slot, today=today)
            if item.device_identity == configured_identity
        ),
        {},
    )


def latest_counters(slot: int, *, today: date | None = None) -> dict[str, float]:
    current = today or date.today()
    configured_identity = current_device_identity(slot)
    if not configured_identity:
        return {}
    cache = DailyCacheStore().load(slot, current)
    if (
        cache
        and cache.get("latest")
        and _source_identity(cache) == configured_identity
    ):
        return {key: float(value) for key, value in cache["latest"].items()}
    with _open(commit=False) as conn:
        rows = conn.execute(
            """SELECT d.closing_json,d.source_json,latest.device_identity
               FROM daily_meter_records d
               LEFT JOIN billing_ledger latest ON latest.id=(
                   SELECT MAX(l.id) FROM billing_ledger l WHERE l.source_daily_record_id=d.id
               )
               WHERE d.device_slot=? ORDER BY d.record_date DESC""",
            (slot,),
        ).fetchall()
    for closing_json, source_json, ledger_identity in rows:
        frozen_identity = _source_identity(source_json) or str(ledger_identity or "")
        if frozen_identity != configured_identity:
            continue
        try:
            counters = json.loads(closing_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(counters, dict):
            return {key: float(value) for key, value in counters.items()}
    return {}


def _matches(key: str, operation: str, size: str, color: str) -> bool:
    text = key.lower()
    if operation not in text or size not in text:
        return False
    if color == "bw":
        return any(token in text for token in ("black", "bw", "gray", "grey"))
    return any(token in text for token in ("color", "single", "double", "two_color")) and not any(
        token in text for token in ("black", "bw", "gray", "grey")
    )


def _sum_existing(counters: dict[str, float], keys: tuple[str, ...]) -> tuple[bool, float]:
    existing = [key for key in keys if key in counters]
    return bool(existing), sum(float(counters[key]) for key in existing)


def _operation_breakdown(counters: dict[str, float], operation: str) -> dict[str, float | None]:
    """Build A3/A4 + Color/B&W from Konica's total/large counter pairs.

    Web Connection exposes operation and size as ``*_total``, ``*_large`` and
    occasionally ``*_long_size`` fields.  It does not use literal A3/A4 names
    in these operation counters.  Per KOMI Report's billing rule, large/long
    is the A3 bucket and the remainder is the A4 bucket.
    """
    prefix = f"counter.{operation}."
    color_families = ("full_color", "bi_color", "mono_color", "single_color", "two_color")
    bw_families = ("bw", "black", "gray", "grey")

    def family_values(families: tuple[str, ...]) -> tuple[bool, float, float]:
        found_total = False
        total = 0.0
        large = 0.0
        for family in families:
            has_total, family_total = _sum_existing(counters, (f"{prefix}{family}_total",))
            if not has_total:
                continue
            found_total = True
            total += family_total
            _, family_large = _sum_existing(
                counters,
                (f"{prefix}{family}_large", f"{prefix}{family}_long_size"),
            )
            large += min(family_total, max(0.0, family_large))
        return found_total, total, large

    color_found, color_total, color_large = family_values(color_families)
    bw_found, bw_total, bw_large = family_values(bw_families)
    operation_total = counters.get(f"{prefix}total")
    classified_total = color_total + bw_total
    other = max(0.0, float(operation_total) - classified_total) if operation_total is not None else None

    return {
        "a3_color": color_large if color_found else None,
        "a4_color": max(0.0, color_total - color_large) if color_found else None,
        "a3_bw": bw_large if bw_found else None,
        "a4_bw": max(0.0, bw_total - bw_large) if bw_found else None,
        "other": other,
    }


def default_usage_groups(counters: dict[str, float]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    derived = {
        "print": _operation_breakdown(counters, "print"),
        "copy": _operation_breakdown(counters, "copy"),
    }
    specs = (
        ("A3 Color (Print)", "print", "a3", "color", "a3_color"),
        ("A3 B&W (Print)", "print", "a3", "bw", "a3_bw"),
        ("A4 Color (Print)", "print", "a4", "color", "a4_color"),
        ("A4 B&W (Print)", "print", "a4", "bw", "a4_bw"),
        ("A3 Color (Copy)", "copy", "a3", "color", "a3_color"),
        ("A3 B&W (Copy)", "copy", "a3", "bw", "a3_bw"),
        ("A4 Color (Copy)", "copy", "a4", "color", "a4_color"),
        ("A4 B&W (Copy)", "copy", "a4", "bw", "a4_bw"),
    )
    used: set[str] = set()
    for label, operation, size, color, derived_key in specs:
        keys = [key for key in counters if _matches(key, operation, size, color)]
        used.update(keys)
        result[label] = sum(counters[key] for key in keys) if keys else derived[operation][derived_key]
    for operation, label in (("print", "Other size (Print)"), ("copy", "Other size (Copy)")):
        keys = [
            key
            for key in counters
            if operation in key.lower()
            and key not in used
            and (
                recognized_paper_size(key) is not None
                or any(token in key.lower() for token in ("custom", "other"))
            )
        ]
        used.update(keys)
        result[label] = sum(counters[key] for key in keys) if keys else derived[operation]["other"]
    scan_keys = [key for key in counters if "scan" in key.lower() and key not in used]
    preferred_scan = "counter.scan_fax.document_read_total"
    if preferred_scan in counters:
        result["SCAN"] = counters[preferred_scan]
        return result
    total_scan = [key for key in scan_keys if key.lower().endswith((".total", "_total"))]
    chosen = total_scan or scan_keys
    result["SCAN"] = max((counters[key] for key in chosen), default=None)
    return result
