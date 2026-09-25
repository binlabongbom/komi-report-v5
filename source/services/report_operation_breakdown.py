"""Evidence-based Print/Copy breakdown shared by UI and Excel reports.

The source counters remain exact in ``daily_raw_counter_records``.  This module
only derives a presentation view when a counter explicitly identifies its
operation.  Missing operation evidence is represented by availability flags;
callers must display an unavailable state instead of guessing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from services.usage import default_usage_groups


@dataclass(frozen=True)
class OperationBreakdown:
    print_a3_color: float = 0.0
    print_a3_bw: float = 0.0
    print_a4_color: float = 0.0
    print_a4_bw: float = 0.0
    print_other: float = 0.0
    copy_a3_color: float = 0.0
    copy_a3_bw: float = 0.0
    copy_a4_color: float = 0.0
    copy_a4_bw: float = 0.0
    copy_other: float = 0.0
    scan: float = 0.0
    available_fields: frozenset[str] = frozenset()
    print_available: bool = False
    copy_available: bool = False
    scan_available: bool = False

    @property
    def print_total(self) -> float:
        return (
            self.print_a3_color
            + self.print_a3_bw
            + self.print_a4_color
            + self.print_a4_bw
            + self.print_other
        )

    @property
    def copy_total(self) -> float:
        return (
            self.copy_a3_color
            + self.copy_a3_bw
            + self.copy_a4_color
            + self.copy_a4_bw
            + self.copy_other
        )


_GROUP_FIELDS = (
    ("print_a3_color", "A3 Color (Print)"),
    ("print_a3_bw", "A3 B&W (Print)"),
    ("print_a4_color", "A4 Color (Print)"),
    ("print_a4_bw", "A4 B&W (Print)"),
    ("print_other", "Other size (Print)"),
    ("copy_a3_color", "A3 Color (Copy)"),
    ("copy_a3_bw", "A3 B&W (Copy)"),
    ("copy_a4_color", "A4 Color (Copy)"),
    ("copy_a4_bw", "A4 B&W (Copy)"),
    ("copy_other", "Other size (Copy)"),
    ("scan", "SCAN"),
)


def breakdown_from_counters(counters: dict[str, float]) -> OperationBreakdown:
    return _counter_breakdown(tuple(counters.items()))


@lru_cache(maxsize=4096)
def _counter_breakdown(items: tuple[tuple[str, float], ...]) -> OperationBreakdown:
    # Results are immutable and depend only on exact canonical values. This
    # reuses daily category summaries without caching prices or identities.
    counters = dict(items)
    groups = default_usage_groups(counters)
    return _from_groups(groups)


def _from_groups(groups: dict[str, float | None]) -> OperationBreakdown:
    values = {
        field: float(groups.get(label) or 0.0)
        for field, label in _GROUP_FIELDS
    }
    return OperationBreakdown(
        **values,
        available_fields=frozenset(field for field, label in _GROUP_FIELDS if groups.get(label) is not None),
        print_available=any(
            groups.get(label) is not None
            for _field, label in _GROUP_FIELDS
            if label.endswith("(Print)")
        ),
        copy_available=any(
            groups.get(label) is not None
            for _field, label in _GROUP_FIELDS
            if label.endswith("(Copy)")
        ),
        scan_available=groups.get("SCAN") is not None,
    )


def _subject_groups(counters: dict[str, float], kind: str) -> dict[str, float | None]:
    """Adapt one subject's Web counter names without changing stored evidence.

    Auth/Track payloads use Bw/FullColor, while device payloads use BwTotal/
    FullColorTotal. Alias totals are alternatives, never additional usage.
    """
    prefix = f"counter.{kind}."
    normalized: dict[str, float] = {}
    conflicts: set[str] = set()
    for key, value in counters.items():
        target = "counter." + key[len(prefix):] if key.startswith(prefix) else key
        if target in normalized and normalized[target] != value:
            conflicts.add(target)
        normalized[target] = value
    unavailable = set()
    for operation in ("print", "copy"):
        base = f"counter.{operation}."
        for color, families in (("Color", ("full_color", "bi_color", "mono_color", "single_color", "two_color")),
                                ("B&W", ("bw", "black", "gray", "grey"))):
            for family in families:
                bare, total = base + family, base + family + "_total"
                aliases = [key for key in (bare, total) if key in normalized]
                if not aliases:
                    continue
                amount = normalized[aliases[0]]
                sizes = [key for key in (bare + "_large", bare + "_long_size") if key in normalized]
                valid = (not conflicts.intersection((*aliases, *sizes))
                         and all(normalized[key] == amount for key in aliases)
                         and bool(sizes) and 0 <= sum(normalized[key] for key in sizes) <= amount)
                normalized.pop(bare, None)
                normalized[total] = amount
                if not valid:
                    unavailable.add((operation, color))
    # Received fax print totals and fax sends are not scanned document totals.
    normalized = {key: value for key, value in normalized.items()
                  if not key.startswith("counter.scan_fax.")
                  or key in {"counter.scan_fax.document_read_total", "counter.scan_fax.scan_total"}}
    groups = default_usage_groups(normalized)
    for operation, color in unavailable:
        for size in ("A3", "A4"):
            groups[f"{size} {color} ({operation.title()})"] = None
    for operation in ("print", "copy"):
        # Missing size/color evidence does not prove an "other paper" count.
        if any(groups[f"{size} {color} ({operation.title()})"] is None
               for size in ("A3", "A4") for color in ("Color", "B&W")):
            groups[f"Other size ({operation.title()})"] = None
    return groups


@lru_cache(maxsize=4096)
def _subject_breakdown(kind: str, items: tuple[tuple[str, float], ...]) -> OperationBreakdown:
    return _from_groups(_subject_groups(dict(items), kind))


def breakdown_from_raw_records(records: Iterable[object]) -> OperationBreakdown:
    """Build a breakdown from exact daily rows without changing Raw history."""

    counters: dict[str, float] = {}
    scopes = set()
    for record in records:
        key = str(getattr(record, "canonical_field", "") or "").strip()
        if not key:
            key = str(getattr(record, "label", "") or "").strip()
        if not key:
            continue
        scopes.add((str(getattr(record, "subject_type", "") or ""),
                    str(getattr(record, "subject_id", "") or ""),
                    getattr(record, "device_slot", None),
                    str(getattr(record, "device_serial_snapshot", "") or "")))
        counters[key] = counters.get(key, 0.0) + max(
            0.0, float(getattr(record, "delta_value", 0.0) or 0.0)
        )
    subjects = {scope for scope in scopes if scope[0]}
    if subjects:
        # A device total and its users describe overlapping pages. Callers
        # group one user/account and physical printer before deriving details.
        if len({scope[:3] for scope in scopes}) != 1 or len({scope[3] for scope in scopes if scope[3]}) > 1:
            return OperationBreakdown()
        kind = next(iter(subjects))[0]
        if kind in {"user", "account", "track"} and any(
                key.startswith(f"counter.{kind}.") for key in counters):
            foreign = tuple("counter." + other + "." for other in {"user", "account", "track"} - {kind})
            if any(key.startswith(foreign) for key in counters):
                return OperationBreakdown()
            return _subject_breakdown(kind, tuple(counters.items()))
    return breakdown_from_counters(counters)


def raw_operation_label(canonical_field: str, label: str) -> str:
    """Return an explicit source operation, never infer an unknown operation."""

    text = f"{canonical_field} {label}".casefold()
    if "print" in text:
        return "Print"
    if "copy" in text:
        return "Copy"
    if "scan" in text or "fax" in text:
        return "Scan / Fax"
    return "ไม่พบข้อมูลแยกประเภท"
