from __future__ import annotations

import inspect
import os
from datetime import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTime
from PyQt6.QtWidgets import QAbstractButton, QApplication, QDialog, QLabel, QWidget

import database
import v5_pages
from i18n import apply_language, set_language
from pages import PageSettings
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.sync_schedule import default_schedule_windows, load_schedule_windows
from services.web_access import ACCESS_HASH_KEY, verify_web_access_code
from services.web_service import WebServiceStatus
from v5_pages import PageFleetSettings, PageSettingsV5, WebAccessCodeDialog


class _LegacySettings(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._authenticated = False
        self.unlock_calls = 0
        self.embed_mode = False

    def set_v5_embed_mode(self) -> None:
        self.embed_mode = True

    def ensure_unlocked(self) -> bool:
        self.unlock_calls += 1
        self._authenticated = True
        return True


class _RegistrationRuntimeDouble:
    def __init__(self, **overrides) -> None:
        self.data = {
            "mode": "online",
            "status": "not_configured",
            "last_sent_at": "",
            "next_attempt_at": "",
            "support_code": "",
            "notice_accepted": False,
            "offline_license": None,
            **overrides,
        }
        self.retry_calls = 0
        self.accept_calls: list[tuple[str, str]] = []
        self.request_paths: list[Path] = []
        self.license_imports: list[tuple[Path, dict[str, str]]] = []

    def snapshot(self) -> dict[str, object]:
        return dict(self.data)

    def retry_now(self) -> int:
        self.retry_calls += 1
        self.data["status"] = "pending"
        return 1

    def accept_notice(self, version: str, accepted_at: str) -> None:
        self.accept_calls.append((version, accepted_at))
        self.data["notice_accepted"] = True

    def set_mode(self, mode: str) -> None:
        self.data["mode"] = mode
        self.data["status"] = (
            "offline_request_required" if mode == "offline" else "waiting_for_internet"
        )

    def create_offline_request(self, path: Path) -> Path:
        self.request_paths.append(path)
        self.data["status"] = "offline_request_ready"
        return path

    def import_offline_license(
        self, path: Path, host_public_keys: dict[str, str]
    ) -> object:
        self.license_imports.append((path, dict(host_public_keys)))
        self.data["status"] = "offline_license"
        self.data["offline_license"] = {
            "expires_at": "2031-08-25T08:00:00Z",
            "bound_devices": [
                {
                    "model": "Synthetic Printer",
                    "serial_number": "SYNTH-UI-1",
                    "device_slot": 1,
                }
            ],
        }
        return object()


class _WebServiceDouble:
    def __init__(self, root: Path) -> None:
        self.started = 0
        self.stopped = 0
        self.restarted = 0
        self.log_path = root / "web-service.log"
        self.runtime_root = root / "web-runtime"

    def _status(self, state: str = "stopped") -> WebServiceStatus:
        port = v5_pages.read_web_port(self.runtime_root / ".env.local")
        return WebServiceStatus(
            state=state,
            local_url=f"http://127.0.0.1:{port}",
            lan_url=f"http://192.0.2.1:{port}",
            detail="test web service",
            log_path=self.log_path,
        )

    def status(self) -> WebServiceStatus:
        return self._status("running" if self.started > self.stopped else "stopped")

    def start(self) -> WebServiceStatus:
        self.started += 1
        return self._status("running")

    def stop(self) -> WebServiceStatus:
        self.stopped += 1
        return self._status("stopped")

    def restart(self) -> WebServiceStatus:
        self.restarted += 1
        return self._status("running")


@pytest.fixture(autouse=True)
def fake_web_service(monkeypatch, tmp_path):
    service = _WebServiceDouble(tmp_path)
    monkeypatch.setattr(v5_pages, "web_service_manager", lambda: service)
    return service


def _database(tmp_path):
    original = database.get_db_path()
    database.set_db_path(tmp_path / "settings.sqlite3")
    database.init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "DMS Printer", "192.0.2.10", model="bizhub C450i", serial="SERIAL-1")]
    )
    return original


def _read_values(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )


