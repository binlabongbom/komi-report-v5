"""Controls UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from datetime import time

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from i18n import apply_language, tr, translate_text
from services.web_access import MIN_ACCESS_CODE_LENGTH, validate_web_access_code
from ui.numeric_inputs import NumericTimeEdit as QTimeEdit
from ui.styles import settings as settings_styles
from ui.styles import text as text_styles
from ui.styles.tokens import F_LG
from widgets import fnt


class ScheduleTimeRangeEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, start: time, end: time, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.start = QTimeEdit(start)
        self.end = QTimeEdit(end)
        for control in (self.start, self.end):
            control.setDisplayFormat("HH:mm")
            control.setMinimumWidth(82)
            control.setMinimumHeight(32)
            control.timeChanged.connect(self.changed)
        arrow = QLabel("–")
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet(text_styles.label('#64748B', background='transparent', border='none'))
        layout.addWidget(self.start)
        layout.addWidget(arrow)
        layout.addWidget(self.end)

    def values(self) -> tuple[time, time]:
        start = self.start.time()
        end = self.end.time()
        return time(start.hour(), start.minute()), time(end.hour(), end.minute())


class WeekdaySelector(QWidget):
    changed = pyqtSignal()
    LABELS = (
        ("จ.", "M"),
        ("อ.", "Tu"),
        ("พ.", "W"),
        ("พฤ.", "Th"),
        ("ศ.", "F"),
        ("ส.", "Sa"),
        ("อา.", "Su"),
    )
    ACCESSIBLE_LABELS = (
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    )

    def __init__(self, weekdays: frozenset[int], parent=None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(3)
        layout.setVerticalSpacing(2)
        self.boxes: list[QCheckBox] = []
        for index, labels in enumerate(self.LABELS):
            box = QCheckBox(tr(*labels))
            box.setChecked(index in weekdays)
            box.setToolTip(self.ACCESSIBLE_LABELS[index])
            box.setAccessibleName(self.ACCESSIBLE_LABELS[index])
            box.setStyleSheet(settings_styles.WEEKDAY_SELECTOR_BOX)
            box.toggled.connect(self.changed)
            layout.addWidget(box, index // 4, index % 4)
            self.boxes.append(box)

    def values(self) -> frozenset[int]:
        return frozenset(index for index, box in enumerate(self.boxes) if box.isChecked())


class WebAccessCodeDialog(QDialog):
    """Simple owner-only dialog for setting the LAN Web access code."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ตั้งรหัสเข้า Web Report")
        self.setModal(True)
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        title = QLabel("รหัสสำหรับเครื่องอื่นใน LAN")
        title.setFont(fnt(F_LG, True))
        title.setStyleSheet(text_styles.label('#102A43', border='none'))
        layout.addWidget(title)
        description = QLabel(
            "ผู้ใช้ที่เปิด Web Report จากเครื่องอื่นต้องใช้รหัสนี้ เมื่อเปลี่ยนแล้วทุกเครื่องจะต้องเข้าสู่ระบบใหม่"
        )
        description.setWordWrap(True)
        description.setStyleSheet(text_styles.label('#52677D', border='none'))
        layout.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.access_code = QLineEdit()
        self.access_code.setEchoMode(QLineEdit.EchoMode.Password)
        self.access_code.setMaxLength(128)
        self.access_code.setPlaceholderText(f"อย่างน้อย {MIN_ACCESS_CODE_LENGTH} ตัวอักษร")
        self.access_code.setAccessibleName("รหัส Web ใหม่")
        self.confirm_code = QLineEdit()
        self.confirm_code.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_code.setMaxLength(128)
        self.confirm_code.setPlaceholderText("กรอกรหัสเดิมอีกครั้ง")
        self.confirm_code.setAccessibleName("ยืนยันรหัส Web ใหม่")
        form.addRow("รหัสใหม่", self.access_code)
        form.addRow("ยืนยันรหัส", self.confirm_code)
        layout.addLayout(form)

        show_code = QCheckBox("แสดงรหัสที่กำลังกรอก")
        show_code.toggled.connect(self._toggle_code_visibility)
        layout.addWidget(show_code)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet(
            settings_styles.WEB_ACCESS_CODE_DIALOG_ERROR
        )
        self.error.hide()
        layout.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_button.setText("บันทึกรหัสใหม่")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("ยกเลิก")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        apply_language(self)

    def _toggle_code_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.access_code.setEchoMode(mode)
        self.confirm_code.setEchoMode(mode)

    def _validate_and_accept(self) -> None:
        try:
            validate_web_access_code(self.access_code.text())
        except ValueError as error:
            self.error.setText(translate_text(str(error)))
            self.error.show()
            self.access_code.setFocus()
            return
        if self.access_code.text() != self.confirm_code.text():
            self.error.setText(
                tr(
                    "รหัสใหม่และช่องยืนยันไม่ตรงกัน",
                    "The new code and confirmation do not match",
                )
            )
            self.error.show()
            self.confirm_code.setFocus()
            return
        self.error.hide()
        self.accept()

    def value(self) -> str:
        return self.access_code.text()
