"""Read and export a selected period entirely outside the Qt event thread."""
from concurrent.futures import CancelledError
from datetime import datetime

from database import report_read_database, report_read_components
from services.daily_cache import DailyCacheStore
from services.monthly_history import load_usage_history
from services.raw_counter_history import load_raw_counter_history
from services.report_scope import report_slots
from services.subject_history import SubjectDailyCacheStore, load_subject_history
from services.report_export_options import ALL_REPORT_SECTIONS, validate_sections
from services.report_period_policy import EXPORT_YEARS, validate_report_period


class EmptyReportError(ValueError):
    diagnostic_code = 'report_empty'


def export_report_selection(target, start, end, *, database_path, devices=(), monthly_records=(),
                            last_sync_at=None, include_waste_adjustment=True,
                            sections=ALL_REPORT_SECTIONS, cancelled, progress):
    def step(percent, message):
        if cancelled.is_set():
            raise CancelledError()
        progress(percent, message)

    validate_report_period(start, end, years=EXPORT_YEARS)
    sections = validate_sections(sections)
    # Lazy import keeps openpyxl initialization off the GUI thread, too.
    from services.report_excel_export import CloudReportsExportData, export_cloud_reports_xlsx
    with report_read_database(database_path, cancelled=cancelled):
        step(5, 'กำลังอ่านยอดรายเครื่อง…')
        slots = report_slots()
        needs_daily = any(key in sections for key in ('printers', 'users', 'daily'))
        daily = tuple(row for row in load_usage_history(slots, granularity='daily', cache=DailyCacheStore())
                      if row.period_start <= end and row.period_end >= start) if needs_daily else ()
        step(20, 'กำลังอ่านข้อมูลผู้ใช้…')
        subjects = tuple(load_subject_history(slots, cache=SubjectDailyCacheStore(), period_start=start, period_end=end)) if 'users' in sections else ()
        # The materialized report rows now own the required values. Keeping the
        # large intermediate counter projections alive alongside Raw and Excel
        # cells makes Python's cyclic-GC pauses block Qt, even in a worker.
        report_read_components().clear()
        step(35, 'กำลังอ่านรายละเอียดมิเตอร์…')
        needs_raw = 'users' in sections or any(key.startswith('legacy_') for key in sections)
        raw = tuple(load_raw_counter_history(slots, period_start=start, period_end=end)) if needs_raw else ()
        report_read_components().clear()
        if not (daily or subjects or raw):
            raise EmptyReportError(f'ไม่มีข้อมูลสำหรับรายงานที่เลือกในช่วง {start:%d/%m/%Y}–{end:%d/%m/%Y}')
        step(40, 'กำลังเตรียมไฟล์ Excel…')
        report = CloudReportsExportData(daily, daily, daily, monthly_records, subjects, devices,
            (start.isoformat(), end.isoformat()), last_sync_at, datetime.now().astimezone(),
            include_waste_adjustment=include_waste_adjustment, raw_counter_records=raw, sections=sections)
        return export_cloud_reports_xlsx(target, report, cancelled=cancelled,
            progress=lambda percent, message: step(40 + percent * 60 // 100, message))
