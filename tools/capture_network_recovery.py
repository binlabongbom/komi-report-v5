"""Capture real recovery UI with synthetic state and all network I/O blocked."""
from pathlib import Path
import os
import sys
import tempfile
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT/'source/tests')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'

def guard(event, values):
    if event in ('socket.connect', 'socket.sendto', 'socket.bind', 'subprocess.Popen', 'os.system'):
        raise PermissionError('Synthetic capture forbids external operations')
sys.addaudithook(guard)

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
import database
from config import build_qss
from i18n import set_language
from qt_render_environment import configure_offscreen_fonts
from ui_consistency import install_button_system
from ui.network_activity import NetworkActivityPanel


class SyntheticRuntime(QObject):
    changed = pyqtSignal()
    activity_changed = pyqtSignal()
    device_updated = pyqtSignal(int)
    state, error, _future = 'unavailable', 'identity_missing', None
    def __init__(self):
        super().__init__()
        self.peer_history = self.peer_network_runtime = self
    def snapshot(self):
        return []
    def active_slots(self):
        return ()


def main():
    app = QApplication([])
    configure_offscreen_fonts(app)
    install_button_system(app)
    app.setStyleSheet(build_qss())
    set_language('th')
    previous = database.get_db_path()
    with tempfile.TemporaryDirectory(prefix='komi-recovery-capture-') as folder:
        try:
            database.set_db_path(Path(folder)/'synthetic.db')
            database.init_db()
            panel = NetworkActivityPanel()
            panel.bind_runtime(SyntheticRuntime())
            panel.resize(1000, 480)
            panel.show()
            deadline = monotonic()+10
            while 'ไม่พบกุญแจสมาชิกเดิม' not in panel.summary.text() and monotonic() < deadline:
                QTest.qWait(10)
            assert 'ไม่พบกุญแจสมาชิกเดิม' in panel.summary.text()
            target = ROOT/'docs/customer-guide/assets-v5.2.12-source/network-recovery.png'
            assert panel.grab().save(str(target))
            panel.close()
            panel._pool.shutdown(wait=True)
            print(target)
        finally:
            database.set_db_path(previous)


if __name__ == '__main__':
    main()
