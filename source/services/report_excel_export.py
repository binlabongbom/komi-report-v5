"""Create a safe, user-facing Excel export for the Reports workspace."""

from __future__ import annotations

import re
import unicodedata
import os
import tempfile
from collections import defaultdict
from concurrent.futures import CancelledError
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from time import monotonic, sleep

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.pricing import PricingRepository
from services.raw_counter_history import RawCounterDailyRecord
from services.report_operation_breakdown import (
    breakdown_from_raw_records,
    raw_operation_label,
)
from services.subject_history import SubjectPeriodUsage
from services.report_export_options import ALL_REPORT_SECTIONS, validate_sections
from services.report_period_policy import EXPORT_YEARS, validate_report_period

NAVY = "123262"
BLUE = "1677C8"
TEAL = "0E7490"
PURPLE = "7C3AED"
PALE = "EAF2F8"
LINE = "D9E2EA"
MUTED = "56677A"
WHITE = "FFFFFF"

_EXCEL_FORMULA_PREFIXES = frozenset("=+-@")
_ILLEGAL_XML_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")
_export_control = ContextVar('excel_export_control', default=(None, None))
_last_ui_yield = ContextVar('excel_export_last_ui_yield', default=0.0)


def _checkpoint(percent=None, message=''):
    cancelled, progress = _export_control.get()
    # CPU-heavy Python loops can repeatedly reacquire the GIL before Qt's
    # Python event filters run on Windows. Leave a brief, bounded opportunity
    # for the GUI to handle input, in addition to moving the work off-thread.
    now = monotonic()
    if cancelled is not None and now - _last_ui_yield.get() >= 0.02:
        sleep(0.001)
        _last_ui_yield.set(monotonic())
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()
    if percent is not None and progress is not None:
        progress(percent, message)
    if cancelled is not None and cancelled.is_set():
        raise CancelledError()

CATEGORY_FIELDS = (
    ("a4_color", "A4 สี"),
    ("a4_bw", "A4 ขาวดำ"),
    ("a3_color", "A3 สี"),
    ("a3_bw", "A3 ขาวดำ"),
)

OPERATION_FIELDS = (
    ("print_a4_color", "Print A4 สี", "a4_color", "print"),
    ("print_a4_bw", "Print A4 ขาวดำ", "a4_bw", "print"),
    ("print_a3_color", "Print A3 สี", "a3_color", "print"),
    ("print_a3_bw", "Print A3 ขาวดำ", "a3_bw", "print"),
    ("print_other", "Print Other", "", "print"),
    ("copy_a4_color", "Copy A4 สี", "a4_color", "copy"),
    ("copy_a4_bw", "Copy A4 ขาวดำ", "a4_bw", "copy"),
    ("copy_a3_color", "Copy A3 สี", "a3_color", "copy"),
    ("copy_a3_bw", "Copy A3 ขาวดำ", "a3_bw", "copy"),
    ("copy_other", "Copy Other", "", "copy"),
)
OPERATION_DEVICE_SUBHEADERS = tuple(
    item
    for _field, label, _cost_field, _operation in OPERATION_FIELDS
    for item in (f"{label} (หน้า)", f"{label} (บาท)")
) + ("Scan", "Print รวม", "Copy รวม", "รวมหน้า", "ค่าใช้จ่ายรวม (บาท)")


@dataclass(frozen=True)
class DailyCategoryCost:
    """Net cost allocated to paper categories for one device-day."""

    device_slot: int
    device_identity: str
    record_date: date
    a4_color: float = 0.0
    a4_bw: float = 0.0
    a3_color: float = 0.0
    a3_bw: float = 0.0
    unallocated: float = 0.0
    available: bool = True

    @property
    def total(self) -> float:
        return round(
            self.a4_color
            + self.a4_bw
            + self.a3_color
            + self.a3_bw
            + self.unallocated,
            2,
        )


@dataclass(frozen=True)
class CloudReportsExportData:
    """Report data that is safe to save outside the local KOMI database."""

    selected_records: tuple[MonthlyUsage, ...]
    selected_daily_records: tuple[MonthlyUsage, ...]
    usage_daily_records: tuple[MonthlyUsage, ...]
    monthly_records: tuple[MonthlyUsage, ...]
    subjects: tuple[SubjectPeriodUsage, ...]
    devices: tuple[DeviceConfig, ...]
    period: tuple[str, str] | None
    last_sync_at: str | None
    generated_at: datetime
    include_waste_adjustment: bool = True
    category_costs: tuple[DailyCategoryCost, ...] = ()
    raw_counter_records: tuple[RawCounterDailyRecord, ...] = ()
    sections: tuple[str, ...] = ALL_REPORT_SECTIONS


@dataclass(frozen=True)
class _DeviceColumn:
    slot: int
    identity: str
    label: str

    @property
    def key(self) -> tuple[int, str]:
        return self.slot, self.identity


def suggested_cloud_reports_filename(at: datetime | None = None) -> str:
    stamp = (at or datetime.now().astimezone()).strftime("%Y%m%d_%H%M%S")
    return f"KOMI_Reports_{stamp}.xlsx"


