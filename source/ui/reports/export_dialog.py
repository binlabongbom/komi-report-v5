"""Export dialog UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from datetime import date, timedelta

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from i18n import tr
from services.report_period_policy import EXPORT_YEARS, latest_allowed_end, latest_export_start
from ui.numeric_inputs import NumericDateEdit as QDateEdit
from ui.styles import text as text_styles
from ui.styles.tokens import C_TEXT2, F_LG
from widgets import fnt


class ReportExportPeriodDialog(QDialog):
    """Choose the date range and sheets before starting the background export."""

    def __init__(
        self,
        start: date,
        end: date,
        *,
        available_start: date | None = None,
        available_end: date | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.available_start = available_start
        self.available_end = available_end
        self.setWindowTitle("Export รายงาน Excel")
        self.setModal(True)
        self.setMinimumWidth(540)
        self.resize(580, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        title = QLabel(tr("เลือกข้อมูลที่ต้องการ Export", "Choose reports to export"))
        title.setFont(fnt(F_LG, True))
        layout.addWidget(title)
        description = QLabel(
            tr("เลือกช่วงเวลาได้สูงสุด 5 ปีต่อไฟล์ และเลือกรายงานที่ต้องการ",
               "Choose up to 5 years per file and select the reports to include.")
        )
        description.setWordWrap(True)
        description.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.start_date = QDateEdit(QDate(start.year, start.month, start.day))
        self.end_date = QDateEdit(QDate(end.year, end.month, end.day))
        for editor in (self.start_date, self.end_date):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd/MM/yyyy")
            editor.setMinimumHeight(34)
            editor.setFixedWidth(190)
        form.addRow(tr("วันที่เริ่มต้น", "Start date"), self.start_date)
        form.addRow(tr("วันที่สิ้นสุด", "End date"), self.end_date)
        layout.addLayout(form)

        quick = QHBoxLayout()
        quick.setSpacing(8)
        current_button = QPushButton(tr("ช่วงที่แสดงอยู่", "Current preview"))
        current_button.clicked.connect(lambda: self._set_range(start, end))
        quick.addWidget(current_button)
        month_button = QPushButton(tr("เดือนนี้", "This month"))
        month_button.clicked.connect(self._set_current_month)
        quick.addWidget(month_button)
        if available_start is not None and available_end is not None:
            fits_all = available_end <= latest_allowed_end(available_start, EXPORT_YEARS)
            all_button = QPushButton(tr('ข้อมูลทั้งหมด', 'All data') if fits_all
                                     else tr('5 ปีล่าสุด', 'Latest 5 years'))
            all_button.clicked.connect(lambda: self._set_range(
                available_start if fits_all else latest_export_start(available_end), available_end))
            quick.addWidget(all_button)
        quick.addStretch(1)
        layout.addLayout(quick)

        from services.report_export_options import REPORT_SECTIONS
        choices_title = QHBoxLayout()
        choices_title.addWidget(QLabel(tr("รายงานที่ส่งออก", "Reports to export")))
        choices_title.addStretch()
        for label, checked in ((tr("เลือกทั้งหมด", "Select all"), True),
                               (tr("ล้างทั้งหมด", "Clear all"), False)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=checked: self._select_all(value))
            choices_title.addWidget(button)
        layout.addLayout(choices_title)
        choices = QGridLayout()
        choices.setHorizontalSpacing(24)
        choices.setVerticalSpacing(10)
        self.section_checks = {}
        for index, (key, thai, english) in enumerate(REPORT_SECTIONS):
            check = QCheckBox(tr(thai, english))
            check.setChecked(True)
            check.toggled.connect(self._validate)
            self.section_checks[key] = check
            choices.addWidget(check, index % 3, index // 3)
        layout.addLayout(choices)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(text_styles.label(C_TEXT2, padding='8px', background='#F5F8FA'))
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        self.export_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.export_button.setText("Export Excel")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("ยกเลิก", "Cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.start_date.dateChanged.connect(self._validate)
        self.end_date.dateChanged.connect(self._validate)
        self._validate()

    def selected_range(self) -> tuple[date, date]:
        return self.start_date.date().toPyDate(), self.end_date.date().toPyDate()

    def selected_sections(self) -> tuple[str, ...]:
        return tuple(key for key, check in self.section_checks.items() if check.isChecked())

    def _select_all(self, checked: bool) -> None:
        for check in self.section_checks.values():
            check.setChecked(checked)

    def _set_range(self, start: date, end: date) -> None:
        self.start_date.setDate(QDate(start.year, start.month, start.day))
        self.end_date.setDate(QDate(end.year, end.month, end.day))

    def _set_current_month(self) -> None:
        today = date.today()
        month_start = today.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        self._set_range(month_start, next_month - timedelta(days=1))

    def _validate(self) -> None:
        start, end = self.selected_range()
        limit = latest_allowed_end(start, EXPORT_YEARS)
        valid = start <= end <= limit and bool(self.selected_sections())
        self.export_button.setEnabled(valid)
        if not valid:
            if start > end:
                message = tr("วันที่เริ่มต้นต้องไม่เกินวันที่สิ้นสุด", "Start date must not be after end date")
            elif end > limit:
                message = tr('Export ได้สูงสุด 5 ปีต่อไฟล์ · เลือกวันสิ้นสุดไม่เกิน {end}',
                             'Export supports up to 5 years per file. Choose an end date on or before {end}').format(end=limit.strftime('%d/%m/%Y'))
            else:
                message = tr("เลือกรายงานอย่างน้อยหนึ่งรายการ", "Select at least one report")
            self.status.setText(message)
            self.status.setStyleSheet(text_styles.label('#B42318', padding='8px', background='#FFF1F0'))
            return
        days = (end - start).days + 1
        available = ""
        if self.available_start is not None and self.available_end is not None:
            available = tr(" · ข้อมูลที่พบ {start}–{end}", " · Available data {start}–{end}").format(
                start=self.available_start.strftime('%d/%m/%Y'),
                end=self.available_end.strftime('%d/%m/%Y'))
        self.status.setText(tr("ช่วงที่เลือก {days:,} วัน · {count} รายงาน{available}",
                               "Selected {days:,} days · {count} reports{available}").format(
                                   days=days, count=len(self.selected_sections()), available=available))
        self.status.setStyleSheet(text_styles.label(C_TEXT2, padding='8px', background='#F5F8FA'))

    def accept(self) -> None:
        self._validate()
        if self.export_button.isEnabled():
            super().accept()

    @classmethod
    def get_selection(
        cls,
        parent,
        start: date,
        end: date,
        *,
        available_start: date | None = None,
        available_end: date | None = None,
    ):
        dialog = cls(
            start,
            end,
            available_start=available_start,
            available_end=available_end,
            parent=parent,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        from services.report_export_options import ReportExportSelection
        return ReportExportSelection(*dialog.selected_range(), dialog.selected_sections())
