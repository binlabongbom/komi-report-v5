"""Create a safe, user-facing Excel export for the Reports workspace."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.pricing import PricingRepository
from services.subject_history import SubjectPeriodUsage

NAVY = "123262"
BLUE = "1677C8"
TEAL = "0E7490"
PURPLE = "7C3AED"
PALE = "EAF2F8"
LINE = "D9E2EA"
MUTED = "56677A"
WHITE = "FFFFFF"

CATEGORY_FIELDS = (
    ("a4_color", "A4 สี"),
    ("a4_bw", "A4 ขาวดำ"),
    ("a3_color", "A3 สี"),
    ("a3_bw", "A3 ขาวดำ"),
)
DEVICE_SUBHEADERS = tuple(
    item
    for _field, label in CATEGORY_FIELDS
    for item in (f"{label} (หน้า)", f"{label} (บาท)")
) + ("Scan", "รวมหน้า", "ค่าใช้จ่ายรวม (บาท)")


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
    category_costs: tuple[DailyCategoryCost, ...] = ()


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
) -> tuple[DailyCategoryCost, ...]:
    """Allocate the exact net total using prices effective on each record day.

    If no historical price basis exists, the value remains explicitly
    unallocated instead of being guessed into a paper category.
    """

    repository = pricing or PricingRepository()
    result: list[DailyCategoryCost] = []
    for record in records:
        day = record.period_start
        prices = repository.get_prices(record.device_slot, day)
        usage = {field: _combined(record, field) for field, _label in CATEGORY_FIELDS}
        basis = {
            field: usage[field] * float(getattr(prices, field, 0.0) or 0.0)
            for field, _label in CATEGORY_FIELDS
        }
        target = round(_combined(record, "net_cost"), 2)
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
                **allocated,
            )
        )
    return tuple(result)


def export_cloud_reports_xlsx(
    target: str | Path,
    report: CloudReportsExportData,
) -> Path:
    """Save three human-readable report views without local credentials."""

    destination = Path(target).expanduser()
    if destination.suffix.casefold() != ".xlsx":
        destination = destination.with_suffix(".xlsx")
    destination.parent.mkdir(parents=True, exist_ok=True)

    records = tuple(report.selected_daily_records or report.selected_records)
    costs = report.category_costs or build_daily_category_costs(records)
    devices = _device_columns(report, records)
    period_text = _period_text(report.period)

    workbook = Workbook()
    machine_sheet = workbook.active
    machine_sheet.title = "การใช้งานรายเครื่อง"
    _write_machine_sheet(machine_sheet, records, costs, devices, period_text)
    _write_user_sheet(
        workbook.create_sheet("มุมมองผู้ใช้"),
        report.subjects,
        devices,
        period_text,
    )
    _write_daily_sheet(
        workbook.create_sheet("มุมมองรายวัน"),
        records,
        costs,
        devices,
        period_text,
    )

    workbook.calculation.fullCalcOnLoad = True
    workbook.calculation.forceFullCalc = True
    workbook.save(destination)
    return destination


def _write_machine_sheet(
    worksheet,
    records: tuple[MonthlyUsage, ...],
    costs: tuple[DailyCategoryCost, ...],
    devices: tuple[_DeviceColumn, ...],
    period_text: str,
) -> None:
    total_columns = 1 + len(CATEGORY_FIELDS) * 2 + 4
    _sheet_title(
        worksheet,
        "การใช้งานรายเครื่อง",
        f"ช่วงวันที่ {period_text} · หนึ่งเครื่องต่อหนึ่งแถว",
        total_columns,
    )
    _header_cell(worksheet.cell(3, 1, "เครื่องพิมพ์"), NAVY)
    _header_cell(worksheet.cell(4, 1, "ชื่อเครื่อง"), NAVY)
    column = 2
    for index, (_field, label) in enumerate(CATEGORY_FIELDS):
        color = (BLUE, TEAL, PURPLE, BLUE)[index]
        worksheet.merge_cells(start_row=3, start_column=column, end_row=3, end_column=column + 1)
        _header_cell(worksheet.cell(3, column, label), color)
        _header_cell(worksheet.cell(4, column, "จำนวนหน้า"), color)
        _header_cell(worksheet.cell(4, column + 1, "ค่าใช้จ่าย (บาท)"), color)
        column += 2
    for group_label, detail_label in (
        ("Scan", "จำนวน"),
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
        for field, _label in CATEGORY_FIELDS:
            row.extend(
                (
                    sum(_combined(record, field) for record in device_records),
                    sum(getattr(cost, field) for cost in device_costs),
                )
            )
        row.extend(
            (
                sum(_combined(record, "scan") for record in device_records),
                sum(_usage_total(record) for record in device_records),
                sum(_combined(record, "net_cost") for record in device_records),
                _review_status(device_records),
            )
        )
        _write_row(worksheet, row_index, row, currency_columns=_machine_currency_columns())
    if not devices:
        _empty_row(worksheet, 5, total_columns, "ไม่มีข้อมูลเครื่องพิมพ์ในช่วงวันที่เลือก")
    _finish_sheet(worksheet, total_columns, max(5, 4 + len(devices)), freeze="B5", first_width=30)


def _write_user_sheet(
    worksheet,
    subjects: tuple[SubjectPeriodUsage, ...],
    devices: tuple[_DeviceColumn, ...],
    period_text: str,
) -> None:
    fixed_columns = 3
    total_columns = fixed_columns + len(devices) * len(DEVICE_SUBHEADERS) + 2
    _sheet_title(
        worksheet,
        "มุมมองผู้ใช้",
        (
            f"ช่วงวันที่ {period_text} · หนึ่งผู้ใช้ต่อหนึ่งแถว · "
            "เครื่องส่งเฉพาะยอดรวมต่อผู้ใช้ จึงไม่ประมาณ A3/A4 สี/ขาวดำหรือค่าใช้จ่าย"
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
        end_column = column + len(DEVICE_SUBHEADERS) - 1
        color = (BLUE, TEAL, PURPLE)[index % 3]
        worksheet.merge_cells(start_row=3, start_column=column, end_row=3, end_column=end_column)
        _header_cell(worksheet.cell(3, column, device.label), color)
        for offset, label in enumerate(DEVICE_SUBHEADERS):
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
    for row_index, ((subject_type, subject_id), group) in enumerate(ordered_groups, start=5):
        subject_records = tuple(group["records"])
        row: list[object] = [group["name"], subject_type, subject_id]
        for device in devices:
            usage = sum(
                record.period_usage
                for record in subject_records
                if _subject_device_key(record) == device.key
            )
            row.extend((None, None, None, None, None, None, None, None, None, usage, None))
        row.extend(
            (
                sum(record.period_usage for record in subject_records),
                "ตรวจสอบ" if any(record.needs_review for record in subject_records) else "พร้อมใช้",
            )
        )
        _write_row(worksheet, row_index, row, currency_columns=set())
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
) -> None:
    total_columns = 1 + len(devices) * len(DEVICE_SUBHEADERS) + 2
    _sheet_title(
        worksheet,
        "มุมมองรายวัน",
        f"ช่วงวันที่ {period_text} · หนึ่งวันต่อหนึ่งแถว ไม่มีวันที่ซ้ำ",
        total_columns,
    )
    _header_cell(worksheet.cell(3, 1, "วันที่"), NAVY)
    _header_cell(worksheet.cell(4, 1, "วันที่"), NAVY)
    column = 2
    for index, device in enumerate(devices):
        end_column = column + len(DEVICE_SUBHEADERS) - 1
        color = (BLUE, TEAL, PURPLE)[index % 3]
        worksheet.merge_cells(start_row=3, start_column=column, end_row=3, end_column=end_column)
        _header_cell(worksheet.cell(3, column, device.label), color)
        for offset, label in enumerate(DEVICE_SUBHEADERS):
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
    cost_index = {(cost.record_date, (cost.device_slot, cost.device_identity)): cost for cost in costs}
    days = sorted({record.period_start for record in records})
    currency_columns = _wide_currency_columns(1, len(devices)) | {total_columns}
    for row_index, day in enumerate(days, start=5):
        row: list[object] = [day]
        daily_usage = 0.0
        daily_cost = 0.0
        for device in devices:
            record = record_index.get((day, device.key))
            cost = cost_index.get((day, device.key))
            if record is None:
                row.extend((0.0,) * len(DEVICE_SUBHEADERS))
                continue
            for field, _label in CATEGORY_FIELDS:
                row.extend((_combined(record, field), getattr(cost, field, 0.0) if cost else 0.0))
            usage_total = _usage_total(record)
            net_cost = _combined(record, "net_cost")
            row.extend((_combined(record, "scan"), usage_total, net_cost))
            daily_usage += usage_total
            daily_cost += net_cost
        row.extend((daily_usage, daily_cost))
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


def _review_status(records: tuple[MonthlyUsage, ...]) -> str:
    return "ตรวจสอบ" if any(record.held_days or record.incomplete_days for record in records) else "พร้อมใช้"


def _period_text(period: tuple[str, str] | None) -> str:
    if period is None:
        return "ข้อมูลทั้งหมด"
    start, end = (date.fromisoformat(value) for value in period)
    return f"{start:%d/%m/%Y} – {end:%d/%m/%Y}"


def _sheet_title(worksheet, title: str, subtitle: str, columns: int) -> None:
    worksheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
    title_cell = worksheet.cell(1, 1, title)
    title_cell.font = Font(name="Aptos Display", size=16, bold=True, color=WHITE)
    title_cell.fill = PatternFill("solid", fgColor=NAVY)
    title_cell.alignment = Alignment(horizontal="left", vertical="center")
    worksheet.row_dimensions[1].height = 28
    worksheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=columns)
    subtitle_cell = worksheet.cell(2, 1, subtitle)
    subtitle_cell.font = Font(name="Aptos", size=10, color=MUTED)
    subtitle_cell.fill = PatternFill("solid", fgColor=PALE)
    subtitle_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    worksheet.row_dimensions[2].height = 30


def _header_cell(cell, color: str) -> None:
    cell.fill = PatternFill("solid", fgColor=color)
    cell.font = Font(name="Aptos", size=10, bold=True, color=WHITE)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_row(worksheet, row_index: int, row: list[object], *, currency_columns: set[int]) -> None:
    for column, value in enumerate(row, start=1):
        cell = worksheet.cell(row_index, column, value)
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
    cell = worksheet.cell(row, 1, message)
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


def _machine_currency_columns() -> set[int]:
    return {3, 5, 7, 9, 12}


def _wide_currency_columns(fixed_columns: int, device_count: int) -> set[int]:
    columns: set[int] = set()
    for device_index in range(device_count):
        start = fixed_columns + 1 + device_index * len(DEVICE_SUBHEADERS)
        columns.update({start + 1, start + 3, start + 5, start + 7, start + 10})
    return columns