def build_daily_category_costs(
    records: tuple[MonthlyUsage, ...],
    *,
    pricing: PricingRepository | None = None,
    include_waste_adjustment: bool = True,
) -> tuple[DailyCategoryCost, ...]:
    """Allocate the selected frozen total using prices effective on each record day.

    If no historical price basis exists, the value remains explicitly
    unallocated instead of being guessed into a paper category.
    """

    repository = pricing or PricingRepository()
    prices_by_day = repository.get_prices_for_days(
        (record.device_slot, record.period_start) for record in records)
    result: list[DailyCategoryCost] = []
    for record in records:
        day = record.period_start
        prices = prices_by_day[(record.device_slot, day)]
        usage = {field: _combined(record, field) for field, _label in CATEGORY_FIELDS}
        basis = {
            field: usage[field] * float(getattr(prices, field, 0.0) or 0.0)
            for field, _label in CATEGORY_FIELDS
        }
        target = round(
            _combined(
                record,
                "net_cost" if include_waste_adjustment else "gross_cost",
            ),
            2,
        )
        allocated = {field: 0.0 for field, _label in CATEGORY_FIELDS}
        total_basis = sum(basis.values())
        unallocated = 0.0
        if target and total_basis > 0:
            nonzero = [field for field, _label in CATEGORY_FIELDS if basis[field] > 0]
            remaining = target
            for field in nonzero[:-1]:
                amount = round(target * basis[field] / total_basis, 2)
                allocated[field] = amount
                remaining -= amount
            if nonzero:
                allocated[nonzero[-1]] = round(remaining, 2)
        elif target:
            unallocated = target
        result.append(
            DailyCategoryCost(
                device_slot=record.device_slot,
                device_identity=_record_identity(record),
                record_date=day,
                unallocated=unallocated,
                available=_cost_available(record),
                **allocated,
            )
        )
    return tuple(result)


def export_cloud_reports_xlsx(
    target: str | Path,
    report: CloudReportsExportData,
    *, cancelled=None, progress=None,
) -> Path:
    """Publish only a complete workbook; cancellation/errors preserve old files."""
    validate_sections(report.sections)
    if report.period is not None:
        validate_report_period(*map(date.fromisoformat, report.period), years=EXPORT_YEARS)
    destination = Path(target).expanduser()
    if destination.suffix.casefold() != '.xlsx':
        destination = destination.with_suffix('.xlsx')
    last_percent = 0
    def monotonic_progress(percent, message):
        nonlocal last_percent
        last_percent = max(last_percent, min(100, int(percent)))
        if progress is not None:
            progress(last_percent, message)
    token = _export_control.set((cancelled, monotonic_progress))
    temporary = None
    try:
        _checkpoint(0, 'กำลังเตรียมรายงาน…')
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix='.komi-export-', suffix='.xlsx', dir=destination.parent)
        os.close(descriptor)
        temporary = Path(name)
        _write_report_workbook(temporary, report)
        _checkpoint(99, 'กำลังบันทึกไฟล์…')
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        _export_control.reset(token)


