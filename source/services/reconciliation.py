from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isclose

Number = int | float


@dataclass(frozen=True)
class ReconciliationProfile:
    """Versioned counter relationships for one Web Connection schema family."""

    profile_id: str
    include_scan_fax_in_device_total: bool
    include_scan_fax_in_device_large: bool
    large_suffixes: tuple[str, ...] = ("large", "long_size")


KONICA_DEVICE_METER_V2 = ReconciliationProfile(
    profile_id="konica.web_connection.device_meter.v2",
    include_scan_fax_in_device_total=True,
    # Live C450i evidence: TotalLarge equals Print/Copy color-family Large.
    # ScanFax PrintLarge is a separate diagnostic counter and must not be added.
    include_scan_fax_in_device_large=False,
)


@dataclass(frozen=True)
class ReconciliationTerm:
    key: str
    label: str
    value: float

    def message(self) -> str:
        return f"{self.label} {self.value:,.0f}"


@dataclass(frozen=True)
class ReconciliationIssue:
    code: str
    left_label: str
    left_value: float
    right_label: str
    right_value: float
    right_terms: tuple[ReconciliationTerm, ...] = ()

    @property
    def difference(self) -> float:
        return self.left_value - self.right_value

    def message(self) -> str:
        return (
            f"{self.left_label} {self.left_value:,.0f} != "
            f"{self.right_label} {self.right_value:,.0f} "
            f"(ต่าง {self.difference:+,.0f})"
        )

    def breakdown(self) -> str:
        if not self.right_terms:
            return ""
        return " + ".join(f"{term.key}={term.value:,.0f}" for term in self.right_terms)


@dataclass(frozen=True)
class ReconciliationReport:
    checked_count: int
    issues: tuple[ReconciliationIssue, ...]
    profile_id: str = KONICA_DEVICE_METER_V2.profile_id

    @property
    def needs_review(self) -> bool:
        return bool(self.issues)

    @property
    def billing_safe(self) -> bool:
        return self.checked_count > 0 and not self.issues

    def summary(self, *, limit: int = 3) -> str:
        if self.checked_count == 0:
            return "ยังไม่มีคู่ Counter เพียงพอสำหรับตรวจผลรวม"
        if not self.issues:
            return f"ตรวจผลรวม {self.checked_count} จุด · ตรงกันทั้งหมด"
        visible = self.issues[: max(1, limit)]
        lines = [f"พบ {len(self.issues)} จุดไม่ตรงกัน · Needs Review"]
        lines.extend(f"- {issue.message()}" for issue in visible)
        hidden = len(self.issues) - len(visible)
        if hidden:
            lines.append(f"- และอีก {hidden} จุด")
        return "\n".join(lines)

    def audit_summary(self, *, limit: int = 3) -> str:
        lines = [self.summary(limit=limit), f"กฎตรวจ: {self.profile_id}"]
        for issue in self.issues[: max(1, limit)]:
            if breakdown := issue.breakdown():
                lines.append(f"องค์ประกอบ {issue.code}: {breakdown}")
        return "\n".join(lines)


_COLOR_FAMILIES = ("full_color", "bi_color", "mono_color", "single_color", "two_color")
_BW_ALIASES = ("bw", "black", "gray", "grey")


def _value(counters: Mapping[str, Number], key: str) -> float | None:
    raw = counters.get(key)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _first_key(counters: Mapping[str, Number], keys: tuple[str, ...]) -> str | None:
    return next((key for key in keys if _value(counters, key) is not None), None)


def _operation_family_names(counters: Mapping[str, Number], operation: str) -> tuple[str, ...]:
    families = [
        family
        for family in _COLOR_FAMILIES
        if _value(counters, f"counter.{operation}.{family}_total") is not None
    ]
    bw_key = _first_key(
        counters,
        tuple(f"counter.{operation}.{family}_total" for family in _BW_ALIASES),
    )
    if bw_key:
        families.append(bw_key.removeprefix(f"counter.{operation}.").removesuffix("_total"))
    return tuple(families)


