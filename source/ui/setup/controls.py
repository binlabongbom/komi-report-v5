"""Controls UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QComboBox, QStyle, QStyledItemDelegate, QStyleOptionViewItem


class SetupDeviceStatusDelegate(QStyledItemDelegate):
    """Preserve the row's explicit status colour when Qt marks it selected."""

    def paint(self, painter, option, index) -> None:
        paint_option = QStyleOptionViewItem(option)
        paint_option.state &= ~QStyle.StateFlag.State_Selected
        super().paint(painter, paint_option, index)


class WizardComboBox(QComboBox):
    """Theme-stable combo box with a painted chevron on every platform."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor("#172033"), 2.0))
        center_y = self.height() / 2.0
        right = self.width() - 13.0
        path = QPainterPath()
        path.moveTo(right - 10.0, center_y - 2.5)
        path.lineTo(right - 5.0, center_y + 2.5)
        path.lineTo(right, center_y - 2.5)
        painter.drawPath(path)
