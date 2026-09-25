"""Fleet UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import socket
import webbrowser
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from database import get_cfg, get_db_path, set_cfg
from i18n import get_language, tr, translate_text
from services.autostart import configure_autostart
from services.build_edition import is_offline_edition
from services.desktop_shortcuts import create_desktop_shortcuts
from services.device_config import DeviceConfigRepository
from services.peer_sync_authorization import (
    PeerSyncAuthorizationError,
    close_pairing_window,
    open_pairing_window,
    pairing_window_status,
)
from services.polling import ScheduleWindow
from services.registration_data_notice import REGISTRATION_NOTICE_VERSION, registration_data_notice
from services.shared_settings import SharedSettingsService
from services.support_diagnostics import with_diagnostic
from services.sync_schedule import default_schedule_windows, dump_schedule_windows, load_schedule_windows
from services.web_access import (
    set_web_access_code,
    set_web_report_passwordless,
    update_web_runtime_values,
    web_access_status,
)
from services.web_port import read_web_port, validate_web_port
from services.web_service import WebServiceStatus, web_service_manager
from ui.common_dialogs import PinnedCountersDialog
from ui.components.notices import show_compact_information
from ui.components.task_header import TaskHeader
from ui.policy import OFFLINE_ACTIVATION_ENABLED
from ui.settings.controls import WebAccessCodeDialog
from ui.settings.sections.autostart import AutostartSection
from ui.settings.sections.billing import BillingSection
from ui.settings.sections.network import NetworkSection
from ui.settings.sections.registration import RegistrationSection
from ui.settings.sections.schedule import ScheduleSection
from ui.settings.sections.support import SupportSection
from ui.setup.wizard import SetupWizardV5
from ui.shared_settings_confirmation import confirm_shared_settings
from ui.styles import settings as settings_styles
from ui.styles import text as text_styles
from ui.styles.tokens import F_2XL
from widgets import btn, fnt


class PageFleetSettings(QWidget):
    changed = pyqtSignal()
    billing_audit_requested = pyqtSignal()
    activity_requested = pyqtSignal()
    advanced_tools_requested = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        registration_runtime=None,
        offline_license_public_keys: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = DeviceConfigRepository()
        self.registration_runtime = registration_runtime
        self.offline_license_public_keys = dict(offline_license_public_keys or {})
        self.web_service = web_service_manager()
        self._dirty_sections: set[str] = set()
        self._active_editor: str | None = None
        self._loading_config = False
        self._task_editors: dict[str, QFrame] = {}
        self._task_buttons: dict[str, QPushButton] = {}
        self._task_closed_labels: dict[str, str] = {}
        self._setup_wizard_dialog: SetupWizardV5 | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 20, 26, 26)
        layout.setSpacing(11)

        header = QFrame()
        header.setObjectName("settings_header")
        header.setStyleSheet(settings_styles.FLEET_SETTINGS_HEADER)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_copy = QVBoxLayout()
        title = QLabel("ตั้งค่าการใช้งาน")
        title.setFont(fnt(F_2XL, True))
        title.setStyleSheet(text_styles.label('#102A43', border='none'))
        subtitle = QLabel("ถ้าระบบทำงานปกติ คุณไม่จำเป็นต้องเปลี่ยนค่าใด")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(text_styles.label('#52677D', border='none'))
        header_copy.addWidget(title)
        header_copy.addWidget(subtitle)
        header_layout.addLayout(header_copy, 1)
        layout.addWidget(header)

        device_card, self.device_summary, edit_devices = self._action_task(
            "เครื่องพิมพ์และราคา",
            "กำลังโหลดข้อมูล…",
            "แก้ไข",
        )
        self.device_summary.setAccessibleName("รายชื่อเครื่องพิมพ์ที่ใช้งาน")
        choose = btn("ข้อมูลที่ใช้ในรายงาน", "outline")
        choose.clicked.connect(self._choose_counters)
        device_row = device_card.layout().itemAt(0).layout()
        if device_row is not None:
            device_row.insertWidget(1, choose, 0, Qt.AlignmentFlag.AlignVCenter)
        edit_devices.clicked.connect(self._edit_devices)
        layout.addWidget(device_card)

        registration_card, self.registration_summary, self.registration_retry_button = self._action_task(
            "การลงทะเบียนและความเป็นส่วนตัว",
            "กำลังตรวจสอบสถานะ…",
            "ลองส่งอีกครั้ง",
        )
        self.registration_section = RegistrationSection(
            registration_card, self.registration_summary, self.registration_retry_button,
            parent=self, on_retry=self._retry_registration,
            on_privacy=self._show_registration_privacy, on_notice=self._accept_registration_notice,
            on_mode=self._set_registration_mode, on_export_request=self._export_offline_request,
            on_import_license=self._import_offline_license,
        )
        self.registration_privacy_button = self.registration_section.registration_privacy_button
        self.registration_notice_accept = self.registration_section.registration_notice_accept
        self.registration_mode_group = self.registration_section.registration_mode_group
        self.registration_online_mode = self.registration_section.registration_online_mode
        self.registration_offline_mode = self.registration_section.registration_offline_mode
        self.offline_license_summary = self.registration_section.offline_license_summary
        self.offline_request_button = self.registration_section.offline_request_button
        self.offline_import_button = self.registration_section.offline_import_button
        layout.addWidget(registration_card)

        (
            billing_card,
            self.billing_summary,
            self.billing_editor,
            self.billing_toggle,
        ) = self._expandable_task(
            "billing",
            "รอบบิล",
            "กำลังโหลดข้อมูล…",
            closed_action="แก้ไข",
        )
        self.billing_section = BillingSection(
            self.billing_editor, on_save=self._save_billing,
            on_cancel=lambda: self._cancel_section("billing"),
            on_dirty=lambda: self._mark_dirty("billing"),
        )
        self.billing_day = self.billing_section.billing_day
        self.waste = self.billing_section.waste
        self.billing_save_status = self.billing_section.billing_save_status
        self.billing_save_button = self.billing_section.billing_save_button
        layout.addWidget(billing_card)

        (
            schedule_card,
            self.schedule_task_summary,
            self.schedule_task_editor,
            self.schedule_toggle,
        ) = self._expandable_task(
            "schedule",
            "การอ่านข้อมูลอัตโนมัติ",
            "กำลังโหลดข้อมูล…",
            closed_action="จัดเวลา",
        )
        self.schedule_section = ScheduleSection(
            self.schedule_task_editor, on_save=self._save_schedule,
            on_cancel=lambda: self._cancel_section("schedule"),
            on_dirty=lambda: self._mark_dirty("schedule"),
        )
        self.schedule = self.schedule_section.schedule
        self.advanced_schedule_button = self.schedule_section.advanced_schedule_button
        self.schedule_editor = self.schedule_section.schedule_editor
        self.schedule_windows_table = self.schedule_section.schedule_windows_table
        self.add_schedule_window_button = self.schedule_section.add_schedule_window_button
        self.schedule_save_status = self.schedule_section.schedule_save_status
        self.schedule_save_button = self.schedule_section.schedule_save_button
        self._schedule_row_controls = self.schedule_section.row_controls
        layout.addWidget(schedule_card)

        self.autostart_program_card, autostart_body = self._task_card_shell()
        self.autostart_section = AutostartSection(
            autostart_body, on_save=self._save_autostart,
            on_cancel=lambda: self._cancel_section("autostart"),
            on_dirty=lambda: self._mark_dirty("autostart"),
        )
        self.autostart = self.autostart_section.autostart
        self.autostart_status = self.autostart_section.autostart_status
        self.autostart_save_status = self.autostart_section.autostart_save_status
        self.autostart_save_button = self.autostart_section.autostart_save_button

        (
            program_card,
            self.web_task_summary,
            self.web_task_editor,
            self.web_toggle,
        ) = self._expandable_task(
            "web",
            "การตั้งค่าเครือข่าย",
            "กำลังตรวจสอบสถานะ…",
            closed_action="จัดการ",
        )
        program_body = self.web_task_editor.layout()
        self.network_section = NetworkSection(
            program_body, parent=self, on_open=self._open_web, on_copy=self._copy_lan_url,
            on_change_code=self._change_web_access_code, on_authorize=self._authorize_peer_sync,
            on_peer_refresh=self._refresh_peer_sync_status, subscribe_changes=self.changed.connect,
            on_save=self._save_web, on_cancel=lambda: self._cancel_section("web"),
            on_dirty=lambda: self._mark_dirty("web"),
        )
        self.web_service_enabled = self.network_section.web_service_enabled
        self.web_port = self.network_section.web_port
        self.web_service_status = self.network_section.web_service_status
        self.web_service_url = self.network_section.web_service_url
        self.open_web_button = self.network_section.open_web_button
        self.copy_web_button = self.network_section.copy_web_button
        self.web_advanced_toggle = self.network_section.web_advanced_toggle
        self.web_advanced_panel = self.network_section.web_advanced_panel
        self.web_report_require_password = self.network_section.web_report_require_password
        self.web_report_access_note = self.network_section.web_report_access_note
        self.web_access_status = self.network_section.web_access_status
        self.change_web_access_button = self.network_section.change_web_access_button
        self.peer_sync_status = self.network_section.peer_sync_status
        self.peer_sync_mode = self.network_section.peer_sync_mode
        self.peer_sync_authorize_button = self.network_section.peer_sync_authorize_button
        self.enroll_member_button = self.network_section.enroll_member_button
        self.shared_history_button = self.network_section.shared_history_button
        self.network_activity = self.network_section.network_activity
        self.web_save_status = self.network_section.web_save_status
        self.web_save_button = self.network_section.web_save_button
        # LAN/Web Report is an operational program setting.  It lives on the
        # Network Settings tab instead of competing with everyday pricing
        # and schedule tasks on the main Settings page.
        self.web_program_card = program_card

        (
            support_card,
            self.support_summary,
            self.support_task_editor,
            self.support_section_toggle,
        ) = self._expandable_task(
            "support",
            "การตั้งค่าขั้นสูง",
            "สำหรับเจ้าหน้าที่และการตรวจสอบระบบ",
            closed_action="เปิด",
        )
        self.support_section = SupportSection(
            self.support_task_editor, on_advanced=self.advanced_tools_requested.emit,
            on_activity=self.activity_requested.emit, on_audit=self.billing_audit_requested.emit,
            on_network=lambda: self._set_active_editor("web"), on_shortcuts=self._create_shortcuts,
        )
        self.support_toggle = self.support_section.support_toggle
        self.support_details = self.support_section.support_details
        self.active_database_path = self.support_section.active_database_path
        self.registration_support_detail = self.support_section.registration_support_detail
        layout.addWidget(support_card)

        self._web_status_timer = QTimer(self)
        from ui.background_read import LatestRead
        self._web_status_reader = LatestRead(self)
        self._web_status_reader.ready.connect(self._refresh_web_status)
        self._web_status_reader.failed.connect(self._web_status_failed)
        self.web_service_status.installEventFilter(self)
        self._web_status_timer.setInterval(2000)
        self._web_status_timer.timeout.connect(self._refresh_web_status)
        self._web_status_timer.timeout.connect(self._refresh_registration_status)
        self._web_status_timer.timeout.connect(self._refresh_peer_sync_status)
        self.refresh_from_config()
        layout.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_runtime_visibility()
        self._refresh_registration_status()
        self._refresh_peer_sync_status()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_runtime_visibility()

    def eventFilter(self, watched, event):
        from PyQt6.QtCore import QEvent
        if watched is self.web_service_status and event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            QTimer.singleShot(0, self._sync_runtime_visibility)
        return super().eventFilter(watched, event)

    def _sync_runtime_visibility(self):
        # The tabbed settings shell reparents the card into Network Settings.
        # Observe that card as well as the original fleet container.
        if self.isVisible() or self.web_service_status.isVisible():
            self._web_status_timer.start()
        else:
            self._web_status_timer.stop()
        if self.web_service_status.isVisible():
            self._refresh_web_status()
        else:
            self._web_status_reader.cancel()

    def _web_status_failed(self, detail):
        self.web_service_status.setText(tr("ตรวจสถานะ Web ไม่สำเร็จ · กำลังรอลองใหม่", "Could not check Web status · Waiting to retry"))
        self.web_service_status.setToolTip(detail)
        self.open_web_button.setEnabled(False)
        self.copy_web_button.setEnabled(False)

    @staticmethod
    def _task_card_shell() -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settings_task_card")
        card.setStyleSheet(
            settings_styles.FLEET_SETTINGS_TASK_CARD_SHELL
        )
        body = QVBoxLayout(card)
        body.setContentsMargins(16, 13, 16, 14)
        body.setSpacing(10)
        return card, body

    def _action_task(
        self,
        title: str,
        summary: str,
        action_text: str,
    ) -> tuple[QFrame, QLabel, QPushButton]:
        card, body = self._task_card_shell()
        action = btn(action_text, "outline")
        header = TaskHeader(title, summary, action)
        body.addLayout(header)
        return card, header.detail, action

    def _expandable_task(
        self,
        key: str,
        title: str,
        summary: str,
        *,
        closed_action: str = "เปลี่ยน",
    ) -> tuple[QFrame, QLabel, QFrame, QPushButton]:
        card, body = self._task_card_shell()
        toggle = btn(translate_text(closed_action), "outline")
        toggle.setCheckable(True)
        toggle.setAccessibleName(
            tr(
                f"เปิดหรือปิด {title}",
                f"Open or close {translate_text(title)}",
            )
        )
        header = TaskHeader(title, summary, toggle)
        body.addLayout(header)

        editor = QFrame()
        editor.setObjectName(f"settings_editor_{key}")
        editor.setStyleSheet(
            settings_styles.fleet_settings_editor(key)
        )
        editor_body = QVBoxLayout(editor)
        editor_body.setContentsMargins(13, 12, 13, 13)
        editor_body.setSpacing(10)
        editor.hide()
        body.addWidget(editor)
        self._task_editors[key] = editor
        self._task_buttons[key] = toggle
        self._task_closed_labels[key] = closed_action
        toggle.toggled.connect(
            lambda checked, task_key=key: self._task_toggle_requested(task_key, checked)
        )
        return card, header.detail, editor, toggle


    def _task_toggle_requested(self, key: str, checked: bool) -> None:
        if checked:
            self._set_active_editor(key)
        elif key == "web" and self._active_editor == "web":
            # LAN settings are nested inside Advanced Settings. Closing the
            # LAN editor must return to the advanced overview, not collapse
            # the entire parent section.
            self._set_active_editor("support")
        elif key == "support" and self._active_editor == "web":
            self._set_active_editor(None)
        elif self._active_editor == key:
            self._set_active_editor(None)

    def _set_active_editor(self, key: str | None, *, force: bool = False) -> bool:
        if key is None and getattr(self, "_section_editor", None) is not None:
            # Tabbed settings retain their form after Save/Cancel.
            key = self._section_editor
        current = self._active_editor
        if current == key:
            return True
        if current is not None and current in self._dirty_sections and not force:
            show_compact_information(
                self,
                tr("ยังไม่ได้บันทึก", "Unsaved changes"),
                tr(
                    "กรุณาบันทึกหรือยกเลิกส่วนที่กำลังแก้ก่อนเปิดส่วนอื่น",
                    "Save or cancel the section you are editing before opening another section.",
                ),
            )
            if key is not None:
                button = self._task_buttons[key]
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            if current is not None:
                current_button = self._task_buttons[current]
                current_button.blockSignals(True)
                current_button.setChecked(True)
                current_button.blockSignals(False)
            return False

        nested_web = (
            key == "web"
            and self.web_program_card.parent() is self.support_task_editor
        )
        for task_key, editor in self._task_editors.items():
            # LAN/Web is a child card of Advanced Settings. Keep the parent
            # editor visible while its nested editor is open.
            visible = task_key == key or (nested_web and task_key == "support")
            editor.setVisible(visible)
            button = self._task_buttons[task_key]
            button.blockSignals(True)
            button.setChecked(visible)
            button.setText(
                tr("ปิด", "Close")
                if visible
                else translate_text(self._task_closed_labels[task_key])
            )
            button.blockSignals(False)
        self._active_editor = key
        return True


    def _mark_dirty(self, section: str) -> None:
        if self._loading_config:
            return
        if section == 'schedule':
            self.schedule_section.invalidate()
        self._dirty_sections.add(section)
        widgets = {
            "billing": (self.billing_save_status, self.billing_save_button),
            "schedule": (self.schedule_save_status, self.schedule_save_button),
            "autostart": (self.autostart_save_status, self.autostart_save_button),
            "web": (self.web_save_status, self.web_save_button),
        }
        status, save_button = widgets[section]
        status.setText(tr("มีการแก้ไขที่ยังไม่ได้บันทึก", "Unsaved changes"))
        status.setStyleSheet(text_styles.label('#B54708', font_weight='700', border='none'))
        save_button.setEnabled(True)
        if section == "schedule":
            self._refresh_schedule()
        self._refresh_task_summaries()

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty_sections)

    def discard_unsaved_changes(self) -> None:
        """Explicitly restore persisted values before the app exits."""
        self._dirty_sections.clear()
        self.refresh_from_config(force=True)
        self._set_active_editor(None, force=True)

    def refresh_from_config(self, *, force: bool = False) -> bool:
        if self._dirty_sections and not force:
            self._refresh_web_status()
            self._refresh_web_access_status()
            return False
        self._loading_config = True
        controls = (
            self.billing_day,
            self.waste,
            self.autostart,
            self.web_service_enabled,
            self.web_port,
            self.web_report_require_password,
        )
        for control in controls:
            control.blockSignals(True)
        self.billing_day.setValue(int(get_cfg("billing_day", "31") or 31))
        self.waste.setValue(float(get_cfg("waste_paper_pct", "2") or 2))
        stored_windows = load_schedule_windows(get_cfg("sync_schedule_windows", ""))
        self.schedule_section.using_defaults = stored_windows is None
        self._replace_schedule_windows(stored_windows if stored_windows is not None else default_schedule_windows())
        registration = self._autostart_registration_status()
        configured_autostart = get_cfg("autostart_enabled", "")
        self.autostart.setChecked(
            registration
            if registration is not None
            else configured_autostart == "1"
        )
        self._refresh_autostart_status(registration)
        self.web_service_enabled.setChecked(get_cfg("web_service_enabled", "1") != "0")
        self.web_port.setValue(read_web_port(self.web_service.runtime_root / ".env.local"))
        sync_status = pairing_window_status()
        self.peer_sync_mode.setCurrentIndex(self.peer_sync_mode.findData("always" if sync_status.open else "off"))
        web_access = web_access_status(self.web_service.runtime_root / ".env.local")
        self.web_report_require_password.setChecked(not web_access.report_passwordless)
        for control in controls:
            control.blockSignals(False)
        device_count = self._refresh_device_summary()
        active_path = str(get_db_path())
        database_text = (
            f"ฐานข้อมูลที่กำลังใช้งาน: {active_path}\n"
            "เปลี่ยน Path, สำรอง และนำ Backup กลับมาใช้ได้ใน การตั้งค่าขั้นสูง"
        )
        self.active_database_path.setText(database_text)
        self.active_database_path.setToolTip(database_text)
        self._dirty_sections.clear()
        for status, save_button in (
            (self.billing_save_status, self.billing_save_button),
            (self.schedule_save_status, self.schedule_save_button),
            (self.autostart_save_status, self.autostart_save_button),
            (self.web_save_status, self.web_save_button),
        ):
            status.setText(tr("ค่าปัจจุบันถูกบันทึกแล้ว", "Current settings are saved"))
            status.setStyleSheet(text_styles.label('#16875D', font_weight='700', border='none'))
            save_button.setEnabled(False)
        self._refresh_schedule()
        self._refresh_task_summaries(device_count=device_count, registration=registration)
        self._refresh_registration_status()
        self._refresh_web_status()
        self._refresh_web_access_status()
        self._refresh_peer_sync_status()
        self._loading_config = False
        return True

    def _authorize_peer_sync(self) -> None:
        try:
            mode = self.peer_sync_mode.currentData()
            if mode == "off":
                close_pairing_window()
            else:
                open_pairing_window(get_cfg("installation_id", ""), always_open=True, continuous=True)
        except PeerSyncAuthorizationError as error:
            QMessageBox.warning(
                self,
                tr("ยังอนุญาตไม่ได้", "Could not authorize sync"),
                with_diagnostic(translate_text(str(error)), error, tr("ยังอนุญาตไม่ได้", "Could not authorize sync")),
            )
            self._refresh_peer_sync_status()
            return
        self._refresh_peer_sync_status()

    def _refresh_peer_sync_status(self) -> None:
        if not hasattr(self, "peer_sync_status"):
            return
        status = pairing_window_status()
        if status.always_open:
            self.peer_sync_status.setText(tr(
                "เปิดตลอด · จำค่าหลังเปิดโปรแกรมใหม่ · กดปิดเพื่อยกเลิกสิทธิ์",
                "Always open · remembered after restart · switch off to revoke access",
            ))
            self.peer_sync_status.setStyleSheet(text_styles.label('#16875D', font_weight='700'))
            return
        if status.open:
            claimed = tr(" · มีเครื่องรับสิทธิ์แล้ว", " · claimed") if status.claimed else ""
            self.peer_sync_status.setText(
                tr(
                    f"เปิดอยู่ · เหลือ {status.seconds_remaining} วินาที",
                    f"Open · {status.seconds_remaining} seconds remaining",
                )
                + claimed
            )
            self.peer_sync_status.setStyleSheet(text_styles.label('#16875D', font_weight='700'))
            return
        self.peer_sync_status.setText(
            tr(
                "ปิดอยู่ · เปิดสิทธิ์บนเครื่องนี้ก่อนให้คอมพิวเตอร์อื่นรับการตั้งค่า",
                "Closed · Enable access here before another computer receives settings",
            )
        )
        self.peer_sync_status.setStyleSheet(text_styles.label('#64748B'))

    def _refresh_registration_status(self) -> None:
        runtime = self._registration_service()
        snapshot = runtime.snapshot()
        mode = str(snapshot.get("mode") or "online")
        effective_status = str(snapshot.get("status") or "not_configured")
        if is_offline_edition():
            self.registration_summary.setText(
                tr(
                    "Offline Installation · พร้อมอ่าน SNMP และใช้งานภายในเครื่องโดยไม่ติดต่อ Host",
                    "Offline Installation · local SNMP collection is ready without Host access",
                )
            )
            self.registration_summary.setToolTip("")
            self.registration_retry_button.setVisible(False)
            self.registration_privacy_button.setVisible(False)
            self.registration_notice_accept.setVisible(False)
            for control in (self.registration_online_mode, self.registration_offline_mode):
                control.setVisible(False)
            self.offline_request_button.setVisible(False)
            self.offline_import_button.setVisible(False)
            self.offline_license_summary.setVisible(False)
            self.registration_support_detail.setText(
                tr(
                    "Edition: Offline Installation · Host traffic: disabled · Local collection: enabled",
                    "Edition: Offline Installation · Host traffic: disabled · Local collection: enabled",
                )
            )
            return
        labels = {
            "not_configured": tr("ยังไม่ได้ตั้งค่า", "Not configured"),
            "waiting_for_internet": tr("รออินเทอร์เน็ต", "Waiting for internet"),
            "pending": tr("รอส่งแบบ Background", "Pending background delivery"),
            "retrying": tr("กำลังลองใหม่", "Retrying"),
            "registered": tr("ลงทะเบียนแล้ว", "Registered"),
            "action_required": tr("ต้องตรวจสอบ", "Needs attention"),
            "needs_review": tr("ต้องตรวจสอบ", "Needs attention"),
            "offline_request_required": tr(
                "Offline License · กรุณาสร้างไฟล์คำขอ",
                "Offline License · export a request file",
            ),
            "offline_request_ready": tr(
                "Offline License · สร้างคำขอแล้ว รอนำเข้า License",
                "Offline License · request exported, waiting for license import",
            ),
            "offline_license": tr("Offline License", "Offline License"),
            "offline_license_expired": tr(
                "Offline License หมดอายุ · กรุณานำเข้า License ใหม่",
                "Offline License expired · import a renewed license",
            ),
            "offline_license_device_mismatch": tr(
                "เครื่องพิมพ์ที่เลือกไม่ตรงกับ Offline License · กรุณาสร้างคำขอและนำเข้า License ใหม่",
                "Selected printers do not match the Offline License · create a new request and import a new license",
            ),
        }
        detail = labels.get(effective_status, tr("ต้องตรวจสอบ", "Needs attention"))
        last_sent_at = str(snapshot.get("last_sent_at") or "")
        if last_sent_at and mode == "online":
            detail += tr(
                f" · ส่งครั้งล่าสุด {last_sent_at}",
                f" · last sent {last_sent_at}",
            )
        if mode == "online":
            detail += tr(
                " · Host จะแยก Desktop ขาดการเชื่อมต่อหลัง 3 วัน และไม่สรุปว่าเครื่องพิมพ์เสีย",
                " · the Host separates Desktop connectivity loss after 3 days and does not claim a printer fault",
            )
        self.registration_summary.setText(detail)
        self.registration_summary.setToolTip("")
        for control in (self.registration_online_mode, self.registration_offline_mode):
            control.blockSignals(True)
        self.registration_online_mode.setChecked(mode == "online")
        self.registration_offline_mode.setChecked(mode == "offline")
        for control in (self.registration_online_mode, self.registration_offline_mode):
            control.blockSignals(False)
        self.registration_retry_button.setVisible(
            mode == "online"
            and effective_status
            in {
                "waiting_for_internet",
                "pending",
                "retrying",
                "action_required",
                "needs_review",
            }
        )
        self.registration_retry_button.setEnabled(mode == "online")
        self.registration_retry_button.setText(tr("ลองส่งอีกครั้ง", "Retry"))
        offline_ui_visible = OFFLINE_ACTIVATION_ENABLED and mode == "offline"
        self.offline_request_button.setVisible(offline_ui_visible)
        self.offline_import_button.setVisible(offline_ui_visible)
        self.offline_license_summary.setVisible(offline_ui_visible)
        license_metadata = snapshot.get("offline_license")
        if mode == "offline" and isinstance(license_metadata, dict):
            expires_at = str(license_metadata.get("expires_at") or "—")
            bound_devices = license_metadata.get("bound_devices")
            bound_rows = []
            if isinstance(bound_devices, list):
                for device in bound_devices:
                    if not isinstance(device, dict):
                        continue
                    bound_rows.append(
                        f"{device.get('model') or 'Unknown'} · {device.get('serial_number') or '—'} · "
                        f"Slot {device.get('device_slot') or '—'}"
                    )
            self.offline_license_summary.setText(
                tr(
                    f"Offline License ใช้งานถึง {expires_at} · ผูกกับ " + ("; ".join(bound_rows) or "—"),
                    f"Offline License valid until {expires_at} · bound to " + ("; ".join(bound_rows) or "—"),
                )
            )
        elif mode == "offline":
            self.offline_license_summary.setText(
                tr(
                    "ยังไม่มี Offline License · สร้างไฟล์คำขอแล้วนำ License ที่ได้รับกลับเข้ามา",
                    "No Offline License yet · export a request and import the issued license file",
                )
            )
        accepted_current = bool(snapshot.get("notice_accepted"))
        self.registration_notice_accept.setChecked(accepted_current)
        self.registration_notice_accept.setVisible(mode == "online")
        self.registration_notice_accept.setEnabled(mode == "online" and not accepted_current)
        support_code = str(snapshot.get("support_code") or "none")
        next_attempt = str(snapshot.get("next_attempt_at") or "—")
        self.registration_support_detail.setText(
            tr(
                f"Registration mode: {mode} · Support code: {support_code} · รอบถัดไป: {next_attempt}",
                f"Registration mode: {mode} · Support code: {support_code} · next attempt: {next_attempt}",
            )
        )

    def _accept_registration_notice(self, checked: bool) -> None:
        if not checked:
            self._refresh_registration_status()
            return
        self._registration_service().accept_notice(
            REGISTRATION_NOTICE_VERSION,
            datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self._refresh_registration_status()
        self.registration_summary.setText(
            tr(
                "รับทราบข้อมูลการลงทะเบียนแล้ว · ระบบจะลงทะเบียนอัตโนมัติเมื่อการเชื่อมต่อพร้อม",
                "Registration Data Notice acknowledged · automatic registration will continue when connectivity is ready",
            )
        )

    def _retry_registration(self) -> None:
        retried = self._registration_service().retry_now()
        self._refresh_registration_status()
        if retried:
            self.registration_summary.setText(
                tr(
                    "จัดคิวใหม่แล้ว · ระบบจะลองส่งใน Background",
                    "Queued again · background delivery will retry",
                )
            )

    def _registration_service(self):
        if self.registration_runtime is None:
            from services.v5_2_runtime import V52RuntimeCoordinator

            self.registration_runtime = V52RuntimeCoordinator(parent=self)
        return self.registration_runtime

    def _set_registration_mode(self, mode: str) -> None:
        if mode == "offline" and not OFFLINE_ACTIVATION_ENABLED:
            return
        try:
            self._registration_service().set_mode(mode)
            set_cfg("v52_registration_mode", mode)
        except (OSError, RuntimeError, ValueError):
            QMessageBox.warning(
                self,
                tr("เปลี่ยนโหมดไม่สำเร็จ", "Could not change mode"),
                tr(
                    "การตั้งค่าเดิมยังคงอยู่ กรุณาลองอีกครั้ง",
                    "The previous setting is unchanged. Please try again.",
                ),
            )
        self._refresh_registration_status()
        self.changed.emit()

    def _export_offline_request(self) -> None:
        if not OFFLINE_ACTIVATION_ENABLED:
            return
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("สร้างคำขอ Offline License", "Export Offline License request"),
            "KOMI-Desktop.komirequest",
            "KOMI Request (*.komirequest)",
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.casefold() != ".komirequest":
            destination = destination.with_suffix(".komirequest")
        try:
            self._registration_service().create_offline_request(destination)
        except (OSError, RuntimeError, ValueError):
            QMessageBox.warning(
                self,
                tr("สร้างคำขอไม่สำเร็จ", "Could not export request"),
                tr(
                    "ตรวจสอบว่าได้เลือกเครื่องพิมพ์และ OS Credential Vault พร้อมใช้งาน",
                    "Check that printers are selected and the OS Credential Vault is available.",
                ),
            )
            return
        self._refresh_registration_status()
        QMessageBox.information(
            self,
            tr("สร้างคำขอแล้ว", "Request exported"),
            tr(
                "บันทึกไฟล์คำขอแล้ว · ไฟล์นี้ไม่มีรหัสผ่านหรือ Token",
                "The request file was saved. It contains no password or token.",
            ),
        )

    def _import_offline_license(self) -> None:
        if not OFFLINE_ACTIVATION_ENABLED:
            return
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            tr("นำเข้าไฟล์ Offline License", "Import Offline License file"),
            "",
            "KOMI License (*.komilicense)",
        )
        if not path:
            return
        try:
            self._registration_service().import_offline_license(
                Path(path), self.offline_license_public_keys
            )
        except (OSError, RuntimeError, ValueError):
            QMessageBox.warning(
                self,
                tr("นำเข้า License ไม่สำเร็จ", "Could not import license"),
                tr(
                    "ไฟล์ไม่ตรงกับ Desktop นี้ หมดอายุ หรือยังไม่มีข้อมูลยืนยันจาก Host",
                    "The file does not match this Desktop, has expired, or Host verification data is unavailable.",
                ),
            )
            return
        self._refresh_registration_status()
        self.changed.emit()
        QMessageBox.information(
            self,
            tr("นำเข้า License แล้ว", "License imported"),
            tr(
                "Offline License พร้อมใช้งาน และไม่มีการส่ง Registration, Status หรือ Meter",
                "Offline License is active and no Registration, Status, or Meter telemetry is sent.",
            ),
        )

    def _show_registration_privacy(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(
            tr("ประกาศข้อมูลการลงทะเบียน", "Registration Data Notice")
        )
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(registration_data_notice(get_language()))
        layout.addWidget(text)
        close_button = btn(tr("ปิด", "Close"), "primary")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        self._registration_privacy_dialog = dialog
        dialog.open()

    def _refresh_device_summary(self) -> int:
        devices = self.repository.list(enabled_only=True)
        if devices:
            names = ", ".join(device.name for device in devices)
            self.device_summary.setText(
                tr(
                    f"{len(devices)}/3 เครื่อง · {names} · เปลี่ยนผ่านขั้นตอนตรวจสอบเครื่องและราคา",
                    f"{len(devices)}/3 printers · {names} · Change through the verified printer and pricing flow",
                )
            )
            self.device_summary.setToolTip(
                "\n".join(
                    f"{device.name} · {device.host} · Serial {device.serial or '—'}"
                    for device in devices
                )
            )
        else:
            self.device_summary.setText(
                tr(
                    "ยังไม่ได้ตั้งค่าเครื่องพิมพ์ · กดเปลี่ยนเพื่อเริ่มต้น",
                    "No printer configured · Select Change to get started",
                )
            )
            self.device_summary.setToolTip("")
        return len(devices)

    def _refresh_task_summaries(
        self,
        *,
        device_count: int | None = None,
        registration: bool | None = None,
    ) -> None:
        if device_count is None:
            device_count = len(self.repository.list(enabled_only=True))
        billing_prefix = (
            tr("กำลังแก้ไข · ", "Editing · ") if "billing" in self._dirty_sections else ""
        )
        self.billing_summary.setText(
            billing_prefix
            + tr(
                f"ปิดรอบวันที่ {self.billing_day.value()} · ส่วนลดกระดาษเสีย {self.waste.value():g}%",
                f"Closes on day {self.billing_day.value()} · Waste-paper discount {self.waste.value():g}%",
            )
        )
        if registration is None:
            registration = self._autostart_registration_status()
        automatic = registration is True or self.autostart.isChecked()
        schedule_prefix = tr("กำลังแก้ไข · ", "Editing · ") if {
            "schedule",
            "autostart",
        } & self._dirty_sections else ""
        automatic_text = tr("เปิดพร้อมระบบ", "Starts at sign-in") if automatic else tr(
            "เปิดแอปด้วยตนเอง", "Open the app manually"
        )
        self.schedule_task_summary.setText(
            schedule_prefix
            + tr(
                f"{automatic_text} · ใช้ตารางเวลา {len(self._schedule_row_controls)} ช่วง",
                f"{automatic_text} · {len(self._schedule_row_controls)} reading windows",
            )
        )
        if device_count == 0:
            self.support_summary.setText(
                tr(
                    "ยังไม่มีเครื่องพิมพ์ · เริ่มจากส่วนเครื่องพิมพ์และราคา",
                    "No printer configured · Start with Printers and pricing",
                )
            )
        else:
            self.support_summary.setText(
                tr(
                    "Database, Backup, Log และ Parser Mapping",
                    "Database, backup, logs, and parser mapping",
                )
            )

    @staticmethod
    def _autostart_registration_status() -> bool | None:
        """Read the planned OS registration path without creating or deleting it."""
        try:
            registration_path = configure_autostart(True, apply=False)
        except OSError:
            return None
        if registration_path is None:
            return None
        return registration_path.exists()

    def _refresh_autostart_status(self, registered: bool | None) -> None:
        self.autostart_section.refresh_status(registered)

    @staticmethod
    def _web_runtime_matches(desired_enabled: bool, status: WebServiceStatus) -> bool:
        if desired_enabled:
            return status.state in {"running", "external", "starting"}
        return status.state in {"stopped", "failed"}

    def _refresh_web_status(self, status: WebServiceStatus | None = None) -> None:
        if status is None:
            if self.web_service_status.isVisible() and not self._web_status_reader.busy:
                self._web_status_reader.request(self.web_service.status)
            return
        self._web_status_reader.cancel()
        self.web_service_status.setToolTip("")
        current = status
        colours = {
            "running": ("#16875D", "#EDF8F2", "#B8DFC9", tr("● พร้อมใช้งาน", "● Ready")),
            "external": (
                "#16875D",
                "#EDF8F2",
                "#B8DFC9",
                tr("● พร้อมใช้งาน (เปิดจากภายนอก)", "● Ready (started externally)"),
            ),
            "starting": ("#8A4B08", "#FFF4E5", "#F4C98B", tr("● กำลังเริ่ม", "● Starting")),
            "failed": ("#B42318", "#FEF3F2", "#F2B8B5", tr("● เริ่มไม่สำเร็จ", "● Start failed")),
            "stopped": ("#64748B", "#F8FAFC", "#D6E0EA", tr("● ปิดอยู่", "● Disabled")),
        }
        colour, background, border, label = colours[current.state]
        self.web_service_status.setText(f"{label} · {translate_text(current.detail)}")
        self.web_service_status.setStyleSheet(
            text_styles.label(colour, background='transparent', border='none', padding='1px 0')
        )
        lan_is_local_only = any(
            marker in current.lan_url.lower()
            for marker in ("127.0.0.1", "localhost", "[::1]")
        )
        if lan_is_local_only:
            address_text = tr(
                "ยังไม่พบที่อยู่ LAN · ตรวจว่าเครื่องนี้เชื่อมต่อเครือข่ายแล้ว",
                "No LAN address found · Check that this computer is connected to the network",
            )
        elif current.state in {"running", "external"}:
            address_text = current.lan_url
        else:
            address_text = tr(
                f"ที่อยู่เมื่อเปิดใช้งาน: {current.lan_url}",
                f"Address when enabled: {current.lan_url}",
            )
        self.web_service_url.setText(address_text)
        self.web_service_url.setToolTip(
            tr(
                f"เครื่องนี้เปิดจากแอป Desktop หรือ {current.local_url}",
                f"On this computer, use the Desktop app or {current.local_url}",
            )
        )
        ready = current.state in {"running", "external"}
        self.open_web_button.setVisible(True)
        self.open_web_button.setEnabled(ready)
        self.copy_web_button.setVisible(True)
        self.copy_web_button.setEnabled(ready and not lan_is_local_only)
        desired_enabled = self.web_service_enabled.isChecked()
        pending = desired_enabled and current.state == "starting"
        runtime_mismatch = not self._web_runtime_matches(desired_enabled, current)
        previous_mismatch = getattr(self, "_web_runtime_mismatch", False)
        if "web" not in self._dirty_sections:
            if pending:
                self.web_save_button.setEnabled(False)
                self.web_save_status.setText(
                    tr(
                        "กำลังเริ่ม Web Report และรอตรวจสอบสถานะ",
                        "Starting Web Report and waiting to verify its status",
                    )
                )
                self.web_save_status.setStyleSheet(
                    text_styles.label('#B54708', font_weight='700', border='none')
                )
            elif runtime_mismatch:
                self.web_save_button.setEnabled(True)
                self.web_save_status.setText(
                    tr(
                        "สถานะบริการยังไม่ตรงกับค่าที่เลือก · กดบันทึกและตรวจสอบ LAN เพื่อลองอีกครั้ง",
                        "The service does not match the selected setting. Save and verify LAN access to try again.",
                    )
                )
                self.web_save_status.setStyleSheet(
                    text_styles.label('#B42318', font_weight='700', border='none')
                )
            elif previous_mismatch:
                self.web_save_button.setEnabled(False)
                self.web_save_status.setText(
                    tr(
                        "การตั้งค่าและสถานะ Web Report ตรงกันแล้ว",
                        "The Web Report setting and service status now match",
                    )
                )
                self.web_save_status.setStyleSheet(
                    text_styles.label('#16875D', font_weight='700', border='none')
                )
        self._web_runtime_mismatch = runtime_mismatch or pending
        if "web" in self._dirty_sections:
            self.web_task_summary.setText(
                tr(
                    "กำลังแก้ไข · การเปลี่ยนแปลงยังไม่มีผลจนกว่าจะบันทึก",
                    "Editing · Changes do not take effect until saved",
                )
            )
        elif pending:
            self.web_task_summary.setText(
                tr(
                    "กำลังเริ่ม Web Report · ระบบกำลังตรวจสอบสถานะ",
                    "Starting Web Report · Waiting to verify the service",
                )
            )
        elif runtime_mismatch and desired_enabled:
            self.web_task_summary.setText(
                tr(
                    "ต้องแก้ไข · ตั้งให้เปิดแล้ว แต่ Web Report ยังไม่เริ่ม",
                    "Needs attention · Web Report is enabled but has not started",
                )
            )
        elif runtime_mismatch:
            self.web_task_summary.setText(
                tr(
                    "ต้องแก้ไข · ตั้งให้ปิดแล้ว แต่ Web Report ยังทำงานอยู่",
                    "Needs attention · Web Report is disabled but is still running",
                )
            )
        elif ready and not lan_is_local_only:
            self.web_task_summary.setText(
                tr(
                    f"เปิดอยู่ · เครื่องอื่นเข้าได้ที่ {current.lan_url}",
                    f"Enabled · Other computers can use {current.lan_url}",
                )
            )
        else:
            self.web_task_summary.setText(
                tr(
                    "ปิดอยู่ · เครื่องอื่นยังเปิดรายงานไม่ได้",
                    "Disabled · Other computers cannot open reports",
                )
            )

    def _open_web(self) -> None:
        webbrowser.open(self.web_service.status().lan_url)

    def _copy_lan_url(self) -> None:
        current = self.web_service.status()
        if any(
            marker in current.lan_url.lower()
            for marker in ("127.0.0.1", "localhost", "[::1]")
        ):
            QMessageBox.information(
                self,
                tr("ยังคัดลอกไม่ได้", "Nothing to copy yet"),
                tr(
                    "ยังไม่พบที่อยู่ LAN กรุณาตรวจการเชื่อมต่อเครือข่าย",
                    "No LAN address was found. Check the network connection.",
                ),
            )
            return
        QApplication.clipboard().setText(current.lan_url)
        self.web_save_status.setText(tr("คัดลอกที่อยู่ LAN แล้ว", "LAN address copied"))
        self.web_save_status.setStyleSheet(text_styles.label('#16875D', font_weight='700', border='none'))

    def _refresh_web_access_status(self) -> None:
        status = web_access_status(self.web_service.runtime_root / ".env.local")
        if status.report_passwordless:
            self.web_access_status.setText(
                tr(
                    "เปิดรายงานแบบอ่านอย่างเดียวได้โดยไม่ใช้รหัส · "
                    "ข้อมูลระบบและเครื่องมือเจ้าหน้าที่ยังต้องเข้าสู่ระบบ",
                    "Read-only reports can be opened without a password · "
                    "System information and staff tools still require sign-in",
                )
            )
            self.web_access_status.setStyleSheet(text_styles.label('#16875D'))
            self.change_web_access_button.setText(
                tr("ตั้งรหัสสำหรับเจ้าหน้าที่", "Set staff access code")
                if not status.configured
                else tr("เปลี่ยนรหัสเจ้าหน้าที่", "Change staff access code")
            )
            return
        if status.configured:
            self.web_access_status.setText(
                tr(
                    f"ตั้งรหัสแล้ว · Username: {status.user} · ระบบไม่แสดงรหัสปัจจุบัน",
                    f"Access code set · Username: {status.user} · The current code is never displayed",
                )
            )
            self.web_access_status.setStyleSheet(text_styles.label('#16875D'))
            self.change_web_access_button.setText(
                tr("เปลี่ยนรหัส Web", "Change Web access code")
            )
        else:
            self.web_access_status.setText(
                tr(
                    "ยังไม่ได้ตั้งรหัส · เครื่องอื่นใน LAN จะยังเข้าสู่ระบบไม่ได้",
                    "Access code not set · Other LAN computers cannot sign in yet",
                )
            )
            self.web_access_status.setStyleSheet(text_styles.label('#B54708'))
            self.change_web_access_button.setText(
                tr("ตั้งรหัส Web", "Set Web access code")
            )

    def _apply_web_access_code(self, access_code: str) -> WebServiceStatus:
        set_web_access_code(self.web_service.runtime_root / ".env.local", access_code)
        before = self.web_service.status()
        if before.state in {"running", "starting"}:
            result = self.web_service.restart()
        elif before.state == "external":
            result = self.web_service.restart()
        elif self.web_service_enabled.isChecked():
            result = self.web_service.start()
        else:
            result = before
        self._refresh_web_access_status()
        self._refresh_web_status(result)
        return result

    def _change_web_access_code(self) -> None:
        dialog = WebAccessCodeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            status = self._apply_web_access_code(dialog.value())
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                tr("เปลี่ยนรหัส Web ไม่สำเร็จ", "Could not change the Web access code"),
                with_diagnostic(translate_text(str(error)), error, tr("เปลี่ยนรหัส Web ไม่สำเร็จ", "Could not change the Web access code")),
            )
            return
        if status.state == "external":
            QMessageBox.warning(
                self,
                tr("บันทึกรหัสแล้ว", "Access code saved"),
                tr(
                    "บันทึกรหัสใหม่แล้ว แต่ Web service เปิดจาก Shortcut แยก กรุณาปิด Web service เดิมและเปิดใหม่ก่อนใช้งาน",
                    "The new code was saved, but Web Report was started from a separate shortcut. Stop and restart that Web service before signing in.",
                ),
            )
            return
        QMessageBox.information(
            self,
            tr("เปลี่ยนรหัส Web แล้ว", "Web access code changed"),
            tr(
                "ตั้งรหัสแล้ว · รายงานยังเปิดได้ทันที หากต้องการล็อก ให้เลือก 'ล็อก Web Report ด้วยรหัสผ่าน' แล้วบันทึก",
                "Password saved. Reports remain open. To protect reports, enable 'Require a password for Web Report' and save.",
            )
            if web_access_status(self.web_service.runtime_root / ".env.local").report_passwordless
            else
            tr(
                "เครื่องอื่นใน LAN ต้องเข้าสู่ระบบใหม่ด้วยรหัสที่เพิ่งตั้ง",
                "Other LAN computers must sign in again with the new code.",
            ),
        )

    def _create_shortcuts(self) -> None:
        try:
            result = create_desktop_shortcuts()
        except Exception as exc:
            QMessageBox.warning(self, "สร้าง Shortcut ไม่สำเร็จ", with_diagnostic(str(exc), exc, "สร้าง Shortcut ไม่สำเร็จ"))
            return
        names = "\n".join(path.name for path in result.created_paths)
        QMessageBox.information(
            self,
            "สร้าง Shortcut แล้ว",
            f"สร้างไว้ที่ {result.desktop_path}\n\n{names}\n\nShortcut ทุกอันเรียก source กลางชุดเดียวกัน",
        )

    def _edit_devices(self) -> None:
        if self._dirty_sections:
            QMessageBox.information(
                self,
                tr("ยังไม่ได้บันทึก", "Unsaved changes"),
                tr(
                    "กรุณาบันทึกหรือยกเลิกส่วนที่กำลังแก้ก่อนเปลี่ยนเครื่องพิมพ์",
                    "Save or cancel the section you are editing before changing printers.",
                ),
            )
            return
        dialog = SetupWizardV5(
            self,
            edit_mode=True,
            registration_runtime=self.registration_runtime,
            offline_license_public_keys=self.offline_license_public_keys,
        )
        self._setup_wizard_dialog = dialog

        def setup_finished(result: int) -> None:
            if result == int(QDialog.DialogCode.Accepted):
                self.refresh_from_config(force=True)
                self.changed.emit()
            self._setup_wizard_dialog = None

        dialog.finished.connect(setup_finished)
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    def _cancel_section(self, section: str) -> None:
        self._dirty_sections.discard(section)
        self.refresh_from_config(force=True)
        self._set_active_editor(None, force=True)

    def _mark_section_saved(
        self,
        section: str,
        *,
        message: str | None = None,
        close: bool = True,
    ) -> None:
        self._dirty_sections.discard(section)
        status, save_button = {
            "billing": (self.billing_save_status, self.billing_save_button),
            "schedule": (self.schedule_save_status, self.schedule_save_button),
            "autostart": (self.autostart_save_status, self.autostart_save_button),
            "web": (self.web_save_status, self.web_save_button),
        }[section]
        status.setText(
            message
            or tr(
                f"บันทึกและตรวจสอบแล้ว {datetime.now():%H:%M} น.",
                f"Saved and verified at {datetime.now():%H:%M}",
            )
        )
        status.setStyleSheet(text_styles.label('#16875D', font_weight='700', border='none'))
        save_button.setEnabled(False)
        self._refresh_task_summaries()
        self.changed.emit()
        if close:
            self._set_active_editor(None, force=True)

    def _commit_shared_settings(self, section: str, changes: dict) -> bool:
        service = SharedSettingsService()
        try:
            preview = service.preview(changes, reason=f"{section}_settings_saved")
            if preview.changes and not confirm_shared_settings(self, preview):
                return False
            service.commit(preview)
            return True
        except Exception as error:
            status = self.billing_save_status if section == "billing" else self.schedule_save_status
            status.setText(tr("บันทึกไม่สำเร็จ: ", "Could not save: ") + str(error))
            status.setStyleSheet(text_styles.label('#B42318', font_weight='700', border='none'))
            return False

    def _save_billing(self) -> None:
        if self.billing_section.save(lambda changes: self._commit_shared_settings("billing", changes)):
            self._mark_section_saved("billing")

    def _save_schedule(self) -> None:
        try:
            schedule_windows = self._schedule_windows_from_table()
        except ValueError as error:
            QMessageBox.warning(
                self,
                tr("ตรวจตารางเวลา", "Check the schedule"),
                with_diagnostic(translate_text(str(error)), error, tr("ตรวจตารางเวลา", "Check the schedule")),
            )
            return
        serialized_windows = dump_schedule_windows(schedule_windows)
        if not self._commit_shared_settings("schedule", {"sync_schedule_windows": serialized_windows}):
            return
        stored_windows = load_schedule_windows(get_cfg("sync_schedule_windows", ""))
        if stored_windows != schedule_windows:
            self.schedule_save_button.setEnabled(True)
            self.schedule_save_status.setText(
                tr(
                    "บันทึกตารางเวลาไม่ครบ กรุณาลองอีกครั้ง",
                    "The schedule was not stored completely. Try again.",
                )
            )
            self.schedule_save_status.setStyleSheet(
                text_styles.label('#B42318', font_weight='700', border='none')
            )
            return
        self.schedule_section.using_defaults = False
        self._refresh_schedule()
        self._mark_section_saved("schedule")

    def _save_autostart(self) -> None:
        expected = self.autostart.isChecked()
        try:
            configure_autostart(expected, apply=True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                tr("ตั้งค่า Auto-start ไม่สำเร็จ", "Could not configure automatic start"),
                with_diagnostic(translate_text(str(exc)), exc, tr("ตั้งค่า Auto-start ไม่สำเร็จ", "Could not configure automatic start")),
            )
            return
        set_cfg("autostart_enabled", "1" if expected else "0")
        registration = self._autostart_registration_status()
        self._refresh_autostart_status(registration)
        if registration is not expected:
            self.autostart_save_button.setEnabled(True)
            self.autostart_save_status.setText(
                tr(
                    "บันทึกค่าแล้ว แต่ OS registration ยังไม่ตรงกับค่าที่เลือก",
                    "The value was saved, but OS registration does not match it yet.",
                )
            )
            self.autostart_save_status.setStyleSheet(
                text_styles.label('#B54708', font_weight='700', border='none')
            )
            self._refresh_task_summaries(registration=registration)
            self.changed.emit()
            return
        self._mark_section_saved("autostart", close=False)

    def _save_web(self) -> None:
        web_enabled = self.web_service_enabled.isChecked()
        env_path = self.web_service.runtime_root / ".env.local"
        previous_access = web_access_status(env_path)
        previous_port = read_web_port(env_path)
        current = self.web_service.status()
        try:
            port = validate_web_port(self.web_port.value())
            if port != previous_port:
                if current.state == "external":
                    raise ValueError("Web service เปิดจากโปรแกรมอื่น กรุณาปิดที่โปรแกรมนั้นก่อนเปลี่ยน Port")
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.bind(("0.0.0.0", port))
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, "เปลี่ยน Port ไม่ได้", with_diagnostic(f"Port ที่เลือกไม่พร้อมใช้งาน: {error}", error, "เปลี่ยน Port ไม่ได้"))
            return
        passwordless = not self.web_report_require_password.isChecked()
        if not passwordless and not previous_access.configured:
            dialog = WebAccessCodeDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            try:
                set_web_access_code(env_path, dialog.value())
            except (OSError, ValueError) as error:
                QMessageBox.warning(self, tr("ตั้งรหัสไม่สำเร็จ", "Could not set password"), with_diagnostic(str(error), error, tr("ตั้งรหัสไม่สำเร็จ", "Could not set password")))
                return
        try:
            set_web_report_passwordless(env_path, passwordless)
            update_web_runtime_values(env_path, {"KOMI_WEB_PORT": str(port)})
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                tr("บันทึกการเข้าถึง Web ไม่สำเร็จ", "Could not save Web access"),
                with_diagnostic(translate_text(str(error)), error, tr("บันทึกการเข้าถึง Web ไม่สำเร็จ", "Could not save Web access")),
            )
            return
        set_cfg("web_service_enabled", "1" if web_enabled else "0")
        access_changed = previous_access.report_passwordless != passwordless or port != previous_port
        if web_enabled and access_changed and current.state in {
            "running",
            "starting",
            "external",
        }:
            web_status = self.web_service.restart()
        else:
            web_status = self.web_service.start() if web_enabled else self.web_service.stop()
        self._refresh_web_status(web_status)
        stored_enabled = get_cfg("web_service_enabled", "") == "1"
        if (
            stored_enabled != web_enabled
            or not self._web_runtime_matches(web_enabled, web_status)
            or web_status.state == "starting"
        ):
            self.web_save_button.setEnabled(web_status.state != "starting")
            self.web_save_status.setText(
                tr(
                    "บันทึกค่าแล้ว แต่สถานะ Web Report ยังไม่ตรง · ตรวจข้อความด้านบนแล้วลองอีกครั้ง",
                    "The setting was saved, but the Web Report status still does not match. Check the message above and try again.",
                )
            )
            self.web_save_status.setStyleSheet(text_styles.label('#B42318', font_weight='700', border='none'))
            self.changed.emit()
            return
        self._mark_section_saved("web")

    def _save(self) -> None:
        """Compatibility dispatcher for older callers; the UI has no global Save."""
        for section, handler in (
            ("billing", self._save_billing),
            ("schedule", self._save_schedule),
            ("web", self._save_web),
        ):
            if section in self._dirty_sections:
                handler()
                return

    def _refresh_schedule(self) -> None:
        self.schedule_section.refresh_summary()

    def _replace_schedule_windows(self, windows: tuple[ScheduleWindow, ...]) -> None:
        self.schedule_section.replace_windows(windows)


    def _add_schedule_window(self) -> None:
        self.schedule_section.add_window()


    def _schedule_windows_from_table(self) -> tuple[ScheduleWindow, ...]:
        return self.schedule_section.values()

    def _choose_counters(self) -> None:
        if PinnedCountersDialog(self.repository, self).exec() == QDialog.DialogCode.Accepted:
            self.changed.emit()
