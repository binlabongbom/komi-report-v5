"""Numeric editors with stable ASCII digits and decimal points on every PC."""

from PyQt6.QtCore import QLocale
from PyQt6.QtWidgets import QDateEdit, QDoubleSpinBox, QSpinBox, QTimeEdit


def configure_numeric_locale():
    """Set the application fallback before creating Qt widgets or delegates.

    UI translations are managed separately by i18n; numeric formatting must
    not inherit native digit substitution from Windows regional preferences.
    """
    QLocale.setDefault(QLocale("en_US"))


class NumericSpinBox(QSpinBox):
    """Integer input independent of the parent and Windows regional settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLocale(QLocale("en_US"))


class NumericDoubleSpinBox(QDoubleSpinBox):
    """Decimal input using 0-9 and '.', including prices and percentages."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLocale(QLocale("en_US"))


class NumericDateEdit(QDateEdit):
    """Stable date digits, also inherited by the popup calendar/year editor."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLocale(QLocale("en_US"))


class NumericTimeEdit(QTimeEdit):
    """Schedule entry with ASCII hour/minute digits."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLocale(QLocale("en_US"))
