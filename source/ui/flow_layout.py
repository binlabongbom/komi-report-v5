"""Wrap complete widgets onto another line without splitting their contents."""
from math import ceil
from PyQt6.QtCore import QEvent, QRect, QSize, Qt
from PyQt6.QtGui import QTextDocument
from PyQt6.QtWidgets import QLayout, QLabel, QWidget, QSizePolicy


class FlowWidget(QWidget):
    """Expose the wrapped height as a constraint, including inside scroll areas."""
    def __init__(self, parent=None, *, spacing=12):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        FlowLayout(self, spacing=spacing)

    def refresh_height(self):
        height = self.layout().heightForWidth(max(1, self.width()))
        if height != self.minimumHeight() or height != self.maximumHeight():
            self.setFixedHeight(height)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_height()

    def event(self, event):
        result = super().event(event)
        if event.type() == QEvent.Type.LayoutRequest and self.layout() is not None:
            self.refresh_height()
        return result


class FlowLabel(QLabel):
    """Prefer the full legend width; wrap text only when an item exceeds its row."""
    def sizeHint(self):
        key = (self.text(), self.font().key())
        if getattr(self, '_hint_key', None) == key:
            return QSize(self._natural_hint)
        document = QTextDocument()
        document.setDocumentMargin(0)
        document.setDefaultFont(self.font())
        document.setHtml(self.text())
        document.setTextWidth(-1)
        self._hint_key = key
        self._natural_hint = QSize(ceil(document.idealWidth()) + 2, ceil(document.size().height()) + 2)
        return QSize(self._natural_hint)


class FlowLayout(QLayout):
    def __init__(self, parent=None, *, spacing=12):
        super().__init__(parent)
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < self.count() else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < self.count() else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self):
        width = sum(item.sizeHint().width() for item in self._items) + self.spacing() * max(0, self.count() - 1)
        return QSize(width, self.heightForWidth(max(1, width)))

    def minimumSize(self):
        return QSize(0, max((item.minimumSize().height() for item in self._items), default=0))

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def _arrange(self, rect, *, apply):
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            # Include children before their parent tab is shown. QWidgetItem
            # otherwise reports an empty hint and collapses a new legend.
            child = item.widget() or item
            hint = child.sizeHint()
            width = min(hint.width(), max(1, rect.width()))
            if x > rect.x() and x + width > rect.right() + 1:
                x, y, line_height = rect.x(), y + line_height + self.spacing(), 0
            height = max(hint.height(), child.heightForWidth(width) if child.hasHeightForWidth() else 0)
            if apply:
                item.setGeometry(QRect(x, y, width, height))
            x += width + self.spacing()
            line_height = max(line_height, height)
        return y + line_height - rect.y()
