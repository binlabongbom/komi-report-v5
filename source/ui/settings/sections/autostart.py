"""Auto-start controls and operating-system status presentation."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import (
    QCheckBox,
    QLabel,
    QVBoxLayout,
)

from i18n import tr
from ui.settings.sections.common import editor_actions
from ui.styles import settings as settings_styles
from ui.styles import text as text_styles
from ui.styles.tokens import F_MD
from widgets import fnt


class AutostartSection:
    """Auto-start controls; the owner coordinates OS registration changes."""

    def __init__(
        self,
        autostart_body: QVBoxLayout,
        *,
        on_save: Callable[[], None],
        on_cancel: Callable[[], None],
        on_dirty: Callable[[], None],
    ) -> None:
        self.autostart = QCheckBox("เปิดโปรแกรมอัตโนมัติเมื่อเข้าสู่ระบบ")
        self.autostart.setAccessibleName("เปิดโปรแกรมอัตโนมัติเมื่อเข้าสู่ระบบ")
        self.autostart_status = QLabel()
        self.autostart_status.setWordWrap(True)
        autostart_title = QLabel("เปิดโปรแกรมอัตโนมัติ")
        autostart_title.setFont(fnt(F_MD, True))
        autostart_title.setStyleSheet(text_styles.label("#102A43", border="none"))
        autostart_note = QLabel("กำหนดให้ KOMI Report เริ่มทำงานเมื่อผู้ใช้เข้าสู่ระบบปฏิบัติการ")
        autostart_note.setWordWrap(True)
        autostart_note.setStyleSheet(text_styles.label("#52677D", border="none"))
        autostart_body.addWidget(autostart_title)
        autostart_body.addWidget(autostart_note)
        autostart_body.addWidget(self.autostart)
        autostart_body.addWidget(self.autostart_status)
        (
            self.autostart_save_status,
            autostart_actions,
            self.autostart_save_button,
        ) = editor_actions(
            "บันทึก Auto-start",
            on_save,
            on_cancel,
        )
        autostart_body.addLayout(autostart_actions)

        self.autostart.toggled.connect(lambda _checked: on_dirty())

    def refresh_status(self, registered: bool | None) -> None:
        if registered is True:
            self.autostart_status.setText(
                tr(
                    "พบ OS registration สำหรับเปิดอัตโนมัติแล้ว",
                    "Automatic start is registered with the operating system",
                )
            )
            self.autostart_status.setStyleSheet(settings_styles.FLEET_SETTINGS_AUTOSTART_STATUS)
        elif registered is False:
            self.autostart_status.setText(
                tr(
                    "ไม่พบ OS registration · เลือก checkbox แล้วกดบันทึกเพื่อเปิดใช้งาน",
                    "No OS registration found. Select the checkbox and save to enable it.",
                )
            )
            self.autostart_status.setStyleSheet(settings_styles.FLEET_SETTINGS_AUTOSTART_STATUS_WARNING)
        else:
            self.autostart_status.setText(
                tr(
                    "ตรวจ OS registration ไม่ได้ · checkbox แสดงค่าที่บันทึกไว้",
                    "OS registration could not be checked. The checkbox shows the stored setting.",
                )
            )
            self.autostart_status.setStyleSheet(settings_styles.FLEET_SETTINGS_AUTOSTART_STATUS_INACTIVE)
