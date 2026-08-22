import json
import os
import secrets
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

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
    QPushButton,
    QTableWidget,
)

import database
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PricingRepository
from services.registration_repository import RegistrationRepository
from v5_pages import NetworkDiscoveryWorker, SetupWizardV5


def _wizard_database(tmp_path):
    original_path = database.get_db_path()
    database.set_db_path(tmp_path / "wizard.sqlite3")
    database.init_db()
    database.set_cfg("company_name", "บริษัท ทดสอบ จำกัด")
    database.set_cfg("client_first_started_at", "2026-08-20")
    return original_path


def _add_selected_device(wizard, name: str, host: str, *, total: int = 100) -> None:
    wizard._upsert_discovered(
        {
            "name": name,
            "host": host,
            "model": "bizhub C450i",
            "serial": f"SN-{host.rsplit('.', 1)[-1]}",
            "result": {"online": True, "web_ok": True, "model": "bizhub C450i", "total": total},
        },
        select=True,
    )


def _visible_thai_ui_texts(wizard) -> list[str]:
    """Return untranslated visible UI copy, excluding the intentional ไทย toggle."""
    has_thai = lambda value: any("\u0e00" <= char <= "\u0e7f" for char in value)
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
        wizard._save()

        assert PricingRepository().get_prices(0, date.today()).a4_color == 2.0
        assert PricingRepository().get_prices(1, date.today()).a4_color == 3.0
        assert database.get_cfg("pricing_mode") == "per_device"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_wizard_uses_the_approved_four_step_flow(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        assert wizard.stack.count() == 4
        assert wizard.step_label.text() == "1 / 4"
        assert wizard.company_name_input.text() == "บริษัท ทดสอบ จำกัด"
        assert wizard.first_started_input.isReadOnly()
        assert wizard.first_started_input.text() == "20/08/2026"
        assert wizard.version_input.isReadOnly()
        assert wizard.version_input.text() == "5.1.0"
        assert wizard.scan_button.text() == "ค้นหาเครื่องพิมพ์อัตโนมัติ"
        assert wizard.advanced_scan_button.text() == "กำหนดช่วง IP"
        assert wizard.manual_setup_button.text() == "เพิ่ม IP ด้วยตนเอง"
        assert wizard.test_button.text() == "ตรวจสอบเครื่องที่เลือก"
        assert wizard.fallback_actions.isHidden()

        _add_selected_device(wizard, "DMS Printer", "192.0.2.10", total=2341)

        wizard._next()
        assert wizard.stack.currentIndex() == 1
        assert wizard.step_label.text() == "2 / 4"
        wizard._next()
        assert wizard.stack.currentIndex() == 2
        assert wizard.step_label.text() == "3 / 4"
        wizard.shared_price_row["a4_color"].setValue(2.0)
        wizard.shared_price_row["a4_bw"].setValue(0.5)
        wizard.shared_price_row["a3_color"].setValue(4.0)
        wizard.shared_price_row["a3_bw"].setValue(1.0)
        wizard._next()
        assert wizard.stack.currentIndex() == 3
        assert wizard.step_label.text() == "4 / 4"
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
        assert "Version 5.1.0" in registration_review
        assert "bizhub C450i × 1" in registration_review
        assert "Serial Number + รุ่นเครื่อง + สถานะเลือกใช้" in registration_review
        assert "IP, MAC, hostname, Credential, Meter" in registration_review
        assert wizard.registration_status_label.text() == "ปิดการส่ง"
        assert wizard.privacy_notice_accepted.isEnabled() is False
        assert "ยังไม่ได้อนุมัติการส่งข้อมูล" in wizard.privacy_notice_status.text()
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


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
        wizard.stack.setCurrentIndex(2)
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
        with database._open(commit=False) as connection:
            raw_envelope = connection.execute(
                "SELECT payload_json FROM registration_outbox WHERE event_type='register'"
            ).fetchone()[0]
        envelope = json.loads(raw_envelope)
        assert envelope["installation_id"] == installation_id
        assert envelope["company_name"] == "บริษัท ทดสอบ จำกัด"
        assert envelope["schema_version"] == 2
        assert envelope["device_inventory"]["konica_discovered_count"] == 4
        assert envelope["device_inventory"]["devices"] == [
            {"serial_number": "SN-10", "model": "bizhub C450i", "selected": True, "device_slot": 1},
            {"serial_number": "SN-11", "model": "bizhub C450i", "selected": True, "device_slot": 2},
            {"serial_number": "SN-12", "model": "bizhub C650i", "selected": False, "device_slot": None},
            {"serial_number": "SN-13", "model": "bizhub C450i", "selected": False, "device_slot": None},
        ]
        assert database.get_cfg("registration_pending_envelope") == ""
        assert database.get_cfg("registration_status") == "pending"
        assert RegistrationRepository().summary().status == "pending"
        serialized = json.dumps(envelope).lower()
        for excluded in ("192.0.2.10", "192.0.2.13", "password", "meter", "user", "document", "application_log"):
            assert excluded not in serialized
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_completes_locally_when_registration_enqueue_fails(tmp_path):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")

        class FailingRegistrationRepository:
            def upsert_profile_and_enqueue_register(self, *args, **kwargs):
                raise RuntimeError("synthetic outbox failure")

        wizard.registration_repository = FailingRegistrationRepository()
        wizard._save()

        assert wizard.result() == int(QDialog.DialogCode.Accepted)
        assert DeviceConfigRepository().setup_complete() is True
        assert database.get_cfg("registration_status") == "action_required"
        wizard.close()
        app.processEvents()
    finally:
        database.set_db_path(original_path)


def test_setup_records_acknowledgement_only_for_complete_approved_notice(tmp_path, monkeypatch):
    original_path = _wizard_database(tmp_path)
    app = QApplication.instance() or QApplication([])
    policy_path = tmp_path / "registration-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "base_url": "https://staging.invalid.example",
                "environment": "staging",
                "bootstrap": {
                    "mode": "vault_header",
                    "header": "X-Synthetic-Bootstrap",
                    "vault_ref": "registration-bootstrap-reference",
                },
                "privacy_notice": {
                    "version": "notice-2026-08",
                    "approved": True,
                    "purpose": "Synthetic registration UI test",
                    "fields": [
                        "installation_id",
                        "company_name",
                        "client_first_started_at",
                        "app_version",
                        "platform",
                        "architecture",
                        "serial_number",
                        "model",
                        "selected",
                        "device_slot",
                        "timestamps",
                        "status",
                    ],
                    "retention": "Synthetic retention",
                    "deletion_contact": "privacy@example.invalid",
                    "legal_basis": "Synthetic legal basis",
                    "access_export": "Synthetic access/export workflow",
                    "approval_reference": "SYNTHETIC-DPO-TEST-REFERENCE",
                    "approved_at": "2026-08-22T00:00:00+00:00",
                    "approval_owner": "Synthetic Test Approver",
                },
                "request_timeout_seconds": 15,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("KOMI_REGISTRATION_POLICY_FILE", str(policy_path))
    try:
        wizard = SetupWizardV5()
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")

        assert wizard.privacy_notice_accepted.isEnabled()
        wizard.privacy_notice_accepted.setChecked(True)
        wizard._save()

        profile = RegistrationRepository().profile()
        assert profile is not None
        assert profile.notice_version == "notice-2026-08"
        assert profile.notice_accepted_at
        assert RegistrationRepository().summary().status == "pending"
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
        wizard = SetupWizardV5(edit_mode=True)
        _add_selected_device(wizard, "DMS Printer", "192.0.2.10")
        wizard.shared_price_mode.setChecked(True)
        wizard.shared_price_row["a4_color"].setValue(2.0)
        wizard.billing_end_day.setCurrentIndex(30)
        wizard.waste_paper_pct.setValue(9.0)

        assert wizard.billing_section.isHidden()
        wizard._save()

        assert database.get_cfg("billing_day") == "17"
        assert database.get_cfg("waste_paper_pct") == "3.5"
        assert PricingRepository().get_prices(0, date.today()).a4_color == 2.0
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
        assert f'db_path = "{target.resolve()}"' in runtime_config.read_text(encoding="utf-8")
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
        wizard.deferred_price_mode.setChecked(True)

        assert wizard.shared_price_box.isHidden()
        assert wizard.per_device_price_box.isHidden()
        assert not wizard.deferred_price_notice.isHidden()
        assert wizard.billing_section.isHidden()

        wizard._next()
        assert wizard.stack.currentIndex() == 3
        assert "ตั้งค่าภายหลัง" in wizard.review_sections["pricing"].text()
        assert "ยังไม่คิดค่าใช้จ่าย" in wizard.review_sections["pricing"].text()
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
        monkeypatch.setattr(
            wizard,
            "_show_wizard_message",
            lambda title, message, **_kwargs: warnings.append((title, message)),
        )

        wizard._next()

        assert wizard.stack.currentIndex() == 2
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
        wizard.stack.setCurrentIndex(2)
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
