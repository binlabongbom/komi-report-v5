"""Capture the actual Reports screen with synthetic data, without LAN access."""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT/'source/tests')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtTest import QTest
from qt_render_environment import configure_offscreen_fonts
from ui.cloud_reports import CloudReportsWidget
from excel_export_fixture import report_for
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
        widget.close()
        app.processEvents()
        print(target)
    finally:
        database.set_db_path(previous)
