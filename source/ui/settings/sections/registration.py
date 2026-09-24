"""Registration card controls; authorization belongs to the coordinator."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QWidget,
)

from i18n import tr
from ui.policy import OFFLINE_ACTIVATION_ENABLED
from ui.styles import settings as settings_styles
from ui.styles import text as text_styles
from widgets import btn


class RegistrationSection:
    """Registration notice and mode controls, with explicit service actions."""

    def __init__(
        self,
        registration_card: QFrame,
        summary: QLabel,
        retry: QPushButton,
        *,
        parent: QWidget,
        on_retry: Callable[[], None],
        on_privacy: Callable[[], None],
        on_notice: Callable[[bool], None],
        on_mode: Callable[[str], None],
        on_export_request: Callable[[], None],
        on_import_license: Callable[[], None],
    ) -> None:
        self.registration_summary = summary
        self.registration_retry_button = retry
        self.registration_summary.setAccessibleName("สถานะการลงทะเบียนโปรแกรม")
        self.registration_retry_button.setAccessibleName("ลองส่งข้อมูลลงทะเบียนอีกครั้ง")
        self.registration_retry_button.clicked.connect(on_retry)
        registration_row = registration_card.layout().itemAt(0).layout()
        self.registration_privacy_button = btn("ดูข้อมูลที่ส่ง", "outline")
        self.registration_privacy_button.setAccessibleName("เปิดดูประกาศข้อมูลการลงทะเบียน")
        self.registration_privacy_button.clicked.connect(on_privacy)
        if registration_row is not None:
            registration_row.insertWidget(
                1,
                self.registration_privacy_button,
                0,
                Qt.AlignmentFlag.AlignVCenter,
            )
        self.registration_notice_accept = QCheckBox(
            tr(
                "ฉันได้อ่านและรับทราบข้อมูลการลงทะเบียนเวอร์ชันปัจจุบัน",
                "I have read and acknowledge the current Registration Data Notice",
            )
        )
        self.registration_notice_accept.setAccessibleName(
            tr(
                "รับทราบข้อมูลการลงทะเบียนเวอร์ชันปัจจุบัน",
                "Acknowledge the current Registration Data Notice",
            )
        )
        self.registration_notice_accept.clicked.connect(on_notice)
        registration_card.layout().addWidget(self.registration_notice_accept)

        registration_mode_row = QHBoxLayout()
        registration_mode_label = QLabel(tr("โหมดการลงทะเบียน", "Registration mode"))
        registration_mode_label.setStyleSheet(text_styles.label("#334155", font_weight="700", border="none"))
        registration_mode_row.addWidget(registration_mode_label)
        self.registration_mode_group = QButtonGroup(parent)
        self.registration_mode_group.setExclusive(True)
        self.registration_online_mode = QRadioButton(tr("ออนไลน์ · ลงทะเบียนอัตโนมัติ", "Online · automatic registration"))
        self.registration_online_mode.setAccessibleName(tr("เลือกรับบริการแบบออนไลน์", "Use Online Registration"))
        self.registration_offline_mode = QRadioButton(tr("ออฟไลน์ · ใช้ไฟล์ License", "Offline · use a license file"))
        self.registration_offline_mode.setAccessibleName(tr("เลือกใช้งานแบบ Offline License", "Use an Offline License"))
        self.registration_mode_group.addButton(self.registration_online_mode)
        self.registration_mode_group.addButton(self.registration_offline_mode)
        registration_mode_row.addWidget(self.registration_online_mode)
        registration_mode_row.addWidget(self.registration_offline_mode)
        registration_mode_row.addStretch()
        registration_card.layout().addLayout(registration_mode_row)
        self.registration_online_mode.clicked.connect(lambda: on_mode("online"))
        self.registration_offline_mode.clicked.connect(lambda: on_mode("offline"))
        registration_mode_label.setVisible(OFFLINE_ACTIVATION_ENABLED)
        self.registration_online_mode.setVisible(OFFLINE_ACTIVATION_ENABLED)
        self.registration_offline_mode.setVisible(OFFLINE_ACTIVATION_ENABLED)

        self.offline_license_summary = QLabel()
        self.offline_license_summary.setWordWrap(True)
        self.offline_license_summary.setAccessibleName(tr("สถานะ Offline License", "Offline License status"))
        self.offline_license_summary.setStyleSheet(settings_styles.FLEET_SETTINGS_OFFLINE_LICENSE_SUMMARY)
        registration_card.layout().addWidget(self.offline_license_summary)
        offline_actions = QHBoxLayout()
        self.offline_request_button = btn(tr("สร้างไฟล์คำขอ…", "Export request…"), "outline")
        self.offline_request_button.setAccessibleName(tr("สร้างคำขอ Offline License", "Export Offline License request"))
        self.offline_request_button.clicked.connect(on_export_request)
        offline_actions.addWidget(self.offline_request_button)
        self.offline_import_button = btn(tr("นำเข้า License…", "Import license…"), "outline")
        self.offline_import_button.setAccessibleName(tr("นำเข้าไฟล์ Offline License", "Import Offline License file"))
        self.offline_import_button.clicked.connect(on_import_license)
        offline_actions.addWidget(self.offline_import_button)
        offline_actions.addStretch()
        registration_card.layout().addLayout(offline_actions)