def reconcile_web_counters(
    counters: Mapping[str, Number],
    *,
    profile: ReconciliationProfile = KONICA_DEVICE_METER_V2,
) -> ReconciliationReport:
    """Validate sums inside one Web Connection device-level Meter snapshot.

    SNMP is intentionally excluded because it is status/trigger data. User and
    Account Track counters are also excluded because public or untracked jobs
    can make their sum differ from the device Meter without indicating an error.
    """

    issues: list[ReconciliationIssue] = []
    checked_count = 0

    def compare(
        code: str,
        left_label: str,
        left: float | None,
        right_label: str,
        right: float | None,
        *,
        right_terms: tuple[ReconciliationTerm, ...] = (),
    ) -> None:
        nonlocal checked_count
        if left is None or right is None:
            return
        checked_count += 1
        if not isclose(left, right, rel_tol=0.0, abs_tol=0.001):
            issues.append(ReconciliationIssue(code, left_label, left, right_label, right, right_terms))

    operation_families: dict[str, tuple[str, ...]] = {}
    for operation in ("print", "copy"):
        families = _operation_family_names(counters, operation)
        operation_families[operation] = families
        operation_total = _value(counters, f"counter.{operation}.total")
        family_totals = [
            _value(counters, f"counter.{operation}.{family}_total")
            for family in families
        ]
        if family_totals and all(value is not None for value in family_totals):
            compare(
                f"{operation}_total_by_color",
                f"{operation.title()} Total",
                operation_total,
                f"รวม {operation.title()} แยกสี",
                sum(value for value in family_totals if value is not None),
            )

        for family in families:
            family_total = _value(counters, f"counter.{operation}.{family}_total")
            large_values = [
                value
                for key in (
                    f"counter.{operation}.{family}_large",
                    f"counter.{operation}.{family}_long_size",
                )
                if (value := _value(counters, key)) is not None
            ]
            if family_total is None or not large_values:
                continue
            checked_count += 1
            large_total = sum(large_values)
            if large_total > family_total:
                issues.append(
                    ReconciliationIssue(
                        f"{operation}_{family}_large_exceeds_total",
                        f"{operation.title()} {family} Large",
                        large_total,
                        f"{operation.title()} {family} Total",
                        family_total,
                    )
                )

    print_total = _value(counters, "counter.print.total")
    copy_total = _value(counters, "counter.copy.total")
    device_total = _value(counters, "counter.total.total")
    if print_total is not None and copy_total is not None:
        total_terms = [
            ReconciliationTerm("counter.print.total", "Print", print_total),
            ReconciliationTerm("counter.copy.total", "Copy", copy_total),
        ]
        if profile.include_scan_fax_in_device_total:
            fax_print = _value(counters, "counter.scan_fax.print_total") or 0.0
            total_terms.append(ReconciliationTerm("counter.scan_fax.print_total", "Scan/Fax print", fax_print))
        compare(
            "device_total_by_operation",
            "Device Total",
            device_total,
            " + ".join(term.label for term in total_terms),
            sum(term.value for term in total_terms),
            right_terms=tuple(total_terms),
        )

    large_terms: list[ReconciliationTerm] = []
    for operation, families in operation_families.items():
        for family in families:
            for suffix in profile.large_suffixes:
                key = f"counter.{operation}.{family}_{suffix}"
                value = _value(counters, key)
                if value is not None:
                    label = f"{operation.title()} {family.replace('_', ' ')} {suffix.replace('_', ' ')}"
                    large_terms.append(ReconciliationTerm(key, label, value))
    if profile.include_scan_fax_in_device_large:
        fax_large = _value(counters, "counter.scan_fax.print_large")
        if fax_large is not None:
            large_terms.append(
                ReconciliationTerm("counter.scan_fax.print_large", "Scan/Fax print large", fax_large)
            )
    if large_terms:
        compare(
            "device_large_by_operation",
            "Device Total Large",
            _value(counters, "counter.total.total_large"),
            "รวม Print/Copy Large แยกประเภท",
            sum(term.value for term in large_terms),
            right_terms=tuple(large_terms),
        )

    paper_family_totals: list[float] = []
    for key in sorted(counters):
        prefix = "counter.paper."
        suffix = ".print_page_total"
        if not (key.startswith(prefix) and key.endswith(suffix)):
            continue
        family = key[len(prefix) : -len(suffix)]
        family_total = _value(counters, key)
        leaf_prefix = f"counter.paper.{family}."
        leaf_values = [
            value
            for leaf_key in counters
            if leaf_key.startswith(leaf_prefix)
            and leaf_key != key
            and (value := _value(counters, leaf_key)) is not None
        ]
        if family_total is not None:
            paper_family_totals.append(family_total)
        if leaf_values:
            compare(
                f"paper_{family}_by_size",
                f"Paper {family} Total",
                family_total,
                f"รวม Paper {family} แยกขนาด",
                sum(leaf_values),
            )

    paper_total = _value(counters, "counter.total.paper")
    paper_size_values = [
        value
        for key in counters
        if key.startswith("counter.total.paper_size_")
        and (value := _value(counters, key)) is not None
    ]
    if paper_size_values:
        compare(
            "paper_total_by_size",
            "Paper Total",
            paper_total,
            "รวม Paper size",
            sum(paper_size_values),
        )
    if paper_family_totals:
        compare(
            "paper_total_by_color",
            "Paper Total",
            paper_total,
            "รวม Paper แยกสี",
            sum(paper_family_totals),
        )

    return ReconciliationReport(
        checked_count=checked_count,
        issues=tuple(issues),
        profile_id=profile.profile_id,
    )