def _write_report_workbook(target, report):
    sections = validate_sections(report.sections)
    destination = Path(target).expanduser()
    if destination.suffix.casefold() != ".xlsx":
        destination = destination.with_suffix(".xlsx")
    destination.parent.mkdir(parents=True, exist_ok=True)

    records = tuple(report.selected_daily_records or report.selected_records)
    cost_field = "net_cost" if report.include_waste_adjustment else "gross_cost"
    cost_note = (
        "ค่าใช้จ่ายหลังคิด % กระดาษเสียตาม Billing Ledger"
        if report.include_waste_adjustment
        else "ค่าใช้จ่ายก่อนหักกระดาษเสีย"
    )
    costs = report.category_costs or (build_daily_category_costs(
        records,
        include_waste_adjustment=report.include_waste_adjustment,
    ) if any(key in sections for key in ('printers', 'users', 'daily')) else ())
    devices = _device_columns(report, records)
    period_text = _period_text(report.period)

    workbook = Workbook()
    workbook.remove(workbook.active)
    detail_notes = [record for record in report.raw_counter_records if record.remarks]
    if detail_notes:
        notes = workbook.create_sheet('หมายเหตุรายละเอียด')
        notes.append(['Slot', 'Serial', 'วันลงยอด', 'ตัวนับ', 'รหัสผู้ใช้/บัญชี', 'อ่านสำเร็จจริงล่าสุด', 'หมายเหตุ'])
        for record in detail_notes:
            _checkpoint()
            values = [record.device_slot + 1, record.device_serial_snapshot, record.record_date.isoformat(),
                      record.canonical_field, record.subject_id, record.last_success or 'ไม่มีจุดอ่านในวันนี้', '\n'.join(record.remarks)]
            notes.append([_neutralize_untrusted_cell_string(v)[0] if isinstance(v, str) else v for v in values])
        notes.freeze_panes = 'A2'
        for column in ('B', 'C', 'E', 'F'):
            notes.column_dimensions[column].width = 26
        notes.column_dimensions['D'].width = 40
        notes.column_dimensions['G'].width = 100
    noted_records = [record for record in records if record.remarks]
    if noted_records:
        all_amended = all(any(note.startswith('ฉบับแก้ไข') for note in r.remarks) for r in noted_records)
        notes = workbook.create_sheet('หมายเหตุฉบับแก้ไข' if all_amended else 'หมายเหตุรายงาน')
        notes.append(["Slot", "Serial", "เริ่มช่วง", "สิ้นสุดช่วง", "หมายเหตุ"])
        for record in noted_records:
            _checkpoint()
            notes.append([record.device_slot + 1,
                _neutralize_untrusted_cell_string(record.device_serial_snapshot)[0],
                record.period_start.isoformat(), record.period_end.isoformat(),
                _neutralize_untrusted_cell_string("\n".join(record.remarks))[0]])
        notes.freeze_panes = "A2"
        notes.column_dimensions["B"].width = 24
        notes.column_dimensions["C"].width = notes.column_dimensions["D"].width = 16
        notes.column_dimensions["E"].width = 100
    writers = {
        'printers': ('การใช้งานรายเครื่อง', lambda sheet: _write_machine_sheet(
            sheet, records, costs, devices, period_text, cost_field=cost_field, cost_note=cost_note)),
        'users': ('มุมมองผู้ใช้', lambda sheet: _write_user_sheet(
            sheet, report.subjects, devices, period_text, report.raw_counter_records, costs, cost_note=cost_note)),
        'daily': ('มุมมองรายวัน', lambda sheet: _write_daily_sheet(
            sheet, records, costs, devices, period_text, cost_field=cost_field, cost_note=cost_note)),
        'legacy_printers': ('Legacy-รายเครื่อง', lambda sheet: _write_legacy_machine_sheet(
            sheet, report.raw_counter_records, report.devices, period_text)),
        'legacy_users': ('Legacy-ผู้ใช้', lambda sheet: _write_legacy_user_sheet(
            sheet, report.raw_counter_records, report.devices, period_text)),
        'legacy_daily': ('Legacy-รายวัน', lambda sheet: _write_legacy_daily_sheet(
            sheet, report.raw_counter_records, report.devices, period_text)),
    }
    for index, key in enumerate(sections):
        title, write = writers[key]
        _checkpoint(10 + index * 75 // len(sections), f'กำลังสร้าง {title}…')
        write(workbook.create_sheet(title, index))

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    _checkpoint(90, 'กำลังเขียนไฟล์ Excel…')
    try:
        workbook.save(destination)
    finally:
        workbook.close()
    return destination


def _raw_type(record: RawCounterDailyRecord) -> tuple[str, str, str]:
    """Keep exact model counters distinct when their labels collide."""

    return record.canonical_field, record.label, record.source_path


def _raw_display_label(
    raw_type: tuple[str, str, str],
    all_types: tuple[tuple[str, str, str], ...],
) -> str:
    field, label, source_path = raw_type
    base = label or field or "Unknown"
    duplicate = sum(
        1 for item in all_types if (item[1] or item[0] or "Unknown") == base
    ) > 1
    return f"{base} [{source_path}]" if duplicate and source_path else base


def _raw_device_identity(
    slot: int,
    serial: str,
    name: str,
) -> str:
    normalized_serial = str(serial or "").strip().casefold()
    if normalized_serial:
        return f"serial:{normalized_serial}"
    return f"unknown:{slot}:{str(name or '').strip().casefold()}"


def _raw_device_key(record: RawCounterDailyRecord) -> tuple[int, str]:
    return (
        int(record.device_slot),
        _raw_device_identity(
            int(record.device_slot),
            record.device_serial_snapshot,
            record.device_name_snapshot,
        ),
    )


def _masked_serial(serial: str) -> str:
    value = str(serial or "").strip()
    return f"••••{value[-4:]}" if value else ""


def _raw_device_columns(
    records: tuple[RawCounterDailyRecord, ...],
    devices: tuple[DeviceConfig, ...],
) -> tuple[_DeviceColumn, ...]:
    columns: dict[tuple[int, str], _DeviceColumn] = {}
    for record in records:
        key = _raw_device_key(record)
        name = record.device_name_snapshot or f"MFP {record.device_slot + 1}"
        serial_suffix = _masked_serial(record.device_serial_snapshot)
        columns.setdefault(
            key,
            _DeviceColumn(
                slot=key[0],
                identity=key[1],
                label=(
                    f"Slot {key[0] + 1} · {name} · {serial_suffix}"
                    if serial_suffix
                    else f"Slot {key[0] + 1} · {name} · ไม่พบ Serial"
                ),
            ),
        )
    for device in devices:
        key = (
            int(device.slot),
            _raw_device_identity(int(device.slot), device.serial, device.name),
        )
        serial_suffix = _masked_serial(device.serial)
        columns.setdefault(
            key,
            _DeviceColumn(
                slot=key[0],
                identity=key[1],
                label=(
                    f"Slot {key[0] + 1} · {device.name} · {serial_suffix}"
                    if serial_suffix
                    else f"Slot {key[0] + 1} · {device.name} · ไม่พบ Serial"
                ),
            ),
        )
    return tuple(sorted(columns.values(), key=lambda item: (item.slot, item.identity)))


def _raw_total(records) -> float | str:
    values = tuple(records)
    if not values:
        return "—"
    total = sum(float(item.delta_value) for item in values)
    if any(item.needs_review for item in values):
        return f"{total:g} · รอตรวจสอบยอดมิเตอร์"
    return total


def _write_legacy_machine_sheet(
    worksheet,
    records: tuple[RawCounterDailyRecord, ...],
    devices: tuple[DeviceConfig, ...],
    period_text: str,
) -> None:
    device_records = tuple(record for record in records if not record.is_subject)
    indexed = defaultdict(list)
    for record in device_records:
        indexed[(_raw_device_key(record), _raw_type(record))].append(record)
    device_columns = _raw_device_columns(records, devices)
    types = tuple(
        sorted({_raw_type(record) for record in device_records}, key=lambda item: (item[1].casefold(), item[0]))
    )
    columns = max(2, 2 + len(device_columns))
    _sheet_title(
        worksheet,
        "Legacy — รายเครื่อง",
        f"ช่วงวันที่ {period_text} · ชื่อ Counter และค่าตรงจากเครื่อง ไม่มีการ Map",
        columns,
    )
    _header_cell(worksheet.cell(4, 1, "กลุ่มงาน"), NAVY)
    _header_cell(worksheet.cell(4, 2, "ประเภท Counter (ชื่อจากเครื่อง)"), NAVY)
    for column, device in enumerate(device_columns, start=3):
        _header_cell(_set_cell_value(worksheet, 4, column, device.label), BLUE)
    for row_no, raw_type in enumerate(types, start=5):
        row: list[object] = [
            raw_operation_label(raw_type[0], raw_type[1]),
            _raw_display_label(raw_type, types),
        ]
        for device in device_columns:
            row.append(
                _raw_total(
                    indexed.get((device.key, raw_type), ())
                )
            )
        _write_row(worksheet, row_no, row, currency_columns=set())
    if not types:
        _empty_row(worksheet, 5, columns, "ไม่มี Raw Counter ในช่วงวันที่เลือก")
    _finish_sheet(worksheet, columns, max(5, 4 + len(types)), freeze="C5", first_width=24)
    worksheet.column_dimensions["B"].width = 34


def _raw_dynamic_columns(
    records: tuple[RawCounterDailyRecord, ...],
) -> tuple[tuple[int, str, str, str, str], ...]:
    return tuple(
        sorted(
            {
                (
                    record.device_slot,
                    _raw_device_key(record)[1],
                    record.canonical_field,
                    record.label,
                    record.source_path,
                )
                for record in records
            },
            key=lambda item: (item[0], item[1], item[3].casefold(), item[2], item[4]),
        )
    )


def _write_legacy_user_sheet(
    worksheet,
    records: tuple[RawCounterDailyRecord, ...],
    devices: tuple[DeviceConfig, ...],
    period_text: str,
) -> None:
    subject_records = tuple(record for record in records if record.is_subject)
    indexed = defaultdict(list)
    for record in subject_records:
        indexed[(record.subject_type, record.subject_id, _raw_device_key(record), _raw_type(record))].append(record)
    names = {item.key: item.label for item in _raw_device_columns(records, devices)}
    dynamic = _raw_dynamic_columns(subject_records)
    subjects = tuple(
        sorted(
            {
                (record.subject_type, record.subject_id, record.subject_name or record.subject_id)
                for record in subject_records
            },
            key=lambda item: (item[2].casefold(), item[0], item[1]),
        )
    )
    columns = max(1, 1 + len(dynamic))
    _sheet_title(
        worksheet,
        "Legacy — ผู้ใช้",
        f"ช่วงวันที่ {period_text} · ทุกประเภท Counter ต่อผู้ใช้และต่อเครื่องตามข้อมูลต้นทาง",
        columns,
    )
    _header_cell(worksheet.cell(4, 1, "ผู้ใช้ / Account"), NAVY)
    raw_types = tuple((item[2], item[3], item[4]) for item in dynamic)
    for column, (slot, identity, field, label, source_path) in enumerate(dynamic, start=2):
        _header_cell(
            _set_cell_value(
                worksheet,
                4,
                column,
                f"{names.get((slot, identity), f'Slot {slot + 1}')}\n"
                f"{raw_operation_label(field, label)} · "
                f"{_raw_display_label((field, label, source_path), raw_types)}",
            ),
            (BLUE, TEAL, PURPLE)[slot % 3],
        )
    for row_no, (subject_type, subject_id, subject_name) in enumerate(subjects, start=5):
        row: list[object] = [f"{subject_name} ({subject_type})"]
        for slot, identity, field, label, source_path in dynamic:
            row.append(
                _raw_total(
                    indexed.get((subject_type, subject_id, (slot, identity), (field, label, source_path)), ())
                )
            )
        _write_row(worksheet, row_no, row, currency_columns=set())
    if not subjects:
        _empty_row(worksheet, 5, columns, "ไม่มี Raw Counter แยกผู้ใช้ / Account")
    _finish_sheet(worksheet, columns, max(5, 4 + len(subjects)), freeze="B5", first_width=28)


def _write_legacy_daily_sheet(
    worksheet,
    records: tuple[RawCounterDailyRecord, ...],
    devices: tuple[DeviceConfig, ...],
    period_text: str,
) -> None:
    device_records = tuple(record for record in records if not record.is_subject)
    indexed = defaultdict(list)
    for record in device_records:
        indexed[(record.record_date, _raw_device_key(record), _raw_type(record))].append(record)
    names = {item.key: item.label for item in _raw_device_columns(records, devices)}
    dynamic = _raw_dynamic_columns(device_records)
    days = tuple(sorted({record.record_date for record in device_records}))
    columns = max(1, 1 + len(dynamic))
    _sheet_title(
        worksheet,
        "Legacy — รายวัน",
        f"ช่วงวันที่ {period_text} · หนึ่งวันต่อหนึ่งแถว · ไม่มีการ Map หรือเดาค่าที่ขาด",
        columns,
    )
    _header_cell(worksheet.cell(4, 1, "วันที่"), NAVY)
    raw_types = tuple((item[2], item[3], item[4]) for item in dynamic)
    for column, (slot, identity, field, label, source_path) in enumerate(dynamic, start=2):
        _header_cell(
            _set_cell_value(
                worksheet,
                4,
                column,
                f"{names.get((slot, identity), f'Slot {slot + 1}')}\n"
                f"{raw_operation_label(field, label)} · "
                f"{_raw_display_label((field, label, source_path), raw_types)}",
            ),
            (BLUE, TEAL, PURPLE)[slot % 3],
        )
    for row_no, day in enumerate(days, start=5):
        row: list[object] = [day]
        for slot, identity, field, label, source_path in dynamic:
            row.append(
                _raw_total(
                    indexed.get((day, (slot, identity), (field, label, source_path)), ())
                )
            )
        _write_row(worksheet, row_no, row, currency_columns=set())
        worksheet.cell(row_no, 1).number_format = "dd/mm/yyyy"
    if not days:
        _empty_row(worksheet, 5, columns, "ไม่มี Raw Counter รายวัน")
    _finish_sheet(worksheet, columns, max(5, 4 + len(days)), freeze="B5", first_width=14)


def _operation_available(records: tuple[MonthlyUsage, ...], operation: str) -> bool:
    return any(
        bool(getattr(record, f"{operation}_available", False))
        or any(
            _combined(record, f"{operation}_{suffix}")
            for suffix in ("a3_color", "a3_bw", "a4_color", "a4_bw", "other")
        )
        for record in records
    )


def _operation_total(records: tuple[MonthlyUsage, ...], operation: str) -> float:
    return sum(
        _combined(record, f"{operation}_{suffix}")
        for record in records
        for suffix in ("a3_color", "a3_bw", "a4_color", "a4_bw", "other")
    )


def _operation_cost(
    records: tuple[MonthlyUsage, ...],
    costs: tuple[DailyCategoryCost, ...],
    operation_field: str,
    category_field: str,
) -> float | None:
    if not category_field or not all(_cost_available(record) for record in records):
        return None
    costs_by_day: defaultdict[date, float] = defaultdict(float)
    for cost in costs:
        costs_by_day[cost.record_date] += float(getattr(cost, category_field, 0.0) or 0.0)
    amount = 0.0
    for record in records:
        category_usage = _combined(record, category_field)
        operation_usage = _combined(record, operation_field)
        if category_usage > 0 and operation_usage > 0:
            if record.period_start not in costs_by_day:
                return None
            amount += costs_by_day[record.period_start] * operation_usage / category_usage
    return round(amount, 2)


from services.report_user_costs import (
    device_daily_evidence as _device_daily_evidence,
    subject_total_cost as _subject_total_cost,
    subject_costs as _allocate_subject_costs,
)


def _subject_costs(subject_records, device_key, evidence):
    return _allocate_subject_costs(subject_records, device_key, evidence, checkpoint=_checkpoint)


def _write_machine_sheet(
    worksheet,
    records: tuple[MonthlyUsage, ...],
    costs: tuple[DailyCategoryCost, ...],
    devices: tuple[_DeviceColumn, ...],
    period_text: str,
    *,
    cost_field: str,
    cost_note: str,
) -> None:
    total_columns = 1 + len(OPERATION_FIELDS) * 2 + 6
    _sheet_title(
        worksheet,
        "การใช้งานรายเครื่อง",
        f"ช่วงวันที่ {period_text} · หนึ่งเครื่องต่อหนึ่งแถว · {cost_note}",
        total_columns,
    )
    _header_cell(worksheet.cell(3, 1, "เครื่องพิมพ์"), NAVY)
    _header_cell(worksheet.cell(4, 1, "ชื่อเครื่อง"), NAVY)
    column = 2
    for _field, label, _cost_field, operation in OPERATION_FIELDS:
        color = BLUE if operation == "print" else TEAL
        worksheet.merge_cells(start_row=3, start_column=column, end_row=3, end_column=column + 1)
        _header_cell(worksheet.cell(3, column, label), color)
        _header_cell(worksheet.cell(4, column, "จำนวนหน้า"), color)
        _header_cell(worksheet.cell(4, column + 1, "ค่าใช้จ่าย (บาท)"), color)
        column += 2
    for group_label, detail_label in (
        ("Scan", "จำนวน"),
        ("Print", "รวมหน้า"),
        ("Copy", "รวมหน้า"),
        ("รวม", "จำนวนหน้า"),
        ("รวม", "ค่าใช้จ่าย (บาท)"),
        ("สถานะ", "ผลตรวจ"),
    ):
        _header_cell(worksheet.cell(3, column, group_label), NAVY)
        _header_cell(worksheet.cell(4, column, detail_label), NAVY)
        column += 1

    grouped_records = _records_by_device(records)
    grouped_costs = _costs_by_device(costs)
    for row_index, device in enumerate(devices, start=5):
        device_records = grouped_records.get(device.key, ())
        device_costs = grouped_costs.get(device.key, ())
        row: list[object] = [device.label]
        print_available = _operation_available(device_records, "print")
        copy_available = _operation_available(device_records, "copy")
        for field, _label, category_field, operation in OPERATION_FIELDS:
            available = print_available if operation == "print" else copy_available
            row.extend(
                (
                    sum(_combined(record, field) for record in device_records)
                    if available
                    else None,
                    _operation_cost(
                        device_records,
                        device_costs,
                        field,
                        category_field,
                    )
                    if available
                    else None,
                )
            )
        row.extend(
            (
                sum(_combined(record, "scan") for record in device_records),
                _operation_total(device_records, "print") if print_available else None,
                _operation_total(device_records, "copy") if copy_available else None,
                sum(_usage_total(record) for record in device_records),
                sum(_combined(record, cost_field) for record in device_records)
                if all(_cost_available(record) for record in device_records) else None,
                _review_status(device_records),
            )
        )
        currency_columns = {
            3 + index * 2 for index in range(len(OPERATION_FIELDS))
        } | {total_columns - 1}
        _write_row(worksheet, row_index, row, currency_columns=currency_columns)
    if not devices:
        _empty_row(worksheet, 5, total_columns, "ไม่มีข้อมูลเครื่องพิมพ์ในช่วงวันที่เลือก")
    _finish_sheet(worksheet, total_columns, max(5, 4 + len(devices)), freeze="B5", first_width=30)


def _write_user_sheet(
    worksheet,
    subjects: tuple[SubjectPeriodUsage, ...],
    devices: tuple[_DeviceColumn, ...],
    period_text: str,
    raw_records: tuple[RawCounterDailyRecord, ...],
    costs: tuple[DailyCategoryCost, ...],
    *,
    cost_note: str,
) -> None:
    fixed_columns = 3
    total_columns = fixed_columns + len(devices) * len(OPERATION_DEVICE_SUBHEADERS) + 2
    _sheet_title(
        worksheet,
        "มุมมองผู้ใช้",
        (
            f"ช่วงวันที่ {period_text} · หนึ่งผู้ใช้ต่อหนึ่งแถว · "
            "แยก Print/Copy เฉพาะ Counter ที่ต้นทางระบุชัดเจน และไม่ประมาณค่าที่ขาด · "
            f"{cost_note}"
        ),
        total_columns,
    )
    for column, (group_label, detail_label) in enumerate(
        (("ผู้ใช้ / Account", "ชื่อ"), ("ประเภท", "User / Account"), ("รหัส", "ID")),
        start=1,
    ):
        _header_cell(worksheet.cell(3, column, group_label), NAVY)
        _header_cell(worksheet.cell(4, column, detail_label), NAVY)
    column = fixed_columns + 1
    for index, device in enumerate(devices):
        end_column = column + len(OPERATION_DEVICE_SUBHEADERS) - 1
        color = (BLUE, TEAL, PURPLE)[index % 3]
        worksheet.merge_cells(start_row=3, start_column=column, end_row=3, end_column=end_column)
        _header_cell(_set_cell_value(worksheet, 3, column, device.label), color)
        for offset, label in enumerate(OPERATION_DEVICE_SUBHEADERS):
            _header_cell(worksheet.cell(4, column + offset, label), color)
        column = end_column + 1
    _header_cell(worksheet.cell(3, column, "รวมทุกเครื่อง"), NAVY)
    _header_cell(worksheet.cell(4, column, "จำนวนหน้า"), NAVY)
    _header_cell(worksheet.cell(3, column + 1, "สถานะ"), NAVY)
    _header_cell(worksheet.cell(4, column + 1, "ผลตรวจ"), NAVY)

    subject_groups: dict[tuple[str, str], dict[str, object]] = {}
    for subject in subjects:
        key = (subject.subject_type, subject.subject_id)
        group = subject_groups.setdefault(key, {"name": subject.subject_name, "records": []})
        group["name"] = subject.subject_name
        group["records"].append(subject)
    ordered_groups = sorted(
        subject_groups.items(),
        key=lambda item: str(item[1]["name"]).casefold(),
    )
    raw_groups: defaultdict[tuple[str, str, tuple[int, str]], list[RawCounterDailyRecord]] = defaultdict(list)
    for record in raw_records:
        if not record.is_subject:
            continue
        identity = (
            f"serial:{record.device_serial_snapshot}"
            if record.device_serial_snapshot
            else f"slot:{record.device_slot}"
        )
        raw_groups[
            (record.subject_type, record.subject_id, (record.device_slot, identity))
        ].append(record)
    evidence = _device_daily_evidence(raw_records, costs)
    for row_index, ((subject_type, subject_id), group) in enumerate(ordered_groups, start=5):
        subject_records = tuple(group["records"])
        row: list[object] = [group["name"], subject_type, subject_id]
        for device in devices:
            usage = sum(
                record.period_usage
                for record in subject_records
                if _subject_device_key(record) == device.key
            )
            subject_raw = tuple(
                raw_groups.get((subject_type, subject_id, device.key), ())
            )
            breakdown = breakdown_from_raw_records(subject_raw)
            amounts = _subject_costs(subject_raw, device.key, evidence)
            for field, _label, category_field, operation in OPERATION_FIELDS:
                available = (
                    breakdown.print_available
                    if operation == "print"
                    else breakdown.copy_available
                )
                row.extend(
                    (
                        getattr(breakdown, field) if available else None,
                        amounts[field]
                        if available
                        else None,
                    )
                )
            row.extend(
                (
                    breakdown.scan if breakdown.scan_available else None,
                    breakdown.print_total if breakdown.print_available else None,
                    breakdown.copy_total if breakdown.copy_available else None,
                    usage,
                    _subject_total_cost(breakdown, amounts),
                )
            )
        row.extend(
            (
                sum(record.period_usage for record in subject_records),
                "ตรวจสอบ" if any(record.needs_review for record in subject_records) else "พร้อมใช้",
            )
        )
        currency_columns = {
            fixed_columns
            + 2
            + device_index * len(OPERATION_DEVICE_SUBHEADERS)
            + field_index * 2
            for device_index in range(len(devices))
            for field_index in range(len(OPERATION_FIELDS))
        } | {
            fixed_columns
            + device_index * len(OPERATION_DEVICE_SUBHEADERS)
            + len(OPERATION_DEVICE_SUBHEADERS)
            for device_index in range(len(devices))
        }
        _write_row(worksheet, row_index, row, currency_columns=currency_columns)
        completed = row_index - 4
        _checkpoint(25 + 25 * completed // len(ordered_groups),
                    f'กำลังสร้างรายงานผู้ใช้ {completed}/{len(ordered_groups)} คน…')
    if not subject_groups:
        _empty_row(worksheet, 5, total_columns, "ไม่มีข้อมูลผู้ใช้ / Account Track ในช่วงวันที่เลือก")
    _finish_sheet(
        worksheet,
        total_columns,
        max(5, 4 + len(subject_groups)),
        freeze="D5",
        first_width=26,
    )


def _write_daily_sheet(
    worksheet,
    records: tuple[MonthlyUsage, ...],
    costs: tuple[DailyCategoryCost, ...],
    devices: tuple[_DeviceColumn, ...],
    period_text: str,
    *,
    cost_field: str,
    cost_note: str,
) -> None:
    total_columns = 1 + len(devices) * len(OPERATION_DEVICE_SUBHEADERS) + 2
    _sheet_title(
        worksheet,
        "มุมมองรายวัน",
        f"ช่วงวันที่ {period_text} · หนึ่งวันต่อหนึ่งแถว ไม่มีวันที่ซ้ำ · {cost_note}",
        total_columns,
    )
    _header_cell(worksheet.cell(3, 1, "วันที่"), NAVY)
    _header_cell(worksheet.cell(4, 1, "วันที่"), NAVY)
    column = 2
    for index, device in enumerate(devices):
        end_column = column + len(OPERATION_DEVICE_SUBHEADERS) - 1
        color = (BLUE, TEAL, PURPLE)[index % 3]
        worksheet.merge_cells(start_row=3, start_column=column, end_row=3, end_column=end_column)
        _header_cell(_set_cell_value(worksheet, 3, column, device.label), color)
        for offset, label in enumerate(OPERATION_DEVICE_SUBHEADERS):
            _header_cell(worksheet.cell(4, column + offset, label), color)
        column = end_column + 1
    for group_label, detail_label in (
        ("รวมทุกเครื่อง", "จำนวนหน้า"),
        ("รวมทุกเครื่อง", "ค่าใช้จ่าย (บาท)"),
    ):
        _header_cell(worksheet.cell(3, column, group_label), NAVY)
        _header_cell(worksheet.cell(4, column, detail_label), NAVY)
        column += 1

    record_index = {(record.period_start, _record_device_key(record)): record for record in records}
    days = sorted({record.period_start for record in records})
    currency_columns = {
        3
        + device_index * len(OPERATION_DEVICE_SUBHEADERS)
        + field_index * 2
        for device_index in range(len(devices))
        for field_index in range(len(OPERATION_FIELDS))
    } | {
        1 + (device_index + 1) * len(OPERATION_DEVICE_SUBHEADERS)
        for device_index in range(len(devices))
    } | {total_columns}
    for row_index, day in enumerate(days, start=5):
        row: list[object] = [day]
        daily_usage = 0.0
        daily_cost = 0.0
        daily_cost_available = True
        for device in devices:
            record = record_index.get((day, device.key))
            if record is None:
                # Blank means unavailable.  A numeric zero would falsely claim
                # that this printer was observed and had no usage that day.
                row.extend((None,) * len(OPERATION_DEVICE_SUBHEADERS))
                continue
            print_available = _operation_available((record,), "print")
            copy_available = _operation_available((record,), "copy")
            cost = next(
                (
                    item
                    for item in costs
                    if item.record_date == day
                    and (item.device_slot, item.device_identity) == device.key
                ),
                None,
            )
            for field, _label, category_field, operation in OPERATION_FIELDS:
                available = print_available if operation == "print" else copy_available
                row.extend(
                    (
                        _combined(record, field) if available else None,
                        _operation_cost(
                            (record,),
                            (cost,) if cost is not None else (),
                            field,
                            category_field,
                        )
                        if available
                        else None,
                    )
                )
            usage_total = _usage_total(record)
            available_cost = _cost_available(record)
            selected_cost = _combined(record, cost_field) if available_cost else None
            row.extend(
                (
                    _combined(record, "scan"),
                    _operation_total((record,), "print") if print_available else None,
                    _operation_total((record,), "copy") if copy_available else None,
                    usage_total,
                    selected_cost,
                )
            )
            daily_usage += usage_total
            daily_cost += selected_cost or 0
            daily_cost_available &= available_cost
        row.extend((daily_usage, daily_cost if daily_cost_available else None))
        _write_row(worksheet, row_index, row, currency_columns=currency_columns)
        worksheet.cell(row_index, 1).number_format = "dd/mm/yyyy"
    if not days:
        _empty_row(worksheet, 5, total_columns, "ไม่มีข้อมูลรายวันในช่วงวันที่เลือก")
    _finish_sheet(worksheet, total_columns, max(5, 4 + len(days)), freeze="B5", first_width=14)


def _device_columns(
    report: CloudReportsExportData,
    records: tuple[MonthlyUsage, ...],
) -> tuple[_DeviceColumn, ...]:
    configured = {device.slot: device for device in report.devices}
    columns: dict[tuple[int, str], _DeviceColumn] = {}
    for record in records:
        identity = _record_identity(record)
        configured_name = configured[record.device_slot].name if record.device_slot in configured else f"MFP {record.device_slot + 1}"
        label = record.device_name_snapshot or configured_name
        columns[(record.device_slot, identity)] = _DeviceColumn(record.device_slot, identity, label)
    for subject in report.subjects:
        identity = _subject_identity(subject)
        configured_name = configured[subject.device_slot].name if subject.device_slot in configured else f"MFP {subject.device_slot + 1}"
        label = subject.device_name_snapshot or configured_name
        columns[(subject.device_slot, identity)] = _DeviceColumn(subject.device_slot, identity, label)
    for device in report.devices:
        if not any(column.slot == device.slot for column in columns.values()):
            identity = f"serial:{device.serial}" if device.serial else f"host:{device.host}"
            columns[(device.slot, identity)] = _DeviceColumn(device.slot, identity, device.name)
    return tuple(sorted(columns.values(), key=lambda item: (item.slot, item.label.casefold(), item.identity)))


def _records_by_device(records: tuple[MonthlyUsage, ...]) -> dict[tuple[int, str], tuple[MonthlyUsage, ...]]:
    grouped: defaultdict[tuple[int, str], list[MonthlyUsage]] = defaultdict(list)
    for record in records:
        grouped[_record_device_key(record)].append(record)
    return {key: tuple(value) for key, value in grouped.items()}


def _costs_by_device(costs: tuple[DailyCategoryCost, ...]) -> dict[tuple[int, str], tuple[DailyCategoryCost, ...]]:
    grouped: defaultdict[tuple[int, str], list[DailyCategoryCost]] = defaultdict(list)
    for cost in costs:
        grouped[(cost.device_slot, cost.device_identity)].append(cost)
    return {key: tuple(value) for key, value in grouped.items()}


def _record_identity(record: MonthlyUsage) -> str:
    return str(record.device_identity or f"slot:{record.device_slot}")


def _record_device_key(record: MonthlyUsage) -> tuple[int, str]:
    return record.device_slot, _record_identity(record)


def _subject_identity(subject: SubjectPeriodUsage) -> str:
    return str(subject.device_identity or f"slot:{subject.device_slot}")


def _subject_device_key(subject: SubjectPeriodUsage) -> tuple[int, str]:
    return subject.device_slot, _subject_identity(subject)


def _combined(record: MonthlyUsage, field: str) -> float:
    return float(getattr(record, field, 0.0) or 0.0) + float(
        getattr(record, f"provisional_{field}", 0.0) or 0.0
    )


def _usage_total(record: MonthlyUsage) -> float:
    value = _combined(record, "total")
    if value:
        return value
    return sum(_combined(record, field) for field, _label in CATEGORY_FIELDS)


def _cost_available(record):
    return not record.provisional_days or record.provisional_cost_available


def _review_status(records: tuple[MonthlyUsage, ...]) -> str:
    if any(record.held_days or record.incomplete_days or not _cost_available(record) for record in records):
        return 'ตรวจสอบ'
    return 'ยอดชั่วคราว' if any(record.provisional_days for record in records) else 'พร้อมใช้'


def _period_text(period: tuple[str, str] | None) -> str:
    if period is None:
        return "ข้อมูลทั้งหมด"
    start, end = (date.fromisoformat(value) for value in period)
    return f"{start:%d/%m/%Y} – {end:%d/%m/%Y}"


def _neutralize_untrusted_cell_string(value: str) -> tuple[str, bool]:
    """Return text that Excel cannot reinterpret as a formula.

    Printer, user, and raw-counter labels are external input even when they
    arrive through a trusted local database.  Excel treats ``=``, ``+``, ``-``
    and ``@`` as formula prefixes, and spreadsheet applications can ignore
    leading whitespace/control characters when deciding how to interpret a
    cell.  Prefixing an apostrophe and setting ``quotePrefix`` preserves the
    displayed text while forcing a string cell.

    XML-illegal controls are removed before writing because openpyxl cannot
    serialize them.  Numeric/date values bypass this function entirely.
    """

    cleaned = _ILLEGAL_XML_CONTROL_RE.sub("", value)
    for character in cleaned:
        category = unicodedata.category(character)
        if character.isspace() or category in {"Cc", "Cf"}:
            continue
        if character in _EXCEL_FORMULA_PREFIXES:
            return f"'{cleaned}", True
        break
    return cleaned, False


def _set_cell_value(
    worksheet,
    row: int,
    column: int,
    value: object,
    *,
    trusted_formula: bool = False,
):
    """Write one cell, neutralizing strings unless explicitly trusted.

    ``trusted_formula`` is reserved for formulas authored by this exporter.
    External values must never set it.  The current report intentionally
    writes no formulas, but retaining this explicit escape hatch prevents a
    future program-authored formula from being silently converted to text.
    """

    neutralized = False
    if isinstance(value, str) and not trusted_formula:
        value, neutralized = _neutralize_untrusted_cell_string(value)
    cell = worksheet.cell(row, column, value)
    if neutralized:
        cell.quotePrefix = True
    return cell


def _sheet_title(worksheet, title: str, subtitle: str, columns: int) -> None:
    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
    title_cell = _set_cell_value(worksheet, 1, 1, title)
    title_cell.font = Font(name="Aptos Display", size=16, bold=True, color=WHITE)
    title_cell.fill = PatternFill("solid", fgColor=NAVY)
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    worksheet.row_dimensions[1].height = 28
    worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=columns)
    subtitle_cell = _set_cell_value(worksheet, 2, 1, subtitle)
    subtitle_cell.font = Font(name="Aptos", size=10, color=MUTED)
    subtitle_cell.fill = PatternFill("solid", fgColor=PALE)
    subtitle_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    worksheet.row_dimensions[2].height = 30


