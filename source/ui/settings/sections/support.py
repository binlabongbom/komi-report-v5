"""Support card and expandable technical details."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from i18n import tr
from ui.styles import settings as settings_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import text as text_styles
from widgets import btn


class SupportSection:
    """Support links and optional details without owning navigation or services."""

    def __init__(
        self,
        editor: QFrame,
        *,
        on_advanced: Callable[[], None],
        on_activity: Callable[[], None],
        on_audit: Callable[[], None],
        on_network: Callable[[], None],
        on_shortcuts: Callable[[], None],
    ) -> None:
        support_body = editor.layout()
        open_advanced = btn("เปิดการตั้งค่าขั้นสูง", "primary")
        open_advanced.clicked.connect(on_advanced)
        support_body.addWidget(open_advanced, 0, Qt.AlignmentFlag.AlignLeft)
        symptom_label = QLabel("พบปัญหาอะไร")
        symptom_label.setStyleSheet(text_styles.label("#334155", font_weight="700", border="none"))
        support_body.addWidget(symptom_label)
        symptom_actions = QHBoxLayout()
        stale_button = btn("ข้อมูลไม่อัปเดต", "outline")
        stale_button.clicked.connect(on_activity)
        symptom_actions.addWidget(stale_button)
        mismatch_button = btn("ยอดไม่ตรง", "outline")
        mismatch_button.clicked.connect(on_audit)
        symptom_actions.addWidget(mismatch_button)
        web_problem_button = btn("เปิด Web ไม่ได้", "outline")
        web_problem_button.clicked.connect(on_network)
        symptom_actions.addWidget(web_problem_button)
        symptom_actions.addStretch()
        support_body.addLayout(symptom_actions)

        staff_label = QLabel("ข้อมูลสำหรับเจ้าหน้าที่")
        staff_label.setStyleSheet(settings_styles.FLEET_SETTINGS_STAFF_LABEL)
        support_body.addWidget(staff_label)
        self.support_toggle = btn("แสดงข้อมูลสำหรับเจ้าหน้าที่", "outline")
        self.support_toggle.setCheckable(True)
        self.support_toggle.setAccessibleName("แสดงหรือซ่อนข้อมูลสำหรับเจ้าหน้าที่")
        self.support_toggle.toggled.connect(self.toggle_details)
        support_body.addWidget(self.support_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.support_details = QFrame()
        self.support_details.setObjectName("settings_support_details")
        self.support_details.setStyleSheet(settings_styles.FLEET_SETTINGS_SUPPORT_DETAILS)
        support_details_layout = QVBoxLayout(self.support_details)
        support_details_layout.setContentsMargins(12, 12, 12, 12)
        support_details_layout.setSpacing(10)
        warning = QLabel("คำเตือน: รายละเอียดบางรายการมีผลต่อฐานข้อมูลและประวัติการใช้งาน โปรดอ่านข้อความยืนยันก่อนดำเนินการ")
        warning.setWordWrap(True)
        warning.setAccessibleName("คำเตือนสำหรับเครื่องมือเจ้าหน้าที่")
        warning.setStyleSheet(surfaces_styles.WARNING_NOTICE)
        support_details_layout.addWidget(warning)
        support_actions = QHBoxLayout()
        activity_button = btn("สถานะและประวัติการอ่าน", "outline")
        activity_button.clicked.connect(on_activity)
        support_actions.addWidget(activity_button)
        audit_button = btn("ตรวจสอบรอบบิล", "outline")
        audit_button.clicked.connect(on_audit)
        support_actions.addWidget(audit_button)
        advanced_button = btn("เปิดการตั้งค่าขั้นสูง", "outline")
        advanced_button.clicked.connect(on_advanced)
        support_actions.addWidget(advanced_button)
        support_actions.addStretch()
        support_details_layout.addLayout(support_actions)
        self.active_database_path = QLabel()
        self.active_database_path.setWordWrap(True)
        self.active_database_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.active_database_path.setAccessibleName("ตำแหน่งฐานข้อมูลที่กำลังใช้งาน")
        self.active_database_path.setStyleSheet(surfaces_styles.READONLY_SUMMARY)
        support_details_layout.addWidget(self.active_database_path)
        self.registration_support_detail = QLabel(tr("ยังไม่แสดงรายละเอียดทางเทคนิค", "Technical details are hidden"))
        self.registration_support_detail.setWordWrap(True)
        self.registration_support_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.registration_support_detail.setAccessibleName(tr("รายละเอียดสำหรับ Support", "Support details"))
        self.registration_support_detail.setStyleSheet(surfaces_styles.READONLY_SUMMARY)
        support_details_layout.addWidget(self.registration_support_detail)
        shortcut_button = btn("สร้าง Shortcut ใหม่", "outline")
        shortcut_button.clicked.connect(on_shortcuts)
        support_details_layout.addWidget(shortcut_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.support_details.hide()
        support_body.addWidget(self.support_details)

    def toggle_details(self, visible: bool) -> None:
        self.support_details.setVisible(visible)
        self.support_toggle.setText(
            tr("ซ่อนข้อมูลสำหรับเจ้าหน้าที่", "Hide staff information")
            if visible
            else tr("แสดงข้อมูลสำหรับเจ้าหน้าที่", "Show staff information")
        )
