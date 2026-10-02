"""Settings card headers shared by immediate actions and expandable editors."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ui.styles import text as text_styles
from ui.styles.tokens import F_MD
from ui.styles.typography import fnt


class TaskHeader(QHBoxLayout):
    """Title, wrapping summary and an action supplied by the owning page.

    A layout deliberately preserves the existing card's widget hierarchy;
    button creation, signal connections and editor state belong to the page.
    """

    def __init__(self, title: str, summary: str, action: QPushButton) -> None:
        super().__init__()
        self.setSpacing(14)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        self.heading = QLabel(title)
        self.heading.setFont(fnt(F_MD, True))
        self.heading.setStyleSheet(text_styles.label("#102A43", border="none"))
        self.detail = QLabel(summary)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(text_styles.label("#52677D", border="none"))
        copy.addWidget(self.heading)
        copy.addWidget(self.detail)
        self.addLayout(copy, 1)
        action.setMinimumWidth(108)
        self.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
