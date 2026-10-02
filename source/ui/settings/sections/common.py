"""Shared field and action-row layout for settings editors."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.styles import settings as settings_styles
from ui.styles import text as text_styles
from widgets import btn


def editor_actions(
    save_text: str,
    save_handler: Callable[[], None],
    cancel_handler: Callable[[], None],
) -> tuple[QLabel, QHBoxLayout, QPushButton]:
    row = QHBoxLayout()
    row.setSpacing(8)
    status = QLabel("ค่าปัจจุบันถูกบันทึกแล้ว")
    status.setWordWrap(True)
    status.setStyleSheet(text_styles.label("#64748B", border="none"))
    row.addWidget(status, 1)
    cancel = btn("ยกเลิก", "outline")
    cancel.clicked.connect(cancel_handler)
    row.addWidget(cancel)
    save = btn(save_text, "success")
    save.setEnabled(False)
    save.clicked.connect(save_handler)
    row.addWidget(save)
    return status, row, save


def field(label: str, control: QWidget, hint: str = "") -> QWidget:
    field = QWidget()
    field.setObjectName("settings_field")
    field.setStyleSheet(settings_styles.FLEET_SETTINGS_FIELD)
    body = QVBoxLayout(field)
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(5)
    name = QLabel(label)
    name.setStyleSheet(text_styles.label("#334155", background="transparent", border="none", font_weight="700"))
    name.setBuddy(control)
    body.addWidget(name)
    control.setMinimumHeight(38)
    control.setMaximumWidth(320)
    body.addWidget(control)
    if hint:
        note = QLabel(hint)
        note.setWordWrap(True)
        note.setStyleSheet(text_styles.label("#64748B", background="transparent", border="none", font_size="10px"))
        body.addWidget(note)
    return field
