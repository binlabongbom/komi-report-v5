"""Wizard UI; owns its widgets and their lifecycle."""
from __future__ import annotations

import ipaddress
import webbrowser
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import DEFAULT_ADMIN_USERNAME, DEFAULT_BILLING_DAY, DEFAULT_WASTE_PCT, PACKAGE_VERSION
from database import copy_database_for_first_run, get_cfg, get_db_path, init_db, set_cfg, set_db_path
from i18n import ENGLISH, ITEM_TRANSLATABLE_ROLE, THAI, apply_language, get_language, set_language, tr, translate_text
from komi_snmp_profiler.credential_store import PUBLIC_FACTORY_ADMIN_PASSWORDS
from komi_snmp_profiler.device_profiles import resolve_device_meter_profile
from runtime_config import RUNTIME_SETTINGS, save_runtime_database_path
from services.build_edition import is_offline_edition
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.legacy_history_import import detect_legacy_history_sources, load_imported_legacy_history
from services.pricing import PriceList, PricingRepository
from services.registration_data_notice import REGISTRATION_NOTICE_VERSION, registration_data_notice
from services.registration_envelope import runtime_platform
from services.registration_errors import error_message, safe_support_code
from services.secondary_setup import SecondaryPeerCandidate, SecondarySetupError, normalize_primary_ipv4
from services.setup_connectivity import SetupConnectivityCheck, SetupConnectivityReport
from services.setup_meter_baselines import SetupMeterBaselines
from services.parser_mapping import apply_parser_mapping_overrides
from services.support_diagnostics import with_diagnostic
from services.v5_2_runtime_state import V52RuntimeStateRepository
from ui.button_system import install_button_system
from ui.policy import OFFLINE_ACTIVATION_ENABLED
from ui.setup.appearance import style_wizard_combo
from ui.setup.controls import WizardComboBox
from ui.setup.legacy_import import LegacyHistoryImportDialog
from ui.setup.steps.company import CompanyStep
from ui.setup.steps.devices import DevicesStep
from ui.setup.steps.meter import MeterReviewDevice, MeterStep
from ui.setup.steps.pricing import PricingStep
from ui.setup.steps.review import ReviewDevice, ReviewStep, SetupReviewData
from ui.setup.workers import (
    DeviceTestResult,
    DeviceTestWorker,
    EnrollmentCommitWorker,
    NetworkDiscoveryWorker,
    SecondaryPeerDiscoveryWorker,
    SecondarySnapshotWorker,
    SetupConnectivityWorker,
    device_test_key,
)
from ui.shared_settings_confirmation import confirm_shared_settings
from ui.styles import setup as setup_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_GREEN, C_RED, C_TEXT2, F_2XL, F_LG, F_MD, F_XL
from widgets import btn, fnt


