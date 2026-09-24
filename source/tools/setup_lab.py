#!/usr/bin/env python3
"""Run the real SetupWizardV5 against a protocol-level virtual printer."""
# ruff: noqa: E402 -- the shared source path must be installed before app imports

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PyQt6.QtWidgets import QApplication, QMessageBox

import database
from config import DEFAULT_FONT_NAME, DEFAULT_FONT_SIZE
from tools.virtual_printer import VirtualPrinterService
from ui_consistency import install_button_system
from ui.numeric_inputs import configure_numeric_locale
from services.application_identity import load_application_icon
from ui.setup.wizard import SetupWizardV5


@dataclass(frozen=True)
class LabNetwork:
    bind_host: str
    discovery_hosts: list[str] | None
    snmp_port: int
    web_port: int


def lab_network(platform: str = sys.platform) -> LabNetwork:
    if platform == "win32":
        return LabNetwork("0.0.0.0", None, 161, 443)
    return LabNetwork("127.0.0.1", ["127.0.0.1"], 1161, 8443)


def main() -> int:
    configure_numeric_locale()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(load_application_icon())
    install_button_system(app)
    app.setFont(app.font().__class__(DEFAULT_FONT_NAME, DEFAULT_FONT_SIZE))
    with tempfile.TemporaryDirectory(prefix="komi-setup-lab-") as temp_dir:
        original_db = database.get_db_path()
        database.set_db_path(Path(temp_dir) / "wizard-lab.sqlite3")
        database.init_db()
        network = lab_network()
        simulator = VirtualPrinterService(
            bind_host=network.bind_host,
            snmp_port=network.snmp_port,
            https_port=network.web_port,
        )
        try:
            simulator.start()
        except OSError as exc:
            QMessageBox.critical(
                None,
                "เปิด Virtual Printer ไม่สำเร็จ",
                "Setup Lab เปิดพอร์ต SNMP/Web สำหรับระบบนี้ไม่สำเร็จ\n\n"
                f"{exc}",
            )
            database.set_db_path(original_db)
            return 2
        try:
            wizard = SetupWizardV5(
                lab_mode=True,
                lab_hosts=network.discovery_hosts,
                lab_snmp_port=network.snmp_port,
                lab_web_port=network.web_port,
            )
            wizard.show()
            wizard.raise_()
            wizard.activateWindow()
            return 0 if wizard.exec() else 1
        finally:
            simulator.stop()
            database.set_db_path(original_db)


if __name__ == "__main__":
    raise SystemExit(main())
