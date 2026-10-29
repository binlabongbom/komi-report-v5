import os
import secrets
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
)

import database
from komi_version import APP_VERSION
from ui.setup import wizard as setup_wizard
from ui.setup.workers import device_test_key
from komi_snmp_profiler.connectors import (
    WebConnectionCertificateError,
    WebConnectionSessionBusyError,
    WebConnectionTlsError,
)
from komi_snmp_profiler.credential_store import PUBLIC_FACTORY_ADMIN_PASSWORDS
from komi_snmp_profiler.models import MeterReading, WebAuthState, WebCounterValue
from runtime_config import load_runtime_settings
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PricingRepository
from services.registration_data_notice import REGISTRATION_NOTICE_VERSION
from services.secondary_setup import SecondaryPeerCandidate
from services.setup_connectivity import SetupConnectivityCheck, SetupConnectivityReport
from services.sync_schedule import default_schedule_windows, dump_schedule_windows
from services.v5_2_outbox import V52OutboxRepository
from services.v5_2_runtime_state import V52RuntimeStateRepository
from v5_pages import (
    DeviceTestResult,
    DeviceTestWorker,
    NetworkDiscoveryWorker,
    SetupWizardV5,
)


class ImmediateRegisteredRuntime:
    def __init__(self) -> None:
        self.status = "waiting_for_internet"

    def set_mode(self, _mode: str) -> None:
        pass

    def configuration_changed(self) -> None:
        self.status = "registered"

    def snapshot(self) -> dict[str, object]:
        return {"status": self.status, "support_code": ""}


def _wizard_database(tmp_path):
    original_path = database.get_db_path()
    database.set_db_path(tmp_path / "wizard.sqlite3")
    database.init_db()
    database.set_cfg("company_name", "บริษัท ทดสอบ จำกัด")
    database.set_cfg("client_first_started_at", "2026-08-20")
    return original_path


