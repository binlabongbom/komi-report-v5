"""Shared light appearance for setup choices and calendar popups."""

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QCalendarWidget, QComboBox

from ui.styles import setup as setup_styles


def style_wizard_combo(combo: QComboBox, palette: QPalette, *, popup_width: int | None = None) -> None:
    """Give non-editable choices the same light treatment on Mac and Windows."""
    combo.setMinimumHeight(40)
    combo.setStyleSheet(setup_styles.CHOICE)
    view = combo.view()
    view.setPalette(palette)
    view.setStyleSheet(setup_styles.SETUP_WIZARD_STYLE_WIZARD_COMBO)
    if popup_width is not None:
        view.setMinimumWidth(popup_width)


def style_price_calendar(calendar: QCalendarWidget, palette: QPalette) -> None:
    """Prevent the native dark calendar popup from escaping the Wizard theme."""
    calendar.setPalette(palette)
    calendar.setGridVisible(False)
    calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
    calendar.setStyleSheet(setup_styles.PRICE_CALENDAR)
