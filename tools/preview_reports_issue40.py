"""Open the Reports source UI with synthetic data, without touching the installed app."""

import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'source'), str(ROOT / 'source/tests')]
os.environ.pop('QT_QPA_PLATFORM', None)
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'
PREVIEW_DIR = ROOT / 'outputs' / 'issue-40-preview'
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from excel_export_fixture import report_for
    from i18n import set_language
    from ui.cloud_reports import CloudReportsWidget
    from ui_consistency import install_button_system

    app = QApplication(sys.argv)
    install_button_system(app)
    set_language('th')
    report = report_for(users=12, days=4, printers=3)
    window = CloudReportsWidget()
    window.setWindowTitle('KOMI Reports - Source Preview - Issue #40 (ข้อมูลจำลอง)')
    window.resize(1280, 800)
    window.set_periods((report.period,), report.period)
    window.set_data(
        records=report.selected_records,
        daily_records=report.selected_daily_records,
        usage_daily_records=report.usage_daily_records,
        monthly_records=report.selected_records,
        subjects=report.subjects,
        devices=report.devices,
        period=report.period,
        last_sync_at='2026-07-04T17:00:00+07:00',
        raw_counter_records=report.raw_counter_records,
    )
    window.show()
    (PREVIEW_DIR / 'pid.txt').write_text(str(os.getpid()), encoding='utf-8')
    QTimer.singleShot(1200, lambda: window.grab().save(str(PREVIEW_DIR / 'overview.png')))
    return app.exec()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        (PREVIEW_DIR / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        raise
