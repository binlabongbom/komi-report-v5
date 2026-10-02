"""Render the five real V5.2 Setup Wizard steps with synthetic offline data.

This helper must never probe LAN printers or call Registration/Production.  It
exists only to create repeatable customer-guide screenshots from the real Qt
widgets.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtWidgets import QApplication

import database
from i18n import THAI, set_language
from komi_snmp_profiler.models import MeterReading, WebAuthState, WebCounterValue
from qt_render_environment import configure_offscreen_fonts
from services.secondary_setup import SecondaryPeerCandidate
from services.setup_connectivity import SetupConnectivityCheck, SetupConnectivityReport
from ui.setup.workers import device_test_key
from v5_pages import DeviceTestResult, SetupWizardV5

OUTPUT_DIR = Path(os.environ.get("KOMI_WIZARD_QA_DIR", "/tmp/komi-v52-wizard-guide"))


def _block_network() -> None:
    def denied(*_args, **_kwargs):
        raise AssertionError("Wizard guide renderer must not access a network")

    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def _capture(app: QApplication, wizard: SetupWizardV5, name: str) -> None:
    app.processEvents()
    image = OUTPUT_DIR / name
    if not wizard.grab().save(str(image), "PNG"):
        raise RuntimeError(f"Unable to save {image}")
    print(image)


def _add_device(
    wizard: SetupWizardV5,
    *,
    name: str,
    host: str,
    model: str,
    serial: str,
    total: int,
) -> None:
    wizard._upsert_discovered(
        {
            "name": name,
            "host": host,
            "model": model,
            "serial": serial,
            "result": {
                "online": True,
                "web_ok": True,
                "model": model,
                "serial": serial,
                "total": total,
                "meter_reading": MeterReading.create(host, [
                    WebCounterValue("counter.total.total", "Total", total, "Total", "Guide.Total"),
                    WebCounterValue("counter.print.total", "Print", total, "Print", "Guide.Print.Total"),
                    WebCounterValue("counter.print.full_color_total", "Print Color", total, "Print", "Guide.Print.Color"),
                ], "web_connection_admin_read_only", WebAuthState.ADMIN),
            },
        },
        select=True,
    )
    device = next(device for device in wizard._configs() if device.host == host)
    entry = next(entry for entry in wizard.discovered_devices if entry["host"] == host)
    wizard._test_result(DeviceTestResult(
        generation=wizard._test_generation, host=host, slot=device.slot,
        payload=entry["result"], connection_key=device_test_key(device),
    ))


def main() -> int:
    _block_network()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    configure_offscreen_fonts(app)
    set_language(THAI)

    with tempfile.TemporaryDirectory(prefix="komi-v52-wizard-guide-") as temp_dir:
        original_path = database.get_db_path()
        try:
            database.set_db_path(Path(temp_dir) / "KOMI_Report_V5_2_Guide.db")
            database.init_db()
            database.set_cfg("company_name", "บริษัท ตัวอย่าง จำกัด")
            database.set_cfg("client_first_started_at", "2026-08-26")

            wizard = SetupWizardV5(legacy_source_paths=[])
            wizard.resize(1120, 720)
            wizard.show()
            guide_path = "Documents/KOMI Report/KOMI_Report_V5_2.db"
            wizard.database_path_input.setText(guide_path)
            wizard.database_path_input.setToolTip(guide_path)
            _capture(app, wizard, "01-setup-company.png")

            problem = wizard._show_setup_connectivity_problem(
                SetupConnectivityReport(
                    started_at="2026-09-17T10:00:00+07:00",
                    base_url="https://www.dmskm.com",
                    checks=(
                        SetupConnectivityCheck(
                            name="Status API",
                            target="https://www.dmskm.com/api/v1/installations/status",
                            ok=False,
                            detail="HTTP 503 | Host unavailable",
                            support_code="host_unavailable",
                            duration_ms=6000,
                        ),
                    ),
                )
            )
            _capture(app, problem, "01c-setup-connectivity-problem.png")
            problem.close()

            wizard._secondary_discovery_finished(
                [
                    SecondaryPeerCandidate(
                        base_url="https://192.0.2.20:3000",
                        company_name="บริษัท สำนักงานใหญ่ จำกัด",
                        printer_count=2,
                        version="5.2.11",
                        certificate_sha256="a" * 64,
                    )
                ],
                "",
            )
            _capture(app, wizard, "01b-setup-company-primary-found.png")

            _add_device(
                wizard,
                name="แผนกบัญชี",
                host="192.0.2.10",
                model="KONICA MINOLTA bizhub C450i",
                serial="GUIDE-C450I-001",
                total=125_000,
            )
            _add_device(
                wizard,
                name="ฝ่ายขาย",
                host="192.0.2.11",
                model="KONICA MINOLTA AccurioPress C7090",
                serial="GUIDE-C7090-002",
                total=250_000,
            )
            wizard._next()
            _capture(app, wizard, "02-setup-printers.png")

            wizard._next()
            _capture(app, wizard, "03-setup-initial-meter.png")
            for index in range(wizard.meter_step.device_combo.count()):
                wizard.meter_step.device_combo.setCurrentIndex(index)
                wizard.meter_step.confirmation.setChecked(True)
            wizard._next()
            wizard.shared_price_row["a4_color"].setValue(2.00)
            wizard.shared_price_row["a4_bw"].setValue(0.20)
            wizard.shared_price_row["a3_color"].setValue(4.00)
            wizard.shared_price_row["a3_bw"].setValue(0.40)
            _capture(app, wizard, "04-setup-pricing.png")

            wizard._next()
            _capture(app, wizard, "05-setup-review.png")
            wizard.close()
            app.processEvents()
        finally:
            database.set_db_path(original_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