def test_fleet_settings_groups_fields_and_live_schedule(tmp_path, monkeypatch, fake_web_service):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    planned: list[tuple[bool, bool]] = []
    registration = tmp_path / "autostart.registered"
    registration.write_text("synthetic registration", encoding="utf-8")

    def fake_configure_autostart(enabled: bool, *, apply: bool = True):
        planned.append((enabled, apply))
        if apply:
            if enabled:
                registration.write_text("synthetic registration", encoding="utf-8")
            else:
                registration.unlink(missing_ok=True)
        return registration

    try:
        monkeypatch.setattr(
            v5_pages,
            "configure_autostart",
            fake_configure_autostart,
        )
        page = PageFleetSettings()
        page.resize(1000, 1200)
        page.show()
        app.processEvents()

        assert "DMS Printer" in page.device_summary.text()
        assert "SERIAL-1" not in page.device_summary.text()
        assert "192.0.2.10" not in page.device_summary.text()
        assert "SERIAL-1" in page.device_summary.toolTip()
        assert "192.0.2.1:3000" in page.web_service_url.text()
        assert "127.0.0.1:3000" not in page.web_service_url.text()
        assert "ฐานข้อมูลที่กำลังใช้งาน:" in page.active_database_path.text()
        assert str(database.get_db_path()) in page.active_database_path.text()
        assert page.autostart.isChecked()
        assert page.web_service_enabled.isChecked()
        assert "พบ OS registration" in page.autostart_status.text()
        assert not page.billing_save_button.isEnabled()
        assert not page.schedule_save_button.isEnabled()
        assert page.web_save_button.isEnabled()
        assert "ต้องแก้ไข" in page.web_task_summary.text()
        assert all(editor.isHidden() for editor in page._task_editors.values())
        assert page.schedule_windows_table.rowCount() == 5
        assert "ใช้ค่าแนะนำของระบบ" in page.schedule.text()
        assert "รอการบันทึก" not in page.schedule.text()
        assert [controls[0].text() for controls in page._schedule_row_controls] == [
            "นอกเวลางาน", "ช่วงเร่งด่วน", "เวลาทำงาน", "ช่วงเร่งด่วน", "นอกเวลางาน"
        ]

        page._set_active_editor("schedule")
        _name, _clock_range, _weekdays, snmp_interval, web_interval = page._schedule_row_controls[2]
        snmp_interval.setValue(20)
        web_interval.setValue(75)

        assert page.schedule_save_button.isEnabled()
        assert page._dirty_sections == {"schedule"}
        assert "ตั้งเวลาอ่านข้อมูลไว้ 5 ช่วง" in page.schedule.text()
        assert "ไม่จำเป็นต้องเปลี่ยนค่ารายละเอียด" in page.schedule.text()

        page._refresh_web_status(
            WebServiceStatus(
                state="stopped",
                local_url="http://127.0.0.1:3000",
                lan_url="http://127.0.0.1:3000",
                detail="test web service",
                log_path=tmp_path / "web-service.log",
            )
        )
        assert "ยังไม่พบที่อยู่ LAN" in page.web_service_url.text()
        assert "127.0.0.1" not in page.web_service_url.text()

        page._save_schedule()
        assert all(apply is False for _enabled, apply in planned)
        stored_windows = load_schedule_windows(database.get_cfg("sync_schedule_windows"))
        assert stored_windows is not None
        assert [item.label for item in stored_windows] == [
            "นอกเวลางาน", "ช่วงเร่งด่วน", "เวลาทำงาน", "ช่วงเร่งด่วน", "นอกเวลางาน"
        ]
        assert int(stored_windows[2].snmp_interval.total_seconds() // 60) == 20
        assert int(stored_windows[2].web_interval.total_seconds() // 60) == 75
        assert stored_windows[2].weekdays == frozenset(range(5))

        page._set_active_editor("billing")
        page.waste.setValue(2.5)
        page._save_billing()
        assert database.get_cfg("waste_paper_pct") == "2.5"

        page._set_active_editor("web")
        page.web_service_enabled.setChecked(False)
        page.web_service_enabled.setChecked(True)
        page._save_web()
        assert database.get_cfg("web_service_enabled") == "1"
        assert fake_web_service.started == 1
        assert not page.web_save_button.isEnabled()
        assert not page._dirty_sections
        page.close()
    finally:
        database.set_db_path(original)


def test_fleet_settings_toggle_stops_web_service(tmp_path, monkeypatch, fake_web_service):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    registration = tmp_path / "autostart.registered"
    try:
        monkeypatch.setattr(v5_pages, "configure_autostart", lambda _enabled, *, apply=True: registration)
        database.set_cfg("web_service_enabled", "1")
        page = PageFleetSettings()
        page.web_service_enabled.setChecked(False)
        page._save_web()

        assert database.get_cfg("web_service_enabled") == "0"
        assert fake_web_service.stopped == 1
        assert "ปิดอยู่" in page.web_service_status.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_compact_settings_opens_one_editor_and_preserves_dirty_draft(
    tmp_path,
    monkeypatch,
):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    registration = tmp_path / "autostart.registered"
    registration.write_text("synthetic registration", encoding="utf-8")
    notices: list[tuple[str, str]] = []
    try:
        monkeypatch.setattr(
            v5_pages,
            "configure_autostart",
            lambda _enabled, *, apply=True: registration,
        )
        monkeypatch.setattr(
            v5_pages,
            "show_compact_information",
            lambda _parent, title, message: notices.append((title, message)),
        )
        database.set_cfg("waste_paper_pct", "2")
        page = PageFleetSettings()

        page.billing_toggle.setChecked(True)
        assert not page.billing_editor.isHidden()
        assert page._active_editor == "billing"

        page.waste.setValue(7.5)
        assert page._dirty_sections == {"billing"}
        assert page.has_unsaved_changes()
        assert page.refresh_from_config() is False
        assert page.waste.value() == 7.5

        page.web_toggle.setChecked(True)
        assert page._active_editor == "billing"
        assert not page.billing_editor.isHidden()
        assert page.web_task_editor.isHidden()
        assert notices and "บันทึกหรือยกเลิก" in notices[-1][1]

        page._cancel_section("billing")
        assert page.waste.value() == 2.0
        assert not page._dirty_sections
        assert not page.has_unsaved_changes()
        page.web_toggle.setChecked(True)
        assert page._active_editor == "web"
        assert not page.web_task_editor.isHidden()
        assert page.billing_editor.isHidden()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_web_recovery_can_start_enabled_but_stopped_service_without_toggling(
    tmp_path,
    monkeypatch,
    fake_web_service,
):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    registration = tmp_path / "autostart.registered"
    try:
        monkeypatch.setattr(
            v5_pages,
            "configure_autostart",
            lambda _enabled, *, apply=True: registration,
        )
        database.set_cfg("web_service_enabled", "1")
        page = PageFleetSettings()

        assert page.web_service_enabled.isChecked()
        assert page.web_save_button.isEnabled()
        assert "ต้องแก้ไข" in page.web_task_summary.text()
        assert not page.has_unsaved_changes()

        page._set_active_editor("web")
        page._save_web()

        assert fake_web_service.started == 1
        assert "เปิดอยู่" in page.web_task_summary.text()
        assert not page.web_save_button.isEnabled()
        assert not page.has_unsaved_changes()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_edit_mode_wizard_keeps_billing_owned_by_settings():
    source = inspect.getsource(v5_pages.SetupWizardV5._save)

    assert 'if not self.edit_mode:' in source
    assert 'set_cfg("billing_day"' in source
    assert 'set_cfg("waste_paper_pct"' in source


def test_web_access_dialog_validates_match_and_minimum_length():
    app = QApplication.instance() or QApplication([])
    dialog = WebAccessCodeDialog()

    dialog.access_code.setText("short")
    dialog.confirm_code.setText("short")
    dialog._validate_and_accept()
    assert dialog.result() == 0
    assert "อย่างน้อย 12" in dialog.error.text()

    dialog.access_code.setText("Valid-LAN-Code-2026")
    dialog.confirm_code.setText("different-code")
    dialog._validate_and_accept()
    assert dialog.result() == 0
    assert "ไม่ตรงกัน" in dialog.error.text()

    dialog.confirm_code.setText("Valid-LAN-Code-2026")
    dialog._validate_and_accept()
    assert dialog.result() == int(QDialog.DialogCode.Accepted)
    dialog.close()
    app.processEvents()


def test_desktop_changes_web_access_and_restarts_owned_service(tmp_path, monkeypatch, fake_web_service):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    registration = tmp_path / "autostart.registered"
    registration.write_text("synthetic registration", encoding="utf-8")
    try:
        monkeypatch.setattr(v5_pages, "configure_autostart", lambda _enabled, *, apply=True: registration)
        fake_web_service.started = 1
        page = PageFleetSettings()

        status = page._apply_web_access_code("Valid-LAN-Code-2026")
        stored = _read_values(fake_web_service.runtime_root / ".env.local")

        assert status.state == "running"
        assert fake_web_service.restarted == 1
        assert verify_web_access_code("Valid-LAN-Code-2026", stored[ACCESS_HASH_KEY])
        assert "Valid-LAN-Code-2026" not in (fake_web_service.runtime_root / ".env.local").read_text(encoding="utf-8")
        assert "ไม่ใช้รหัส" in page.web_access_status.text()
        assert page.change_web_access_button.text() == "เปลี่ยนรหัสเจ้าหน้าที่"
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_fleet_settings_allows_adding_and_removing_custom_schedule_windows(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    registration = tmp_path / "autostart.registered"
    registration.write_text("synthetic registration", encoding="utf-8")
    try:
        monkeypatch.setattr(v5_pages, "configure_autostart", lambda _enabled, *, apply=True: registration)
        page = PageFleetSettings()

        page._add_schedule_window()
        name, clock_range, weekdays, snmp_interval, web_interval = page._schedule_row_controls[-1]
        name.setText("รอบเช็กเที่ยง")
        clock_range.start.setTime(QTime(12, 0))
        clock_range.end.setTime(QTime(12, 20))
        for box in weekdays.boxes:
            box.setChecked(False)
        weekdays.boxes[5].setChecked(True)
        snmp_interval.setValue(2)
        web_interval.setValue(12)
        page._save_schedule()

        stored = load_schedule_windows(database.get_cfg("sync_schedule_windows"))
        assert stored is not None
        assert [item for item in stored if item.label != "รอบเช็กเที่ยง"] == list(default_schedule_windows())
        added = next(item for item in stored if item.label == "รอบเช็กเที่ยง")
        assert added.start == time(12, 0)
        assert added.end == time(12, 20)
        assert added.weekdays == frozenset({5})
        assert int(added.snmp_interval.total_seconds() // 60) == 2
        assert int(added.web_interval.total_seconds() // 60) == 12
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_fleet_autostart_reflects_missing_os_registration(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    registration = tmp_path / "missing-autostart-registration"
    planned: list[tuple[bool, bool]] = []
    try:
        monkeypatch.setattr(
            v5_pages,
            "configure_autostart",
            lambda enabled, *, apply=True: (
                planned.append((enabled, apply)) or registration
            ),
        )
        page = PageFleetSettings()
        page.show()
        app.processEvents()

        assert not page.autostart.isChecked()
        assert "ไม่พบ OS registration" in page.autostart_status.text()
        assert not page.schedule_save_button.isEnabled()
        assert not page.autostart_save_button.isEnabled()

        page.autostart.setChecked(True)
        assert page.autostart_save_button.isEnabled()
        assert not page.schedule_save_button.isEnabled()
        page._cancel_section("autostart")

        database.set_cfg("autostart_enabled", "1")
        page.refresh_from_config()
        assert not page.autostart.isChecked()
        assert "ไม่พบ OS registration" in page.autostart_status.text()
        assert len(planned) >= 2
        assert all(item == (True, False) for item in planned)
        page.close()
    finally:
        database.set_db_path(original)


def test_v5_database_path_tools_are_available_without_replacing_active_database(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    stale_path = tmp_path / "configured-but-not-active.sqlite3"
    try:
        database.set_cfg("db_path", str(stale_path))
        legacy = PageSettings()
        page = PageSettingsV5(legacy)
        page.resize(1000, 800)
        page.show()
        app.processEvents()

        active_path = str(database.get_db_path())
        assert not legacy._btn_change_db_path.isHidden()
        assert not legacy._v5_db_migration_note.isHidden()
        assert "ฐานข้อมูลที่กำลังใช้จะไม่ถูกทับ" in legacy._v5_db_migration_note.text()
        assert active_path in legacy.db_lbl.text()
        assert str(stale_path) not in legacy.db_lbl.text()
        assert active_path in page.fleet_content.active_database_path.text()
        assert str(stale_path) not in page.fleet_content.active_database_path.text()
        assert "เปลี่ยน Path" in page.fleet_content.active_database_path.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_v5_hides_duplicate_editors_and_opens_tools_without_password(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        legacy = PageSettings()
        page = PageSettingsV5(legacy)
        page.resize(1000, 800)
        page.show()
        app.processEvents()

        assert len(legacy._v5_duplicate_cards) == 4
        assert all(card.isHidden() for card in legacy._v5_duplicate_cards)

        page.setCurrentWidget(page.legacy)
        app.processEvents()

        assert all(card.isHidden() for card in legacy._v5_duplicate_cards)
        assert any(not widget.isHidden() for widget in legacy._protected_widgets)
        assert legacy._authenticated
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_settings_tools_do_not_request_password(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        legacy = _LegacySettings()
        page = PageSettingsV5(legacy)
        assert legacy.embed_mode

        page.setCurrentWidget(page.legacy)
        assert legacy.unlock_calls == 0
        # Advanced settings uses the shared tab shell without a password gate.
        assert page.currentWidget() is page.fleet
        assert page.ensure_unlocked()
        assert legacy.unlock_calls == 0
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_settings_shows_simple_registration_status_and_manual_retry(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    runtime = _RegistrationRuntimeDouble(
        status="retrying",
        next_attempt_at="2026-08-22T01:02:00+00:00",
        support_code="offline",
    )
    try:
        page = PageFleetSettings(registration_runtime=runtime)
        page.show()
        app.processEvents()

        assert "กำลังลองใหม่" in page.registration_summary.text()
        assert page.registration_retry_button.isVisible()
        assert page.registration_retry_button.isEnabled()
        assert page.registration_privacy_button.isVisible()
        assert page.registration_summary.toolTip() == ""
        assert page.registration_support_detail.isVisible() is False

        page.registration_retry_button.click()

        assert "จัดคิวใหม่แล้ว" in page.registration_summary.text()
        assert runtime.retry_calls == 1
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_registration_settings_copy_switches_to_english(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        set_language("en")
        page = PageFleetSettings()
        apply_language(page)
        page.show()
        app.processEvents()

        assert page.registration_privacy_button.text() == "View data sent"
        assert page.registration_summary.text().startswith("Not configured")
        assert "does not claim a printer fault" in page.registration_summary.text()
        assert page.registration_summary.accessibleName() == "Application registration status"
        page.close()
        app.processEvents()
    finally:
        set_language("th")
        database.set_db_path(original)


def test_settings_can_accept_current_privacy_notice_and_requeue(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    runtime = _RegistrationRuntimeDouble(status="waiting_for_internet")
    try:
        page = PageFleetSettings(registration_runtime=runtime)
        page.show()
        app.processEvents()

        assert page.registration_notice_accept.isEnabled()
        page.registration_notice_accept.click()

        assert runtime.accept_calls
        assert runtime.data["notice_accepted"] is True
        assert "รับทราบข้อมูลการลงทะเบียนแล้ว" in page.registration_summary.text()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_settings_routes_local_enqueue_failure_back_to_setup(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    runtime = _RegistrationRuntimeDouble(
        status="needs_review", support_code="contract_invalid"
    )
    try:
        page = PageFleetSettings(registration_runtime=runtime)
        page.show()
        app.processEvents()

        assert "ต้องตรวจสอบ" in page.registration_summary.text()
        assert page.registration_retry_button.text() == "ลองส่งอีกครั้ง"
        assert page.registration_retry_button.isEnabled()
        page.registration_retry_button.click()
        assert runtime.retry_calls == 1
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_offline_license_settings_are_hidden_while_activation_is_disabled(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    runtime = _RegistrationRuntimeDouble(
        mode="offline", status="offline_request_required"
    )
    host_keys = {"synthetic-kid": "synthetic-public-verification-value"}
    messages: list[str] = []
    monkeypatch.setattr(
        v5_pages.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "desktop-request"), ""),
    )
    monkeypatch.setattr(
        v5_pages.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(tmp_path / "desktop.komilicense"), ""),
    )
    monkeypatch.setattr(
        v5_pages.QMessageBox,
        "information",
        lambda *args: messages.append(" ".join(str(value) for value in args[1:])),
    )
    try:
        page = PageFleetSettings(
            registration_runtime=runtime,
            offline_license_public_keys=host_keys,
        )
        page.show()
        app.processEvents()

        assert not page.offline_request_button.isVisible()
        assert not page.offline_import_button.isVisible()
        assert not page.offline_license_summary.isVisible()
        assert not page.registration_offline_mode.isVisible()
        assert page.registration_retry_button.isVisible() is False
        visible_copy = " ".join(
            widget.text()
            for widget in page.findChildren((QLabel, QAbstractButton))
            if widget.isVisible()
        ).casefold()
        for forbidden in ("api key", "public key", "token", "synthetic-public"):
            assert forbidden not in visible_copy

        assert runtime.request_paths == []
        assert runtime.license_imports == []
        assert messages == []
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_disabled_offline_license_ui_does_not_call_export_runtime(
    tmp_path, monkeypatch
):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)

    class FailingRuntime(_RegistrationRuntimeDouble):
        def create_offline_request(self, path: Path) -> Path:
            raise ValueError("raw-private-key-and-token-detail")

    runtime = FailingRuntime(mode="offline", status="offline_request_required")
    warnings: list[str] = []
    monkeypatch.setattr(
        v5_pages.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(tmp_path / "desktop.komirequest"), ""),
    )
    monkeypatch.setattr(
        v5_pages.QMessageBox,
        "warning",
        lambda *args: warnings.append(" ".join(str(value) for value in args[1:])),
    )
    try:
        page = PageFleetSettings(registration_runtime=runtime)
        page.offline_request_button.click()

        assert warnings == []
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_settings_v5_routes_support_details_through_section_tabs(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        legacy = _LegacySettings()
        page = PageSettingsV5(legacy)

        assert page.fleet_content.schedule_editor.isHidden()
        assert page.fleet_content.support_details.isHidden()
        assert page.count() == 4
        assert page.section_tabs.count() == 4

        assert page.fleet_content.support_toggle.isHidden()
        assert page.fleet_content.support_details.isHidden()

        page.fleet_content.billing_audit_requested.emit()
        assert page.currentWidget() is page.audit

        page.show_main()
        page.fleet_content.activity_requested.emit()
        assert page.currentWidget() is page.activity

        page.show_main()
        page.fleet_content.advanced_tools_requested.emit()
        assert page.currentWidget() is page.fleet
        assert legacy.unlock_calls == 0
        assert not page.fleet_content.support_task_editor.isHidden()
        assert page.section_tabs.currentIndex() == 3
        assert page.fleet_content.autostart_program_card.parent() is page.fleet_content
        assert page.fleet_content.web_program_card.parent() is (
            page.fleet_content.support_task_editor
        )
        assert page.legacy_content.parent() is page.fleet_content.support_task_editor
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_advanced_settings_and_nested_lan_stay_inline_without_horizontal_scroll(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        legacy = PageSettings()
        page = PageSettingsV5(legacy)
        # This matches the content width left by the sidebar at the supported
        # 1024-pixel desktop viewport.
        page.resize(805, 720)
        page.show()
        page.show_advanced()
        app.processEvents()

        content = page.fleet_content
        assert page.currentWidget() is page.fleet
        assert content.support_task_editor.isVisibleTo(page)
        assert page.advanced_page.horizontalScrollBar().maximum() == 0

        # Exercise the real nested LAN toggle. The parent Advanced section
        # must remain visible, otherwise the LAN form is hidden by its parent.
        content.web_toggle.click()
        app.processEvents()
        assert content._active_editor == "web"
        assert content.support_task_editor.isVisibleTo(page)
        assert content.web_task_editor.isVisibleTo(page)
        assert page.advanced_page.horizontalScrollBar().maximum() == 0

        assert not content.web_report_require_password.isChecked()
        content.web_report_require_password.setChecked(True)
        app.processEvents()
        assert content.web_report_access_note.isHidden()
        assert content.web_access_status.isVisibleTo(page)
        content._dirty_sections.discard("web")

        content.web_toggle.click()
        app.processEvents()
        assert content._active_editor == "support"
        assert content.support_task_editor.isVisibleTo(page)
        assert content.web_task_editor.isHidden()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_schedule_delete_button_is_compact_and_removes_only_its_row(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        page = PageFleetSettings()
        page.resize(805, 720)
        page.show()
        assert page._set_active_editor("schedule")
        page.advanced_schedule_button.setChecked(True)
        app.processEvents()

        before = page.schedule_windows_table.rowCount()
        delete_buttons = [
            button
            for button in page.schedule_windows_table.findChildren(QAbstractButton)
            if button.text() == "✕"
        ]
        assert len(delete_buttons) == before
        assert all(
            button.fontMetrics().horizontalAdvance(button.text()) + 8
            <= button.maximumWidth()
            for button in delete_buttons
        )

        delete_buttons[-1].click()
        app.processEvents()
        assert page.schedule_windows_table.rowCount() == before - 1
        assert len(page._schedule_row_controls) == before - 1
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_v5_tools_hide_all_duplicate_device_and_billing_editors(tmp_path):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        legacy = PageSettings()
        page = PageSettingsV5(legacy)

        assert len(legacy._v5_duplicate_cards) == 4
        assert all(card.isHidden() for card in legacy._v5_duplicate_cards)
        assert not any(card in legacy._protected_widgets for card in legacy._v5_duplicate_cards)
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_settings_opens_setup_without_a_nested_dialog_event_loop():
    source = inspect.getsource(PageFleetSettings._edit_devices)

    assert "dialog.open()" in source
    assert ".exec(" not in source


def test_web_custom_port_is_saved_restarted_and_restored(tmp_path, monkeypatch, fake_web_service):
    import socket

    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        fake_web_service.started = 1
        page = PageFleetSettings()
        page.web_port.setValue(port)
        assert page.web_save_button.isEnabled()
        page._save_web()
        assert fake_web_service.restarted == 1
        assert v5_pages.read_web_port(fake_web_service.runtime_root / ".env.local") == port
        assert f":{port}" in page.web_service_url.text()
        page.refresh_from_config(force=True)
        assert page.web_port.value() == port
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_web_password_lock_sets_a_code_before_closing_reports(tmp_path, monkeypatch, fake_web_service):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    monkeypatch.setattr(v5_pages.WebAccessCodeDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(v5_pages.WebAccessCodeDialog, "value", lambda self: "Chosen-LAN-Password-2026")
    try:
        fake_web_service.started = 1
        page = PageFleetSettings()
        assert not page.web_report_require_password.isChecked()
        page.web_report_require_password.setChecked(True)
        page._save_web()
        env = fake_web_service.runtime_root / ".env.local"
        status = v5_pages.web_access_status(env)
        assert status.configured and not status.report_passwordless
        assert fake_web_service.restarted == 1
        assert verify_web_access_code("Chosen-LAN-Password-2026", _read_values(env)[ACCESS_HASH_KEY])
        assert page.web_report_require_password.isChecked()
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_cancel_password_setup_keeps_reports_open(tmp_path, monkeypatch, fake_web_service):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    monkeypatch.setattr(v5_pages.WebAccessCodeDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    try:
        page = PageFleetSettings()
        page.web_report_require_password.setChecked(True)
        page._save_web()
        status = v5_pages.web_access_status(fake_web_service.runtime_root / ".env.local")
        assert status.report_passwordless and not status.configured
        assert fake_web_service.restarted == 0
        assert "web" in page._dirty_sections
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_web_occupied_port_is_rejected_before_any_settings_change(tmp_path, monkeypatch, fake_web_service):
    import socket

    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    warnings = []
    monkeypatch.setattr(v5_pages.QMessageBox, "warning", lambda *args: warnings.append(args[-1]))
    try:
        page = PageFleetSettings()
        with socket.socket() as occupied:
            occupied.bind(("0.0.0.0", 0))
            occupied.listen()
            page.web_port.setValue(occupied.getsockname()[1])
            page.web_report_require_password.setChecked(True)
            page._save_web()
        assert warnings
        assert v5_pages.read_web_port(fake_web_service.runtime_root / ".env.local") == 3000
        assert v5_pages.web_access_status(fake_web_service.runtime_root / ".env.local").report_passwordless
        assert fake_web_service.restarted == 0
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)


def test_secondary_always_open_selector_restores_and_can_revoke(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    original = _database(tmp_path)
    monkeypatch.setenv("KOMI_PEER_SYNC_STATE_FILE", str(tmp_path / "peer.json"))
    try:
        database.set_cfg("installation_id", "test-primary")
        page = PageFleetSettings()
        page.peer_sync_mode.setCurrentIndex(2)
        page.peer_sync_authorize_button.click()
        assert v5_pages.pairing_window_status().always_open
        assert "เปิดตลอด" in page.peer_sync_status.text()
        page.refresh_from_config(force=True)
        assert page.peer_sync_mode.currentData() == "always"
        page.peer_sync_mode.setCurrentIndex(0)
        page.peer_sync_authorize_button.click()
        assert not v5_pages.pairing_window_status().open
        page.close()
        app.processEvents()
    finally:
        database.set_db_path(original)
