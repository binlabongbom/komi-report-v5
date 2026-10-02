"""Notices UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from i18n import tr
from ui.styles import text as text_styles
from widgets import btn


def show_compact_information(parent: QWidget, title: str, message: str) -> None:
    """Consistent compact notice that does not inherit oversized native alerts."""

    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumWidth(420)
    dialog.setMaximumWidth(560)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 20, 22, 18)
    layout.setSpacing(16)
    body = QLabel(message)
    body.setWordWrap(True)
    body.setStyleSheet(text_styles.label('#243244', font_weight='650', border='none'))
    layout.addWidget(body)
    actions = QHBoxLayout()
    actions.addStretch()
    confirm = btn(tr("ตกลง", "OK"), "primary")
    confirm.setMinimumWidth(104)
    confirm.clicked.connect(dialog.accept)
    actions.addWidget(confirm)
    layout.addLayout(actions)
    dialog.exec()
