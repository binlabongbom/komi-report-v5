"""Read and export a selected period entirely outside the Qt event thread."""
from concurrent.futures import CancelledError
from datetime import datetime

from database import report_read_database
from services.daily_cache import DailyCacheStore
from services.monthly_history import load_usage_history
from services.raw_counter_history import load_raw_counter_history
from services.report_scope import report_slots
from services.subject_history import SubjectDailyCacheStore, load_subject_history


class EmptyReportError(ValueError):
    pass


def export_report_selection(target, start, end, *, database_path, devices=(), monthly_records=(),
                            last_sync_at=None, include_waste_adjustment=True, cancelled, progress):
    def step(percent, message):
        if cancelled.is_set():
            raise CancelledError()
        progress(percent, message)

    if start > end:
        raise ValueError('วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด')
    # Lazy import keeps openpyxl initialization off the GUI thread, too.
    from services.report_excel_export import CloudReportsExportData, export_cloud_reports_xlsx
    with report_read_database(database_path):
        step(5, 'กำลังอ่านยอดรายเครื่อง…')
        slots = report_slots()
        daily = tuple(row for row in load_usage_history(slots, granularity='daily', cache=DailyCacheStore())
                      if row.period_start <= end and row.period_end >= start)
        if not daily:
            raise EmptyReportError('ไม่มีข้อมูลรายงานในช่วงวันที่เลือก กรุณาเลือกช่วงเวลาใหม่')
        step(20, 'กำลังอ่านข้อมูลผู้ใช้…')
        subjects = tuple(load_subject_history(slots, cache=SubjectDailyCacheStore(), period_start=start, period_end=end))
        step(35, 'กำลังอ่านรายละเอียดมิเตอร์…')
        raw = tuple(load_raw_counter_history(slots, period_start=start, period_end=end))
        step(40, 'กำลังเตรียมไฟล์ Excel…')
        report = CloudReportsExportData(daily, daily, daily, monthly_records, subjects, devices,
            (start.isoformat(), end.isoformat()), last_sync_at, datetime.now().astimezone(),
            include_waste_adjustment=include_waste_adjustment, raw_counter_records=raw)
        return export_cloud_reports_xlsx(target, report, cancelled=cancelled,
            progress=lambda percent, message: step(40 + percent * 60 // 100, message))
