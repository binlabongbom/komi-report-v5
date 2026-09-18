"""Capture changed source screens using a temporary, synthetic database only."""
from pathlib import Path
import os
import sys
import tempfile
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT/'source/tests')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['KOMI_DISCOVERY_DISABLED'] = '1'

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from qt_render_environment import configure_offscreen_fonts
import database
from test_billing_web_amendment import setup, confirm
from test_network_activity import Runtime, row
from services.peer_billing_amendments import PeerBillingAmendments
from services.web_observations import WebObservationStore
from ui.billing_web_amendment import BillingWebAmendmentDialog
from ui.network_activity import NetworkActivityPanel


def wait_for(predicate):
    deadline = monotonic() + 15
    while not predicate() and monotonic() < deadline:
        QTest.qWait(20)
    if not predicate():
        raise RuntimeError('Preview did not become ready')


def capture():
    app = QApplication.instance() or QApplication([])
    configure_offscreen_fonts(app)
    target = ROOT/'docs/customer-guide/assets-v5.2.12-source'
    previous = database.get_db_path()
    with tempfile.TemporaryDirectory(prefix='komi-guide-synthetic-') as folder:
        database.set_db_path(Path(folder)/'synthetic.db')
        database.init_db()
        try:
            service, scope, _ = setup()
            dialog = BillingWebAmendmentDialog(scope, service=service)
            dialog.show()
            dialog.load()
            wait_for(lambda: dialog.future is None and dialog.preview is not None)
            dialog.reason.setText('ตรวจหลักฐานช่วงขาดการอ่าน · ตัวอย่างข้อมูลจำลอง')
            app.processEvents()
            assert dialog.grab().save(str(target/'web-billing-amendment.png'))
            dialog.close()
            dialog.pool.shutdown(wait=True)
            confirm(service, scope, service.preview(*scope))
            transfer = PeerBillingAmendments(authorize=lambda *a: True)
            amendment = transfer.pending('PC-A')
            transfer.acknowledge('PC-A', {'amendment_id': amendment['id'], 'committed': True})
            store = WebObservationStore()
            store.acknowledge('PC-A', [e['id'] for e in store.pending('PC-A')])
            rows = [row('PC-A', 'complete'), row('PC-B', 'pending')]
            rows[0].update(error='', last_success='2026-09-18T10:15:00+07:00')
            runtime = Runtime(rows)
            panel = NetworkActivityPanel()
            panel.resize(1120, 360)
            panel.bind_runtime(runtime)
            panel.show()
            wait_for(lambda: panel.table.rowCount() == 2)
            app.processEvents()
            assert panel.grab().save(str(target/'network-activity.png'))
            panel.close()
            panel._pool.shutdown(wait=True)
            from pages import PageManual
            evidence = ROOT/'outputs/manual-qa/peer-sync'
            evidence.mkdir(parents=True, exist_ok=True)
            manual = PageManual()
            manual.resize(1120, 780)
            manual.show()
            app.processEvents()
            assert manual.grab().save(str(evidence/'in-app-manual.png'))
            manual._scroll_to_manual_section(3)
            app.processEvents()
            assert manual.grab().save(str(evidence/'in-app-settings-guide.png'))
            manual.close()
        finally:
            database.set_db_path(previous)
    print(target)


if __name__ == '__main__':
    capture()
