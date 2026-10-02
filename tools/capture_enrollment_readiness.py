"""Capture real Qt enrollment/accounting controls with synthetic data only."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'),str(ROOT/'source/tests')]
# Installs the capture guard: no network, child processes, or shell calls.
import capture_network_recovery  # noqa: F401 — installs capture safety guards
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QDate
from PyQt6.QtTest import QTest
from time import monotonic
import database
from config import build_qss
from qt_render_environment import configure_offscreen_fonts
from ui_consistency import install_button_system
from komi_snmp_profiler.credential_store import SessionCredentialStore
from services import device_config
from test_shared_billing import setup
from ui.peer_enrollment_approval import EnrollmentApprovalDialog
from ui.peer_reinstallation import PeerReinstallationDialog
from ui.shared_billing import SharedBillingDialog


def main():
    app = QApplication([])
    configure_offscreen_fonts(app)
    install_button_system(app)
    app.setStyleSheet(build_qss())
    previous = database.get_db_path()
    original_store = device_config.platform_credential_store
    vault = SessionCredentialStore()
    device_config.platform_credential_store = lambda:vault
    target = ROOT/'docs/customer-guide/assets-v5.2.12-source'
    with tempfile.TemporaryDirectory(prefix='komi-readiness-capture-') as folder:
        try:
            database.set_db_path(Path(folder)/'synthetic.db')
            database.init_db()
            service, _ = setup()
            dialogs = [EnrollmentApprovalDialog(),PeerReinstallationDialog(),SharedBillingDialog(service=service)]
            billing = dialogs[-1]
            billing.start.setDate(QDate(2026,9,18))
            billing.end.setDate(QDate(2026,9,21))
            billing.reason.setText('ตรวจหลักฐานจำลองก่อนลงบัญชี')
            billing.prepare()
            deadline = monotonic()+10
            while billing.future is not None and monotonic()<deadline:
                QTest.qWait(10)
            assert billing.review and billing.review['ready']
            for name,dialog in zip(('enrollment-approval','clean-reinstallation','shared-accounting'),dialogs):
                dialog.show()
                QTest.qWait(100)
                assert dialog.grab().save(str(target/f'{name}.png'))
                dialog.close()
                if hasattr(dialog, "pool"):
                    dialog.pool.shutdown(wait=True)
            print(target)
        finally:
            database.set_db_path(previous)
            device_config.platform_credential_store = original_store


if __name__ == '__main__':
    main()
