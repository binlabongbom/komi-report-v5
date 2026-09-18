"""Capture the actual Reports screen with synthetic data, without LAN access."""
from pathlib import Path
import os
import sys
import tempfile
from functools import partial
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT/'source/tests')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtTest import QTest
from qt_render_environment import configure_offscreen_fonts
from ui.cloud_reports import CloudReportsWidget
from excel_export_fixture import report_for
from services.report_excel_export import export_cloud_reports_xlsx
from ui.report_export import ReportExportController
import database

app = QApplication([])
configure_offscreen_fonts(app)
previous = database.get_db_path()
with tempfile.TemporaryDirectory(prefix='komi-excel-capture-') as folder:
    try:
        database.set_db_path(Path(folder)/'qa.db')
        database.init_db()
        report = report_for(users=3, days=2)
        widget = CloudReportsWidget()
        widget.resize(1140, 780)
        widget.set_periods((report.period,), report.period)
        widget.set_data(records=report.selected_records, daily_records=report.selected_daily_records,
            usage_daily_records=report.usage_daily_records, monthly_records=report.monthly_records,
            subjects=report.subjects, devices=report.devices, period=report.period,
            last_sync_at=None, raw_counter_records=report.raw_counter_records)
        widget.show()
        QTest.qWait(100)
        assert not widget.findChildren(QPushButton, 'cloud_period_export')
        target = ROOT/'docs/customer-guide/assets-v5.2.12-source/reports-excel.png'
        assert widget.grab().save(str(target))
        controller = ReportExportController(widget)
        results, errors = [], []
        controller.succeeded.connect(results.append)
        controller.failed.connect(errors.append)
        try:
            controller.start(partial(export_cloud_reports_xlsx, Path(folder)/'progress.xlsx', report_for()))
            deadline = monotonic() + 45
            while controller.busy and controller.dialog.progress_bar.value() < 30 and monotonic() < deadline:
                QTest.qWait(10)
            assert controller.busy and controller.dialog.progress_bar.value() >= 30, errors
            progress_target = target.with_name('reports-excel-progress.png')
            assert controller.dialog.grab().save(str(progress_target))
            while controller.busy and monotonic() < deadline:
                QTest.qWait(10)
            assert results and not errors and not controller.busy, errors
            print(progress_target)
        finally:
            controller.shutdown()
        widget.close()
        app.processEvents()
        print(target)
    finally:
        database.set_db_path(previous)
