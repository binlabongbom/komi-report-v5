"""Network settings controls and local dialog ownership."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from i18n import tr
from ui.numeric_inputs import NumericSpinBox as QSpinBox
from ui.settings.sections.common import editor_actions
from ui.styles import settings as settings_styles
from ui.styles import text as text_styles
from widgets import btn


class NetworkSection:
    """Network controls with explicit actions; service transactions stay with Fleet."""

    def __init__(
        self,
        program_body: QVBoxLayout,
        *,
        parent: QWidget,
        on_open: Callable[[], None],
        on_copy: Callable[[], None],
        on_change_code: Callable[[], None],
        on_authorize: Callable[[], None],
        on_peer_refresh: Callable[[], None],
        subscribe_changes: Callable[[Callable], object],
        on_save: Callable[[], None],
        on_cancel: Callable[[], None],
        on_dirty: Callable[[], None],
    ) -> None:
        def section_title(thai, english):
            label = QLabel(tr(thai, english))
            label.setStyleSheet(text_styles.label("#123262", font_weight="700", padding="4px 0"))
            return label

        web_service_card = QFrame()
        web_service_card.setObjectName("web_service_settings")
        web_service_card.setStyleSheet(settings_styles.BUILD_NETWORK_SETTINGS_WEB_SERVICE_CARD)
        web_service_layout = QVBoxLayout(web_service_card)
        web_service_layout.setContentsMargins(0, 0, 0, 8)
        web_service_layout.setSpacing(10)
        web_service_layout.addWidget(section_title("รายงานผ่านเว็บ", "Web reports"))
        web_service_row = QHBoxLayout()
        self.web_service_enabled = QCheckBox("เปิด Web Report ให้เครื่องอื่นใน LAN")
        self.web_service_enabled.setAccessibleName("เปิดรายงานผ่าน Web สำหรับเครื่องอื่นใน LAN")
        web_service_row.addWidget(self.web_service_enabled, 1)
        self.web_port = QSpinBox()
        self.web_port.setRange(1024, 65535)
        self.web_port.setValue(3000)
        self.web_port.setMaximumWidth(100)
        self.web_port.setAccessibleName("Port สำหรับ Web Report ใน LAN")
        self.web_port.setToolTip(tr("พอร์ตสำหรับเปิดรายงานผ่านเว็บ · ค่าเริ่มต้น 3000", "Web report port · default 3000"))
        web_service_layout.addLayout(web_service_row)
        self.web_service_status = QLabel()
        self.web_service_status.setWordWrap(True)
        web_service_layout.addWidget(self.web_service_status)
        address_row = QHBoxLayout()
        self.web_service_url = QLabel()
        self.web_service_url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.web_service_url.setWordWrap(True)
        self.web_service_url.setAccessibleName("ที่อยู่ Web Report สำหรับเครื่องอื่นใน LAN")
        self.web_service_url.setStyleSheet(settings_styles.BUILD_NETWORK_SETTINGS_WEB_SERVICE_URL)
        address_row.addWidget(self.web_service_url, 1)
        self.open_web_button = btn("เปิด Web", "outline")
        self.open_web_button.clicked.connect(on_open)
        address_row.addWidget(self.open_web_button)
        self.copy_web_button = btn("คัดลอก", "outline")
        self.copy_web_button.clicked.connect(on_copy)
        address_row.addWidget(self.copy_web_button)
        web_service_layout.addLayout(address_row)
        self.web_advanced_toggle = QToolButton()
        self.web_advanced_toggle.setText(tr("ตั้งค่าพอร์ต", "Port settings"))
        self.web_advanced_toggle.setCheckable(True)
        self.web_advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.web_advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.web_advanced_toggle.setStyleSheet(settings_styles.BUILD_NETWORK_SETTINGS_WEB_ADVANCED_TOGGLE)
        web_service_layout.addWidget(self.web_advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.web_advanced_panel = QWidget()
        port_layout = QHBoxLayout(self.web_advanced_panel)
        port_layout.setContentsMargins(0, 0, 0, 0)
        port_layout.addWidget(QLabel(tr("พอร์ต", "Port")))
        port_layout.addWidget(self.web_port)
        port_hint = QLabel(tr("ค่าเริ่มต้น 3000 · เปลี่ยนเมื่อพอร์ตถูกใช้งาน", "Default 3000 · change if the port is occupied"))
        port_hint.setWordWrap(True)
        port_layout.addWidget(port_hint, 1)
        self.web_advanced_panel.hide()
        self.web_advanced_toggle.toggled.connect(self.web_advanced_panel.setVisible)
        self.web_advanced_toggle.toggled.connect(
            lambda opened: self.web_advanced_toggle.setArrowType(
                Qt.ArrowType.DownArrow if opened else Qt.ArrowType.RightArrow
            )
        )
        web_service_layout.addWidget(self.web_advanced_panel)
        program_body.addWidget(web_service_card)

        web_security = QFrame()
        web_security.setObjectName("web_security")
        web_security.setStyleSheet(settings_styles.BUILD_NETWORK_SETTINGS_WEB_SECURITY)
        web_security_layout = QHBoxLayout(web_security)
        web_security_layout.setContentsMargins(0, 8, 0, 8)
        web_security_copy = QVBoxLayout()
        web_security_copy.addWidget(section_title("การเข้าดูรายงาน", "Report access"))
        self.web_report_require_password = QCheckBox(
            tr("ล็อก Web Report ด้วยรหัสผ่าน", "Require a password for Web Report")
        )
        self.web_report_require_password.setAccessibleName(
            tr("ล็อก Web Report ด้วยรหัสผ่าน", "Require a password for Web Report")
        )
        self.web_report_require_password.setToolTip(
            tr(
                "ค่าเริ่มต้นเปิดรายงานได้ทันที · เลือกตัวเลือกนี้เมื่อต้องการตั้งรหัสก่อนเข้าดู",
                "Reports open immediately by default. Enable this option to protect them with a password.",
            )
        )
        web_security_copy.addWidget(self.web_report_require_password)
        self.web_report_access_note = QLabel(
            tr(
                "ค่าเริ่มต้น: เครื่องใน LAN เปิดที่อยู่ด้านล่างเพื่อดูรายงานได้ทันทีโดยไม่ต้องใส่รหัส · ตั้งรหัสและเปิดการล็อกได้เมื่อต้องการ",
                "By default, LAN computers can open the address below to view reports immediately. Set a password and enable the lock whenever needed.",
            )
        )
        self.web_report_access_note.setWordWrap(True)
        self.web_report_access_note.hide()
        self.web_access_status = QLabel()
        self.web_access_status.setWordWrap(True)
        self.web_access_status.setAccessibleName("สถานะรหัสเข้า Web Report")
        web_security_copy.addWidget(self.web_access_status)
        web_security_layout.addLayout(web_security_copy, 1)
        self.change_web_access_button = btn("ตั้งรหัส", "outline")
        self.change_web_access_button.setAccessibleName("ตั้งหรือเปลี่ยนรหัสเข้า Web Report")
        self.change_web_access_button.clicked.connect(on_change_code)
        web_security_layout.addWidget(self.change_web_access_button)
        program_body.addWidget(web_security)

        peer_sync = QFrame()
        peer_sync.setObjectName("peer_sync_authorization")
        peer_sync.setStyleSheet(settings_styles.BUILD_NETWORK_SETTINGS_PEER_SYNC)
        peer_sync_layout = QHBoxLayout(peer_sync)
        peer_sync_layout.setContentsMargins(0, 8, 0, 8)
        peer_sync_copy = QVBoxLayout()
        peer_sync_title = section_title("รับสมาชิกและใช้ข้อมูลร่วมกัน", "Member access and shared data")
        self.peer_sync_status = QLabel()
        self.peer_sync_status.setWordWrap(True)
        self.peer_sync_status.setAccessibleName("สถานะการอนุญาตรับการตั้งค่า")
        peer_sync_copy.addWidget(peer_sync_title)
        peer_sync_copy.addWidget(self.peer_sync_status)
        setup_note = QLabel(
            tr(
                "เปิดรับสมาชิกตลอดโดยอัตโนมัติ · เครื่องใหม่เลือกเข้ากลุ่มใน Wizard ได้ ไม่ต้องกดเปิดรับซ้ำที่ต้นทาง",
                "Joining is enabled automatically and stays open. New computers join through the Wizard without repeated approval on this computer.",
            )
        )
        setup_note.setWordWrap(True)
        peer_sync_copy.addWidget(setup_note)
        peer_sync_layout.addLayout(peer_sync_copy, 1)
        self.peer_sync_mode = QComboBox()
        self.peer_sync_mode.setProperty("i18n_items", True)
        self.peer_sync_mode.addItem("ปิด", "off")
        self.peer_sync_mode.addItem("เปิดตลอด", "always")
        self.peer_sync_mode.setAccessibleName("ระยะเวลาอนุญาตรับการตั้งค่า")
        peer_sync_layout.addWidget(self.peer_sync_mode)
        self.peer_sync_authorize_button = btn(tr("บันทึกสิทธิ์เข้ากลุ่ม", "Save member access"), "outline")
        self.peer_sync_authorize_button.setAccessibleName("ใช้การตั้งค่าสิทธิ์ให้คอมพิวเตอร์อื่นรับการตั้งค่า")
        self.peer_sync_authorize_button.clicked.connect(on_authorize)
        peer_sync_layout.addWidget(self.peer_sync_authorize_button)
        program_body.addWidget(peer_sync)
        from ui.peer_enrollment_approval import EnrollmentApprovalDialog

        self.enroll_member_button = btn(tr("รายละเอียดการเข้าร่วมกลุ่ม", "About joining a group"), "outline")

        def approve_member():
            dialog = EnrollmentApprovalDialog(parent)
            dialog.finished.connect(on_peer_refresh)
            dialog.open()
            self._enrollment_approval_dialog = dialog

        self.enroll_member_button.clicked.connect(approve_member)
        program_body.addWidget(self.enroll_member_button, 0, Qt.AlignmentFlag.AlignLeft)
        from ui.shared_settings_history import show_shared_settings_history

        self.shared_history_button = btn(tr("ประวัติการตั้งค่าร่วม", "Shared settings history"), "outline")
        self.shared_history_button.clicked.connect(lambda: show_shared_settings_history(parent))
        program_body.addWidget(self.shared_history_button, 0, Qt.AlignmentFlag.AlignLeft)
        from ui.network_activity import NetworkActivityPanel

        self.network_activity = NetworkActivityPanel(parent)
        subscribe_changes(self.network_activity.schedule_refresh)
        program_body.addWidget(self.network_activity)
        (
            self.web_save_status,
            web_save_actions,
            self.web_save_button,
        ) = editor_actions(
            "บันทึกและตรวจสอบ LAN",
            on_save,
            on_cancel,
        )
        program_body.addLayout(web_save_actions)

        self.web_service_enabled.toggled.connect(lambda _checked: on_dirty())
        self.web_port.valueChanged.connect(lambda _value: on_dirty())
        self.web_report_require_password.toggled.connect(lambda _checked: on_dirty())
