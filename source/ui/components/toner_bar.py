"""Shared toner rendering for printer cards and the overview."""

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.styles import surfaces, tokens


class TonerBar(QWidget):
    """A toner percentage track with page-specific geometry supplied by its caller."""

    def __init__(
        self,
        key: str,
        value: object,
        color: str,
        parent=None,
        *,
        object_name: str = "toner_level_bar",
        height: int = 20,
        minimum_width: int = 42,
        maximum_width: int | None = None,
        preferred_width: int | None = None,
        background: str = "#FFFFFF",
    ) -> None:
        super().__init__(parent)
        self.key = key
        self.color = QColor(color)
        self._background = QColor(background)
        self._preferred_width = preferred_width
        try:
            self.value = max(0.0, min(100.0, float(value)))
            self.value_text = f"{self.value:,.0f}%"
        except (TypeError, ValueError):
            self.value = 0.0
            self.value_text = "—"
        self.setObjectName(object_name)
        self.setProperty("tonerKey", key)
        self.setProperty("tonerPercent", self.value if self.value_text != "—" else None)
        self.setMinimumWidth(minimum_width)
        if maximum_width is not None:
            self.setMaximumWidth(maximum_width)
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAutoFillBackground(False)
        self.setStyleSheet(surfaces.TRANSPARENT)

    def sizeHint(self) -> QSize:
        if self._preferred_width is None:
            return super().sizeHint()
        return QSize(self._preferred_width, self.height())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Paint the card background too, so rounded corners cannot inherit
        # the application-wide gray QWidget background.
        painter.fillRect(self.rect(), self._background)
        rect = QRectF(0.5, 0.5, max(0.0, self.width() - 1.0), max(0.0, self.height() - 1.0))
        path = QPainterPath()
        path.addRoundedRect(rect, 6.0, 6.0)
        painter.fillPath(path, QColor(tokens.C_TONER_TRACK))
        if self.value > 0:
            painter.save()
            painter.setClipPath(path)
            fill = QColor(self.color)
            fill.setAlphaF(0.20)
            painter.fillRect(
                QRectF(rect.left(), rect.top(), rect.width() * self.value / 100.0, rect.height()),
                fill,
            )
            painter.restore()
        painter.setPen(QPen(QColor(tokens.C_TONER_BORDER), 1.0))
        painter.drawPath(path)
        painter.setPen(self.color)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self.key}  {self.value_text}")
