"""Evidence-based Print/Copy breakdown shared by UI and Excel reports.

The source counters remain exact in ``daily_raw_counter_records``.  This module
only derives a presentation view when a counter explicitly identifies its
operation.  Missing operation evidence is represented by availability flags;
callers must display an unavailable state instead of guessing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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
    groups = default_usage_groups(counters)
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


def breakdown_from_raw_records(records: Iterable[object]) -> OperationBreakdown:
    """Build a breakdown from exact daily rows without changing Raw history."""

    counters: dict[str, float] = {}
    for record in records:
        key = str(getattr(record, "canonical_field", "") or "").strip()
        if not key:
            key = str(getattr(record, "label", "") or "").strip()
        if not key:
            continue
        counters[key] = counters.get(key, 0.0) + max(
            0.0, float(getattr(record, "delta_value", 0.0) or 0.0)
        )
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
