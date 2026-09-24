"""Open source Reports against a temporary SQLite snapshot of the local app DB."""

import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))
os.environ.pop('QT_QPA_PLATFORM', None)
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'
STATUS = ROOT / 'outputs' / 'issue-40-preview' / 'snapshot-status.txt'
STATUS.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    import database
    from i18n import set_language
    from ui_consistency import install_button_system

    live_path = Path(database.get_db_path())
    if not live_path.is_file():
        raise FileNotFoundError(live_path)
    with tempfile.TemporaryDirectory(prefix='komi-report-preview-') as temp_dir:
        snapshot_path = Path(temp_dir) / 'report-snapshot.db'
        with sqlite3.connect(f'file:{live_path.as_posix()}?mode=ro', uri=True) as source:
            with sqlite3.connect(snapshot_path) as target:
                source.backup(target)
        database.set_db_path(snapshot_path)

        app = QApplication(sys.argv)
        install_button_system(app)
        set_language('th')
        from v5_pages import PageHistoryV5

        window = PageHistoryV5(staged=True)
        window.setWindowTitle('KOMI Reports - Source Preview (สำเนาข้อมูลจริง · Preview 12 เดือน / Export 5 ปี)')
        app.aboutToQuit.connect(window.shutdown_report_loading)
        window.resize(1280, 800)
        window.show()
        window.on_reports_opened()
        STATUS.write_text(f'opening pid={os.getpid()} snapshot={snapshot_path}\n', encoding='utf-8')

        def record_load() -> None:
            if window.report_center.has_data:
                QTimer.singleShot(1200, lambda: window.grab().save(
                    str(STATUS.parent / 'snapshot-overview.png')))
                STATUS.write_text(f'ready pid={os.getpid()} period={window.report_center.current_period()}\n',
                                  encoding='utf-8')
            else:
                QTimer.singleShot(500, record_load)

        QTimer.singleShot(500, record_load)
        return app.exec()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        STATUS.write_text(traceback.format_exc(), encoding='utf-8')
        raise