def _add_selected_device(wizard, name: str, host: str, *, total: int = 100) -> None:
    if wizard.registration_runtime is None:
        wizard.registration_runtime = ImmediateRegisteredRuntime()
    wizard._upsert_discovered(
        {
            "name": name,
            "host": host,
            "model": "bizhub C450i",
            "serial": f"SN-{host.rsplit('.', 1)[-1]}",
            "result": {
                "online": True, "web_ok": True, "model": "bizhub C450i", "total": total,
                "serial": f"SN-{host.rsplit('.', 1)[-1]}",
                "meter_reading": _meter_reading(host, total),
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
    wizard.privacy_notice_accepted.setChecked(True)


def _meter_reading(host: str, total: int = 100) -> MeterReading:
    values = {
        "counter.total.total": total,
        "counter.print.total": total,
        "counter.print.full_color_total": total,
        "counter.print.full_color_large": 0,
        "counter.print.bw_total": 0,
        "counter.print.bw_large": 0,
        "counter.copy.total": 0,
        "counter.copy.full_color_total": 0,
        "counter.copy.full_color_large": 0,
        "counter.copy.bw_total": 0,
        "counter.copy.bw_large": 0,
        "counter.scan_fax.document_read_total": 0,
    }
    return MeterReading.create(host, [
        WebCounterValue(key, key, value, key.split(".")[1], f"fixture.{key}")
        for key, value in values.items()
    ], "web_connection_admin_read_only", WebAuthState.ADMIN)


def _confirm_meter(wizard) -> None:
    """Explicitly review every new printer through the real meter controls."""
    wizard._enter_meter_step()
    step = wizard.meter_step
    for index in range(step.device_combo.count()):
        step.device_combo.setCurrentIndex(index)
        if not step.confirmation.isHidden() and step.confirmation.isEnabled():
            step.confirmation.setChecked(True)
    assert step.ready


def _visible_thai_ui_texts(wizard) -> list[str]:
    """Return untranslated visible UI copy, excluding the intentional ไทย toggle."""
    def has_thai(value: str) -> bool:
        return any("\u0e00" <= char <= "\u0e7f" for char in value)

    untranslated: list[str] = []
    for widget in wizard.findChildren((QLabel, QAbstractButton, QGroupBox)):
        if (
            widget.isVisible()
            and widget is not wizard.thai_language_button
            and has_thai(widget.text())
        ):
            untranslated.append(widget.text())
    for combo in wizard.findChildren(QComboBox):
        if combo.isVisible():
            untranslated.extend(
                combo.itemText(index)
                for index in range(combo.count())
                if has_thai(combo.itemText(index))
            )
    for table in wizard.findChildren(QTableWidget):
        if not table.isVisible():
            continue
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            if item is not None and has_thai(item.text()):
                untranslated.append(item.text())
        for row in range(table.rowCount()):
            for column in range(table.columnCount()):
                item = table.item(row, column)
                if item is not None and has_thai(item.text()):
                    untranslated.append(item.text())
    return untranslated


def test_setup_wizard_switches_between_shared_and_per_device_prices(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()

        assert wizard.shared_price_mode.isChecked()
        assert wizard.shared_price_mode.isCheckable()
        assert wizard.price_mode_group.exclusive()
        assert not wizard.shared_price_box.isHidden()
        assert wizard.per_device_price_box.isHidden()

        wizard.per_device_price_mode.setChecked(True)

        assert wizard.shared_price_box.isHidden()
        assert not wizard.per_device_price_box.isHidden()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_successful_device_test_advances_once_and_failed_test_stays_on_device_step(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])
        _add_selected_device(wizard, "TEST Printer", "192.0.2.10")
        wizard._next()
        assert wizard.stack.currentIndex() == 1

        wizard._test_finished()
        app.processEvents()

        assert wizard.stack.currentIndex() == 2
        assert wizard.step_label.text() == "3 / 5"
        wizard._test_finished()
        app.processEvents()
        assert wizard.stack.currentIndex() == 2
        wizard.close()

        failed = SetupWizardV5(legacy_source_paths=[])
        _add_selected_device(failed, "Failed Printer", "192.0.2.11")
        failed.discovered_devices[0]["result"] = {
            "online": True,
            "web_ok": False,
            "tested": True,
        }
        failed._next()
        failed._test_finished()
        app.processEvents()
        assert failed.stack.currentIndex() == 1
        failed.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_keeps_each_per_device_price_separate(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        _add_selected_device(wizard, "Sales Printer", "192.0.2.11")
        wizard.per_device_price_mode.setChecked(True)
        wizard.price_rows[0]["a4_color"].setValue(2.0)
        wizard.price_rows[1]["a4_color"].setValue(3.0)
        wizard._update_review()

        pricing_review = wizard.review_sections["pricing"].text()
        assert "DMS Printer: A4 สี <b>2.00</b>" in pricing_review
        assert "Sales Printer: A4 สี <b>3.00</b>" in pricing_review
        _confirm_meter(wizard)
        wizard._save()

        assert PricingRepository().get_prices(0, date.today()).a4_color == 2.0
        assert PricingRepository().get_prices(1, date.today()).a4_color == 3.0
        assert database.get_cfg("pricing_mode") == "per_device"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_uses_the_approved_five_step_flow(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        assert wizard.stack.count() == 5
        assert wizard.step_label.text() == "1 / 5"
        assert wizard.company_name_input.text() == "บริษัท ทดสอบ จำกัด"
        assert wizard.first_started_input.isReadOnly()
        assert wizard.first_started_input.text() == "20/08/2026"
        assert wizard.version_input.isReadOnly()
        assert wizard.version_input.text() == APP_VERSION
        assert wizard.scan_button.text() == "ค้นหาเครื่องพิมพ์อัตโนมัติ"
        assert wizard.advanced_scan_button.text() == "กำหนดช่วง IP"
        assert wizard.manual_setup_button.text() == "เพิ่ม IP ด้วยตนเอง"
        assert wizard.test_button.text() == "ตรวจสอบเครื่องที่เลือก"
        assert wizard.fallback_actions.isHidden()

        _add_selected_device(wizard, "DMS Printer", "192.0.2.10", total=2341)

        wizard._next()
        assert wizard.stack.currentIndex() == 1
        assert wizard.step_label.text() == "2 / 5"
        wizard._next()
        assert wizard.stack.currentIndex() == 2
        assert wizard.step_label.text() == "3 / 5"
        assert not wizard.next_button.isEnabled()
        _confirm_meter(wizard)
        wizard._next()
        assert wizard.stack.currentIndex() == 3
        assert wizard.step_label.text() == "4 / 5"
        wizard.shared_price_row["a4_color"].setValue(2.0)
        wizard.shared_price_row["a4_bw"].setValue(0.5)
        wizard.shared_price_row["a3_color"].setValue(4.0)
        wizard.shared_price_row["a3_bw"].setValue(1.0)
        wizard._next()
        assert wizard.stack.currentIndex() == 4
        assert wizard.step_label.text() == "5 / 5"
        assert "บริษัท ทดสอบ จำกัด" in wizard.review_sections["organization"].text()
        assert "DMS Printer" in wizard.review_sections["devices"].text()
        pricing_review = wizard.review_sections["pricing"].text()
        assert "A4 สี <b>2.00</b>" in pricing_review
        assert "A4 ขาวดำ <b>0.50</b>" in pricing_review
        assert "A3 สี <b>4.00</b>" in pricing_review
        assert "A3 ขาวดำ <b>1.00</b> บาท/หน้า" in pricing_review
        assert wizard.next_button.text() == "บันทึกและเปิดโปรแกรม"
        assert "พร้อมนำเครื่องพิมพ์เข้าระบบ" in wizard.review_ready_note.text()
        registration_review = wizard.review_sections["registration"].text()
        assert f"Version {APP_VERSION}" in registration_review
        assert "bizhub C450i × 1" in registration_review
        assert "Serial Number + รุ่นเครื่อง + สถานะเลือกใช้ + Aggregate Total Meter" in registration_review
        assert "IP, MAC, hostname, Credential, Counter รายละเอียด" in registration_review
        assert wizard.registration_status_label.text() == "รอลงทะเบียน"
        assert wizard.privacy_notice_accepted.isHidden()
        assert wizard.registration_online_mode.isHidden()
        assert wizard.registration_offline_mode.isHidden()
        assert REGISTRATION_NOTICE_VERSION in wizard.privacy_notice_status.text()
        assert wizard.choose_database_path_button.text() == "Browse"
        assert wizard.legacy_import_button.text() == "Import"
        assert wizard.first_started_input.width() < wizard.company_name_input.width()
        assert wizard.version_input.width() < wizard.company_name_input.width()
        wizard.view_privacy_notice_button.click()
        app.processEvents()
        notice_dialog = wizard._wizard_child_dialogs[-1]
        notice_copy = notice_dialog.findChild(QPlainTextEdit).toPlainText()
        assert notice_dialog.isVisible()
        assert "ข้อมูลที่ส่ง" in notice_copy
        assert "Serial Number" in notice_copy
        assert "ไม่ส่ง IP address" in notice_copy
        notice_dialog.close()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_secondary_snapshot_populates_setup_and_requires_fresh_device_verification(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        test_calls = []
        wizard._test_all = lambda: test_calls.append(True)
        candidate = SecondaryPeerCandidate(
            base_url="https://192.0.2.20:3000",
            company_name="บริษัท เครื่องหลัก จำกัด",
            printer_count=1,
            version="5.2.0",
            certificate_sha256="a" * 64,
        )
        snapshot = {
            "contract": "komi-secondary-setup/v1",
            "generated_at": "2026-08-26T10:00:00+07:00",
            "organization": {
                "company_name": "บริษัท เครื่องหลัก จำกัด",
                "first_started_at": "2026-08-01",
                "primary_installation_id": "primary-id",
            },
            "settings": {
                "pricing_mode": "shared",
                "billing_day": 25,
                "waste_paper_pct": 1.5,
                "work_start": "08:00",
                "work_end": "17:00",
                "sync_schedule_windows": dump_schedule_windows(
                    default_schedule_windows()
                ),
            },
            "devices": [
                {
                    "slot": 0,
                    "name": "แผนกบัญชี",
                    "host": "192.0.2.10",
                    "model": "KONICA MINOLTA bizhub C450i",
                    "serial": "SER-001",
                    "tls_mode": "fingerprint",
                    "tls_fingerprint": "b" * 64,
                    "prices": {
                        "a3_color": 4.0,
                        "a3_bw": 1.0,
                        "a4_color": 2.0,
                        "a4_bw": 0.2,
                    },
                }
            ],
        }

        wizard._apply_secondary_snapshot(candidate, snapshot)
        app.processEvents()

        assert wizard.company_name_input.text() == "บริษัท เครื่องหลัก จำกัด"
        assert wizard.stack.currentIndex() == 1
        assert wizard.secondary_candidate == candidate
        assert test_calls == [True]
        entry = wizard.discovered_devices[0]
        assert entry["selected"] is True
        assert entry["name"] == "แผนกบัญชี"
        assert entry["result"]["synced_from_primary"] is True
        assert entry["result"]["online"] is False
        assert entry["result"]["web_ok"] is False
        assert wizard.shared_price_row["a4_color"].value() == 2.0
        assert wizard.billing_end_day.currentData() == 25
        assert wizard.waste_paper_pct.value() == 1.5
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_secondary_manual_primary_ip_uses_one_validated_host(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        calls: list[tuple[list[str] | None, str]] = []
        wizard._start_secondary_discovery = (
            lambda hosts=None, *, manual_host="": calls.append((hosts, manual_host))
        )

        wizard.secondary_manual_ip.setText(" 192.168.50.25 ")
        wizard._secondary_manual_join_clicked()
        assert calls == [(["192.168.50.25"], "192.168.50.25")]

        wizard.secondary_manual_ip.setText("primary.local")
        wizard._secondary_manual_join_clicked()
        assert calls == [(["192.168.50.25"], "192.168.50.25")]
        assert "Primary IP" in wizard.secondary_join_status.text()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_secondary_setup_stays_compact_until_a_primary_is_found_or_requested(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()

        assert wizard.secondary_join_card.isHidden()
        assert not wizard.secondary_existing_button.isHidden()

        wizard.secondary_existing_button.click()
        assert not wizard.secondary_join_card.isHidden()
        assert not wizard.secondary_manual_row.isHidden()
        assert "Primary IP" in wizard.secondary_join_status.text()

        candidate = SecondaryPeerCandidate(
            base_url="https://192.0.2.20:3000",
            company_name="บริษัท เครื่องหลัก จำกัด",
            printer_count=1,
            version="5.2.11",
            certificate_sha256="a" * 64,
        )
        child_count = len(wizard._wizard_child_dialogs)
        wizard._secondary_discovery_finished([candidate], "")

        assert not wizard.secondary_join_card.isHidden()
        assert wizard.secondary_manual_row.isHidden()
        assert wizard.secondary_existing_button.isHidden()
        assert wizard.secondary_join_button.text() == "ดึงการตั้งค่า"
        assert "พบเครื่องหลัก 1 เครื่อง" in wizard.secondary_join_status.text()
        assert len(wizard._wizard_child_dialogs) == child_count

        wizard.close()
        app.processEvents()

        no_primary = SetupWizardV5()
        no_primary._secondary_discovery_finished([], "")
        assert not no_primary.secondary_join_card.isHidden()
        assert not no_primary.secondary_existing_button.isHidden()
        assert no_primary.secondary_manual_row.isHidden()
        assert no_primary.secondary_join_button.text() == "ค้นหาอีกครั้ง"
        assert no_primary.secondary_join_button.isEnabled()
        calls = []
        no_primary._start_secondary_discovery = lambda: calls.append("search")
        no_primary.secondary_join_button.click()
        assert calls == ["search"]
        no_primary._secondary_discovery_finished([], "LAN unavailable")
        assert no_primary.secondary_join_button.text() == "ค้นหาอีกครั้ง"
        assert no_primary.secondary_join_status.toolTip() == "LAN unavailable"
        no_primary.secondary_join_button.click()
        assert calls == ["search", "search"]
        no_primary._secondary_discovery_finished([candidate], "")
        assert no_primary.secondary_join_button.text() == "ดึงการตั้งค่า"
        no_primary.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_connectivity_passes_silently_and_failure_opens_copyable_details(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        passed = SetupConnectivityReport(
            started_at="2026-09-17T10:00:00+07:00",
            base_url="https://www.dmskm.com",
            checks=(
                SetupConnectivityCheck(
                    name="Registration API",
                    target="https://www.dmskm.com/api/v1/installations/register",
                    ok=True,
                    detail="HTTP 405 · endpoint reachable",
                ),
            ),
        )
        wizard = SetupWizardV5()
        child_count = len(wizard._wizard_child_dialogs)
        wizard._setup_connectivity_finished(passed, "")
        assert wizard.stack.currentIndex() == 1
        assert len(wizard._wizard_child_dialogs) == child_count
        wizard.close()
        app.processEvents()

        failed = SetupConnectivityReport(
            started_at="2026-09-17T10:00:00+07:00",
            base_url="https://www.dmskm.com",
            checks=(
                SetupConnectivityCheck(
                    name="Status API",
                    target="https://www.dmskm.com/api/v1/installations/status",
                    ok=False,
                    detail="HTTP 503 · Host unavailable",
                    support_code="host_unavailable",
                ),
            ),
        )
        blocked = SetupWizardV5()
        blocked._setup_connectivity_finished(failed, "")
        app.processEvents()

        assert blocked.stack.currentIndex() == 0
        dialog = blocked._wizard_child_dialogs[-1]
        details = dialog.findChild(QPlainTextEdit, "setup_connectivity_details")
        assert details is not None
        assert "Support code: host_unavailable" in details.toPlainText()
        assert "company name" in details.toPlainText()
        copy_button = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == "คัดลอกรายละเอียด"
        )
        copy_button.click()
        assert QApplication.clipboard().text() == details.toPlainText()
        dialog.close()
        blocked.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_secondary_setup_persists_received_schedule_only_when_local_value_is_missing(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        received_schedule = dump_schedule_windows(default_schedule_windows())
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "Secondary Printer", "192.0.2.10")
        wizard.secondary_candidate = SecondaryPeerCandidate(
            base_url="https://192.0.2.20:3000",
            company_name="บริษัท เครื่องหลัก จำกัด",
            printer_count=1,
            version="5.2.5",
            certificate_sha256="a" * 64,
        )
        wizard.secondary_snapshot = {
            "organization": {"primary_installation_id": "primary-id"},
            "settings": {"sync_schedule_windows": received_schedule},
        }

        _confirm_meter(wizard)
        wizard._save()

        assert database.get_cfg("sync_schedule_windows") == received_schedule
        assert database.get_cfg("desktop_role") == "secondary"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_verify_selected_devices_passes_current_configs_to_worker(tmp_path, monkeypatch):
    """Regression: clicking Verify must not reference a stale/missing devices variable."""

    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    captured: dict[str, object] = {}

    def capture_worker(devices, **kwargs):
        captured["devices"] = devices
        captured["kwargs"] = kwargs
        raise RuntimeError("worker captured")

    monkeypatch.setattr(setup_wizard, "DeviceTestWorker", capture_worker)
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")

        with pytest.raises(RuntimeError, match="worker captured"):
            wizard._test_all()

        devices = captured["devices"]
        assert isinstance(devices, list)
        assert len(devices) == 1
        assert devices[0].host == "192.0.2.10"
        assert captured["kwargs"]["generation"] == 1
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_advanced_scan_enter_uses_the_requested_ipv4_range():
    assert SetupWizardV5._advanced_scan_hosts(
        "192.168.1.1", "192.168.1.3"
    ) == ["192.168.1.1", "192.168.1.2", "192.168.1.3"]

    with pytest.raises(ValueError, match="IPv4"):
        SetupWizardV5._advanced_scan_hosts("192.168.1.10", "192.168.1.1")


def test_setup_wizard_uses_compact_language_toggle_only_on_first_step(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()

        assert not wizard.language_switch.isHidden()
        assert wizard.thai_language_button.text() == "ไทย"
        assert wizard.english_language_button.text() == "EN"
        assert wizard.thai_language_button.isChecked()
        assert wizard.language_button_group.exclusive()

        wizard.english_language_button.click()
        assert database.get_cfg("ui_language") == "en"
        assert wizard.english_language_button.isChecked()
        assert wizard.thai_language_button.text() == "ไทย"
        assert wizard.english_language_button.text() == "EN"

        wizard._next()
        assert wizard.language_switch.isHidden()
        wizard._back()
        assert not wizard.language_switch.isHidden()
        assert wizard.thai_language_button.text() == "ไทย"

        wizard.thai_language_button.click()
        assert database.get_cfg("ui_language") == "th"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_english_mode_has_no_untranslated_visible_copy(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Example Company")
    database.set_cfg("ui_language", "en")
    try:
        wizard = SetupWizardV5(lab_mode=True, legacy_source_paths=[])
        wizard.resize(1120, 720)
        wizard.show()
        app.processEvents()
        assert _visible_thai_ui_texts(wizard) == []

        _add_selected_device(wizard, "Virtual Printer", "127.0.0.1")
        wizard._next()
        app.processEvents()
        assert _visible_thai_ui_texts(wizard) == []

        wizard._next()
        app.processEvents()
        assert _visible_thai_ui_texts(wizard) == []

        _confirm_meter(wizard)
        wizard._next()
        app.processEvents()
        assert _visible_thai_ui_texts(wizard) == []

        wizard.deferred_price_mode.click()
        wizard._next()
        app.processEvents()
        assert _visible_thai_ui_texts(wizard) == []

        wizard._set_wizard_language("th")
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_modals_keep_light_palette_and_complete_english(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Example Company")
    database.set_cfg("ui_language", "en")
    captured: list[QDialog] = []

    try:
        wizard = SetupWizardV5(lab_mode=True, legacy_source_paths=[])
        _add_selected_device(wizard, "Virtual Printer", "127.0.0.1")

        for open_dialog in (
            wizard._advanced_scan,
            wizard._manual_setup,
            lambda: wizard._open_credentials("127.0.0.1"),
            wizard._name_selected_devices,
        ):
            open_dialog()
            dialog = wizard._wizard_child_dialogs[-1]
            captured.append(dialog)
            dialog.reject()
            app.processEvents()

        assert len(captured) == 4
        for dialog in captured:
            assert dialog.objectName() == "wizard_modal"
            assert dialog.palette().color(QPalette.ColorRole.Window).name() == "#f4f7fa"
            assert "background: #F4F7FA" in dialog.styleSheet()
            copy = [
                widget.text()
                for widget in dialog.findChildren((QLabel, QAbstractButton, QGroupBox))
            ]
            placeholders = [
                field.placeholderText()
                for field in dialog.findChildren(QLineEdit)
            ]
            assert not any(
                "\u0e00" <= char <= "\u0e7f"
                for text in [dialog.windowTitle(), *copy, *placeholders]
                for char in text
            )

        wizard._set_wizard_language("th")
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_flow_does_not_use_nested_dialog_exec():
    import inspect

    source = inspect.getsource(SetupWizardV5)
    assert ".exec(" not in source
    assert "dialog.open()" in source


def test_setup_wizard_uses_a_centered_screen_bounded_window(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])
        available = (wizard.screen() or app.primaryScreen()).availableGeometry()

        assert wizard.parent() is None
        assert wizard.minimumWidth() == 800
        assert wizard.minimumHeight() == 520
        assert wizard.width() <= min(1120, available.width())
        assert wizard.height() <= min(720, available.height())
        assert abs(wizard.frameGeometry().center().x() - available.center().x()) <= 2
        assert abs(wizard.frameGeometry().center().y() - available.center().y()) <= 2

        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_stays_readable_when_macos_uses_a_dark_palette(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    original_palette = app.palette()
    dark_palette = QPalette(original_palette)
    dark_palette.setColor(QPalette.ColorRole.Window, QColor("#242424"))
    dark_palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
    dark_palette.setColor(QPalette.ColorRole.Base, QColor("#303030"))
    dark_palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF"))
    app.setPalette(dark_palette)
    try:
        wizard = SetupWizardV5(lab_mode=True)

        assert wizard.objectName() == "setup_wizard_v5"
        assert wizard.palette().color(QPalette.ColorRole.Window).name() == "#f4f7fa"
        assert wizard.palette().color(QPalette.ColorRole.WindowText).name() == "#172033"
        assert (
            wizard.company_form.fieldGrowthPolicy()
            == QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        assert wizard.company_name_input.minimumWidth() >= 470
        assert all("color:#334155" in label.styleSheet() for label in wizard.company_form_labels)

        _add_selected_device(wizard, "Virtual Printer", "127.0.0.1")
        wizard.stack.setCurrentIndex(1)
        assert wizard.device_table.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
        assert wizard.device_table.palette().color(QPalette.ColorRole.Text).name() == "#172033"
        assert (
            wizard.device_table.palette().color(QPalette.ColorRole.HighlightedText).name()
            == "#172033"
        )
        assert wizard.price_scroll.viewport().palette().color(QPalette.ColorRole.Base).name() == "#f4f7fa"
        assert wizard.price_content.palette().color(QPalette.ColorRole.Window).name() == "#f4f7fa"
        assert wizard.effective_date.calendarWidget().palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
        assert all(
            spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
            for spin in wizard.shared_price_row.values()
        )
        assert wizard.title.wordWrap()
        assert wizard.header_controls.sizePolicy().horizontalPolicy().name == "Maximum"

        wizard.resize(980, 620)
        wizard.show()
        app.processEvents()
        image = wizard.grab().toImage()
        assert image.pixelColor(4, 4).name() == "#f4f7fa"
        table_image = wizard.device_table.viewport().grab().toImage()
        assert table_image.pixelColor(4, table_image.height() - 4).name() == "#ffffff"
        wizard.stack.setCurrentIndex(3)
        app.processEvents()
        price_image = wizard.price_scroll.viewport().grab().toImage()
        assert price_image.pixelColor(4, 4).name() == "#f4f7fa"
        wizard.close()
        app.processEvents()
    finally:
        app.setPalette(original_palette)
        database.set_db_path(original_path)


def test_setup_wizard_lab_selects_only_snmp_discovered_virtual_printer(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(lab_mode=True)
        wizard._discovery_result(
            {
                "host": "192.168.1.50",
                "model": "KONICA MINOLTA bizhub C450i Virtual",
                "serial": "KOMI-DEMO-001",
                "total": 125430,
            }
        )

        assert wizard.selection_badge.text() == "เลือกแล้ว 1/3"
        assert wizard.discovered_devices[0]["is_virtual"] is True
        assert wizard.discovered_devices[0]["name"] == "KM bizhub C450i Virtual"
        assert "รอตรวจสอบ Web" in wizard.device_table.item(0, 4).text()
        wizard._configs()

        wizard._test_result(
            0,
            {
                "online": True,
                "web_ok": True,
                "model": "KONICA MINOLTA bizhub C450i Virtual",
                "serial": "KOMI-DEMO-001",
                "total": 125430,
            },
        )
        assert "VIRTUAL · พร้อมใช้งาน · SNMP + Web ผ่าน" in wizard.device_table.item(0, 4).text()

        wizard._next()
        assert wizard.stack.currentIndex() == 1
        wizard._next()
        assert wizard.stack.currentIndex() == 2
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_lab_uses_real_ports_for_user_supplied_lan_range(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(
            lab_mode=True,
            lab_hosts=["127.0.0.1"],
            lab_snmp_port=1161,
            lab_web_port=8443,
        )

        assert wizard._scan_parameters(None) == (["127.0.0.1"], 1161)
        real_range = ["10.244.116.1", "10.244.116.254"]
        assert wizard._scan_parameters(real_range) == (real_range, 161)
        assert wizard._lab_endpoint_ports() == {"127.0.0.1": (1161, 8443)}

        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_manual_setup_keeps_explicit_admin_credentials_only_in_memory(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        first_password = secrets.token_urlsafe(18)
        second_password = secrets.token_urlsafe(18)
        wizard._add_manual_entries(
            [
                ("192.0.2.41", first_password),
                ("192.0.2.42", second_password),
                ("", secrets.token_urlsafe(18)),
            ]
        )
        devices = wizard._configs()
        assert [device.host for device in devices] == ["192.0.2.41", "192.0.2.42"]
        assert all(device.username == "administrator" for device in devices)
        assert [device.password for device in devices] == [first_password, second_password]
        assert wizard.selection_badge.text() == "เลือกแล้ว 2/3"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_preserves_existing_slot_when_rows_change_order(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        DeviceConfigRepository().replace_all(
            [DeviceConfig(1, "แผนกบุคคล", "192.0.2.21", serial="OLD-SLOT-2")]
        )
        wizard = SetupWizardV5(edit_mode=True)
        _add_selected_device(wizard, "แผนกบัญชี", "192.0.2.20")

        by_host = {device.host: device.slot for device in wizard._configs()}

        assert by_host == {"192.0.2.21": 1, "192.0.2.20": 0}
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_requires_fresh_verification_for_saved_online_device(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        DeviceConfigRepository().replace_all(
            [
                DeviceConfig(
                    0,
                    "เครื่องพิมพ์เดิม",
                    "192.0.2.31",
                    model="KONICA MINOLTA bizhub C450i",
                    serial="SAVED-ONLINE",
                    enabled=True,
                    connection_status="online",
                )
            ]
        )
        wizard = SetupWizardV5(edit_mode=True)

        saved_result = wizard.results[0]
        assert saved_result["online"] is False
        assert saved_result["web_ok"] is False
        assert saved_result["saved"] is True
        assert "บันทึกไว้ · รอตรวจสอบรอบนี้" in wizard.device_table.item(0, 4).text()

        wizard.stack.setCurrentIndex(1)
        wizard._update_device_actions()
        assert wizard.next_button.isEnabled() is False

        wizard._test_result(
            0,
            {
                "online": True,
                "web_ok": True,
                "model": "KONICA MINOLTA bizhub C450i",
                "serial": "SAVED-ONLINE",
                "total": 100,
            },
        )
        assert "พร้อมใช้งาน · SNMP + Web ผ่าน" in wizard.device_table.item(0, 4).text()
        assert wizard.next_button.isEnabled() is True
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_shortens_konica_model_for_default_name():
    assert SetupWizardV5._default_device_name("KONICA MINOLTA bizhub C450i", "MFP 1") == "KM bizhub C450i"
    assert SetupWizardV5._default_device_name("bizhub C750i", "MFP 2") == "KM bizhub C750i"


def test_setup_wizard_uses_neutral_192_168_1_ip_examples():
    assert SetupWizardV5.ADVANCED_SCAN_EXAMPLES == ("เช่น 192.168.1.1", "เช่น 192.168.1.255")
    assert [SetupWizardV5._manual_ip_example(index) for index in range(3)] == [
        "เช่น 192.168.1.101",
        "เช่น 192.168.1.102",
        "เช่น 192.168.1.103",
    ]


def test_network_discovery_cancel_does_not_wait_for_probe_timeout():
    worker = NetworkDiscoveryWorker([f"192.0.2.{index}" for index in range(1, 40)])
    probe_started = threading.Event()
    release_probes = threading.Event()

    def slow_probe(_host: str):
        probe_started.set()
        release_probes.wait(2)
        return None

    worker._probe = slow_probe  # type: ignore[method-assign]
    runner = threading.Thread(target=worker.run)
    runner.start()
    try:
        assert probe_started.wait(1)
        started = time.perf_counter()
        worker.cancel()
        runner.join(0.3)
        elapsed = time.perf_counter() - started

        assert not runner.is_alive()
        assert elapsed < 0.25
    finally:
        release_probes.set()
        runner.join(2)


def test_network_discovery_reports_completed_host_progress():
    hosts = ["192.0.2.1", "192.0.2.2", "192.0.2.3"]
    worker = NetworkDiscoveryWorker(hosts)
    updates: list[tuple[int, int]] = []
    worker.progress_count.connect(lambda completed, total: updates.append((completed, total)))
    worker._probe = lambda _host: None  # type: ignore[method-assign]

    worker.run()

    assert updates[0] == (0, 3)
    assert updates[-1] == (3, 3)


def test_setup_wizard_shows_exact_ip_scan_progress(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])

        assert wizard.scan_progress_bar.isHidden()
        wizard._scan_progress_changed(12, 20)

        assert not wizard.scan_progress_bar.isHidden()
        assert wizard.scan_progress_bar.minimum() == 0
        assert wizard.scan_progress_bar.maximum() == 20
        assert wizard.scan_progress_bar.value() == 12
        assert wizard.scan_progress_bar.format() == "สแกน 12 / 20 IP (60%)"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_cancel_restores_scan_controls_immediately(tmp_path, monkeypatch):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    probe_started = threading.Event()
    release_probes = threading.Event()

    def slow_probe(_worker, _host: str):
        probe_started.set()
        release_probes.wait(2)
        return None

    monkeypatch.setattr(NetworkDiscoveryWorker, "_probe", slow_probe)
    wizard = SetupWizardV5(legacy_source_paths=[])
    try:
        wizard._scan_network([f"192.0.2.{index}" for index in range(1, 40)])
        deadline = time.perf_counter() + 1
        while not probe_started.is_set() and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert probe_started.is_set()

        started = time.perf_counter()
        wizard._cancel_scan()
        deadline = started + 0.5
        while wizard._scan_thread is not None and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.005)

        assert wizard._scan_thread is None
        assert time.perf_counter() - started < 0.5
        assert wizard.scan_button.isEnabled()
        assert wizard.cancel_scan_button.isHidden()
        assert wizard.scan_status.text() == "ยกเลิกการค้นหาแล้ว"
    finally:
        release_probes.set()
        wizard.close()
        app.processEvents()
        database.set_db_path(original_path)


def test_setup_wizard_requests_active_threads_to_stop_before_close(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])

    class RunningThread:
        def __init__(self):
            self.interrupted = False
            self.quit_requested = False

        def isRunning(self):
            return True

        def requestInterruption(self):
            self.interrupted = True

        def quit(self):
            self.quit_requested = True

        def wait(self, timeout_ms):
            return timeout_ms == 5000

    try:
        wizard = SetupWizardV5()
        scan_thread = RunningThread()
        test_thread = RunningThread()
        wizard._scan_thread = scan_thread
        wizard._thread = test_thread

        assert wizard._stop_active_workers()
        assert scan_thread.interrupted and scan_thread.quit_requested
        assert test_thread.interrupted and test_thread.quit_requested
    finally:
        wizard._scan_thread = None
        wizard._thread = None
        wizard.close()
        app.processEvents()
        database.set_db_path(original_path)


def test_setup_wizard_selects_scanned_rows_without_a_default_password(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        for index in range(3):
            _add_selected_device(wizard, f"Printer {index + 1}", f"192.0.2.{index + 10}", total=100 + index)

        assert wizard.device_table.rowCount() == 3
        assert wizard.selection_badge.text() == "เลือกแล้ว 3/3"
        devices = wizard._configs()
        assert [device.host for device in devices] == ["192.0.2.10", "192.0.2.11", "192.0.2.12"]
        assert all(device.username == "administrator" for device in devices)
        assert all(device.password == "" for device in devices)
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_device_test_worker_pins_first_self_signed_certificate(monkeypatch) -> None:
    fingerprint = "ab" * 32
    policies: list[str] = []

    monkeypatch.setattr(
        "ui.setup.workers.SnmpTotalProbe.read",
        lambda _probe, _host: SimpleNamespace(
            model="KONICA MINOLTA bizhub C450i",
            serial="SERIAL-1",
            total=100,
            total_oid="1.2.3",
            oid_values=(("1.2.3", "100"),),
        ),
    )
    monkeypatch.setattr(
        "ui.setup.workers.server_certificate_fingerprint",
        lambda _host: fingerprint,
    )

    def read(_reader, host: str):
        policy = _reader.public_connector.tls_policy
        policies.append(policy.mode)
        if policy.mode == "system":
            raise WebConnectionCertificateError("self-signed")
        assert policy.fingerprint_sha256 == fingerprint
        counter = WebCounterValue("counter.total.total", "Total", 100, "Total", "test")
        return MeterReading.create(
            host,
            [counter],
            "web_connection_admin_read_only",
            WebAuthState.ADMIN,
        )

    monkeypatch.setattr("ui.setup.workers.MeterReader.read", read)
    result = DeviceTestWorker(
        [
            DeviceConfig(
                0,
                "MFP 1",
                "192.0.2.10",
                password=secrets.token_urlsafe(18),
            )
        ]
    )._test(
        DeviceConfig(
            0,
            "MFP 1",
            "192.0.2.10",
            password=secrets.token_urlsafe(18),
        )
    )

    assert policies == ["system", "fingerprint"]
    assert result["web_ok"] is True
    assert result["tls_mode"] == "fingerprint"
    assert result["tls_fingerprint"] == fingerprint
    assert result["web_auth_state"] == "admin"
    assert result["meter_reading"].host == "192.0.2.10"
    assert result["meter_reading"].counters[0].count == 100


def test_device_test_worker_passes_pinned_policy_to_legacy_admin_connector(monkeypatch) -> None:
    fingerprint = "cd" * 32
    policies: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "ui.setup.workers.SnmpTotalProbe.read",
        lambda _probe, _host: SimpleNamespace(
            model="KONICA MINOLTA bizhub C458",
            serial="C458-SERIAL",
            total=27_467,
            total_oid="1.2.3",
            oid_values=(("1.2.3", "27467"),),
        ),
    )
    monkeypatch.setattr(
        "ui.setup.workers.server_certificate_fingerprint",
        lambda _host, **_kwargs: fingerprint,
    )

    def read(reader, host: str, *, model: str = ""):
        policy = reader.legacy_admin_connector.tls_policy
        policies.append((policy.mode, policy.compatibility.value))
        assert model.endswith("bizhub C458")
        if policy.mode == "system":
            raise WebConnectionCertificateError("self-signed")
        assert policy.fingerprint_sha256 == fingerprint
        counter = WebCounterValue("counter.total.total", "Total", 27_467, "Total", "test")
        return MeterReading.create(
            host,
            [counter],
            "web_connection_legacy_xml_admin",
            WebAuthState.ADMIN,
        )

    monkeypatch.setattr("ui.setup.workers.MeterReader.read", read)
    device = DeviceConfig(
        0,
        "bizhub C458",
        "192.0.2.7",
        password=secrets.token_urlsafe(18),
        model="KONICA MINOLTA bizhub C458",
    )

    result = DeviceTestWorker([device])._test(device)

    assert policies == [("system", "tls11_legacy"), ("fingerprint", "tls11_legacy")]
    assert result["web_ok"] is True
    assert result["tls_mode"] == "fingerprint"
    assert result["tls_fingerprint"] == fingerprint
    assert result["web_auth_state"] == "admin"


def test_device_test_worker_does_not_request_customer_password_for_tls_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "ui.setup.workers.SnmpTotalProbe.read",
        lambda _probe, _host: SimpleNamespace(
            model="KONICA MINOLTA bizhub C368",
            serial="C368-SERIAL",
            total=202_254,
            total_oid="1.2.3",
            oid_values=(("1.2.3", "202254"),),
        ),
    )
    monkeypatch.setattr(
        "ui.setup.workers.MeterReader.read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            WebConnectionTlsError("TLS compatibility failed")
        ),
    )
    device = DeviceConfig(
        0,
        "bizhub C368",
        "192.0.2.11",
        model="KONICA MINOLTA bizhub C368",
    )

    result = DeviceTestWorker([device])._test(device)

    assert result["online"] is True
    assert result["web_ok"] is False
    assert result["credential_required"] is False
    assert "Code: tls_handshake" in result["error"]
    assert "WebConnectionTlsError" in result["error"]
    assert result["meter_reading"] is None


def test_device_test_worker_reports_session_busy_without_requesting_password(monkeypatch) -> None:
    monkeypatch.setattr(
        "ui.setup.workers.SnmpTotalProbe.read",
        lambda _probe, _host: SimpleNamespace(
            model="KONICA MINOLTA bizhub C458",
            serial="C458-SERIAL",
            total=243_744,
            total_oid="1.2.3",
            oid_values=(("1.2.3", "243744"),),
        ),
    )
    monkeypatch.setattr(
        "ui.setup.workers.MeterReader.read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            WebConnectionSessionBusyError("legacy session busy")
        ),
    )
    device = DeviceConfig(
        0,
        "bizhub C458",
        "192.0.2.16",
        model="KONICA MINOLTA bizhub C458",
    )

    result = DeviceTestWorker([device])._test(device)

    assert result["online"] is True
    assert result["web_ok"] is False
    assert result["session_busy"] is True
    assert result["credential_required"] is False
    assert "Code: session_busy" in result["error"]


def test_device_test_worker_accepts_public_meter_for_public_capable_press_even_if_password_was_entered(monkeypatch) -> None:
    monkeypatch.setattr(
        "ui.setup.workers.SnmpTotalProbe.read",
        lambda _probe, _host: SimpleNamespace(
            model="KONICA MINOLTA bizhub C450i",
            serial="SERIAL-1",
            total=100,
            total_oid="1.2.3",
            oid_values=(("1.2.3", "100"),),
        ),
    )
    counter = WebCounterValue("counter.total.total", "Total", 100, "Total", "test")
    monkeypatch.setattr(
        "ui.setup.workers.MeterReader.read",
        lambda _reader, host: MeterReading.create(
            host,
            [counter],
            "web_connection_public",
            WebAuthState.PUBLIC_FALLBACK,
        ),
    )
    device = DeviceConfig(
        0,
        "MFP 1",
        "192.0.2.10",
        password=secrets.token_urlsafe(18),
    )

    result = DeviceTestWorker([device])._test(device)

    assert result["web_ok"] is True
    assert result["web_auth_state"] == "public_fallback"


def test_setup_wizard_keeps_selected_table_text_stable_and_marks_failed_test(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        assert "QTableWidget#setup_device_table:focus" in wizard.device_table.styleSheet()
        assert wizard.device_table.itemDelegate().__class__.__name__ == "SetupDeviceStatusDelegate"
        assert wizard.test_button.parent() is wizard
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard._configs()

        wizard._test_result(
            0,
            {
                "online": False,
                "web_ok": False,
                "model": "bizhub C450i",
                "serial": "SN-10",
                "total": None,
                "error": "Web: authentication failed",
            },
        )

        assert "ไม่ผ่าน" in wizard.device_table.item(0, 4).text()
        assert wizard.device_table.item(0, 1).background().color().name().lower() == "#fdecec"

        wizard._test_result(
            0,
            {
                "online": True,
                "web_ok": True,
                "model": "bizhub C450i",
                "serial": "SN-10",
                "total": 100,
                "error": None,
            },
        )
        assert wizard.device_table.item(0, 1).background().color().name().lower() == "#edf8f2"
        wizard._set_device_selected(0, False)
        app.processEvents()
        assert wizard.selection_badge.text() == "เลือกแล้ว 0/3"
        assert wizard.device_table.item(0, 1).background().style().name == "NoBrush"
        assert wizard.device_table.item(0, 4).foreground().color().name().lower() == "#16a34a"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_marks_customer_password_required_without_exposing_a_default(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "Legacy Office", "192.0.2.7")
        wizard._test_generation = 4

        wizard._test_result(
            DeviceTestResult(
                generation=4,
                host="192.0.2.7",
                slot=0,
                payload={
                    "online": True,
                    "web_ok": False,
                    "credential_required": True,
                    "error": "KOMI Diagnostic v1\nCode: factory_credentials_rejected\n",
                },
            )
        )

        assert "factory_credentials_rejected" in wizard.device_table.item(0, 4).text()
        assert "รหัสเริ่มต้นใช้เข้าสู่เครื่องนี้ไม่ได้" in wizard.device_table.item(0, 4).text()
        assert wizard.device_table.item(0, 5).text() == "ใส่รหัส"
        assert wizard.discovered_devices[0]["password"] == ""
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_marks_session_busy_and_opens_printer_web_instead_of_password(
    tmp_path,
    monkeypatch,
):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    opened: list[str] = []
    monkeypatch.setattr(setup_wizard.webbrowser, "open", opened.append)
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "KONICA MINOLTA bizhub C458", "192.0.2.16")
        wizard.discovered_devices[0]["model"] = "KONICA MINOLTA bizhub C458"
        wizard._test_generation = 9

        wizard._test_result(
            DeviceTestResult(
                generation=9,
                host="192.0.2.16",
                slot=0,
                payload={
                    "online": True,
                    "web_ok": False,
                    "session_busy": True,
                    "credential_required": False,
                    "error": "Web Connection session busy",
                },
            )
        )

        assert "Logout" in wizard.device_table.item(0, 4).text()
        assert wizard.device_table.item(0, 5).text() == "เปิด Web"
        assert "รหัส" not in wizard.device_table.item(0, 4).text()
        assert wizard.device_table.item(0, 4).foreground().color().name() == "#b45309"
        assert "Logout" in wizard.device_table.item(0, 5).toolTip()

        wizard._device_table_action(0, 5)
        assert opened == ["https://192.0.2.16/wcd/"]
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_keeps_successful_public_factory_password_only_in_memory_until_save(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "Legacy Office", "192.0.2.7")
        wizard.discovered_devices[0]["password"] = ""
        wizard._test_generation = 5

        wizard._test_result(
            DeviceTestResult(
                generation=5,
                host="192.0.2.7",
                slot=0,
                payload={
                    "online": True,
                    "web_ok": True,
                    "credential_default_index": 1,
                    "model": "KONICA MINOLTA bizhub C458",
                    "serial": "LEGACY-7",
                    "total": 100,
                },
            )
        )

        assert wizard.discovered_devices[0]["password"] == PUBLIC_FACTORY_ADMIN_PASSWORDS[1]
        with sqlite3.connect(database.get_db_path()) as connection:
            dump = "\n".join(connection.iterdump())
        assert PUBLIC_FACTORY_ADMIN_PASSWORDS[0] not in dump
        assert PUBLIC_FACTORY_ADMIN_PASSWORDS[1] not in dump
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_binds_test_results_to_host_and_ignores_stale_generation(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "AccurioPress C7090", "192.0.2.16")
        _add_selected_device(wizard, "bizhub C450i", "192.0.2.6")
        for entry in wizard.discovered_devices:
            entry["name_is_default"] = True
        wizard._configs()
        wizard._test_generation = 7

        wizard._test_result(
            DeviceTestResult(
                generation=7,
                host="192.0.2.16",
                slot=0,
                payload={
                    "online": False,
                    "web_ok": False,
                    "model": "KONICA MINOLTA AccurioPress C7090",
                    "serial": "C7090-SERIAL",
                    "error": "session busy",
                },
            )
        )
        wizard._test_result(
            DeviceTestResult(
                generation=7,
                host="192.0.2.6",
                slot=0,
                payload={
                    "online": True,
                    "web_ok": True,
                    "model": "KONICA MINOLTA bizhub C450i",
                    "serial": "C450I-SERIAL",
                    "total": 267040,
                },
            )
        )

        by_host = {entry["host"]: entry for entry in wizard.discovered_devices}
        assert by_host["192.0.2.16"]["result"]["web_ok"] is False
        assert by_host["192.0.2.16"]["model"].endswith("AccurioPress C7090")
        assert by_host["192.0.2.16"]["name"] == "AccurioPress C7090"
        assert by_host["192.0.2.6"]["result"]["web_ok"] is True
        assert by_host["192.0.2.6"]["model"].endswith("bizhub C450i")

        wizard._test_result(
            DeviceTestResult(
                generation=6,
                host="192.0.2.16",
                slot=0,
                payload={
                    "online": True,
                    "web_ok": True,
                    "model": "KONICA MINOLTA bizhub C450i",
                    "serial": "WRONG-STALE-SERIAL",
                    "total": 999999,
                },
            )
        )
        assert by_host["192.0.2.16"]["result"]["web_ok"] is False
        assert by_host["192.0.2.16"]["serial"] == "C7090-SERIAL"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_keeps_verified_certificate_pin_in_device_config(tmp_path) -> None:
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard._configs()
        fingerprint = "cd" * 32

        wizard._test_result(
            0,
            {
                "online": True,
                "web_ok": True,
                "model": "bizhub C450i",
                "serial": "SN-10",
                "total": 100,
                "tls_mode": "fingerprint",
                "tls_fingerprint": fingerprint,
                "web_auth_state": "admin",
            },
        )

        device = wizard._configs()[0]
        assert device.tls_mode == "fingerprint"
        assert device.tls_fingerprint == fingerprint
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_shared_price_is_written_to_every_selected_device(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        _add_selected_device(wizard, "Sales Printer", "192.0.2.11")
        for suffix, model in ((12, "bizhub C650i"), (13, "bizhub C450i")):
            wizard._upsert_discovered(
                {
                    "name": f"Scanned Printer {suffix}",
                    "host": f"192.0.2.{suffix}",
                    "model": model,
                    "serial": f"SN-{suffix}",
                    "found_in_registration_scan": True,
                    "result": {"online": True, "web_ok": False, "model": model, "serial": f"SN-{suffix}"},
                }
            )
        wizard.shared_price_mode.setChecked(True)
        wizard.shared_price_row["a4_color"].setValue(2.0)
        wizard.shared_price_row["a4_bw"].setValue(1.0)
        wizard.shared_price_row["a3_color"].setValue(4.0)
        wizard.shared_price_row["a3_bw"].setValue(2.0)
        wizard.billing_end_day.setCurrentIndex(30)
        wizard.waste_paper_pct.setValue(2.0)
        _confirm_meter(wizard)
        wizard._save()

        assert [item.name for item in DeviceConfigRepository().list(enabled_only=True)] == ["DMS Printer", "Sales Printer"]
        for slot in (0, 1):
            prices = PricingRepository().get_prices(slot, date.today())
            assert prices.a4_color == 2.0
            assert prices.a4_bw == 1.0
            assert prices.a3_color == 4.0
            assert prices.a3_bw == 2.0
        assert database.get_cfg("pricing_mode") == "shared"
        assert database.get_cfg("billing_day") == "31"
        assert database.get_cfg("waste_paper_pct") == "2.0"
        installation_id = database.get_cfg("installation_id")
        assert installation_id
        runtime_state = V52RuntimeStateRepository().internal()
        assert runtime_state is not None
        assert runtime_state["installation_id"] == installation_id
        assert runtime_state["company_name"] == "บริษัท ทดสอบ จำกัด"
        assert runtime_state["mode"] == "online"
        assert runtime_state["notice_version"] == REGISTRATION_NOTICE_VERSION
        assert runtime_state["notice_accepted_at"]
        inventory = V52RuntimeStateRepository().registration_devices()
        assert len(inventory) == 4
        assert sum(bool(item["selected"]) for item in inventory) == 2
        assert {item["serial_number"] for item in inventory} == {
            "SN-10", "SN-11", "SN-12", "SN-13"
        }
        with database._open(commit=False) as connection:
            legacy_count = connection.execute(
                "SELECT COUNT(*) FROM registration_outbox WHERE event_type='register'"
            ).fetchone()[0]
        assert legacy_count == 0
        assert database.get_cfg("registration_pending_envelope") == ""
        assert database.get_cfg("registration_status") == "v52_configured"
        assert [item.serial for item in DeviceConfigRepository().list(enabled_only=True)] == [
            "SN-10",
            "SN-11",
        ]
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_keeps_local_configuration_but_does_not_open_when_registration_enqueue_fails(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")

        class FailingRuntimeStateRepository:
            def configure(self, *args, **kwargs):
                raise RuntimeError("synthetic outbox failure")

        wizard.registration_state = FailingRuntimeStateRepository()
        _confirm_meter(wizard)
        wizard._save()

        assert wizard.result() == int(QDialog.DialogCode.Rejected)
        assert DeviceConfigRepository().setup_complete() is True
        assert database.get_cfg("registration_status") == "action_required"
        assert not wizard.registration_offline_button.isVisible()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_records_current_v52_notice_acknowledgement(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")

        assert wizard.privacy_notice_accepted.isHidden()
        wizard.privacy_notice_accepted.setChecked(False)
        _confirm_meter(wizard)
        wizard._save()

        state = V52RuntimeStateRepository().internal()
        assert state is not None
        assert state["notice_version"] == REGISTRATION_NOTICE_VERSION
        assert state["notice_accepted_at"]
        # The fake transport reports success to the Wizard; the durable state
        # remains at its pre-network state because this test does not run the
        # real runtime processor.
        assert state["status"] == "waiting_for_internet"
        assert wizard.result() == int(QDialog.DialogCode.Accepted)
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_hidden_legacy_mode_cannot_bypass_online_registration(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard.registration_offline_mode.setChecked(True)
        wizard.privacy_notice_accepted.setChecked(False)
        wizard.registration_runtime = None

        _confirm_meter(wizard)
        wizard._save()

        assert wizard.result() == int(QDialog.DialogCode.Rejected)
        state = V52RuntimeStateRepository().internal()
        assert state is not None
        assert state["mode"] == "online"
        assert state["notice_version"] == REGISTRATION_NOTICE_VERSION
        assert state["notice_accepted_at"]
        assert not wizard.registration_offline_button.isVisible()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_registration_progress_can_be_cancelled_back_to_review(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        dialog = wizard._registration_dialog_ui()
        dialog.open()
        app.processEvents()

        assert wizard.registration_cancel_button.text() == "ยกเลิก"
        assert wizard.registration_cancel_button.isVisible()

        wizard.registration_cancel_button.click()
        app.processEvents()

        assert not dialog.isVisible()
        assert wizard.result() == int(QDialog.DialogCode.Rejected)
        assert wizard.next_button.isEnabled()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_offline_registration_entry_point_is_disabled_without_creating_runtime(
    tmp_path, monkeypatch
):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    exported = tmp_path / "customer.komirequest"

    class OfflineRuntime:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs
            self.mode = "online"
            self.exported: Path | None = None

        def set_mode(self, mode: str) -> None:
            self.mode = mode

        def create_offline_request(self, path: Path) -> Path:
            self.exported = path
            path.write_text("offline-request", encoding="utf-8")
            return path

    import services.v5_2_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "V52RuntimeCoordinator", OfflineRuntime)
    monkeypatch.setattr(
        setup_wizard.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(exported), "KOMI Request (*.komirequest)"),
    )
    try:
        wizard = SetupWizardV5(registration_runtime=None)
        wizard._open_offline_registration()
        app.processEvents()

        assert wizard._wizard_child_dialogs == []
        assert wizard.registration_runtime is None
        assert not exported.exists()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_records_notice_without_customer_checkbox(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard.privacy_notice_accepted.setChecked(False)

        _confirm_meter(wizard)
        wizard._save()

        assert wizard.result() == int(QDialog.DialogCode.Accepted)
        assert DeviceConfigRepository().setup_complete() is True
        state = V52RuntimeStateRepository().internal()
        assert state is not None
        assert state["notice_version"] == REGISTRATION_NOTICE_VERSION
        assert state["notice_accepted_at"]
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_edit_mode_keeps_billing_settings_owned_by_settings(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        database.set_cfg("billing_day", "17")
        database.set_cfg("waste_paper_pct", "3.5")
        V52RuntimeStateRepository().configure(
            "online",
            "บริษัท ทดสอบ จำกัด",
            "existing-installation",
            "2026-08-20",
            REGISTRATION_NOTICE_VERSION,
            "2026-08-20T09:00:00+07:00",
        )
        wizard = SetupWizardV5(edit_mode=True)
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard.shared_price_mode.setChecked(True)
        wizard.shared_price_row["a4_color"].setValue(2.0)
        wizard.billing_end_day.setCurrentIndex(30)
        wizard.waste_paper_pct.setValue(9.0)

        assert wizard.billing_section.isHidden()
        _confirm_meter(wizard)
        wizard._save()

        assert database.get_cfg("billing_day") == "17"
        assert database.get_cfg("waste_paper_pct") == "3.5"
        assert PricingRepository().get_prices(0, date.today()).a4_color == 2.0
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_edit_printer_invalidates_offline_binding_and_never_sends_after_restart(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])

    class NoSendRuntime:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def set_mode(self, _mode: str) -> None:
            self.calls.append("set_mode")

        def configuration_changed(self) -> None:
            self.calls.append("configuration_changed")

        def snapshot(self) -> dict[str, object]:
            self.calls.append("snapshot")
            return {"status": "offline_license", "support_code": ""}

    class NoSendClient:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("Offline mode must never call the Host client")

    try:
        state = V52RuntimeStateRepository()
        state.configure(
            "offline",
            "บริษัท ทดสอบ จำกัด",
            "offline-installation",
            "2026-08-20",
            "",
            "",
            registration_devices=[
                {
                    "serial_number": "OLD-SERIAL",
                    "model": "bizhub C450i",
                    "selected": True,
                    "device_slot": 1,
                }
            ],
        )
        state.save_offline_license(
            license_id="offline-license-1",
            expires_at="2031-08-20T00:00:00+00:00",
            kid="host-key-1",
            bound_devices=[
                {
                    "serial_number": "OLD-SERIAL",
                    "model": "bizhub C450i",
                    "device_slot": 1,
                }
            ],
        )
        before = state.internal()
        assert before is not None
        database.set_cfg("v52_registration_mode", "offline")
        database.set_cfg("registration_status", "offline_license")

        runtime = NoSendRuntime()
        wizard = SetupWizardV5(edit_mode=True, registration_runtime=runtime)
        _add_selected_device(wizard, "Replacement Printer", "192.0.2.22")
        _confirm_meter(wizard)
        wizard._save()

        assert wizard.result() == int(QDialog.DialogCode.Accepted)
        assert runtime.calls == []
        after = V52RuntimeStateRepository().internal()
        assert after is not None
        for field in (
            "mode",
            "status",
            "notice_version",
            "notice_accepted_at",
            "offline_request_json",
            "offline_license_id",
            "offline_license_expires_at",
            "offline_license_kid",
            "offline_bound_devices_json",
            "next_status_at",
            "next_meter_at",
        ):
            assert after[field] == before[field]
        assert database.get_cfg("v52_registration_mode") == "offline"
        assert database.get_cfg("registration_status") == "offline_license"
        assert V52RuntimeStateRepository().registration_devices() == [
            {
                "serial_number": "SN-22",
                "model": "bizhub C450i",
                "selected": True,
                "device_slot": 1,
            }
        ]
        assert all(
            V52OutboxRepository().active_count(event_type) == 0
            for event_type in ("register", "status", "meter")
        )

        from services.v5_2_runtime import V52RuntimeCoordinator

        client = NoSendClient()
        restarted = V52RuntimeCoordinator(client=client)
        assert restarted.processor.recover_after_restart() == 0
        assert restarted.processor.run_once(force_recovery=True) is False
        assert client.calls == 0
        assert restarted.snapshot()["mode"] == "offline"
        assert restarted.usage_eligibility() == (
            False,
            "offline_license_device_mismatch",
        )
        assert restarted.snapshot()["status"] == "offline_license_device_mismatch"
        restarted.stop()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_edit_printer_missing_registration_state_saves_nothing(tmp_path, monkeypatch):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    messages: list[tuple[str, str]] = []
    try:
        wizard = SetupWizardV5(edit_mode=True)
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        monkeypatch.setattr(
            wizard,
            "_show_wizard_message",
            lambda title, message, **_kwargs: messages.append((title, message)),
        )

        wizard._save()

        assert wizard.result() == int(QDialog.DialogCode.Rejected)
        assert DeviceConfigRepository().list() == []
        assert V52RuntimeStateRepository().internal() is None
        assert messages and "ไม่พบสถานะ Registration เดิม" in messages[0][1]
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_does_not_scan_before_user_enters_device_step(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])

        assert wizard.stack.currentIndex() == 0
        assert wizard._scan_thread is None
        assert "ยังไม่ได้สแกนเครือข่าย" in wizard.scan_status.text()
        assert not wizard.legacy_import_button.isHidden()
        assert wizard.legacy_import_button.parent() is wizard.database_path_container
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_creates_and_persists_selected_database_path(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    target = tmp_path / "customer-data" / "KOMI_Report_V5.db"
    runtime_config = tmp_path / "runtime.toml"
    try:
        wizard = SetupWizardV5(runtime_config_path=str(runtime_config))

        assert wizard.database_path_input.text() == str(Path(database.get_db_path()).resolve())
        assert wizard._set_database_destination(str(target)) is True
        assert not target.exists()

        wizard._activate_selected_database_path()

        assert database.get_db_path() == target.resolve()
        assert target.is_file()
        assert load_runtime_settings(config_path=runtime_config).db_path == target.resolve()
        with sqlite3.connect(target) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='readings'"
            ).fetchone() == ("readings",)
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_can_defer_pricing_with_explicit_no_charge_state(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard._next()
        wizard._next()
        _confirm_meter(wizard)
        wizard._next()
        wizard.deferred_price_mode.setChecked(True)

        assert wizard.shared_price_box.isHidden()
        assert wizard.per_device_price_box.isHidden()
        assert not wizard.deferred_price_notice.isHidden()
        assert wizard.billing_section.isHidden()

        wizard._next()
        assert wizard.stack.currentIndex() == 4
        assert "ตั้งค่าภายหลัง" in wizard.review_sections["pricing"].text()
        assert "ยังไม่คิดค่าใช้จ่าย" in wizard.review_sections["pricing"].text()
        _confirm_meter(wizard)
        wizard._save()

        assert database.get_cfg("pricing_mode") == "deferred"
        assert PricingRepository().get_prices(0, date.today()).a4_color == 0.0
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_company_validation_is_inline_and_recovers_on_typing(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])
        wizard.company_name_input.clear()

        wizard._next()

        assert wizard.stack.currentIndex() == 0
        assert not wizard.company_name_error.isHidden()
        assert wizard.company_name_error.text() == "กรุณากรอกชื่อบริษัท"
        assert "#B42318" in wizard.company_name_input.styleSheet()

        wizard.company_name_input.setText("บริษัท ลูกค้า จำกัด")
        assert wizard.company_name_error.isHidden()
        assert "#B8C7D9" in wizard.company_name_input.styleSheet()
        wizard._next()
        assert wizard.stack.currentIndex() == 1
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_owned_alert_keeps_copy_and_action_inside_dialog(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])
        dialog = wizard._build_wizard_message(
            "ข้อมูลไม่ครบ",
            "ทุกเครื่องที่เลือกต้องผ่านทั้ง SNMP และ Web Connection ก่อนดำเนินการ",
        )
        dialog.show()
        app.processEvents()

        message = dialog.findChild(QLabel, "wizard_alert_message")
        confirm = dialog.findChild(QPushButton, "btn_primary")
        assert dialog.minimumWidth() >= 500
        assert message is not None and message.wordWrap()
        assert message.width() >= 350
        assert confirm is not None and confirm.text() == "ตกลง"
        assert confirm.minimumWidth() >= 104
        assert confirm.geometry().right() <= dialog.contentsRect().right()

        dialog.close()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_requires_explicit_deferred_choice_for_all_zero_prices(
    tmp_path, monkeypatch
):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    warnings = []
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard._next()
        wizard._next()
        _confirm_meter(wizard)
        wizard._next()
        monkeypatch.setattr(
            wizard,
            "_show_wizard_message",
            lambda title, message, **_kwargs: warnings.append((title, message)),
        )

        wizard._next()

        assert wizard.stack.currentIndex() == 3
        assert warnings[0][0] == "ราคายังเป็น 0.00 ทั้งหมด"
        assert "ตั้งค่าราคาภายหลัง" in warnings[0][1]
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_price_fields_keep_currency_outside_the_input(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        assert wizard.shared_price_row["a4_color"].suffix() == ""
        assert wizard.shared_price_row["a4_color"].minimumHeight() >= 42
        assert wizard.shared_price_row["a4_color"].maximumWidth() == 230
        assert wizard.price_content.maximumWidth() == 1280
        assert "ราคา 0.00" in wizard.price_intro.text()
        assert wizard.billing_end_day.count() == 31
        assert wizard.billing_end_day.maximumWidth() == 300
        assert wizard.billing_end_day.itemText(30) == "วันที่ 31 ของเดือน"
        wizard.billing_end_day.setCurrentIndex(14)
        assert wizard._billing_day() == 15
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_shared_pricing_and_billing_fit_without_scrolling(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5(legacy_source_paths=[])
        wizard.stack.setCurrentIndex(3)
        wizard.resize(1120, 720)
        wizard.show()
        app.processEvents()

        assert wizard.shared_price_mode.isChecked()
        assert wizard.price_scroll.verticalScrollBar().maximum() == 0
        assert wizard.billing_section.isVisible()
        assert wizard.billing_section.geometry().bottom() <= wizard.price_scroll.viewport().height()
        assert wizard.waste_paper_pct.isVisible()
        assert wizard.billing_end_day.isVisible()

        wizard.resize(980, 620)
        app.processEvents()
        assert wizard.price_scroll.verticalScrollBar().maximum() == 0
        assert wizard.billing_section.geometry().bottom() <= wizard.price_scroll.viewport().height()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


@pytest.fixture(autouse=True)
def accept_reviewed_setup_in_existing_workflow_tests(monkeypatch):
    monkeypatch.setattr(setup_wizard, "confirm_shared_settings", lambda *_: True)


def test_setup_cancel_shared_review_does_not_configure_or_register(tmp_path, monkeypatch):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        monkeypatch.setattr(setup_wizard, "confirm_shared_settings", lambda *_: False)
        _confirm_meter(wizard)
        wizard._save()
        assert DeviceConfigRepository().list(enabled_only=True) == []
        assert V52RuntimeStateRepository().internal() is None
        with database._open(commit=False) as conn:
            assert conn.execute("SELECT count(*) FROM price_history").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM peer_settings_revisions").fetchone()[0] == 0
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_change_during_review_keeps_external_edit_and_draft(tmp_path, monkeypatch):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        errors = []
        def review(*_args):
            database.set_cfg("billing_day", "22")
            return True
        monkeypatch.setattr(setup_wizard, "confirm_shared_settings", review)
        monkeypatch.setattr(wizard, "_show_wizard_message", lambda *args: errors.append(args))
        _confirm_meter(wizard)
        wizard._save()
        assert errors and "เปลี่ยน" in errors[0][1]
        assert database.get_cfg("billing_day") == "22"
        assert DeviceConfigRepository().list(enabled_only=True) == []
        assert V52RuntimeStateRepository().internal() is None
        assert wizard._configs()[0].host == "192.0.2.10"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_new_printer_save_cannot_bypass_meter_confirmation(monkeypatch):
    QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Meter review test")
    wizard = SetupWizardV5(legacy_source_paths=[])
    _add_selected_device(wizard, "New printer", "192.0.2.10")
    messages = []
    monkeypatch.setattr(wizard, "_show_wizard_message", lambda *args, **kwargs: messages.append(args))

    wizard._save()

    assert messages
    assert DeviceConfigRepository().list(enabled_only=True) == []
    with database._open(commit=False) as connection:
        assert connection.execute("SELECT COUNT(*) FROM slot_meter_heads").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM web_observations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM price_history").fetchone()[0] == 0
    wizard.close()


def test_three_printers_require_individual_confirmation_before_the_single_pricing_step():
    QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Meter review test")
    wizard = SetupWizardV5(legacy_source_paths=[])
    for index in range(3):
        _add_selected_device(wizard, f"Printer {index + 1}", f"192.0.2.{10 + index}", total=100 + index)
    wizard._next()
    wizard._next()
    assert wizard.stack.currentWidget() is wizard.meter_step
    assert wizard.meter_step.device_combo.count() == 3
    assert wizard.meter_step.views.count() == 2
    assert not wizard.next_button.isEnabled()
    pricing = wizard.pricing_step

    for index in range(3):
        wizard.meter_step.device_combo.setCurrentIndex(index)
        assert wizard.meter_step.raw_table.rowCount() > 0
        assert wizard.meter_step.parser_table.rowCount() > 0
        wizard.meter_step.confirmation.setChecked(True)
        assert wizard.next_button.isEnabled() is (index == 2)
    assert wizard.meter_step.confirmed_slots == (0, 1, 2)
    wizard._next()
    assert wizard.stack.currentWidget() is pricing
    assert wizard.step_label.text() == "4 / 5"
    wizard._back()
    assert wizard.stack.currentWidget() is wizard.meter_step
    assert wizard.meter_step.confirmed_slots == (0, 1, 2)
    wizard._next()
    wizard.deferred_price_mode.setChecked(True)
    wizard._next()
    assert wizard.stack.currentWidget() is wizard.review_step
    assert not wizard.review_step.meter_section.isHidden()
    assert not wizard.review_step.meter_edit_button.isHidden()
    assert "Slot 3" in wizard.review_sections["meter"].text()
    wizard.review_step.meter_edit_button.click()
    assert wizard.stack.currentWidget() is wizard.meter_step
    assert wizard.meter_step.confirmed_slots == (0, 1, 2)
    wizard._next()
    wizard._next()
    wizard._go_to_step(3)
    assert wizard.stack.currentWidget() is pricing
    wizard._save()
    with database._open(commit=False) as connection:
        assert connection.execute("SELECT COUNT(*) FROM slot_meter_heads").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM web_observations").fetchone()[0] == 3
    wizard.close()


def test_reading_refresh_requires_new_confirmation_and_stale_result_cannot_change_evidence():
    QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Meter review test")
    wizard = SetupWizardV5(legacy_source_paths=[])
    _add_selected_device(wizard, "New printer", "192.0.2.10")
    _confirm_meter(wizard)
    before = dict(wizard._meter_evidence)
    wizard._test_result(DeviceTestResult(
        generation=wizard._test_generation - 1, host="192.0.2.10", slot=0,
        payload={"online": True, "web_ok": True, "serial": "WRONG-OLD-RESULT",
                 "total": 999, "meter_reading": _meter_reading("192.0.2.10", 999)},
    ))
    assert wizard._meter_evidence == before
    assert wizard.meter_step.confirmed_slots == (0,)

    wizard._test_result(DeviceTestResult(
        generation=wizard._test_generation, host="192.0.2.10", slot=0,
        payload={"online": True, "web_ok": True, "serial": "SN-10",
                 "total": 101, "meter_reading": _meter_reading("192.0.2.10", 101)},
    ))
    wizard._enter_meter_step()
    assert wizard._meter_evidence != before
    assert wizard.meter_step.confirmed_slots == ()
    assert not wizard.next_button.isEnabled()
    wizard.close()


def test_legacy_printer_with_successful_history_skips_new_baseline_and_back_skips_meter():
    QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Existing customer")
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(
        0, "Legacy printer", "192.0.2.10", serial="SN-10", last_total=100,
        last_success_at="2026-08-20T09:00:00+07:00",
    )])
    wizard = SetupWizardV5(legacy_source_paths=[])
    _add_selected_device(wizard, "Legacy printer", "192.0.2.10", total=110)
    wizard._next()
    wizard._next()
    assert wizard.stack.currentWidget() is wizard.pricing_step
    assert wizard.meter_step.confirmed_slots == ()
    wizard._back()
    assert wizard.stack.currentWidget() is wizard.devices_step
    with database._open(commit=False) as connection:
        assert connection.execute("SELECT COUNT(*) FROM slot_meter_heads").fetchone()[0] == 0
        assert connection.execute("SELECT last_total FROM devices WHERE slot=0").fetchone()[0] == 100
    wizard.deferred_price_mode.setChecked(True)
    wizard._save()
    assert wizard.result() == int(QDialog.DialogCode.Accepted)
    with database._open(commit=False) as connection:
        assert connection.execute("SELECT last_success_at FROM devices WHERE slot=0").fetchone()[0] == "2026-08-20T09:00:00+07:00"
    wizard.close()
    reopened = SetupWizardV5(legacy_source_paths=[])
    _add_selected_device(reopened, "Legacy printer", "192.0.2.10", total=111)
    reopened._next()
    reopened._next()
    assert reopened.stack.currentWidget() is reopened.pricing_step
    assert reopened.meter_step.confirmed_slots == ()
    with database._open(commit=False) as connection:
        assert connection.execute("SELECT COUNT(*) FROM slot_meter_heads").fetchone()[0] == 0
    reopened.close()


def test_confirmed_meter_is_committed_to_the_selected_first_run_database(tmp_path):
    QApplication.instance() or QApplication([])
    original_path = database.get_db_path()
    database.set_cfg("company_name", "First run customer")
    target = tmp_path / "customer-data" / "selected.sqlite3"
    runtime_config = tmp_path / "selected-runtime.toml"
    wizard = SetupWizardV5(legacy_source_paths=[], runtime_config_path=str(runtime_config))
    try:
        _add_selected_device(wizard, "New printer", "192.0.2.10", total=2475)
        assert wizard._set_database_destination(str(target))
        _confirm_meter(wizard)
        wizard.deferred_price_mode.setChecked(True)
        wizard._save()

        assert wizard.result() == int(QDialog.DialogCode.Accepted)
        assert database.get_db_path() == target.resolve()
        assert load_runtime_settings(config_path=runtime_config).db_path == target.resolve()
        with sqlite3.connect(target) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert connection.execute("SELECT serial FROM devices WHERE slot=0").fetchone() == ("SN-10",)
            assert connection.execute("SELECT COUNT(*) FROM slot_meter_heads").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM web_observations").fetchone()[0] == 1
        with sqlite3.connect(original_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM slot_meter_heads").fetchone()[0] == 0
    finally:
        wizard.close()
        database.set_db_path(original_path)


def test_authentication_edit_invalidates_evidence_and_rejects_inflight_old_connection_result():
    app = QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Meter review test")
    wizard = SetupWizardV5(legacy_source_paths=[])
    _add_selected_device(wizard, "New printer", "192.0.2.10")
    _confirm_meter(wizard)
    previous = wizard._configs()[0]
    in_flight = DeviceTestResult(
        generation=wizard._test_generation, host=previous.host, slot=previous.slot,
        payload={"online": True, "web_ok": True, "serial": previous.serial,
                 "total": 200, "meter_reading": _meter_reading(previous.host, 200)},
        connection_key=device_test_key(previous),
    )
    wizard._open_credentials(previous.host)
    dialog = wizard._wizard_child_dialogs[-1]
    password = next(field for field in dialog.findChildren(QLineEdit)
                    if field.echoMode() == QLineEdit.EchoMode.Password)
    password.setText("synthetic-updated-password")
    dialog.accept()
    app.processEvents()
    assert wizard._meter_evidence == {}
    assert wizard.meter_step.confirmed_slots == ()
    assert wizard._configs()[0].password == "synthetic-updated-password"

    wizard._test_result(in_flight)

    assert wizard._meter_evidence == {}
    assert not wizard.discovered_devices[0]["result"]["web_ok"]
    wizard.close()


def test_explicit_xml_selection_roundtrips_and_invalidates_old_evidence():
    app = QApplication.instance() or QApplication([])
    database.set_cfg("company_name", "Synthetic XML test")
    wizard = SetupWizardV5(legacy_source_paths=[])
    try:
        _add_selected_device(wizard, "bizhub 367", "192.0.2.10")
        _confirm_meter(wizard)
        previous = wizard._configs()[0]
        wizard._open_credentials(previous.host)
        dialog = wizard._wizard_child_dialogs[-1]
        combo = dialog.findChild(QComboBox, "web_protocol")
        assert combo.currentData() == "auto"
        combo.setCurrentIndex(combo.findData("legacy_xml_public"))
        password = next(field for field in dialog.findChildren(QLineEdit)
                        if field.echoMode() == QLineEdit.EchoMode.Password)
        assert not password.isEnabled()
        dialog.accept()
        app.processEvents()
        assert wizard._configs()[0].web_protocol == "legacy_xml_public"
        assert wizard._meter_evidence == {}
        assert device_test_key(previous) != device_test_key(wizard._configs()[0])
        wizard._open_credentials(previous.host)
        dialog = wizard._wizard_child_dialogs[-1]
        combo = dialog.findChild(QComboBox, "web_protocol")
        assert combo.currentData() == "legacy_xml_public"
        combo.setCurrentIndex(combo.findData("legacy_xml_admin"))
        password = next(field for field in dialog.findChildren(QLineEdit)
                        if field.echoMode() == QLineEdit.EchoMode.Password)
        assert password.isEnabled()
        dialog.accept()
        app.processEvents()
        assert wizard._configs()[0].web_protocol == "legacy_xml_admin"
    finally:
        wizard.close()


@pytest.mark.parametrize("protocol", ["legacy_xml_public", "legacy_xml_admin"])
def test_setup_worker_passes_explicit_xml_choice_even_when_snmp_identifies_unknown_model(monkeypatch, protocol):
    monkeypatch.setattr("ui.setup.workers.SnmpTotalProbe.read", lambda *_: SimpleNamespace(
        model="bizhub 457", serial="SYNTHETIC", total=100, total_oid="1.2.3", oid_values=()))
    calls = []
    def read(reader, host, *, model, web_protocol):
        calls.append((model, web_protocol))
        return MeterReading.create(host,
            [WebCounterValue("counter.total.total", "Total", 100, "Total", "synthetic")],
            "xml", WebAuthState.PUBLIC if protocol == "legacy_xml_public" else WebAuthState.ADMIN)
    monkeypatch.setattr("ui.setup.workers.MeterReader.read", read)
    device = DeviceConfig(0, "Synthetic", "192.0.2.10", web_protocol=protocol)
    result = DeviceTestWorker([device])._test(device)
    assert result["web_ok"]
    assert calls == [("bizhub 457", protocol)]


def test_waste_hover_explains_quantity_rounding_and_preserves_zero():
    app = QApplication.instance() or QApplication([])
    database.set_cfg('waste_paper_pct', '0')
    wizard = SetupWizardV5(legacy_source_paths=[])
    try:
        assert wizard.waste_paper_pct.value() == 0
        assert '101' in wizard.waste_paper_pct.toolTip()
        assert '96' in wizard.waste_paper_pct.toolTip()
        assert '.5' in wizard.waste_paper_pct.toolTip()
    finally:
        wizard.close()
        app.processEvents()
