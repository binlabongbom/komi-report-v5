"""Shared page navigation for reports, settings and their detail views."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from config import F_2XL, page_tabs_qss
from widgets import fnt


class PageHeading(QWidget):
    """Consistent title, description and spacing above the navigation tabs."""

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title = QLabel(title)
        self.title.setFont(fnt(F_2XL, True))
        self.title.setStyleSheet("color:#102A43;border:none;background:transparent;")
        self.description = QLabel(description)
        self.description.setWordWrap(True)
        self.description.setStyleSheet("color:#52677D;border:none;background:transparent;")
        layout.addWidget(self.title)
        layout.addWidget(self.description)


class PageTabs(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabPosition(QTabWidget.TabPosition.North)
        self.setUsesScrollButtons(True)
        self.tabBar().setExpanding(False)
        self.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self.setStyleSheet(page_tabs_qss())
