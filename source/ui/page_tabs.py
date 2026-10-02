"""Shared page navigation for reports, settings and their detail views."""

from ui.styles import text as text_styles
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from ui.styles.tokens import F_2XL
from ui.styles.navigation import page_tabs_qss
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
        self.title.setStyleSheet(text_styles.label('#102A43', border='none', background='transparent'))
        self.description = QLabel(description)
        self.description.setWordWrap(True)
        self.description.setStyleSheet(text_styles.label('#52677D', border='none', background='transparent'))
        layout.addWidget(self.title)
        layout.addWidget(self.description)


class PageTabs(QTabWidget):
    def set_compact(self, compact: bool):
        if getattr(self, "_compact", None) != compact:
            self._compact = compact
            # Density changes only the tab buttons. Restyling QTabWidget also
            # repolishes every chart/table in its pages, including hidden tabs.
            self.tabBar().setStyleSheet(page_tabs_qss(compact=compact))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabPosition(QTabWidget.TabPosition.North)
        self.setUsesScrollButtons(True)
        self.tabBar().setExpanding(False)
        self.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self._compact = False
        self.setStyleSheet(page_tabs_qss())
