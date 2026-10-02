"""Capture performance loading/retry screens on a disposable synthetic DB."""
from pathlib import Path
from threading import Event
from time import monotonic
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT/'source/tests')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'
def guard(event, values):
    if event in ('socket.connect', 'socket.sendto', 'socket.bind', 'subprocess.Popen', 'os.system'):
        raise PermissionError('Synthetic capture forbids external operations')
sys.addaudithook(guard)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from qt_render_environment import configure_offscreen_fonts
import database
from config import build_qss
from i18n import set_language, apply_language
from ui_consistency import install_button_system
from ui.archive_settings import ArchiveSettingsPanel
from pages import PageOverview, PageManual
from test_report_detail_archive import fixture

def wait(predicate):
    until = monotonic()+15
    while not predicate() and monotonic()<until:
        QTest.qWait(10)
    assert predicate()

def main():
    app = QApplication([])
    configure_offscreen_fonts(app)
    install_button_system(app)
    app.setStyleSheet(build_qss())
    target = ROOT/'qa/v5.2.12/issue-19/screens'
    target.mkdir(parents=True, exist_ok=True)
    def capture(widget, name):
        apply_language(widget)
        app.processEvents()
        assert widget.grab().save(str(target/name))
    previous = database.get_db_path()
    with tempfile.TemporaryDirectory(prefix='komi-perf-capture-') as folder:
        database.set_db_path(Path(folder)/'fixture.db')
        database.init_db()
        fixture()
        for language in ('th', 'en'):
            set_language(language)
            panel = ArchiveSettingsPanel()
            panel.resize(980, 350)
            gate = Event()
            original = panel.archive.stats
            panel._default_archive = False
            panel.archive.stats = lambda **kw: (gate.wait(10), original(**kw))[1]
            panel.show()
            capture(panel, f'archive-loading-{language}.png')
            gate.set()
            wait(lambda: not panel.metadata_reader.busy)
            capture(panel, f'archive-ready-{language}.png')
            if language == 'th':
                assert panel.grab().save(str(ROOT/'docs/customer-guide/assets-v5.2.12-source/archive-settings.png'))
            panel._metadata_failed('Synthetic read failure')
            capture(panel, f'archive-error-{language}.png')
            panel.metadata_reader.shutdown()
            panel.close()
            panel.deleteLater()
            page = PageOverview(lambda: [])
            page.resize(1180, 900)
            page.show()
            page._summary_failed('Synthetic read failure')
            capture(page, f'overview-retry-{language}.png')
            page.summary_reader.shutdown()
            page.close()
            page.deleteLater()
            manual = PageManual()
            manual.resize(1180, 900)
            manual.show()
            capture(manual, f'manual-{language}.png')
            manual.close()
            manual.deleteLater()
        database.set_db_path(previous)
    print(target)

if __name__ == '__main__':
    main()
