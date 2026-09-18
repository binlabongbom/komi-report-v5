"""Run directly with unittest as well as through the main pytest suite."""

import unittest

from PyQt6.QtCore import QDate, QLocale, QTime, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QProgressBar, QSpinBox, QStyledItemDelegate, QWidget

from ui.numeric_inputs import (
    NumericDateEdit, NumericDoubleSpinBox, NumericSpinBox, NumericTimeEdit,
    configure_numeric_locale,
)


class NumericInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_date_calendar_and_time_under_regional_locales(self):
        previous = QLocale()
        try:
            for name in ("th_TH", "ar_EG", "fa_IR", "de_DE"):
                with self.subTest(locale=name):
                    QLocale.setDefault(QLocale(name))
                    parent = QWidget()
                    parent.setLocale(QLocale(name))
                    editor = NumericDateEdit(QDate(2026, 9, 17), parent)
                    editor.setDisplayFormat("dd/MM/yyyy")
                    editor.setCalendarPopup(True)
                    self.assertEqual(editor.text(), "17/09/2026")
                    calendar = editor.calendarWidget()
                    self.assertEqual(calendar.locale().zeroDigit(), "0")
                    calendar.setSelectedDate(QDate(2026, 10, 23))
                    self.assertEqual(editor.text(), "23/10/2026")
                    year = calendar.findChild(QSpinBox)
                    self.assertIsNotNone(year)
                    self.assertEqual(year.locale().zeroDigit(), "0")
                    clock = NumericTimeEdit(QTime(9, 45), parent)
                    clock.setDisplayFormat("HH:mm")
                    self.assertEqual(clock.text(), "09:45")
                    clock.setCurrentSection(clock.Section.MinuteSection)
                    clock.stepUp()
                    self.assertEqual(clock.time(), QTime(9, 46))
                    self.assertEqual(clock.text(), "09:46")
                    parent.close()
        finally:
            QLocale.setDefault(previous)

    def test_application_fallback_for_delegates_progress_and_charts(self):
        from PyQt6.QtCharts import QChart

        previous = QLocale()
        try:
            QLocale.setDefault(QLocale("ar_EG"))
            configure_numeric_locale()
            root = QWidget()
            delegate = QStyledItemDelegate(root)
            self.assertEqual(delegate.displayText(1234, root.locale()), "1,234")
            progress = QProgressBar(root)
            progress.setValue(75)
            self.assertEqual(progress.text(), "75%")
            chart = QChart()
            # Existing charts use C-locale labels when localization is disabled.
            self.assertFalse(chart.localizeNumbers())
            self.assertEqual(chart.locale().zeroDigit(), "0")
            root.close()
        finally:
            QLocale.setDefault(previous)

    def test_display_edit_and_step_under_regional_locales(self):
        previous = QLocale()
        try:
            # Arabic/Persian exercise non-ASCII digits; German exercises ','.
            for locale_name in ("th_TH", "ar_EG", "fa_IR", "de_DE"):
                with self.subTest(locale=locale_name):
                    QLocale.setDefault(QLocale(locale_name))
                    parent = QWidget()
                    parent.setLocale(QLocale(locale_name))
                    money = NumericDoubleSpinBox(parent)
                    money.setRange(0, 1000000)
                    money.setDecimals(2)
                    money.setSingleStep(0.01)
                    money.setSuffix(" บาท")
                    money.setValue(1234.5)
                    self.assertEqual(money.text(), "1234.50 บาท")
                    money.selectAll()
                    QTest.keyClicks(money, "6789.25")
                    QTest.keyClick(money, Qt.Key.Key_Return)
                    self.assertEqual(money.value(), 6789.25)
                    money.stepUp()
                    self.assertAlmostEqual(money.value(), 6789.26)
                    self.assertEqual(money.text(), "6789.26 บาท")

                    count = NumericSpinBox(parent)
                    count.setRange(0, 100000)
                    count.setValue(1234)
                    self.assertEqual(count.text(), "1234")
                    count.selectAll()
                    QTest.keyClicks(count, "9876")
                    QTest.keyClick(count, Qt.Key.Key_Return)
                    self.assertEqual(count.value(), 9876)
                    count.stepUp()
                    self.assertEqual(count.text(), "9877")

                    # Explicit locale must survive later reparenting/locale changes.
                    other_parent = QWidget()
                    other_parent.setLocale(QLocale("ar_EG"))
                    money.setParent(other_parent)
                    count.setParent(other_parent)
                    other_parent.setLocale(QLocale("fa_IR"))
                    self.assertEqual(money.text(), "6789.26 บาท")
                    self.assertEqual(count.text(), "9877")
                    parent.close()
                    other_parent.close()
        finally:
            QLocale.setDefault(previous)


if __name__ == "__main__":
    unittest.main()