def _header_cell(cell, color: str) -> None:
    if isinstance(cell.value, str):
        value, neutralized = _neutralize_untrusted_cell_string(cell.value)
        cell.value = value
        if neutralized:
            cell.quotePrefix = True
    cell.fill = PatternFill("solid", fgColor=color)
    cell.font = Font(name="Aptos", size=10, bold=True, color=WHITE)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_row(worksheet, row_index: int, row: list[object], *, currency_columns: set[int]) -> None:
    _checkpoint()
    for column, value in enumerate(row, start=1):
        cell = _set_cell_value(worksheet, row_index, column, value)
        is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
        cell.alignment = Alignment(horizontal="right" if is_number else "left", vertical="center")
        if column in currency_columns and is_number:
            cell.number_format = "#,##0.00"
        elif is_number:
            cell.number_format = "#,##0"
        if row_index % 2 == 0:
            cell.fill = PatternFill("solid", fgColor="F7FAFC")


def _empty_row(worksheet, row: int, columns: int, message: str) -> None:
    worksheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=columns)
    cell = _set_cell_value(worksheet, row, 1, message)
    cell.font = Font(italic=True, color=MUTED)
    cell.alignment = Alignment(horizontal="center", vertical="center")
    cell.fill = PatternFill("solid", fgColor="F7FAFC")
    worksheet.row_dimensions[row].height = 28


def _finish_sheet(
    worksheet,
    columns: int,
    last_row: int,
    *,
    freeze: str,
    first_width: float,
) -> None:
    worksheet.sheet_view.showGridLines = False
    worksheet.freeze_panes = freeze
    worksheet.auto_filter.ref = f"A4:{get_column_letter(columns)}{last_row}"
    worksheet.row_dimensions[3].height = 27
    worksheet.row_dimensions[4].height = 38
    worksheet.column_dimensions["A"].width = first_width
    for column in range(2, columns + 1):
        worksheet.column_dimensions[get_column_letter(column)].width = 14
    side = Side(style="thin", color=LINE)
    border = Border(bottom=side, right=side)
    for row in worksheet.iter_rows(min_row=3, max_row=last_row, min_col=1, max_col=columns):
        for cell in row:
            cell.border = border