class SetupWizardV5(QDialog):
    ADVANCED_SCAN_EXAMPLES = ("เช่น 192.168.1.1", "เช่น 192.168.1.255")

    _LIGHT_STYLE = setup_styles.SETUP_PANEL

    _MODAL_LIGHT_STYLE = setup_styles.SETUP_MODAL

    def __init__(
        self,
        parent=None,
        *,
        edit_mode: bool = False,
        lab_mode: bool = False,
        lab_hosts: list[str] | None = None,
        lab_snmp_port: int = 161,
        lab_web_port: int = 443,
        legacy_source_paths: list[str] | None = None,
        runtime_config_path: str | None = None,
        registration_runtime=None,
        offline_license_public_keys: dict[str, str] | None = None,
        secondary_peer_hosts: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._apply_light_appearance()
        install_button_system(QApplication.instance())
        set_language(get_cfg("ui_language", THAI))
        self.repository = DeviceConfigRepository()
        self.registration_state = V52RuntimeStateRepository()
        self.registration_runtime = registration_runtime
        self.offline_license_public_keys = dict(offline_license_public_keys or {})
        self.secondary_peer_hosts = secondary_peer_hosts
        self.secondary_candidates: list[SecondaryPeerCandidate] = []
        self.secondary_candidate: SecondaryPeerCandidate | None = None
        self.secondary_snapshot: dict[str, object] | None = None
        self.secondary_enrollment = None
        self._enrollment_commit_thread = None
        self._secondary_discovery_thread: QThread | None = None
        self._secondary_discovery_worker: SecondaryPeerDiscoveryWorker | None = None
        self._secondary_discovery_manual_host = ""
        self._secondary_manual_revealed = False
        self._secondary_sync_thread: QThread | None = None
        self._secondary_sync_worker: SecondarySnapshotWorker | None = None
        self._secondary_sync_dialog: QDialog | None = None
        self._secondary_sync_cancelled = False
        self._secondary_auto_review = False
        self._setup_connectivity_thread: QThread | None = None
        self._setup_connectivity_worker: SetupConnectivityWorker | None = None
        self.pricing = PricingRepository()
        self.edit_mode = edit_mode
        self.lab_mode = lab_mode
        self.lab_hosts = lab_hosts
        self.lab_snmp_port = lab_snmp_port
        self.lab_web_port = lab_web_port
        self.runtime_config_path = Path(runtime_config_path or RUNTIME_SETTINGS.config_path)
        self.selected_database_path = Path(get_db_path()).expanduser().resolve(strict=False)
        self.legacy_source_paths = detect_legacy_history_sources(
            legacy_source_paths or (),
            include_known_locations=legacy_source_paths is None,
        )
        self.has_legacy_history = bool(
            self.legacy_source_paths or load_imported_legacy_history()
        )
        self.results: dict[int, dict] = {}
        self._meter_evidence = {}
        self._meter_step_required = False
        self._test_generation = 0
        self._auto_advance_pending = False
        self._registration_in_progress = False
        self._registration_dialog: QDialog | None = None
        self._registration_poll_timer: QTimer | None = None
        self._registration_deadline: datetime | None = None
        # QDialog.open() is asynchronous; retain every child dialog for the
        # Wizard lifetime as required by Qt and to keep macOS Accessibility
        # from querying a wrapper that Python has already released.
        self._wizard_child_dialogs: list[QDialog] = []
        self._thread: QThread | None = None
        self._scan_thread: QThread | None = None
        self._worker: DeviceTestWorker | None = None
        self._scan_worker: NetworkDiscoveryWorker | None = None
        self.setWindowTitle(f"ตั้งค่า KOMI Report V{PACKAGE_VERSION}")
        self.setMinimumSize(800, 520)
        self._build()
        self._load_existing()
        apply_language(self)
        self._sync_language_switch()
        self._fit_to_available_screen()
        if (
            not self.edit_mode
            and not self.lab_mode
            and not self.repository.setup_complete()
            and QApplication.platformName() != "offscreen"
        ):
            QTimer.singleShot(350, self._start_secondary_discovery)

    def _fit_to_available_screen(self) -> None:
        """Keep the Wizard a normal centered window on common office displays."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(1120, 720)
            return
        available = screen.availableGeometry()
        width = min(1120, max(self.minimumWidth(), int(available.width() * 0.90)))
        height = min(720, max(self.minimumHeight(), int(available.height() * 0.90)))
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _apply_light_appearance(self) -> None:
        """Keep onboarding readable and identical when the OS uses Dark Mode."""
        self.setObjectName("setup_wizard_v5")
        palette = QPalette(self.palette())
        light_roles = {
            QPalette.ColorRole.Window: "#F4F7FA",
            QPalette.ColorRole.WindowText: "#172033",
            QPalette.ColorRole.Base: "#FFFFFF",
            QPalette.ColorRole.AlternateBase: "#F7FAFD",
            QPalette.ColorRole.Text: "#172033",
            QPalette.ColorRole.Button: "#FFFFFF",
            QPalette.ColorRole.ButtonText: "#172033",
            QPalette.ColorRole.Highlight: "#DCEEFF",
            QPalette.ColorRole.HighlightedText: "#102A43",
            QPalette.ColorRole.PlaceholderText: "#52677D",
            QPalette.ColorRole.ToolTipBase: "#173A63",
            QPalette.ColorRole.ToolTipText: "#FFFFFF",
        }
        for role, colour in light_roles.items():
            palette.setColor(role, QColor(colour))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#64748B"))
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#64748B"))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setStyleSheet(self._LIGHT_STYLE)

    def _prepare_wizard_dialog(self, dialog: QDialog) -> None:
        """Keep every Wizard-owned modal readable when macOS uses Dark Mode."""
        dialog.setObjectName("wizard_modal")
        dialog.setPalette(self.palette())
        dialog.setAutoFillBackground(True)
        dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        dialog.setStyleSheet(self._MODAL_LIGHT_STYLE)
        apply_language(dialog)
        if get_language() == ENGLISH:
            for field in dialog.findChildren(QLineEdit):
                field.setPlaceholderText(translate_text(field.placeholderText()))

    def _style_wizard_combo(self, combo: QComboBox, *, popup_width: int | None = None) -> None:
        style_wizard_combo(combo, self.palette(), popup_width=popup_width)


    def _open_wizard_child(
        self,
        dialog: QDialog,
        on_finished: Callable[[int], None] | None = None,
    ) -> QDialog:
        """Open a retained modal child without spinning a nested event loop."""
        if dialog.objectName() != "wizard_modal":
            self._prepare_wizard_dialog(dialog)
        self._wizard_child_dialogs.append(dialog)
        if on_finished is not None:
            dialog.finished.connect(on_finished)
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()
        return dialog

    def _build_wizard_message(
        self,
        title: str,
        message: str,
        *,
        icon: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_MessageBoxWarning,
    ) -> QDialog:
        """Build a stable cross-platform alert instead of a native QMessageBox.

        macOS can recalculate a native QMessageBox after the application-wide
        button styling is applied, which leaves the action outside the visible
        dialog.  This Qt-owned layout keeps the copy and action inside a known
        responsive width on macOS, Windows and Linux.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.setMinimumWidth(500)
        dialog.setMaximumWidth(680)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(20)
        content = QHBoxLayout()
        content.setSpacing(18)
        content.setAlignment(Qt.AlignmentFlag.AlignTop)

        icon_label = QLabel()
        icon_label.setObjectName("wizard_alert_icon")
        icon_label.setFixedSize(52, 52)
        icon_label.setPixmap(self.style().standardIcon(icon).pixmap(48, 48))
        icon_label.setAccessibleName(
            tr("คำเตือน", "Warning")
            if icon == QStyle.StandardPixmap.SP_MessageBoxWarning
            else tr("ข้อมูล", "Information")
        )
        content.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("wizard_alert_title")
        heading.setFont(fnt(F_LG, True))
        heading.setWordWrap(True)
        from services.support_diagnostics import diagnose, safe_text, warning_report
        message = safe_text(message)
        heading_text, marker, report_tail = message.partition('KOMI Diagnostic v1\n')
        report = marker + report_tail if marker else warning_report(title, message)
        visible_message = heading_text.strip()
        if marker:
            diagnostic = diagnose(report)
            visible_message = (visible_message + '\n' if visible_message else '') + f'Error Code: {diagnostic.error_code}\n' + diagnostic.summary + '\n' + diagnostic.action
        else:
            visible_message = message + f'\nError Code: {diagnose(report).error_code}'
        message_label = QLabel(visible_message)
        message_label.setObjectName("wizard_alert_message")
        message_label.setFont(fnt(F_MD))
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        message_label.setMinimumWidth(350)
        message_label.setMaximumWidth(500)
        copy.addWidget(heading)
        copy.addWidget(message_label)
        content.addLayout(copy, 1)
        root.addLayout(content)

        if marker:
            details = QPlainTextEdit(report)
            details.setReadOnly(True)
            details.setMaximumHeight(180)
            details.setObjectName('wizard_diagnostic_details')
            root.addWidget(details)

        actions = QHBoxLayout()
        copy_diagnostic = btn(tr('คัดลอกรายละเอียด', 'Copy details'), 'outline')
        copy_diagnostic.clicked.connect(lambda: QApplication.clipboard().setText(report))
        actions.addWidget(copy_diagnostic)
        actions.addStretch()
        confirm = btn(tr("ตกลง", "OK"), "primary")
        confirm.setAccessibleName(tr("ปิดข้อความ", "Close message"))
        confirm.setMinimumWidth(104)
        confirm.clicked.connect(dialog.accept)
        actions.addWidget(confirm)
        root.addLayout(actions)

        self._prepare_wizard_dialog(dialog)
        dialog.adjustSize()
        dialog.resize(max(500, dialog.sizeHint().width()), dialog.sizeHint().height())
        return dialog

    def _show_wizard_message(
        self,
        title: str,
        message: str,
        *,
        icon: QStyle.StandardPixmap = QStyle.StandardPixmap.SP_MessageBoxWarning,
    ) -> None:
        self._open_wizard_child(
            self._build_wizard_message(title, message, icon=icon)
        )

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        header = QHBoxLayout()
        header.setSpacing(16)
        self.title = QLabel("ข้อมูลองค์กร")
        self.title.setFont(fnt(F_2XL, True))
        self.title.setWordWrap(True)
        self.title.setMinimumWidth(0)
        self.title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(self.title, 1)
        self.header_controls = QWidget()
        self.header_controls.setObjectName("wizard_header_controls")
        header_tools = QHBoxLayout(self.header_controls)
        header_tools.setContentsMargins(0, 0, 0, 0)
        header_tools.setSpacing(10)
        self.language_switch = QFrame()
        self.language_switch.setObjectName("wizard_language_switch")
        self.language_switch.setAccessibleName("ภาษา / Language")
        language_layout = QHBoxLayout(self.language_switch)
        language_layout.setContentsMargins(2, 2, 2, 2)
        language_layout.setSpacing(0)
        self.language_button_group = QButtonGroup(self)
        self.language_button_group.setExclusive(True)
        self.thai_language_button = QPushButton("ไทย")
        self.thai_language_button.setCheckable(True)
        self.thai_language_button.setAccessibleName("ใช้ภาษาไทย")
        self.english_language_button = QPushButton("EN")
        self.english_language_button.setCheckable(True)
        self.english_language_button.setAccessibleName("Use English")
        self.language_button_group.addButton(self.thai_language_button)
        self.language_button_group.addButton(self.english_language_button)
        self.thai_language_button.clicked.connect(
            lambda: self._set_wizard_language(THAI)
        )
        self.english_language_button.clicked.connect(
            lambda: self._set_wizard_language(ENGLISH)
        )
        language_layout.addWidget(self.thai_language_button)
        language_layout.addWidget(self.english_language_button)
        header_tools.addWidget(self.language_switch)
        self.step_label = QLabel("1 / 5")
        self.step_label.setStyleSheet(text_styles.label('#1769AA', font_weight='700'))
        self.step_label.setAccessibleName("ความคืบหน้าการตั้งค่า")
        header_tools.addWidget(self.step_label)
        self.header_controls.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        header.addWidget(self.header_controls, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.progress_labels: list[QLabel] = []
        for step_name in ("องค์กร", "เครื่องพิมพ์", "มิเตอร์เริ่มต้น", "ราคา", "ตรวจสอบ"):
            label = QLabel(step_name)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(30)
            self.progress_labels.append(label)
            progress.addWidget(label, 1)
        root.addLayout(progress)
        self._update_progress(0)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._company_page())
        self.stack.addWidget(self._device_page())
        self.meter_step = MeterStep(self)
        self.meter_step.readiness_changed.connect(self._meter_readiness_changed)
        self.stack.addWidget(self.meter_step)
        self.stack.addWidget(self._price_page())
        self.stack.addWidget(self._review_page())
        root.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        self.note = QLabel("ขั้นที่ 1: กรอกชื่อบริษัท · วันที่เริ่มใช้และ Version มาจากระบบอัตโนมัติ")
        self.note.setWordWrap(True)
        self.note.setStyleSheet(text_styles.label(C_TEXT2))
        nav.addWidget(self.note, 1)
        self.back_button = btn("← ย้อนกลับ", "outline")
        self.back_button.setVisible(False)
        self.back_button.clicked.connect(self._back)
        nav.addWidget(self.back_button)
        nav.addWidget(self.test_button)
        self.test_button.setVisible(False)
        self.next_button = btn("ค้นหาเครื่องพิมพ์ →", "primary")
        self.next_button.clicked.connect(self._next)
        nav.addWidget(self.next_button)
        root.addLayout(nav)

    def _company_page(self) -> QWidget:
        self.company_step = step = CompanyStep(self.selected_database_path, lab_mode=self.lab_mode, parent=self)
        step.primary_search_requested.connect(self._secondary_join_clicked)
        step.primary_join_requested.connect(self._secondary_manual_join_clicked)
        step.primary_port_changed.connect(self._secondary_port_changed)
        step.primary_options_requested.connect(self._show_secondary_manual_options)
        step.database_path_requested.connect(self._choose_database_destination)
        step.legacy_import_requested.connect(self._open_legacy_history_import)
        step.privacy_notice_requested.connect(self._show_privacy_notice)
        # Explicit aliases preserve integrations that access wizard controls.
        self.company_scroll = step.company_scroll
        self.secondary_join_card = step.secondary_join_card
        self.secondary_join_title = step.secondary_join_title
        self.secondary_join_status = step.secondary_join_status
        self.secondary_join_button = step.secondary_join_button
        self.secondary_manual_row = step.secondary_manual_row
        self.secondary_manual_ip = step.secondary_manual_ip
        self.secondary_primary_port = step.secondary_primary_port
        self.secondary_manual_button = step.secondary_manual_button
        self.company_card = step.company_card
        self.company_form = step.company_form
        self.company_name_input = step.company_name_input
        self.company_name_error = step.company_name_error
        self.company_name_container = step.company_name_container
        self.secondary_existing_button = step.secondary_existing_button
        self.first_started_input = step.first_started_input
        self.version_input = step.version_input
        self.database_path_container = step.database_path_container
        self.database_path_input = step.database_path_input
        self.choose_database_path_button = step.choose_database_path_button
        self.legacy_import_button = step.legacy_import_button
        self.database_path_status = step.database_path_status
        self.company_form_labels = step.company_form_labels
        self.privacy_notice_status = step.privacy_notice_status
        self.view_privacy_notice_button = step.view_privacy_notice_button
        self.company_notice = step.company_notice
        self.privacy_notice_accepted = step.privacy_notice_accepted
        self.registration_mode_group = step.registration_mode_group
        self.registration_online_mode = step.registration_online_mode
        self.registration_offline_mode = step.registration_offline_mode
        return step

    def _show_privacy_notice(self) -> None:
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
        self._open_wizard_child(dialog)

    def _registration_mode_changed(self, _checked: bool = False) -> None:
        online = self.registration_online_mode.isChecked()
        self.privacy_notice_accepted.setEnabled(online)
        if hasattr(self, "review_sections") and self._selected_entries():
            self._update_review()

    def _set_wizard_language(self, language: str) -> None:
        """Apply and persist a language selected on the first setup screen."""
        set_language(language)
        set_cfg("ui_language", language)
        if hasattr(self, "review_sections") and self._selected_entries():
            self._update_review()
        apply_language(self)
        self.meter_step.retranslate()
        self._sync_language_switch()

    def _sync_language_switch(self) -> None:
        """Keep the compact language labels stable in either UI language."""
        is_english = get_language() == ENGLISH
        for button in (self.thai_language_button, self.english_language_button):
            button.blockSignals(True)
        self.thai_language_button.setText("ไทย")
        self.english_language_button.setText("EN")
        self.thai_language_button.setChecked(not is_english)
        self.english_language_button.setChecked(is_english)
        for button in (self.thai_language_button, self.english_language_button):
            button.blockSignals(False)

    def _show_secondary_manual_options(self) -> None:
        """Reveal the compact opt-in controls for an existing Primary."""

        self._secondary_manual_revealed = True
        self.secondary_candidates = []
        self.secondary_join_title.setText(
            tr("เชื่อมต่อ KOMI Report เครื่องหลัก", "Connect to a KOMI Report Primary")
        )
        self.secondary_join_status.setText(
            tr(
                "ระบุ Primary IP หรือค้นหาเครื่องหลักในเครือข่าย LAN",
                "Enter the Primary IP or search for it on the LAN.",
            )
        )
        self.secondary_join_status.setStyleSheet(text_styles.label('#52677D'))
        self.secondary_join_button.setText(tr("ค้นหาอัตโนมัติ", "Search automatically"))
        self.secondary_manual_row.setVisible(True)
        self.secondary_join_card.setVisible(True)
        self.secondary_existing_button.setVisible(False)
        self.secondary_manual_ip.setFocus()
        QTimer.singleShot(
            0,
            lambda: self.company_scroll.ensureWidgetVisible(self.secondary_join_card),
        )

    def _start_secondary_discovery(
        self,
        hosts: list[str] | None = None,
        *,
        manual_host: str = "",
    ) -> None:
        """Look for an already-configured Desktop before creating a new setup."""

        if self._secondary_discovery_thread is not None or self._secondary_sync_thread is not None:
            return
        self._secondary_discovery_manual_host = manual_host
        self.secondary_join_button.setEnabled(False)
        self.secondary_join_button.setText(tr("กำลังค้นหา…", "Searching…"))
        self.secondary_join_status.setToolTip("")
        self.secondary_manual_button.setEnabled(False)
        self.secondary_manual_ip.setEnabled(False)
        self.secondary_primary_port.setEnabled(False)
        self.secondary_join_status.setText(
            tr(
                "กำลังค้นหา KOMI Report เครื่องหลักในเครือข่าย LAN…",
                "Searching the LAN for an existing KOMI Report Primary…",
            )
        )
        thread = QThread(self)
        worker = SecondaryPeerDiscoveryWorker(
            hosts if hosts is not None else self.secondary_peer_hosts,
            port=self.secondary_primary_port.value(),
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._secondary_discovery_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._secondary_discovery_thread = thread
        self._secondary_discovery_worker = worker
        thread.start()

    def _secondary_port_changed(self, _value: int) -> None:
        self.secondary_candidates = []
        self.secondary_join_button.setText(tr("ค้นหาเครื่องหลัก", "Find Primary"))

    def _secondary_join_clicked(self) -> None:
        if self.secondary_candidates:
            self._show_secondary_candidate_dialog(self.secondary_candidates)
            return
        self._start_secondary_discovery()

    def _secondary_manual_join_clicked(self) -> None:
        try:
            host = normalize_primary_ipv4(self.secondary_manual_ip.text())
        except SecondarySetupError as exc:
            self.secondary_join_status.setText(str(exc))
            self.secondary_join_status.setStyleSheet(text_styles.label('#C62828', font_weight='650'))
            self.secondary_manual_ip.setFocus()
            return
        self.secondary_candidates = []
        self.secondary_join_status.setStyleSheet(text_styles.label('#52677D'))
        self._start_secondary_discovery([host], manual_host=host)

    def _secondary_discovery_finished(self, candidates: object, error: str) -> None:
        self._secondary_discovery_thread = None
        self._secondary_discovery_worker = None
        self.secondary_join_button.setEnabled(True)
        self.secondary_manual_button.setEnabled(True)
        self.secondary_manual_ip.setEnabled(True)
        self.secondary_primary_port.setEnabled(True)
        self.secondary_join_status.setToolTip(error or "")
        self.secondary_join_button.setText(tr("ค้นหาเครื่องหลัก", "Find Primary"))
        self.secondary_candidates = [
            item for item in (candidates if isinstance(candidates, list) else [])
            if isinstance(item, SecondaryPeerCandidate)
        ]
        if self.secondary_candidates:
            self._secondary_discovery_manual_host = ""
            self.secondary_join_card.setVisible(True)
            self.secondary_existing_button.setVisible(False)
            self.secondary_manual_row.setVisible(False)
            self.secondary_join_title.setText(
                tr(
                    "พบ KOMI Report เครื่องหลักในระบบ",
                    "KOMI Report Primary found",
                )
            )
            self.secondary_join_button.setText(
                tr("ดึงการตั้งค่า", "Import settings")
            )
            self.secondary_join_status.setStyleSheet(text_styles.label('#52677D'))
            self.secondary_join_status.setText(
                tr(
                    f"พบเครื่องหลัก {len(self.secondary_candidates)} เครื่อง · "
                    "ต้องการดึงข้อมูลบริษัท เครื่องพิมพ์ ราคา และรอบบิลหรือไม่",
                    f"Found {len(self.secondary_candidates)} Primary Desktop(s). "
                    "Import its company, printer, pricing and billing settings?",
                )
            )
            return
        manual_host = self._secondary_discovery_manual_host
        self._secondary_discovery_manual_host = ""
        self.secondary_join_card.setVisible(True)
        self.secondary_join_title.setText(tr("ค้นหา KOMI Report ในเครือข่าย", "Find KOMI Report on the network"))
        self.secondary_join_button.setText(tr("ค้นหาอีกครั้ง", "Search again"))
        self.secondary_join_status.setToolTip(error or "")
        if manual_host:
            self.secondary_join_card.setVisible(True)
            self.secondary_existing_button.setVisible(False)
            self.secondary_manual_row.setVisible(True)
            self.secondary_join_status.setText(
                tr(
                    f"ไม่พบ KOMI Report Primary ที่ {manual_host} · ตรวจ IP และ LAN แล้วลองใหม่",
                    f"No KOMI Report Primary found at {manual_host} · check the IP and LAN, then retry",
                )
            )
            self.secondary_join_status.setStyleSheet(
                text_styles.label('#C62828', font_weight='650')
            )
            if error:
                self.secondary_join_status.setToolTip(error)
            return
        self.secondary_existing_button.setVisible(not self._secondary_manual_revealed)
        self.secondary_manual_row.setVisible(self._secondary_manual_revealed)
        self.secondary_join_status.setStyleSheet(text_styles.label('#52677D'))
        self.secondary_join_status.setText(
            tr(
                "ยังไม่พบเครื่องตอบกลับ · ตรวจ LAN และเปิด KOMI บนเครื่องที่ตั้งค่าไว้แล้ว",
                "No response yet. Check the LAN and open KOMI on a configured computer.",
            )
        )
        if error:
            self.secondary_join_status.setToolTip(error)

    def _show_secondary_candidate_dialog(
        self,
        candidates: list[SecondaryPeerCandidate],
    ) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("พบ KOMI Report เครื่องหลัก", "KOMI Report Primary found"))
        dialog.setMinimumWidth(620)
        layout = QVBoxLayout(dialog)
        title = QLabel(tr("พบการตั้งค่าที่ใช้งานอยู่ใน LAN", "Existing LAN setup found"))
        title.setFont(fnt(F_XL, True))
        layout.addWidget(title)
        copy = QLabel(
            tr(
                "Secondary จะดึงเฉพาะชื่อบริษัท เครื่องพิมพ์ ราคา และรอบบิล "
                "จากนั้นทดสอบเครื่องพิมพ์จากเครื่องนี้อีกครั้งก่อนบันทึก",
                "The Secondary copies only company, printer, price and billing settings, "
                "then verifies every printer from this computer before saving.",
            )
        )
        copy.setWordWrap(True)
        copy.setStyleSheet(text_styles.label('#52677D'))
        layout.addWidget(copy)
        selector = WizardComboBox()
        for candidate in candidates:
            selector.addItem(
                f"{candidate.company_name} · {candidate.base_url} · "
                f"{candidate.printer_count} {tr('เครื่องพิมพ์', 'printer(s)')}",
                candidate,
            )
        self._style_wizard_combo(selector, popup_width=560)
        layout.addWidget(selector)
        safety = QLabel(
            tr(
                "เข้าร่วมแล้วจะ Sync การตั้งค่าและประวัติการใช้งานต่อเนื่อง การเปลี่ยนค่ามีผลกับสมาชิกอื่น โดยไม่คัดลอกรหัสผ่านเครื่องพิมพ์หรือสิทธิ์ลงทะเบียน Host",
                "Joining enables ongoing settings and usage sync. Shared changes affect other members. Printer passwords and Host registration rights are not copied.",
            )
        )
        safety.setWordWrap(True)
        safety.setStyleSheet(
            setup_styles.SETUP_WIZARD_SAFETY
        )
        layout.addWidget(safety)
        actions = QHBoxLayout()
        actions.addStretch()
        normal = btn(tr("ตั้งค่าเครื่องนี้เอง", "Set up independently"), "outline")
        sync = btn(tr("เข้าร่วมและใช้การตั้งค่าร่วมกัน", "Join and share settings"), "primary")
        normal.clicked.connect(dialog.reject)
        sync.clicked.connect(dialog.accept)
        actions.addWidget(normal)
        actions.addWidget(sync)
        layout.addLayout(actions)

        def candidate_finished(result: int) -> None:
            if result != int(QDialog.DialogCode.Accepted):
                return
            candidate = selector.currentData()
            if isinstance(candidate, SecondaryPeerCandidate):
                self._start_secondary_snapshot(candidate)

        return self._open_wizard_child(dialog, candidate_finished)

    def _start_secondary_snapshot(
        self,
        candidate: SecondaryPeerCandidate,
    ) -> None:
        if self._secondary_sync_thread is not None:
            return
        try:
            self._activate_selected_database_path()
        except Exception as error:
            self._show_wizard_message(tr('เตรียมฐานข้อมูลไม่สำเร็จ', 'Database preparation failed'), with_diagnostic(str(error), error, tr('เตรียมฐานข้อมูลไม่สำเร็จ', 'Database preparation failed')))
            return
        self._secondary_sync_cancelled = False
        progress = QDialog(self)
        progress.setWindowTitle(tr("กำลัง Sync การตั้งค่า", "Syncing setup"))
        progress.setMinimumWidth(500)
        progress_layout = QVBoxLayout(progress)
        title = QLabel(tr("กำลังดึงการตั้งค่าจากเครื่องหลัก…", "Copying setup from Primary…"))
        title.setFont(fnt(F_LG, True))
        progress_layout.addWidget(title)
        detail = QLabel(
            tr(
                "กำลังตรวจสมาชิก ประวัติการตั้งค่า และฐานมิเตอร์ ยกเลิกได้ก่อนบันทึก",
                "Checking membership, settings history and meter baselines. You can cancel before saving.",
            )
        )
        detail.setWordWrap(True)
        progress_layout.addWidget(detail)
        bar = QProgressBar()
        bar.setRange(0, 0)
        progress_layout.addWidget(bar)
        cancel = btn(tr("ยกเลิก", "Cancel"), "outline")
        cancel.clicked.connect(lambda: self._cancel_secondary_snapshot(progress))
        progress_layout.addWidget(cancel, 0, Qt.AlignmentFlag.AlignRight)
        self._secondary_sync_dialog = self._open_wizard_child(progress)

        thread = QThread(self)
        worker = SecondarySnapshotWorker(candidate)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda snapshot, error: self._secondary_snapshot_finished(
                candidate,
                snapshot,
                error,
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._secondary_snapshot_stopped)
        thread.finished.connect(thread.deleteLater)
        self._secondary_sync_thread = thread
        self._secondary_sync_worker = worker
        thread.start()

    def _cancel_secondary_snapshot(self, dialog: QDialog) -> None:
        self._secondary_sync_cancelled = True
        if self._secondary_sync_worker is not None:
            self._secondary_sync_worker.cancelled.set()
        dialog.reject()

    def _secondary_snapshot_finished(
        self,
        candidate: SecondaryPeerCandidate,
        snapshot: object,
        error: str,
    ) -> None:
        if self._secondary_sync_dialog is not None:
            self._secondary_sync_dialog.accept()
            self._secondary_sync_dialog = None
        if self._secondary_sync_cancelled:
            if hasattr(snapshot, 'close'):
                snapshot.close()
            self.secondary_join_status.setText(
                tr("ยกเลิกการ Sync แล้ว · ยังไม่มีการเปลี่ยนแปลง", "Sync cancelled · no changes were made")
            )
            return
        from services.peer_enrollment import EnrollmentPreview
        if isinstance(snapshot, EnrollmentPreview):
            if self.secondary_enrollment is not None:
                self.secondary_enrollment.close()
            self.secondary_enrollment = snapshot
            snapshot = snapshot.snapshot()
        if error or not isinstance(snapshot, dict):
            self._show_wizard_message(
                tr("Sync ไม่สำเร็จ", "Sync failed"),
                with_diagnostic(error or tr("เครื่องหลักส่งข้อมูลไม่ครบ", "The Primary returned incomplete data"), error, tr("Sync ไม่สำเร็จ", "Sync failed")),
            )
            return
        try:
            self._apply_secondary_snapshot(candidate, snapshot)
        except (KeyError, TypeError, ValueError, SecondarySetupError) as exc:
            self._show_wizard_message(tr("Sync ไม่สำเร็จ", "Sync failed"), with_diagnostic(str(exc), exc, tr("Sync ไม่สำเร็จ", "Sync failed")))

    def _secondary_snapshot_stopped(self):
        self._secondary_sync_thread = None
        self._secondary_sync_worker = None

    def _apply_secondary_snapshot(
        self,
        candidate: SecondaryPeerCandidate,
        snapshot: dict[str, object],
    ) -> None:
        organization = snapshot["organization"]
        settings = snapshot["settings"]
        devices = snapshot["devices"]
        if not isinstance(organization, dict) or not isinstance(settings, dict) or not isinstance(devices, list):
            raise SecondarySetupError("ข้อมูลจากเครื่องหลักไม่สมบูรณ์")
        self.company_name_input.setText(str(organization["company_name"]))
        self.first_started_input.setText(
            self._display_first_started(str(organization["first_started_at"]))
        )
        self.discovered_devices.clear()
        self.results.clear()
        self.device_table.setRowCount(0)
        for raw in devices:
            if not isinstance(raw, dict):
                raise SecondarySetupError("ข้อมูลเครื่องพิมพ์จากเครื่องหลักไม่ถูกต้อง")
            slot = int(raw["slot"])
            self._upsert_discovered(
                {
                    "slot": slot,
                    "name": str(raw["name"]),
                    "name_is_default": False,
                    "host": str(raw["host"]),
                    "model": str(raw["model"]),
                    "serial": str(raw["serial"]),
                    "username": DEFAULT_ADMIN_USERNAME,
                    "password": "",
                    "tls_mode": str(raw["tls_mode"]),
                    "tls_fingerprint": str(raw["tls_fingerprint"]),
                    "found_in_registration_scan": True,
                    "result": {
                        "online": False,
                        "web_ok": False,
                        "tested": False,
                        "synced_from_primary": True,
                        "model": str(raw["model"]),
                        "serial": str(raw["serial"]),
                    },
                },
                select=True,
            )
            prices = raw["prices"]
            if not isinstance(prices, dict):
                raise SecondarySetupError("ราคาจากเครื่องหลักไม่ถูกต้อง")
            for key, spin in self.price_rows[slot].items():
                spin.setValue(float(prices[key]))
            if slot == 0:
                for key, spin in self.shared_price_row.items():
                    spin.setValue(float(prices[key]))
        pricing_mode = str(settings["pricing_mode"])
        self.shared_price_mode.setChecked(pricing_mode == "shared")
        self.per_device_price_mode.setChecked(pricing_mode == "per_device")
        self.deferred_price_mode.setChecked(pricing_mode == "deferred")
        self.waste_paper_pct.setValue(float(settings["waste_paper_pct"]))
        self.billing_end_day.setCurrentIndex(int(settings["billing_day"]) - 1)
        self.secondary_candidate = candidate
        self.secondary_snapshot = snapshot
        if self.secondary_enrollment is not None:
            # Joining preserves the reviewed history; later edits use shared Settings.
            for control in (self.company_name_input, self.shared_price_mode,
                    self.per_device_price_mode, self.deferred_price_mode,
                    self.waste_paper_pct, self.billing_end_day, self.effective_date,
                    *self.shared_price_row.values(),
                    *(spin for row in self.price_rows for spin in row.values())):
                control.setEnabled(False)
        self.secondary_join_status.setText(
            tr(
                "รับการตั้งค่าแล้ว · กำลังทดสอบเครื่องพิมพ์จาก Secondary เครื่องนี้",
                "Setup copied · verifying printers from this Secondary Desktop",
            )
        )
        self._secondary_auto_review = True
        if self.stack.currentIndex() == 0:
            self._next()
        else:
            QTimer.singleShot(0, self._test_all)

    def _choose_database_destination(self) -> None:
        start = str(self.selected_database_path)
        selected, _ = QFileDialog.getSaveFileName(
            self,
            tr("เลือก Path สำหรับสร้าง Database", "Choose where to create the database"),
            start,
            "SQLite Database (*.db *.sqlite *.sqlite3)",
        )
        if selected:
            self._set_database_destination(selected)

    def _set_database_destination(self, selected: str) -> bool:
        """Validate and stage a new database path without creating it yet."""
        candidate = Path(selected).expanduser()
        if not candidate.suffix:
            candidate = candidate.with_suffix(".db")
        candidate = candidate.resolve(strict=False)
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        if candidate.exists() and candidate != active:
            self._show_wizard_message(
                tr("Path นี้มีไฟล์อยู่แล้ว", "A file already exists at this path"),
                tr(
                    "กรุณาเลือกชื่อ Database ใหม่ หรือใช้ปุ่ม ‘นำเข้าฐานข้อมูลเดิม’",
                    "Choose a new database filename or use ‘Import existing database’.",
                ),
            )
            return False
        self.selected_database_path = candidate
        self.database_path_input.setText(str(candidate))
        self.database_path_input.setToolTip(str(candidate))
        if self.lab_mode:
            status = tr(
                "SETUP LAB · แสดง Path เพื่อทดสอบเท่านั้น และจะไม่สร้างไฟล์จริง",
                "SETUP LAB · the path is shown for testing and no database file will be created",
            )
        elif candidate == active:
            status = tr(
                "ใช้ Database Path ค่าเริ่มต้นนี้",
                "Using this default database path",
            )
        else:
            status = tr(
                "พร้อมสร้าง Database ใหม่เมื่อกดบันทึก · ยังไม่มีการเขียนไฟล์",
                "Ready to create the database when setup is saved · no file has been written yet",
            )
        self.database_path_status.setText(status)
        self.database_path_status.setStyleSheet(text_styles.label('#52677D', border='none'))
        self.database_path_status.setVisible(True)
        return True

    def _activate_selected_database_path(self) -> None:
        """Create, verify and activate the staged first-run database destination."""
        if self.lab_mode:
            return
        active = Path(get_db_path()).expanduser().resolve(strict=False)
        target = self.selected_database_path.expanduser().resolve(strict=False)
        if target == active:
            return
        created = copy_database_for_first_run(target)
        try:
            save_runtime_database_path(created, config_path=self.runtime_config_path)
        except Exception:
            created.unlink(missing_ok=True)
            raise
        set_db_path(created)
        init_db()

    def _update_progress(self, active_step: int) -> None:
        for index, label in enumerate(self.progress_labels):
            if index < active_step:
                style = setup_styles.UPDATE_PROGRESS_STYLE
            elif index == active_step:
                style = setup_styles.UPDATE_PROGRESS_STYLE_ACTIVE
            else:
                style = setup_styles.UPDATE_PROGRESS_STYLE_INACTIVE
            label.setStyleSheet(style)

    def _device_page(self) -> QWidget:
        self.devices_step = step = DevicesStep(self)
        step.scan_requested.connect(self._scan_network)
        step.cancel_scan_requested.connect(self._cancel_scan)
        step.advanced_scan_requested.connect(self._advanced_scan)
        step.manual_setup_requested.connect(self._manual_setup)
        step.device_action_requested.connect(self._device_table_action)
        step.verify_requested.connect(self._test_all)
        # Explicit aliases preserve integrations that access wizard controls.
        self.scan_button = step.scan_button
        self.cancel_scan_button = step.cancel_scan_button
        self.fallback_toggle = step.fallback_toggle
        self.selection_badge = step.selection_badge
        self.fallback_actions = step.fallback_actions
        self.advanced_scan_button = step.advanced_scan_button
        self.manual_setup_button = step.manual_setup_button
        self.scan_status = step.scan_status
        self.scan_progress_bar = step.scan_progress_bar
        self.device_table = step.device_table
        self.test_button = step.test_button
        self.discovered_devices: list[dict] = []
        return step


    def _cancel_scan(self) -> None:
        if self._scan_thread is None:
            return
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        if self._secondary_sync_worker is not None:
            self._secondary_sync_worker.cancelled.set()
            self._secondary_sync_cancelled = True
        self._scan_thread.requestInterruption()
        self.scan_status.setText("กำลังยกเลิกการค้นหา…")
        self.cancel_scan_button.setEnabled(False)

    def _open_legacy_history_import(self) -> None:
        dialog = LegacyHistoryImportDialog(self)
        def import_finished(_result: int) -> None:
            if dialog.import_result is not None:
                imported = dialog.import_result.imported_rows
                self.database_path_status.setText(
                    tr(
                        f"นำเข้าประวัติ V4.6 แล้ว {imported:,} รายการ · ไม่เปลี่ยนการตั้งค่าเครื่อง",
                        f"Imported {imported:,} V4.6 history rows · printer settings unchanged",
                    )
                )
                self.database_path_status.setStyleSheet(
                    text_styles.label(C_GREEN, border='none', font_weight='700')
                )
                self.database_path_status.setVisible(True)

        self._open_wizard_child(dialog, import_finished)

    def _review_page(self) -> QWidget:
        self.review_step = step = ReviewStep(self)
        step.edit_requested.connect(self._go_to_step)
        # Explicit aliases preserve integrations that access wizard controls.
        self.review_sections = step.review_sections
        self.review_ready_note = step.review_ready_note
        self.registration_status_label = step.registration_status_label
        return step

    def _go_to_step(self, target_step: int) -> None:
        while self.stack.currentIndex() > target_step:
            previous = self.stack.currentIndex()
            self._back()
            if self.stack.currentIndex() >= previous:
                # A changed baseline can stop backward navigation with a
                # validation message; do not spin on the GUI thread.
                break

    def _price_page(self) -> QWidget:
        self.pricing_step = step = PricingStep(edit_mode=self.edit_mode, parent=self)
        # Explicit aliases preserve integrations that access wizard controls.
        self.price_scroll = step.price_scroll
        self.price_content = step.price_content
        self.price_intro = step.price_intro
        self.shared_price_mode = step.shared_price_mode
        self.per_device_price_mode = step.per_device_price_mode
        self.deferred_price_mode = step.deferred_price_mode
        self.price_mode_group = step.price_mode_group
        self.effective_row_widget = step.effective_row_widget
        self.effective_date = step.effective_date
        self.deferred_price_notice = step.deferred_price_notice
        self.shared_price_box = step.shared_price_box
        self.shared_price_row = step.shared_price_row
        self.per_device_price_box = step.per_device_price_box
        self.price_rows = step.price_rows
        self.device_price_cards = step.device_price_cards
        self.billing_section = step.billing_section
        self.billing_defaults = step.billing_defaults
        self.waste_paper_pct = step.waste_paper_pct
        self.billing_end_day = step.billing_end_day
        return step

    def _refresh_device_price_cards(self) -> None:
        self.pricing_step.set_devices(self._configs())

    def _load_existing(self) -> None:
        first_started = get_cfg("client_first_started_at", "") or date.today().isoformat()
        self.first_started_input.setText(self._display_first_started(first_started))
        self.company_name_input.setText(get_cfg("company_name", "") or "")
        if self.lab_mode and not self.company_name_input.text().strip():
            self.company_name_input.setText("บริษัท ตัวอย่าง จำกัด")
        registration_snapshot = self.registration_state.snapshot()
        self.privacy_notice_accepted.setChecked(
            bool(registration_snapshot.get("notice_accepted"))
        )
        saved_mode = str(registration_snapshot.get("mode") or "online")
        self.registration_offline_mode.setChecked(saved_mode == "offline")
        self.registration_online_mode.setChecked(saved_mode != "offline")
        self._registration_mode_changed()
        existing_devices = self.repository.list()
        for device in existing_devices:
            result = {
                # A saved status is historical evidence, not proof that the
                # printer is reachable in this setup session.  Always require
                # a fresh SNMP + Web verification before showing Ready.
                "online": False,
                "web_ok": False,
                "tested": False,
                "saved": True,
                "previous_connection_status": device.connection_status,
                "model": device.model,
                "serial": device.serial,
                "total": device.last_total,
            }
            self.results[device.slot] = result
            self._upsert_discovered(
                {
                    "slot": device.slot,
                    "name": device.name,
                    "host": device.host,
                    "model": device.model,
                    "serial": device.serial,
                    "username": device.username,
                    "password": device.password,
                    "tls_mode": device.tls_mode,
                    "tls_fingerprint": device.tls_fingerprint,
                    "web_protocol": device.web_protocol,
                    "result": result,
                },
                select=device.enabled,
            )
        today = date.today()
        for slot, row in enumerate(self.price_rows):
            prices = self.pricing.get_prices(slot, today)
            for key, spin in row.items():
                spin.setValue(getattr(prices, key))
        if existing_devices:
            first_prices = self.pricing.get_prices(existing_devices[0].slot, today)
            for key, spin in self.shared_price_row.items():
                spin.setValue(getattr(first_prices, key))
        self.waste_paper_pct.setValue(float(get_cfg("waste_paper_pct", str(DEFAULT_WASTE_PCT)) or DEFAULT_WASTE_PCT))
        billing_day = int(get_cfg("billing_day", str(DEFAULT_BILLING_DAY)) or DEFAULT_BILLING_DAY)
        self.billing_end_day.setCurrentIndex(max(0, min(30, billing_day - 1)))
        mode = get_cfg("pricing_mode", "per_device" if existing_devices else "shared")
        self.shared_price_mode.setChecked(mode not in {"per_device", "deferred"})
        self.per_device_price_mode.setChecked(mode == "per_device")
        self.deferred_price_mode.setChecked(mode == "deferred")
        self.pricing_step.refresh_mode()

    @staticmethod
    def _display_first_started(value: str) -> str:
        try:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        except ValueError:
            return value

    def _selected_entries(self) -> list[dict]:
        return [entry for entry in self.discovered_devices if entry.get("selected")]

    def _selection_changed(self) -> None:
        # A confirmation is for the selected physical printer in its Slot.
        self.meter_step.invalidate()
        selected_count = len(self._selected_entries())
        self.selection_badge.setText(f"เลือกแล้ว {selected_count}/3")
        for row in range(len(self.discovered_devices)):
            self._render_discovered_row(row)
        self._update_device_actions()

    def _set_device_selected(self, row: int, selected: bool) -> None:
        if row >= len(self.discovered_devices):
            return
        entry = self.discovered_devices[row]
        if selected and not entry.get("selected") and len(self._selected_entries()) >= 3:
            self._show_wizard_message(
                "เลือกได้สูงสุด 3 เครื่อง",
                "KOMI Report V5 ตั้งค่าได้สูงสุด 3 เครื่อง",
                icon=QStyle.StandardPixmap.SP_MessageBoxInformation,
            )
            self._render_discovered_row(row)
            return
        entry["selected"] = selected
        self._selection_changed()

    def _upsert_discovered(self, payload: dict, *, select: bool = False) -> None:
        host = str(payload["host"])
        row = next((index for index, item in enumerate(self.discovered_devices) if item["host"] == host), None)
        if row is None:
            entry = {
                "slot": payload.get("slot"),
                "name": payload.get("name") or payload.get("model") or host,
                "name_is_default": bool(payload.get("name_is_default", False)),
                "host": host,
                "model": payload.get("model") or "—",
                "serial": payload.get("serial") or "—",
                "username": payload.get("username") or DEFAULT_ADMIN_USERNAME,
                "password": payload.get("password") or "",
                "tls_mode": payload.get("tls_mode") or "system",
                "tls_fingerprint": payload.get("tls_fingerprint") or "",
                "web_protocol": payload.get("web_protocol") or "auto",
                "result": payload.get("result") or {"online": True, "web_ok": False},
                "is_virtual": bool(payload.get("is_virtual", False)),
                "found_in_registration_scan": bool(payload.get("found_in_registration_scan", False)),
                "selected": bool(select),
            }
            self.discovered_devices.append(entry)
            row = len(self.discovered_devices) - 1
        else:
            entry = self.discovered_devices[row]
            old_model = str(entry.get("model") or "")
            old_serial = str(entry.get("serial") or "")
            entry.update({key: value for key, value in payload.items() if key != "host" and value is not None})
            entry["host"] = host
            entry["result"] = payload.get("result", entry.get("result", {}))
            identity_changed = (
                str(entry.get("model") or "") != old_model
                or str(entry.get("serial") or "") != old_serial
            )
            if identity_changed and "result" not in payload:
                entry["result"] = {"online": True, "web_ok": False}
        self._render_discovered_row(row)
        if select:
            entry["selected"] = True
            self._selection_changed()

    def _render_discovered_row(self, row: int) -> None:
        entry = self.discovered_devices[row]
        self.device_table.setRowCount(len(self.discovered_devices))
        result = entry.get("result", {})
        selected = bool(entry.get("selected"))
        if result.get("testing"):
            status, color = "● กำลังตรวจสอบ SNMP และ Web…", "#1769AA"
            background = QColor("#E3F0FB") if selected else None
        elif result.get("online") and result.get("web_ok"):
            prefix = "● VIRTUAL · " if entry.get("is_virtual") else "● "
            status, color = f"{prefix}พร้อมใช้งาน · SNMP + Web ผ่าน", C_GREEN
            background = QColor("#EDF8F2") if selected else None
        elif result.get("session_busy"):
            status, color = (
                "● Web กำลังถูกใช้งาน · Logout หน้าเครื่องแล้วตรวจสอบอีกครั้ง",
                "#B45309",
            )
            background = QColor("#FFF7E6") if selected else None
        elif result.get("credential_required"):
            from services.support_diagnostics import diagnose
            web_error = str(result.get('error') or '').split('\n\nKOMI Diagnostic v1\n')[-1]
            diagnostic = diagnose(web_error)
            status, color = f"● {diagnostic.summary} [{diagnostic.error_code} / {diagnostic.code}]", C_RED
            background = QColor("#FDECEC") if selected else None
        elif result.get("tested"):
            from services.support_diagnostics import diagnose
            diagnostic = diagnose(str(result.get("error") or ''))
            status, color = f"● ไม่ผ่าน · {diagnostic.summary} [{diagnostic.error_code} / {diagnostic.code}]", C_RED
            background = QColor("#FDECEC") if selected else None
        elif result.get("online"):
            status, color = "● พบเครื่อง · รอตรวจสอบ Web", C_TEXT2
            background = QColor("#E3F0FB") if selected else None
        elif result.get("saved"):
            status, color = "บันทึกไว้ · รอตรวจสอบรอบนี้", C_TEXT2
            background = QColor("#E3F0FB") if selected else None
        elif result.get("error"):
            from services.support_diagnostics import diagnose
            diagnostic = diagnose(str(result['error']))
            status, color = f"● ไม่ผ่าน · {diagnostic.summary} [{diagnostic.error_code} / {diagnostic.code}]", C_RED
            background = QColor("#FDECEC")
        else:
            status, color = "รอทดสอบ", C_TEXT2
            background = QColor("#E3F0FB") if selected else None
        checkbox = QCheckBox()
        checkbox.setChecked(selected)
        checkbox.setAccessibleName(f"เลือก {entry['name']}")
        checkbox.setToolTip(f"เลือก {entry['name']} เข้าระบบ")
        checkbox.toggled.connect(
            lambda checked, current_row=row: self._set_device_selected(current_row, checked)
        )
        checkbox_container = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(8, 0, 8, 0)
        checkbox_layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignCenter)
        if background is not None:
            checkbox_container.setStyleSheet(setup_styles.setup_wizard_checkbox_container(background.name()))
        self.device_table.setCellWidget(row, 0, checkbox_container)

        values = (entry["model"], entry["host"], entry["serial"], status)
        for column, value in enumerate(values, start=1):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignVCenter
                | (Qt.AlignmentFlag.AlignRight if column == 2 else Qt.AlignmentFlag.AlignLeft)
            )
            if column == 4:
                item.setData(ITEM_TRANSLATABLE_ROLE, True)
                item.setForeground(QColor(color))
            if background is not None:
                item.setBackground(background)
            if (
                result.get("tested")
                and not result.get("session_busy")
                and not (result.get("online") and result.get("web_ok"))
            ):
                item.setForeground(QColor(C_RED) if column == 4 else QColor("#7F1D1D"))
            item.setToolTip(str(result.get('error') or value) if column == 4 else str(value))
            self.device_table.setItem(row, column, item)
        if result.get("session_busy"):
            action_text = "เปิด Web"
        elif result.get("credential_required"):
            action_text = "ใส่รหัส"
        else:
            action_text = "ตั้งค่า"
        credential_item = QTableWidgetItem(action_text)
        credential_item.setData(ITEM_TRANSLATABLE_ROLE, True)
        credential_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        credential_item.setForeground(QColor("#1769AA"))
        if result.get("session_busy"):
            credential_item.setToolTip(
                f"เปิด Web Connection ของ {entry['name']} เพื่อ Logout แล้วตรวจสอบใหม่"
            )
        else:
            credential_item.setToolTip(f"ตั้งค่า Username / Password สำหรับ {entry['name']}")
        if background is not None:
            credential_item.setBackground(background)
        self.device_table.setItem(row, 5, credential_item)

    def _device_table_action(self, row: int, column: int) -> None:
        if column == 4 and 0 <= row < len(self.discovered_devices):
            entry = self.discovered_devices[row]
            error = entry.get('result', {}).get('error')
            if error:
                self._show_wizard_message(f"ผลการเชื่อมต่อ · {entry['name']}", str(error))
            return
        if column != 5 or row >= len(self.discovered_devices):
            return
        entry = self.discovered_devices[row]
        if entry.get("result", {}).get("session_busy"):
            profile = resolve_device_meter_profile(
                str(entry.get("model") or entry.get("name") or "")
            )
            webbrowser.open(f"{profile.web_scheme}://{entry['host']}/wcd/")
            return
        self._open_credentials(str(entry["host"]))

    def _open_credentials(self, host: str) -> None:
        entry = next((item for item in self.discovered_devices if item["host"] == host), None)
        if entry is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Web Connection / User / Password · {host}")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        username = QLineEdit(entry["username"])
        current_password = (
            ""
            if entry.get("credential_origin") == "public_factory_default"
            else entry["password"]
        )
        password = QLineEdit(current_password)
        password.setEchoMode(QLineEdit.EchoMode.Password)
        protocol = QComboBox()
        protocol.setObjectName("web_protocol")
        protocol.addItem("Auto (model profile)", "auto")
        protocol.addItem("Legacy XML · Public", "legacy_xml_public")
        protocol.addItem("Legacy XML · Administrator", "legacy_xml_admin")
        protocol.setCurrentIndex(max(0, protocol.findData(entry.get("web_protocol", "auto"))))
        form.addRow("Web Connection", protocol)
        form.addRow("Username", username)
        form.addRow("Password", password)
        layout.addLayout(form)
        profile = resolve_device_meter_profile(str(entry.get("model") or entry.get("name") or ""))
        hint = QLabel(
            tr(
                "เครื่องรุ่นนี้อ่าน Counter XML แบบ Administrator · กรอกบัญชีที่ผู้ดูแลอนุญาต "
                "แล้วกดทดสอบใน KOMI; ไม่ลองรหัสเริ่มต้นอัตโนมัติ",
                "This model reads Administrator XML counters. Enter an authorized account, "
                "then test in KOMI; factory passwords are not tried automatically.",
            ) if not profile.allow_factory_admin_credentials else tr(
                f"Username: {DEFAULT_ADMIN_USERNAME} · ระบบลองรหัสเริ่มต้น 2 แบบอัตโนมัติแล้ว "
                "กรอกเฉพาะเมื่อเครื่องถูกเปลี่ยนรหัส",
                f"Username: {DEFAULT_ADMIN_USERNAME} · Two public defaults are tested automatically; "
                "enter a password only when the customer changed it",
            )
        )
        auto_hint = hint.text()
        def protocol_changed() -> None:
            selected = protocol.currentData()
            public = selected == "legacy_xml_public"
            username.setEnabled(not public)
            password.setEnabled(not public)
            hint.setText(
                "Public XML: อ่าน Counter โดยไม่เข้าสู่ระบบ แม้เคยบันทึกบัญชีไว้"
                if public else
                "Administrator XML: ใช้บัญชีที่คุณกรอกเท่านั้น ไม่ลองรหัสเริ่มต้น"
                if selected == "legacy_xml_admin" else auto_hint
            )
        protocol.currentIndexChanged.connect(protocol_changed)
        protocol_changed()
        hint.setWordWrap(True)
        hint.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        save = btn("บันทึก", "primary")
        cancel.clicked.connect(dialog.reject)
        save.clicked.connect(dialog.accept)
        actions.addWidget(cancel)
        actions.addWidget(save)
        layout.addLayout(actions)
        def credentials_finished(result: int) -> None:
            if result == int(QDialog.DialogCode.Accepted):
                entry["web_protocol"] = str(protocol.currentData())
                entry["username"] = username.text().strip() or DEFAULT_ADMIN_USERNAME
                entry["password"] = password.text()
                entry["credential_origin"] = "customer" if password.text() else ""
                entry["result"] = {"online": True, "web_ok": False}
                slot = entry.get("slot")
                if slot is not None:
                    self._meter_evidence.pop(int(slot), None)
                    self.meter_step.invalidate(int(slot))
                self._render_discovered_row(self.discovered_devices.index(entry))
                self._update_device_actions()

        self._open_wizard_child(dialog, credentials_finished)

    def _advanced_scan(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Advanced scan")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        start = QLineEdit()
        end = QLineEdit()
        start.setPlaceholderText(self.ADVANCED_SCAN_EXAMPLES[0])
        end.setPlaceholderText(self.ADVANCED_SCAN_EXAMPLES[1])
        form.addRow("IP เริ่มต้น", start)
        form.addRow("IP สิ้นสุด", end)
        layout.addLayout(form)
        hint = QLabel("สแกนได้สูงสุด 1,024 IP ต่อครั้ง")
        hint.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(hint)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        confirm = btn("เริ่ม Advanced scan", "primary")
        cancel.clicked.connect(dialog.reject)
        confirm.setDefault(True)
        confirm.setAutoDefault(True)
        cancel.setAutoDefault(False)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        def submit_scan() -> None:
            if self._scan_thread is not None:
                return
            try:
                hosts = self._advanced_scan_hosts(start.text(), end.text())
            except ValueError as exc:
                hint.setText(str(exc))
                hint.setStyleSheet(text_styles.label(C_RED, font_weight='700'))
                start.setFocus()
                return
            dialog.accept()
            self._scan_network(hosts)

        confirm.clicked.connect(submit_scan)
        start.returnPressed.connect(submit_scan)
        end.returnPressed.connect(submit_scan)
        self._open_wizard_child(dialog)

    @staticmethod
    def _advanced_scan_hosts(start: str, end: str) -> list[str]:
        """Validate a bounded IPv4 range without closing the input dialog."""

        try:
            first = ipaddress.ip_address(start.strip())
            last = ipaddress.ip_address(end.strip())
        except ValueError as exc:
            raise ValueError("กรุณาระบุ IPv4 เริ่มต้นและสิ้นสุดให้ถูกต้อง") from exc
        if first.version != 4 or last.version != 4 or int(last) < int(first):
            raise ValueError("กรุณาระบุช่วง IPv4 จากค่าน้อยไปหาค่ามาก")
        values = range(int(first), int(last) + 1)
        if len(values) > 1024:
            raise ValueError("กรุณาแบ่งช่วงให้ไม่เกิน 1,024 IP")
        return [str(ipaddress.ip_address(value)) for value in values]

    def _manual_setup(self) -> None:
        """Add up to three devices directly when network discovery is not useful."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Manual setup")
        dialog.setMinimumWidth(650)
        layout = QVBoxLayout(dialog)
        hint = QLabel("กรอก IP ของเครื่องที่ต้องการตั้งค่าได้สูงสุด 3 เครื่อง · Username ใช้ administrator")
        hint.setWordWrap(True)
        hint.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)
        for column, text in enumerate(("เครื่อง", "IP address", "Username", "Password")):
            header = QLabel(text)
            header.setStyleSheet(text_styles.label('#123A63', font_weight='700'))
            grid.addWidget(header, 0, column)
        rows: list[tuple[QLineEdit, QLineEdit]] = []
        for index in range(3):
            grid.addWidget(QLabel(f"MFP {index + 1}"), index + 1, 0)
            host = QLineEdit()
            host.setPlaceholderText(self._manual_ip_example(index))
            grid.addWidget(host, index + 1, 1)
            grid.addWidget(QLabel(DEFAULT_ADMIN_USERNAME), index + 1, 2)
            password = QLineEdit()
            password.setPlaceholderText(tr("กรอก Administrator password", "Enter Administrator password"))
            password.setEchoMode(QLineEdit.EchoMode.Password)
            grid.addWidget(password, index + 1, 3)
            rows.append((host, password))
        layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        confirm = btn("เพิ่มเครื่องที่กรอก", "primary")
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        actions.addWidget(cancel)
        actions.addWidget(confirm)
        layout.addLayout(actions)
        def manual_finished(result: int) -> None:
            if result != int(QDialog.DialogCode.Accepted):
                return
            try:
                self._add_manual_entries(
                    [
                        (
                            host.text().strip(),
                            password.text(),
                        )
                        for host, password in rows
                    ]
                )
            except ValueError as exc:
                self._show_wizard_message("IP address ไม่ถูกต้อง", with_diagnostic(str(exc), exc, "IP address ไม่ถูกต้อง"))

        self._open_wizard_child(dialog, manual_finished)

    @staticmethod
    def _manual_ip_example(index: int) -> str:
        return f"เช่น 192.168.1.{101 + index}"

    def _add_manual_entries(self, entries: list[tuple[str, str]]) -> None:
        """Validate manual rows, then make those rows the current selection."""
        valid_entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        for host, password in entries:
            if not host:
                continue
            try:
                address = ipaddress.ip_address(host)
            except ValueError as exc:
                raise ValueError(f"{host} ไม่ใช่ IP address ที่ถูกต้อง") from exc
            if address.version != 4:
                raise ValueError(f"{host} ต้องเป็น IPv4 address")
            if host not in seen:
                valid_entries.append((host, password))
                seen.add(host)
        if not valid_entries:
            raise ValueError("กรุณากรอก IP อย่างน้อย 1 เครื่อง")

        self.device_table.clearSelection()
        for host, password in valid_entries[:3]:
            self._upsert_discovered(
                {
                    "name": host,
                    "name_is_default": True,
                    "host": host,
                    "model": "รอทดสอบ",
                    "serial": "—",
                    "username": DEFAULT_ADMIN_USERNAME,
                    "password": password,
                    "result": {"online": False, "web_ok": False},
                },
                select=True,
            )
        self.scan_status.setText("เพิ่มเครื่องด้วย Manual setup แล้ว · กดทดสอบการเชื่อมต่อเพื่ออ่าน Model และ Serial")
        self._selection_changed()

    @staticmethod
    def _default_device_name(model: str, fallback: str) -> str:
        cleaned = " ".join(model.split())
        upper = cleaned.upper()
        if upper.startswith("KONICA MINOLTA"):
            cleaned = cleaned[len("KONICA MINOLTA") :].strip()
        if cleaned.upper().startswith("KM "):
            return cleaned
        if cleaned.casefold().startswith("bizhub"):
            return f"KM {cleaned}"
        return cleaned or fallback

    def _name_selected_devices(
        self,
        on_complete: Callable[[], None] | None = None,
    ) -> QDialog | None:
        """Confirm logical Slots and installation-point names after connection tests."""
        selected = self._selected_entries()
        if not selected:
            return None
        self._assign_selected_slots(selected)
        existing_names = {device.slot: device.name for device in self.repository.list()}
        dialog = QDialog(self)
        dialog.setWindowTitle("กำหนด Slot และจุดติดตั้ง")
        dialog.setMinimumWidth(720)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Slot คือจุดติดตั้งหรือแผนก · เปลี่ยนเครื่องในอนาคตให้ใช้ Slot เดิมเพื่อให้ประวัติต่อเนื่อง"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(text_styles.label('#176B49', background='#EDF8F2', border='1px solid #B8DFC9', padding='10px'))
        layout.addWidget(intro)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(9)
        for column, text in enumerate(("Slot", "IP address", "ชื่อจุดติดตั้ง / แผนก")):
            label = QLabel(text)
            label.setStyleSheet(text_styles.label('#123A63', font_weight='700'))
            grid.addWidget(label, 0, column)
        mapping_inputs: list[tuple[dict, QComboBox, QLineEdit]] = []
        for index, entry in enumerate(selected):
            slot_combo = WizardComboBox()
            for slot in range(3):
                slot_combo.addItem(f"Slot {slot + 1}", slot)
            slot_combo.setCurrentIndex(int(entry["slot"]))
            slot_combo.setMinimumWidth(132)
            self._style_wizard_combo(slot_combo, popup_width=160)
            grid.addWidget(slot_combo, index + 1, 0)
            grid.addWidget(QLabel(entry["host"]), index + 1, 1)
            slot = int(entry["slot"])
            default_name = existing_names.get(slot) or str(entry.get("name") or "").strip()
            if not default_name or default_name == entry["host"]:
                default_name = self._default_device_name(
                    str(entry.get("model") or ""),
                    f"จุดติดตั้ง {slot + 1}",
                )
            name_input = QLineEdit(default_name)
            name_input.setPlaceholderText("เช่น แผนกบัญชี")
            grid.addWidget(name_input, index + 1, 2)
            mapping_inputs.append((entry, slot_combo, name_input))
        layout.addLayout(grid)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = btn("ยกเลิก", "outline")
        proceed = btn("ถัดไป →", "primary")
        cancel.clicked.connect(dialog.reject)
        actions.addWidget(cancel)
        actions.addWidget(proceed)
        layout.addLayout(actions)

        def confirm_names() -> None:
            chosen_slots = [
                int(slot_combo.currentData())
                for _entry, slot_combo, _name in mapping_inputs
            ]
            if len(set(chosen_slots)) != len(chosen_slots):
                self._show_wizard_message(
                    "Slot ซ้ำกัน", "เครื่องแต่ละเครื่องต้องอยู่คนละ Slot"
                )
                return
            for entry, slot_combo, name_input in mapping_inputs:
                slot = int(slot_combo.currentData())
                entry["slot"] = slot
                entry["name"] = (
                    name_input.text().strip() or f"จุดติดตั้ง {slot + 1}"
                )
            dialog.accept()

        proceed.clicked.connect(confirm_names)

        def naming_finished(result: int) -> None:
            if result == int(QDialog.DialogCode.Accepted) and on_complete is not None:
                on_complete()

        return self._open_wizard_child(dialog, naming_finished)

    def _scan_network(self, hosts: list[str] | None = None) -> None:
        if isinstance(hosts, bool):
            hosts = None
        if self._scan_thread is not None or self._thread is not None:
            return
        self._test_generation += 1
        self._meter_evidence.clear()
        self.meter_step.invalidate()
        self.scan_button.setEnabled(False)
        self.advanced_scan_button.setEnabled(False)
        self.manual_setup_button.setEnabled(False)
        self.scan_button.setText("กำลังค้นหา…")
        self.cancel_scan_button.setEnabled(True)
        self.cancel_scan_button.setVisible(True)
        thread = QThread(self)
        effective_hosts, snmp_port = self._scan_parameters(hosts)
        worker = NetworkDiscoveryWorker(effective_hosts, snmp_port=snmp_port)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._discovery_result)
        worker.progress.connect(self.scan_status.setText)
        worker.progress_count.connect(self._scan_progress_changed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._scan_finished)
        self._scan_thread = thread
        self._scan_worker = worker
        thread.start()

    def _scan_progress_changed(self, completed: int, total: int) -> None:
        self.devices_step.set_scan_progress(completed, total)

    def _scan_parameters(self, hosts: list[str] | None) -> tuple[list[str] | None, int]:
        """Use virtual ports only for the explicit local simulator endpoint."""
        effective_hosts = hosts
        if self.lab_mode and effective_hosts is None and self.lab_hosts:
            effective_hosts = list(self.lab_hosts)
        virtual_hosts = set(self.lab_hosts or ())
        uses_virtual_endpoint = bool(
            self.lab_mode
            and effective_hosts
            and virtual_hosts
            and set(effective_hosts).issubset(virtual_hosts)
        )
        return effective_hosts, self.lab_snmp_port if uses_virtual_endpoint else 161

    def _lab_endpoint_ports(self) -> dict[str, tuple[int, int]]:
        if not self.lab_mode:
            return {}
        return {
            host: (self.lab_snmp_port, self.lab_web_port)
            for host in (self.lab_hosts or ())
        }

    def _discovery_result(self, result: dict) -> None:
        is_virtual = str(result.get("serial") or "").startswith("KOMI-DEMO-")
        model = str(result.get("model") or "")
        self._upsert_discovered(
            {
                **result,
                "name": self._default_device_name(model, str(result.get("host") or "เครื่องพิมพ์")),
                "name_is_default": True,
                "is_virtual": is_virtual,
                "found_in_registration_scan": True,
                "result": {**result, "online": True, "web_ok": False},
            },
            select=self.lab_mode and is_virtual,
        )

    def _scan_finished(self) -> None:
        self._scan_thread = None
        self._scan_worker = None
        self.scan_button.setEnabled(True)
        self.advanced_scan_button.setEnabled(True)
        self.manual_setup_button.setEnabled(True)
        self.scan_button.setText("ค้นหาอีกครั้ง")
        self.cancel_scan_button.setVisible(False)
        self.cancel_scan_button.setEnabled(True)
        self._update_device_actions()
        if self.lab_mode:
            virtual_entries = [entry for entry in self._selected_entries() if entry.get("is_virtual")]
            if virtual_entries:
                self.scan_status.setText("พบ Virtual Printer ผ่าน SNMP แล้ว · กำลังทดสอบ Web Connection จริง…")
                QTimer.singleShot(100, self._test_all)

    def _stop_active_workers(self, timeout_ms: int = 5000) -> bool:
        """Ask setup workers to stop before Qt destroys their QThread owners."""
        threads = [
            thread
            for thread in (
                self._scan_thread,
                self._thread,
                self._secondary_discovery_thread,
                self._secondary_sync_thread,
                self._setup_connectivity_thread,
            )
            if thread is not None and thread.isRunning()
        ]
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        for thread in threads:
            thread.requestInterruption()
            thread.quit()
        return all(thread.wait(timeout_ms) for thread in threads)

    def closeEvent(self, event) -> None:
        if self._enrollment_commit_thread is not None:
            event.ignore()
            return
        if not self._stop_active_workers():
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self._enrollment_commit_thread is not None:
            return
        if not self._stop_active_workers():
            return
        if self._secondary_sync_worker is not None:
            self._secondary_sync_worker.cancelled.set()
            self._secondary_sync_cancelled = True
        if self.secondary_enrollment is not None:
            self.secondary_enrollment.close()
            self.secondary_enrollment = None
        super().reject()

    def _configs(self) -> list[DeviceConfig]:
        devices: list[DeviceConfig] = []
        selected = self._selected_entries()
        self._assign_selected_slots(selected)
        for entry in selected:
            slot = int(entry["slot"])
            result = entry.get("result", {})
            self.results[slot] = result
            devices.append(
                DeviceConfig(
                    slot=slot,
                    name=entry["name"],
                    host=entry["host"],
                    username=entry["username"],
                    password=entry["password"],
                    tls_mode=entry.get("tls_mode", "system"),
                    tls_fingerprint=entry.get("tls_fingerprint", ""),
                    web_protocol=entry.get("web_protocol", "auto"),
                    enabled=True,
                    model=result.get("model") or entry["model"].replace("—", ""),
                    serial=result.get("serial") or entry["serial"].replace("—", ""),
                    connection_status="online" if result.get("online") else "pending",
                    last_total=result.get("total"),
                )
            )
        if not devices:
            raise ValueError("กรุณาตั้งค่าเครื่องอย่างน้อย 1 เครื่อง")
        return devices

    def _registration_devices(self) -> list[dict[str, object]]:
        """Return scan results plus selected manual devices without network identity."""
        by_serial: dict[str, dict[str, object]] = {}
        for entry in self.discovered_devices:
            selected = bool(entry.get("selected"))
            if not selected and not entry.get("found_in_registration_scan"):
                continue
            result = entry.get("result", {})
            serial_number = str(result.get("serial") or entry.get("serial") or "").strip()
            model = str(result.get("model") or entry.get("model") or "").strip()
            if not serial_number or serial_number == "—":
                continue
            raw_slot = entry.get("slot")
            candidate = {
                "serial_number": serial_number,
                "model": model or "Unknown",
                "selected": selected,
                "device_slot": int(raw_slot) + 1 if selected and raw_slot is not None else None,
            }
            current = by_serial.get(serial_number)
            # One physical printer may expose more than one IP/interface. Keep
            # one serial row and prefer the selected endpoint when applicable.
            if current is None or (selected and not current["selected"]):
                by_serial[serial_number] = candidate
        return list(by_serial.values())

    @staticmethod
    def _assign_selected_slots(selected: list[dict]) -> None:
        """Preserve existing logical Slots and assign only genuinely new devices."""

        used: set[int] = set()
        pending: list[dict] = []
        for entry in selected:
            raw_slot = entry.get("slot")
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                pending.append(entry)
                continue
            if 0 <= slot <= 2 and slot not in used:
                entry["slot"] = slot
                used.add(slot)
            else:
                pending.append(entry)
        available = [slot for slot in range(3) if slot not in used]
        for entry, slot in zip(pending, available, strict=False):
            entry["slot"] = slot

    def _test_all(self) -> None:
        try:
            devices = self._configs()
        except ValueError as exc:
            self._show_wizard_message("ข้อมูลไม่ครบ", with_diagnostic(str(exc), exc, "ข้อมูลไม่ครบ"))
            return
        if self._thread is not None:
            return
        self._auto_advance_pending = False
        self._test_generation += 1
        generation = self._test_generation
        self._meter_evidence.clear()
        self.meter_step.invalidate()
        for entry in self._selected_entries():
            entry["result"] = {"testing": True, "online": False, "web_ok": False}
            self._render_discovered_row(self.discovered_devices.index(entry))
        self.test_button.setEnabled(False)
        self.test_button.setText("กำลังตรวจสอบเครื่องที่เลือก…")
        self.scan_button.setEnabled(False)
        self.advanced_scan_button.setEnabled(False)
        self.manual_setup_button.setEnabled(False)
        self.fallback_toggle.setEnabled(False)
        thread = QThread(self)
        worker = DeviceTestWorker(
            devices,
            snmp_port=161,
            web_port=443,
            endpoint_ports=self._lab_endpoint_ports(),
            generation=generation,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self._test_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._test_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _test_result(
        self,
        report: DeviceTestResult | int,
        legacy_payload: dict | None = None,
    ) -> None:
        if isinstance(report, int):
            entry = next(
                (
                    item
                    for item in self.discovered_devices
                    if item.get("slot") == report and item.get("selected")
                ),
                None,
            )
            if entry is None or legacy_payload is None:
                return
            report = DeviceTestResult(
                generation=self._test_generation,
                host=str(entry["host"]),
                slot=report,
                payload=legacy_payload,
            )
        if report.generation != self._test_generation:
            return
        payload = {**report.payload, "tested": True, "testing": False}
        row = next(
            (
                index
                for index, entry in enumerate(self.discovered_devices)
                if entry.get("host") == report.host
            ),
            None,
        )
        if row is None:
            return
        entry = self.discovered_devices[row]
        if not entry.get("selected"):
            return
        if report.connection_key:
            current = next((d for d in self._configs() if d.host == report.host), None)
            if current is None or device_test_key(current) != report.connection_key:
                return
        entry["result"] = payload
        entry["model"] = payload.get("model") or entry["model"]
        entry["serial"] = payload.get("serial") or entry["serial"]
        if entry.get("name_is_default"):
            entry["name"] = self._default_device_name(
                str(entry["model"]), str(entry["host"])
            )
        entry["tls_mode"] = payload.get("tls_mode") or entry.get("tls_mode", "system")
        entry["tls_fingerprint"] = payload.get("tls_fingerprint") or entry.get("tls_fingerprint", "")
        default_index = payload.get("credential_default_index")
        if (
            not entry.get("password")
            and isinstance(default_index, int)
            and not isinstance(default_index, bool)
            and 0 <= default_index < len(PUBLIC_FACTORY_ADMIN_PASSWORDS)
        ):
            entry["password"] = PUBLIC_FACTORY_ADMIN_PASSWORDS[default_index]
            entry["credential_origin"] = "public_factory_default"
        current_slot = entry.get("slot")
        if current_slot is not None:
            self.results[int(current_slot)] = payload
            self._meter_evidence.pop(int(current_slot), None)
            self.meter_step.invalidate(int(current_slot))
            reading = payload.get("meter_reading")
            if reading is not None and payload.get("web_ok"):
                device = next(d for d in self._configs() if d.host == report.host)
                try:
                    if str(payload.get("serial") or "").strip() in {"", "—", "-"}:
                        raise ValueError(tr(
                            "ยังยืนยัน Serial จากผลทดสอบครั้งนี้ไม่ได้ · ย้อนกลับไปตรวจสอบเครื่องพิมพ์อีกครั้ง",
                            "The current test did not confirm the printer serial. Go back and verify the printer again.",
                        ))
                    self._meter_evidence[device.slot] = SetupMeterBaselines.capture(device, reading)
                except (ValueError, TypeError) as error:
                    payload["meter_error"] = str(error)
        self._render_discovered_row(row)
        self._update_device_actions()

    def _test_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.test_button.setEnabled(True)
        self.test_button.setText("ตรวจสอบเครื่องที่เลือก")
        self.scan_button.setEnabled(True)
        self.advanced_scan_button.setEnabled(True)
        self.manual_setup_button.setEnabled(True)
        self.fallback_toggle.setEnabled(True)
        try:
            self._configs()
        except ValueError:
            return
        all_ready = all(
            entry.get("result", {}).get("online")
            and entry.get("result", {}).get("web_ok")
            for entry in self._selected_entries()
        )
        if all_ready:
            if self.lab_mode:
                self.scan_status.setText("Virtual Printer พร้อมใช้งาน · ผ่าน SNMP และ Web แล้ว")
            self._update_device_actions()
            if self._secondary_auto_review:
                self._secondary_auto_review = False
                self._show_review_step()
                return
            if self.stack.currentIndex() == 1 and not self._auto_advance_pending:
                self._auto_advance_pending = True
                QTimer.singleShot(0, self._auto_advance_after_successful_test)
        if self._secondary_auto_review:
            self._secondary_auto_review = False
            failed = [
                str(entry.get("name") or entry.get("host"))
                for entry in self._selected_entries()
                if not (
                    entry.get("result", {}).get("online")
                    and entry.get("result", {}).get("web_ok")
                )
            ]
            self._show_wizard_message(
                tr("ต้องตรวจสอบบางเครื่อง", "Some printers need attention"),
                tr(
                    "รับการตั้งค่าจาก Primary แล้ว แต่ Secondary เครื่องนี้ยังเชื่อมต่อบางเครื่องไม่ผ่าน "
                    "กรุณาตั้งค่าสิทธิ์เฉพาะรายการด้านล่างแล้วกดตรวจสอบอีกครั้ง:\n",
                    "Primary setup was copied, but this Secondary could not verify every printer. "
                    "Configure access for the entries below and verify again:\n",
                )
                + "\n".join(f"• {name}" for name in failed),
            )

    def _auto_advance_after_successful_test(self) -> None:
        """Advance exactly once after every selected printer remains verified."""
        if not self._auto_advance_pending:
            return
        self._auto_advance_pending = False
        if self.stack.currentIndex() != 1:
            return
        selected = self._selected_entries()
        if not selected or not all(
            entry.get("result", {}).get("online")
            and entry.get("result", {}).get("web_ok")
            for entry in selected
        ):
            return
        self._next()

    def _update_device_actions(self) -> None:
        selected = self._selected_entries()
        all_ready = bool(selected) and all(
            entry.get("result", {}).get("online")
            and entry.get("result", {}).get("web_ok")
            for entry in selected
        )
        if self.stack.currentIndex() == 1:
            self.next_button.setEnabled(all_ready)
        if self._thread is None:
            self.test_button.setEnabled(bool(selected))
        if all_ready:
            self.scan_status.setText(
                f"พร้อมนำเข้าระบบ {len(selected)} เครื่อง · ผ่าน SNMP และ Web ครบแล้ว"
            )

    def _next(self) -> None:
        index = self.stack.currentIndex()
        if index == 0:
            if not self.company_step.validate():
                return
            if (
                self.edit_mode
                or self.lab_mode
                or is_offline_edition()
                or QApplication.platformName() == "offscreen"
            ):
                self._enter_device_step()
            else:
                self._start_setup_connectivity()
            return
        if index == 1:
            try:
                self._configs()
            except ValueError as exc:
                self._show_wizard_message("ข้อมูลไม่ครบ", with_diagnostic(str(exc), exc, "ข้อมูลไม่ครบ"))
                return
            not_ready = [
                str(entry.get("name") or entry.get("host"))
                for entry in self._selected_entries()
                if not (
                    entry.get("result", {}).get("online")
                    and entry.get("result", {}).get("web_ok")
                )
            ]
            if not_ready:
                self._show_wizard_message(
                    "ยังทดสอบไม่ผ่าน",
                    "ทุกเครื่องที่เลือกต้องผ่านทั้ง SNMP และ Web Connection ก่อนดำเนินการ:\n"
                    + "\n".join(f"• {name}" for name in not_ready),
                )
                return
            if QApplication.platformName() != "offscreen":
                self._name_selected_devices(on_complete=self._enter_meter_step)
                return
            self._enter_meter_step()
            return
        if index == 2:
            try:
                self._prepare_meter_plan()
            except (ValueError, TypeError) as error:
                self._show_wizard_message("ตรวจมิเตอร์เริ่มต้น", str(error))
                return
            self._enter_price_step()
            return
        if index == 3:
            if self._all_selected_prices_are_zero() and not self.deferred_price_mode.isChecked():
                self._show_wizard_message(
                    "ราคายังเป็น 0.00 ทั้งหมด",
                    "กรุณากรอกราคาอย่างน้อยหนึ่งรายการ หรือเลือก ‘ตั้งค่าราคาภายหลัง’ "
                    "เพื่อยืนยันว่าขณะนี้ยังไม่คิดค่าใช้จ่าย",
                )
                self.deferred_price_mode.setFocus()
                return
            self._show_review_step()
            return
        if index == 4:
            self._save()

    def _start_setup_connectivity(self) -> None:
        """Verify every required Host API before leaving the first page."""

        if self._setup_connectivity_thread is not None:
            return
        self.next_button.setEnabled(False)
        self.next_button.setText(
            tr("กำลังตรวจสอบการเชื่อมต่อ…", "Checking connectivity…")
        )
        thread = QThread(self)
        worker = SetupConnectivityWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._setup_connectivity_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._setup_connectivity_thread = thread
        self._setup_connectivity_worker = worker
        thread.start()

    def _setup_connectivity_finished(self, report: object, internal_error: str) -> None:
        self._setup_connectivity_thread = None
        self._setup_connectivity_worker = None
        self.next_button.setEnabled(True)
        self.next_button.setText(tr("ค้นหาเครื่องพิมพ์ →", "Find printers →"))

        if not isinstance(report, SetupConnectivityReport):
            report = SetupConnectivityReport(
                started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                base_url="https://www.dmskm.com",
                checks=(
                    SetupConnectivityCheck(
                        name="Connectivity check",
                        target="KOMI Host",
                        ok=False,
                        detail=f"Diagnostic could not start ({internal_error or 'unknown error'})",
                        support_code="diagnostic_error",
                    ),
                ),
            )
        if report.ok:
            self._enter_device_step()
            return
        self._show_setup_connectivity_problem(report)

    def _show_setup_connectivity_problem(
        self,
        report: SetupConnectivityReport,
    ) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle(
            tr("ตรวจสอบการเชื่อมต่อไม่ผ่าน", "Connectivity check failed")
        )
        dialog.resize(780, 520)
        dialog.setMinimumSize(680, 460)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel(
            tr(
                "ยังเชื่อมต่อบริการที่จำเป็นได้ไม่ครบ",
                "Some required services could not be reached",
            )
        )
        title.setFont(fnt(F_XL, True))
        layout.addWidget(title)
        explanation = QLabel(
            tr(
                "กดคัดลอกรายละเอียดแล้วส่งให้ทีม KOMI Support เพื่อวิเคราะห์ปัญหา "
                "ข้อมูลนี้ไม่มีชื่อบริษัท IP เครื่องพิมพ์ รหัสผ่าน Counter เอกสาร หรือ Log",
                "Copy these details and send them to KOMI Support for analysis. "
                "They contain no company name, printer IP, password, counter, document or log.",
            )
        )
        explanation.setWordWrap(True)
        explanation.setStyleSheet(text_styles.label('#52677D'))
        layout.addWidget(explanation)

        details = QPlainTextEdit()
        details.setObjectName("setup_connectivity_details")
        details.setReadOnly(True)
        details.setPlainText(report.support_text())
        details.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(details, 1)

        actions = QHBoxLayout()
        copy_button = btn(tr("คัดลอกรายละเอียด", "Copy details"), "outline")
        retry_button = btn(tr("ทดสอบอีกครั้ง", "Test again"), "primary")
        close_button = btn(tr("ปิด", "Close"), "outline")

        def copy_details() -> None:
            QApplication.clipboard().setText(details.toPlainText())
            copy_button.setText(tr("คัดลอกแล้ว", "Copied"))

        def retry() -> None:
            dialog.accept()
            QTimer.singleShot(0, self._start_setup_connectivity)

        copy_button.clicked.connect(copy_details)
        retry_button.clicked.connect(retry)
        close_button.clicked.connect(dialog.reject)
        actions.addWidget(copy_button)
        actions.addStretch()
        actions.addWidget(close_button)
        actions.addWidget(retry_button)
        layout.addLayout(actions)
        self._prepare_wizard_dialog(dialog)
        return self._open_wizard_child(dialog)

    def _enter_device_step(self) -> None:
        """Enter step 2 after the silent Host connectivity gate passes."""

        self.stack.setCurrentIndex(1)
        self.title.setText("นำเครื่องพิมพ์เข้าระบบ")
        self.step_label.setText("2 / 5")
        self.language_switch.setVisible(False)
        self.note.setText("ขั้นที่ 2: ค้นหา เลือก และตรวจสอบเครื่องพิมพ์ก่อนนำเข้าระบบ")
        self._update_progress(1)
        self.back_button.setVisible(True)
        self.test_button.setVisible(True)
        self.next_button.setText("ถัดไป →")
        self._update_device_actions()
        apply_language(self)
        self._sync_language_switch()
        if self._secondary_auto_review:
            QTimer.singleShot(0, self._test_all)
        if (
            not self.discovered_devices
            and self._scan_thread is None
            and QApplication.platformName() != "offscreen"
        ):
            QTimer.singleShot(
                0,
                lambda: self._scan_network(self.lab_hosts if self.lab_mode else None),
            )

    def _meter_readiness_changed(self, ready: bool) -> None:
        if hasattr(self, "next_button") and self.stack.currentIndex() == 2:
            self.next_button.setEnabled(ready)

    def _refresh_meter_step(self):
        devices = self._configs()
        service = SetupMeterBaselines()
        requirements = {item.slot: item for item in service.classify(devices)}
        entries = {entry["host"]: entry for entry in self._selected_entries()}
        views = []
        for device in devices:
            result = entries[device.host].get("result", {})
            evidence = self._meter_evidence.get(device.slot)
            raw = result.get("meter_reading")
            error = result.get("meter_error", "")
            required = requirements[device.slot].requires_confirmation
            if required:
                try:
                    service.validate_evidence(device, evidence)
                    raw = evidence.reading
                except (ValueError, TypeError) as exc:
                    error = str(exc)
            normalized = apply_parser_mapping_overrides(raw, device.serial) if raw is not None else None
            views.append(MeterReviewDevice(device=device, reading=normalized,
                requires_confirmation=required, error=error if required else "", raw_reading=raw))
        self._meter_step_required = any(item.requires_confirmation for item in requirements.values())
        self.meter_step.set_devices(views)
        return devices

    def _prepare_meter_plan(self, devices=None):
        devices = devices if devices is not None else self._configs()
        return SetupMeterBaselines().prepare(devices, self._meter_evidence,
                                              self.meter_step.confirmed_slots)

    def _enter_meter_step(self) -> None:
        """Review new baselines; ordinary edits/upgrades retain existing history."""
        if self.secondary_enrollment is not None:
            self._enter_price_step()
            return
        try:
            self._refresh_meter_step()
        except (ValueError, TypeError) as error:
            self._show_wizard_message("ตรวจมิเตอร์เริ่มต้น", str(error))
            return
        if not self._meter_step_required:
            self._enter_price_step()
            return
        self.stack.setCurrentIndex(2)
        self.title.setText(tr("มิเตอร์เริ่มต้น", "Initial meter"))
        self.step_label.setText("3 / 5")
        self.note.setText(tr("ขั้นที่ 3: ตรวจค่ามิเตอร์และยืนยันฐานของเครื่องใหม่",
                             "Step 3: Review meter readings and confirm new printer baselines"))
        self._update_progress(2)
        self.back_button.setVisible(True)
        self.test_button.setVisible(False)
        self.next_button.setText(tr("ไปหน้าราคา →", "Continue to prices →"))
        self.next_button.setEnabled(self.meter_step.ready)
        apply_language(self)
        self._sync_language_switch()

    def _enter_price_step(self) -> None:
        self.stack.setCurrentIndex(3)
        self._refresh_device_price_cards()
        self.test_button.setVisible(False)
        self.title.setText("ตั้งค่าราคา")
        self.step_label.setText("4 / 5")
        self.note.setText(
            tr("ขั้นที่ 4: ตั้งราคาตอนนี้ หรือเลือกตั้งค่าภายหลังอย่างชัดเจน",
               "Step 4: Set prices now or explicitly choose to set them later")
        )
        self._update_progress(3)
        self.back_button.setVisible(True)
        self.next_button.setText("ตรวจสอบการตั้งค่า →")
        self.next_button.setEnabled(True)
        apply_language(self)
        self._sync_language_switch()

    def _show_review_step(self) -> None:
        """Enter the shared final review from normal or Secondary setup flow."""

        self._update_review()
        self.stack.setCurrentIndex(4)
        self.title.setText("ตรวจสอบและเริ่มใช้งาน")
        self.step_label.setText("5 / 5")
        self.note.setText(tr("ขั้นที่ 5: ตรวจสอบแต่ละส่วนก่อนนำเครื่องพิมพ์เข้าระบบ",
                             "Step 5: Review all settings before saving printers"))
        self._update_progress(4)
        self.back_button.setVisible(True)
        self.test_button.setVisible(False)
        self.next_button.setEnabled(True)
        self.next_button.setText("จบการทดสอบ" if self.lab_mode else "บันทึกและเปิดโปรแกรม")
        if self.secondary_candidate is not None:
            self.review_ready_note.setText(
                tr(
                    "พร้อมบันทึก Secondary Desktop\n"
                    "เครื่องพิมพ์ทั้งหมดผ่านการตรวจสอบจากเครื่องนี้แล้ว และ Desktop เครื่องนี้จะลงทะเบียนแยกบน Host",
                    "Secondary Desktop is ready\n"
                    "All printers were verified from this computer; it will register as a separate Host installation.",
                )
            )
        apply_language(self)
        self._sync_language_switch()

    def _back(self) -> None:
        index = self.stack.currentIndex()
        if index <= 0:
            return
        if index == 4:
            self._enter_price_step()
            return
        if index == 3 and self._meter_step_required:
            self._enter_meter_step()
            return
        if index in (2, 3):
            self._enter_device_step()
            return
        self.stack.setCurrentIndex(0)
        self.title.setText("ข้อมูลองค์กร")
        self.step_label.setText("1 / 5")
        self.note.setText("ขั้นที่ 1: กรอกชื่อบริษัท · วันที่เริ่มใช้และ Version มาจากระบบอัตโนมัติ")
        self._update_progress(0)
        self.back_button.setVisible(False)
        self.test_button.setVisible(False)
        self.language_switch.setVisible(True)
        self.next_button.setText("ค้นหาเครื่องพิมพ์ →")
        self.next_button.setEnabled(True)
        apply_language(self)
        self._sync_language_switch()

    def _update_review(self) -> None:
        entries = {str(entry.get("host")): entry for entry in self._selected_entries()}
        devices = tuple(
            ReviewDevice(device.slot, device.name, device.model,
                         entries.get(device.host, {}).get("result", {}).get("total"))
            for device in self._configs()
        )
        self.review_step.render(SetupReviewData(
            company_name=self.company_name_input.text(), first_started=self.first_started_input.text(),
            version=PACKAGE_VERSION, devices=devices, pricing=self.pricing_step.selection(),
            edit_mode=self.edit_mode, offline_edition=is_offline_edition(), platform=runtime_platform(),
            meter_summary=tuple(self.meter_step.summary_lines()),
            meter_editable=self._meter_step_required,
        ))
        apply_language(self)
        self._sync_language_switch()


    def _save(self) -> None:
        if self._enrollment_commit_thread is not None:
            return
        existing_registration_state: dict[str, object] | None = None
        if self.edit_mode:
            current_database_path = Path(get_db_path()).expanduser().resolve(strict=False)
            if self.selected_database_path != current_database_path:
                self._show_wizard_message(
                    tr("เปลี่ยนเครื่องพิมพ์ไม่ได้", "Could not change printers"),
                    tr(
                        "การเปลี่ยน Database Path ให้ทำจากการตั้งค่าขั้นสูงก่อน แล้วเปิดแก้ไขเครื่องพิมพ์อีกครั้ง",
                        "Change the Database Path from Advanced Settings first, then reopen printer editing.",
                    ),
                )
                return
            existing_registration_state = self.registration_state.internal()
            if existing_registration_state is None:
                self._show_wizard_message(
                    tr("เปลี่ยนเครื่องพิมพ์ไม่ได้", "Could not change printers"),
                    tr(
                        "ไม่พบสถานะ Registration เดิม จึงยังไม่บันทึกการเปลี่ยนแปลง กรุณาตรวจสอบ Registration ก่อนลองอีกครั้ง",
                        "The existing Registration state is missing, so no changes were saved. Check Registration before trying again.",
                    ),
                )
                return
        try:
            company_name = " ".join(self.company_name_input.text().split())
            if not company_name:
                raise ValueError("กรุณากรอกชื่อบริษัท")
            registration_mode = (
                str(existing_registration_state["mode"])
                if existing_registration_state is not None
                else ("offline" if is_offline_edition() else "online")
            )
            if registration_mode not in {"online", "offline"}:
                raise ValueError("สถานะ Registration เดิมไม่ถูกต้อง")
            devices = self._configs()
            # Revalidate immediately before any write; direct Save must not
            # bypass the meter review or accept an obsolete reading.
            baseline_plan = None if self.secondary_enrollment is not None else self._prepare_meter_plan(devices)
            if self.lab_mode:
                self.accept()
                return
            if self.secondary_enrollment is not None and self.selected_database_path.resolve() != self.secondary_enrollment.path:
                raise ValueError('ตำแหน่งฐานข้อมูลเปลี่ยน กรุณารับการตั้งค่ากลุ่มใหม่ก่อนบันทึก')
            self._activate_selected_database_path()
            from services.setup_settings import SetupSettingsService
            if baseline_plan is not None and baseline_plan.database_path != str(Path(get_db_path()).resolve()):
                # First-run setup can copy the database to the selected folder.
                baseline_plan = self._prepare_meter_plan(devices)
            service = SetupSettingsService(self.repository)
            effective = self.effective_date.date().toPyDate()
            shared = self.shared_price_mode.isChecked()
            deferred = self.deferred_price_mode.isChecked()
            price_updates = []
            for device in devices:
                row = self.shared_price_row if shared else self.price_rows[device.slot]
                price_updates.append((device.slot, effective, PriceList(**{
                    key: 0.0 if deferred else spin.value() for key, spin in row.items()
                })))
            settings = {
                "pricing_mode": "deferred" if deferred else ("shared" if shared else "per_device"),
                "work_start": get_cfg("work_start", "08:00") or "08:00",
                "work_end": get_cfg("work_end", "17:00") or "17:00",
                "snmp_interval_minutes": "5",
                "db_path": str(get_db_path()),
                "company_name": company_name,
                "client_first_started_at": get_cfg("client_first_started_at", "") or date.today().isoformat(),
                "installation_id": get_cfg("installation_id", "") or str(uuid4()),
                "v52_registration_mode": registration_mode,
            }
            if not self.edit_mode:
                settings.update(billing_day=str(self._billing_day()),
                                waste_paper_pct=str(round(self.waste_paper_pct.value(), 1)))
            installation_id = settings["installation_id"]
            if self.secondary_enrollment is not None:
                from services.setup_settings import LOCAL_KEYS
                enrollment = self.secondary_enrollment
                if company_name != enrollment.payload['organization']['company_name']:
                    raise ValueError('บริษัทเปลี่ยนหลังเลือกกลุ่ม กรุณารับการตั้งค่าใหม่')
                expected_devices = {(d['slot'], d['host'], d['serial']) for d in enrollment.payload['devices']}
                if {(d.slot, d.host, d.serial) for d in devices if d.enabled} != expected_devices:
                    raise ValueError('เครื่องพิมพ์ต้องตรงกับกลุ่มที่เลือก กรุณารับการตั้งค่าใหม่')
                installation_id = enrollment.identity.installation_id
                settings['installation_id'] = installation_id
                local = {k: v for k, v in settings.items() if k in LOCAL_KEYS}
                self._save_enrollment(enrollment, local, company_name, registration_mode, installation_id, devices)
                return
            if self.secondary_candidate is not None and self.secondary_snapshot is not None:
                organization = self.secondary_snapshot.get("organization", {})
                received = self.secondary_snapshot.get("settings", {})
                received_schedule = str(received.get("sync_schedule_windows") or "").strip()
                if received_schedule and not get_cfg("sync_schedule_windows", ""):
                    settings["sync_schedule_windows"] = received_schedule
                settings.update(
                    desktop_role="secondary",
                    primary_peer_url=self.secondary_candidate.base_url,
                    primary_peer_certificate_sha256=self.secondary_candidate.certificate_sha256,
                    primary_installation_id=str(organization.get("primary_installation_id") or ""),
                )
            elif not get_cfg("desktop_role", ""):
                settings["desktop_role"] = "primary"
            preview = service.preview(devices, settings, price_updates,
                registration_devices=self._registration_devices() if self.edit_mode else None,
                baseline_plan=baseline_plan)
            if preview.changes and not confirm_shared_settings(self, preview):
                return
            service.commit(preview)
        except Exception as exc:
            self._show_wizard_message("บันทึกไม่สำเร็จ", with_diagnostic(str(exc), exc, "บันทึกไม่สำเร็จ"))
            return

        if self.edit_mode:
            # Editing printers is a local Settings action.  Preserve the
            # existing Online/Offline lifecycle and let its normal schedule
            # observe the updated inventory; never enqueue or send here.
            self.accept()
            return

        self._complete_setup_registration(company_name, registration_mode, installation_id)

    def _save_enrollment(self, preview, settings, company, mode, identity, devices):
        # Network, vault and large ancestry imports never block Qt's GUI thread.
        self.setEnabled(False)
        thread = QThread(self)
        worker = EnrollmentCommitWorker(preview, settings, self.repository, devices)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        self._enrollment_commit_thread, self._enrollment_commit_worker = thread, worker
        self._enrollment_registration = (company, mode, identity)
        worker.finished.connect(lambda error: setattr(self, '_enrollment_error', error))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._enrollment_saved(self._enrollment_error))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @pyqtSlot(str)
    def _enrollment_saved(self, error):
        self._enrollment_commit_thread = self._enrollment_commit_worker = None
        self.setEnabled(True)
        if error:
            if self.secondary_enrollment.committed:
                # The local transaction is durable; finish registration normally.
                # Runtime keeps the pending marker and offers explicit reconnect.
                dialog = self._build_wizard_message(tr('รอยืนยันจากกลุ่ม', 'Waiting for group confirmation'),
                    tr('บันทึกสมาชิกบนเครื่องนี้แล้ว ลงทะเบียนต่อได้ เมื่อเครื่องต้นทางกลับมาออนไลน์ ให้กดค้นหาและเชื่อมต่อสมาชิกเดิมอีกครั้ง ไม่ต้องเปิดอนุญาตซ้ำ',
                       'Membership is saved locally. Continue registration. When the source is online, choose Find and reconnect existing members; no renewed approval is required.'))
                self._open_wizard_child(dialog, lambda _result: self._finish_enrollment_registration())
            else:
                self._show_wizard_message(tr('เข้ากลุ่มยังไม่ครบ', 'Enrollment incomplete'), with_diagnostic(error, error, tr('เข้ากลุ่มยังไม่ครบ', 'Enrollment incomplete')))
            return
        self._finish_enrollment_registration()

    def _finish_enrollment_registration(self):
        self.secondary_enrollment.close()
        self.secondary_enrollment = None
        self._complete_setup_registration(*self._enrollment_registration)

    def _complete_setup_registration(self, company_name, registration_mode, installation_id):
        # Configuration stays local and durable if registration fails. The
        # application itself remains closed until Online Registration succeeds
        # or a valid Host-signed Offline License is imported.
        try:
            self.registration_state.configure(
                registration_mode,
                company_name,
                installation_id,
                get_cfg("client_first_started_at", "") or date.today().isoformat(),
                REGISTRATION_NOTICE_VERSION if registration_mode == "online" else "",
                (
                    datetime.now().astimezone().isoformat(timespec="seconds")
                    if registration_mode == "online"
                    else ""
                ),
                registration_devices=self._registration_devices(),
            )
            set_cfg("registration_pending_envelope", "")
            set_cfg("registration_status", "v52_configured")
        except Exception:
            set_cfg("registration_pending_envelope", "")
            set_cfg("registration_status", "action_required")
            dialog = self._registration_dialog_ui()
            if not dialog.isVisible():
                dialog.open()
            self._show_registration_failure("contract_invalid")
            return
        if is_offline_edition():
            # Edition is fixed by the signed/staged installer.  There is no
            # online call and no request/license exchange in this package.
            if self.registration_runtime is not None:
                try:
                    self.registration_runtime.set_mode("offline")
                except (OSError, RuntimeError, ValueError):
                    self._show_wizard_message(
                        tr("เปิดใช้งาน Offline ไม่สำเร็จ", "Could not enable Offline mode"),
                        tr("บันทึกการตั้งค่าแล้ว แต่สถานะภายในไม่พร้อม กรุณาเปิดโปรแกรมใหม่", "Setup was saved, but local state is not ready. Restart the app."),
                    )
                    return
            self.registration_status_label.setText(
                tr("พร้อมใช้แบบ Offline", "Offline ready")
            )
            self.accept()
        else:
            self._start_online_registration()

    def _registration_dialog_ui(self) -> QDialog:
        if self._registration_dialog is not None:
            return self._registration_dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ลงทะเบียน KOMI Report", "Register KOMI Report"))
        dialog.setMinimumWidth(520)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        layout = QVBoxLayout(dialog)
        title = QLabel(tr("กำลังลงทะเบียนออนไลน์", "Registering online"))
        title.setFont(fnt(F_XL, True))
        layout.addWidget(title)
        self.registration_progress = QProgressBar()
        self.registration_progress.setRange(0, 0)
        self.registration_progress.setTextVisible(False)
        layout.addWidget(self.registration_progress)
        self.registration_result_copy = QLabel(
            tr("กำลังติดต่อ Host กรุณารอสักครู่…", "Contacting the Host. Please wait…")
        )
        self.registration_result_copy.setWordWrap(True)
        layout.addWidget(self.registration_result_copy)
        actions = QHBoxLayout()
        actions.addStretch()
        self.registration_cancel_button = btn(tr("ยกเลิก", "Cancel"), "outline")
        self.registration_retry_button = btn(tr("ลองอีกครั้ง", "Retry"), "outline")
        self.registration_offline_button = btn(
            tr("ลงทะเบียน Offline", "Offline Registration"), "primary"
        )
        self.registration_cancel_button.clicked.connect(dialog.reject)
        self.registration_retry_button.clicked.connect(self._retry_online_registration)
        self.registration_offline_button.clicked.connect(self._open_offline_registration)
        actions.addWidget(self.registration_cancel_button)
        actions.addWidget(self.registration_retry_button)
        actions.addWidget(self.registration_offline_button)
        layout.addLayout(actions)
        self.registration_retry_button.setVisible(False)
        self.registration_offline_button.setVisible(False)
        dialog.finished.connect(lambda _result: self._registration_dialog_closed())
        self._prepare_wizard_dialog(dialog)
        self._registration_dialog = dialog
        return dialog

    def _start_online_registration(self) -> None:
        if is_offline_edition():
            self._open_offline_registration()
            return
        if self._registration_in_progress:
            return
        self._registration_in_progress = True
        self.next_button.setEnabled(False)
        dialog = self._registration_dialog_ui()
        self.registration_progress.setVisible(True)
        self.registration_progress.setRange(0, 0)
        self.registration_result_copy.setStyleSheet(text_styles.label('#334155'))
        self.registration_result_copy.setText(
            tr("กำลังติดต่อ Host กรุณารอสักครู่…", "Contacting the Host. Please wait…")
        )
        self.registration_retry_button.setVisible(False)
        self.registration_offline_button.setVisible(False)
        self.registration_cancel_button.setVisible(True)
        if not dialog.isVisible():
            dialog.open()
        runtime = self.registration_runtime
        if runtime is None:
            self._show_registration_failure("client_not_configured")
            return
        try:
            # Do not acquire the send lock or reset lifecycle while an Online
            # request is already running; observe its eventual result instead.
            if runtime.snapshot().get("mode") != "online":
                runtime.set_mode("online")
            runtime.configuration_changed()
        except Exception:
            self._show_registration_failure("contract_invalid")
            return
        self._registration_deadline = datetime.now().astimezone() + timedelta(seconds=25)
        timer = self._registration_poll_timer
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(250)
            timer.timeout.connect(self._poll_registration_result)
            self._registration_poll_timer = timer
        timer.start()
        self._poll_registration_result()

    def _poll_registration_result(self) -> None:
        if not self._registration_in_progress:
            return
        runtime = self.registration_runtime
        if runtime is None:
            self._show_registration_failure("client_not_configured")
            return
        snapshot = runtime.snapshot()
        # Wait for the active attempt, not stale status left by a previous one.
        if snapshot.get("request_in_progress"):
            if self._registration_deadline and datetime.now().astimezone() >= self._registration_deadline:
                self.registration_result_copy.setText(tr(*error_message("registration_pending")))
            return
        status = str(snapshot.get("status") or "")
        if status == "registered":
            self._registration_succeeded()
            return
        if status in {"needs_review", "retrying"}:
            self._show_registration_failure(str(snapshot.get("support_code") or status))
            return
        if self._registration_deadline and datetime.now().astimezone() >= self._registration_deadline:
            # The UI deadline is not a network diagnosis. Keep observing so a
            # late success updates this same dialog; Cancel remains available.
            self.registration_result_copy.setText(tr(*error_message("registration_pending")))

    def _registration_succeeded(self) -> None:
        if self._registration_poll_timer is not None:
            self._registration_poll_timer.stop()
        self._registration_in_progress = False
        self.registration_progress.setRange(0, 1)
        self.registration_progress.setValue(1)
        self.registration_cancel_button.setVisible(False)
        self.registration_result_copy.setStyleSheet(text_styles.label(C_GREEN, font_weight='700'))
        self.registration_result_copy.setText(
            tr("✓ ลงทะเบียนสำเร็จ กำลังเปิดโปรแกรม…", "✓ Registration successful. Opening the app…")
        )
        self.registration_status_label.setText(tr("ลงทะเบียนแล้ว", "Registered"))
        if QApplication.platformName() == "offscreen":
            self._complete_registered_setup()
            return
        QTimer.singleShot(650, self._complete_registered_setup)

    def _complete_registered_setup(self) -> None:
        if self._registration_dialog is not None:
            self._registration_dialog.accept()
        self.accept()

    def _show_registration_failure(self, code: str) -> None:
        if self._registration_poll_timer is not None:
            self._registration_poll_timer.stop()
        self._registration_in_progress = False
        self.next_button.setEnabled(True)
        self.registration_progress.setVisible(False)
        safe = safe_support_code(code)
        self.registration_result_copy.setStyleSheet(text_styles.label(C_RED, font_weight='700'))
        self.registration_result_copy.setText(
            tr(*error_message(safe)) + "\nSupport Code: " + safe
            + "\n" + tr("การตั้งค่าถูกเก็บไว้แล้ว กดยกเลิกเพื่อกลับไปตรวจสอบ", "Your setup is saved. Cancel to review it.")
        )
        self.registration_retry_button.setVisible(True)
        self.registration_offline_button.setVisible(OFFLINE_ACTIVATION_ENABLED)
        self.registration_status_label.setText(tr("ต้องลงทะเบียน", "Registration required"))

    def _retry_online_registration(self) -> None:
        self._start_online_registration()

    def _registration_service(self):
        """Create the V5.2 runtime only when online registration is requested.

        Setup remains local-first and the default runtime remains fail-closed
        because it has no implicit Production client.  Offline Activation is
        retained behind ``OFFLINE_ACTIVATION_ENABLED`` for a future release,
        but no customer entry point can invoke it while that flag is disabled.
        """

        if self.registration_runtime is None:
            from services.v5_2_runtime import V52RuntimeCoordinator

            self.registration_runtime = V52RuntimeCoordinator(parent=self)
        return self.registration_runtime

    def _open_offline_registration(self) -> None:
        if not OFFLINE_ACTIVATION_ENABLED:
            return
        runtime = self._registration_service()
        runtime.set_mode("offline")
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("ลงทะเบียน Offline", "Offline Registration"))
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        copy = QLabel(
            tr(
                "1. ส่งออกไฟล์ .komirequest ให้ผู้ดูแลออก License\n"
                "2. นำเข้าไฟล์ .komilicense ที่ได้รับกลับมา",
                "1. Export a .komirequest file for the administrator\n"
                "2. Import the returned .komilicense file",
            )
        )
        copy.setWordWrap(True)
        layout.addWidget(copy)
        actions = QHBoxLayout()
        cancel_button = btn(tr("ยกเลิก", "Cancel"), "outline")
        export_button = btn(tr("ส่งออก Request", "Export Request"), "outline")
        import_button = btn(tr("นำเข้า License", "Import License"), "primary")
        actions.addStretch()
        actions.addWidget(cancel_button)
        actions.addWidget(export_button)
        actions.addWidget(import_button)
        layout.addLayout(actions)

        def export_request() -> None:
            path, _ = QFileDialog.getSaveFileName(
                dialog,
                tr("บันทึก Offline License Request", "Save Offline License Request"),
                "KOMI-Offline.komirequest",
                "KOMI Request (*.komirequest)",
            )
            if not path:
                return
            destination = Path(path)
            if destination.suffix.casefold() != ".komirequest":
                destination = destination.with_suffix(".komirequest")
            try:
                runtime.set_mode("offline")
                runtime.create_offline_request(destination)
                copy.setText(tr("ส่งออก Request แล้ว รอไฟล์ License จากผู้ดูแล", "Request exported. Wait for the License file."))
            except Exception as exc:
                copy.setText(str(exc))

        def import_license() -> None:
            path, _ = QFileDialog.getOpenFileName(
                dialog,
                tr("เลือก Offline License", "Choose Offline License"),
                "",
                "KOMI License (*.komilicense)",
            )
            if not path:
                return
            try:
                runtime.import_offline_license(
                    Path(path), self.offline_license_public_keys
                )
            except Exception as exc:
                copy.setStyleSheet(text_styles.label(C_RED, font_weight='700'))
                copy.setText(str(exc))
                return
            dialog.accept()
            if self._registration_dialog is not None:
                self._registration_dialog.accept()
            self.accept()

        cancel_button.clicked.connect(dialog.reject)
        export_button.clicked.connect(export_request)
        import_button.clicked.connect(import_license)
        self._open_wizard_child(dialog)

    def _registration_dialog_closed(self) -> None:
        if self._registration_poll_timer is not None:
            self._registration_poll_timer.stop()
        self._registration_in_progress = False
        self.next_button.setEnabled(True)

    def _billing_day(self) -> int:
        return self.pricing_step.selection().billing_day

    def _all_selected_prices_are_zero(self) -> bool:
        selection = self.pricing_step.selection()
        # Shared/deferred modes do not require device configuration validation.
        slots = tuple(sorted({device.slot for device in self._configs()})) if selection.mode == "per_device" else ()
        return selection.all_selected_rates_are_zero(slots)
