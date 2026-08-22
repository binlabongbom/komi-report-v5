from datetime import UTC, date, datetime

from openpyxl import load_workbook

from services.device_config import DeviceConfig
from services.monthly_history import MonthlyUsage
from services.report_excel_export import (
    CloudReportsExportData,
    DailyCategoryCost,
    export_cloud_reports_xlsx,
)
from services.subject_history import SubjectPeriodUsage


def _usage(day: date, *, slot: int, identity: str, name: str, total: float) -> MonthlyUsage:
    return MonthlyUsage(
        device_slot=slot,
        period_start=day,
        period_end=day,
        total=total,
        a3_color=10 + slot,
        a3_bw=5 + slot,
        a4_color=50 + slot,
        a4_bw=55 + slot,
        scan=12 + slot,
        gross_cost=30 + slot,
        net_cost=29.4 + slot,
        day_count=1,
        incomplete_days=0,
        device_identity=identity,
        device_name_snapshot=name,
        device_serial_snapshot=identity.removeprefix("serial:"),
    )


def _subject(
    day: date,
    *,
    slot: int,
    identity: str,
    name: str,
    usage: float,
) -> SubjectPeriodUsage:
    return SubjectPeriodUsage(
        device_slot=slot,
        period_start=day,
        period_end=day,
        subject_type="user",
        subject_id="u-1",
        subject_name="alice",
        latest_total=500,
        period_usage=usage,
        reset_count=0,
        missing_baseline_days=0,
        incomplete_days=0,
        sample_count=2,
        latest_at="2026-08-06T09:00:00+07:00",
        warnings=(),
        device_identity=identity,
        device_name_snapshot=name,
        device_serial_snapshot=identity.removeprefix("serial:"),
    )


def test_cloud_reports_export_writes_three_wide_safe_views(tmp_path):
    day = date(2026, 8, 6)
    first = _usage(day, slot=0, identity="serial:SER-A", name="MFP 1", total=120)
    second = _usage(day, slot=1, identity="serial:SER-B", name="MFP 2", total=80)
    output = export_cloud_reports_xlsx(
        tmp_path / "reports",
        CloudReportsExportData(
            selected_records=(first, second),
            selected_daily_records=(first, second),
            usage_daily_records=(first, second),
            monthly_records=(first, second),
            subjects=(
                _subject(day, slot=0, identity="serial:SER-A", name="MFP 1", usage=75),
                _subject(day, slot=1, identity="serial:SER-B", name="MFP 2", usage=25),
            ),
            devices=(
                DeviceConfig(
                    0,
                    "MFP 1",
                    "192.0.2.10",
                    username="administrator",
                    password="do-not-export-this",
                    serial="SER-A",
                ),
                DeviceConfig(
                    1,
                    "MFP 2",
                    "192.0.2.11",
                    username="administrator",
                    password="also-private",
                    serial="SER-B",
                ),
            ),
            period=("2026-08-01", "2026-08-31"),
            last_sync_at="2026-08-06T08:50:00+07:00",
            generated_at=datetime(2026, 8, 6, 8, 55, tzinfo=UTC),
            category_costs=(
                DailyCategoryCost(0, "serial:SER-A", day, 10, 5, 8, 6.4),
                DailyCategoryCost(1, "serial:SER-B", day, 11, 5, 8, 6.4),
            ),
        ),
    )

    assert output.name == "reports.xlsx"
    workbook = load_workbook(output, data_only=False)
    assert workbook.sheetnames == [
        "การใช้งานรายเครื่อง",
        "มุมมองผู้ใช้",
        "มุมมองรายวัน",
    ]

    machines = workbook["การใช้งานรายเครื่อง"]
    assert machines["A5"].value == "MFP 1"
    assert machines["B5"].value == 50
    assert machines["C5"].value == 10
    assert machines["L5"].value == 29.4
    assert machines.freeze_panes == "B5"

    users = workbook["มุมมองผู้ใช้"]
    assert users["A5"].value == "alice"
    assert users["M5"].value == 75
    assert users["X5"].value == 25
    assert users["Z5"].value == 100
    assert users["D5"].value is None
    assert users.freeze_panes == "D5"

    daily = workbook["มุมมองรายวัน"]
    assert daily["A5"].value.date() == day
    assert daily.max_row == 5
    assert daily["B5"].value == 50
    assert daily["M5"].value == 51
    assert daily["X5"].value == 200
    assert daily.freeze_panes == "B5"

    all_text = "\n".join(
        str(cell.value)
        for worksheet in workbook.worksheets
        for row in worksheet.iter_rows()
        for cell in row
        if cell.value is not None
    )
    assert "do-not-export-this" not in all_text
    assert "also-private" not in all_text
    assert "192.0.2.10" not in all_text
    assert "SER-A" not in all_text


def test_daily_view_has_one_row_per_date_even_with_multiple_printers(tmp_path):
    first_day = date(2026, 8, 6)
    second_day = date(2026, 8, 7)
    records = (
        _usage(first_day, slot=0, identity="serial:A", name="MFP 1", total=10),
        _usage(first_day, slot=1, identity="serial:B", name="MFP 2", total=20),
        _usage(second_day, slot=0, identity="serial:A", name="MFP 1", total=30),
    )
    output = export_cloud_reports_xlsx(
        tmp_path / "daily.xlsx",
        CloudReportsExportData(
            selected_records=records,
            selected_daily_records=records,
            usage_daily_records=records,
            monthly_records=(),
            subjects=(),
            devices=(),
            period=(first_day.isoformat(), second_day.isoformat()),
            last_sync_at=None,
            generated_at=datetime.now(UTC),
        ),
    )
    daily = load_workbook(output)["มุมมองรายวัน"]
    assert daily.max_row == 6
    assert [daily.cell(row, 1).value.date() for row in (5, 6)] == [first_day, second_day]
