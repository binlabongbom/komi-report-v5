"""Schedule editor, row lifecycle, validation, and display summaries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import time, timedelta

from PyQt6.QtCore import Qt, QTime
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QVBoxLayout,
)

from i18n import get_language, tr
from services.polling import ScheduleWindow
from ui.numeric_inputs import NumericSpinBox as QSpinBox
from ui.settings.controls import ScheduleTimeRangeEditor, WeekdaySelector
from ui.settings.sections.common import editor_actions
from ui.styles import settings as settings_styles
from ui.styles import surfaces as surfaces_styles
from ui.styles import tables as tables_styles
from ui.styles import text as text_styles
from widgets import btn


class ScheduleSection:
    """Own the schedule editor and validate its draft without saving it."""

    def __init__(
        self,
        editor: QFrame,
        *,
        on_save: Callable[[], None],
        on_cancel: Callable[[], None],
        on_dirty: Callable[[], None],
    ) -> None:
        self._on_dirty = on_dirty
        self.using_defaults = False
        self._rendered_windows = None
        schedule_body = editor.layout()
        self.schedule = QLabel()
        self.schedule.setWordWrap(True)
        self.schedule.setMinimumHeight(54)
        self.schedule.setAccessibleName("สรุปเวลาการอ่านข้อมูลอัตโนมัติ")
        self.schedule.setStyleSheet(surfaces_styles.INFO_BOX)
        schedule_body.addWidget(self.schedule)
        self.advanced_schedule_button = btn(
            tr("ปรับเวลาแบบละเอียด", "Edit detailed schedule"),
            "outline",
        )
        self.advanced_schedule_button.setCheckable(True)
        self.advanced_schedule_button.setAccessibleName(
            tr(
                "แสดงหรือซ่อนการตั้งเวลาแบบละเอียด",
                "Show or hide the detailed schedule",
            )
        )
        self.advanced_schedule_button.toggled.connect(self.toggle_editor)
        schedule_body.addWidget(self.advanced_schedule_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.schedule_editor = QFrame()
        self.schedule_editor.setObjectName("schedule_editor")
        self.schedule_editor.setStyleSheet(settings_styles.FLEET_SETTINGS_SCHEDULE_EDITOR)
        schedule_editor_layout = QVBoxLayout(self.schedule_editor)
        schedule_editor_layout.setContentsMargins(10, 10, 10, 10)
        schedule_editor_layout.setSpacing(8)
        schedule_hint = QLabel(
            tr(
                "สำหรับเจ้าหน้าที่: กำหนดช่วงเวลา วัน และความถี่แยกตามแหล่งข้อมูล หากไม่แน่ใจให้ใช้ค่าเดิม",
                "For staff: set time ranges, days, and reading intervals. Keep the defaults if you are unsure.",
            )
        )
        schedule_hint.setWordWrap(True)
        schedule_hint.setStyleSheet(text_styles.label("#64748B", border="none"))
        schedule_editor_layout.addWidget(schedule_hint)
        self.schedule_windows_table = QTableWidget(0, 6)
        self.schedule_windows_table.setHorizontalHeaderLabels(
            [
                tr("ชื่อช่วงเวลา", "Window name"),
                tr("เริ่ม–สิ้นสุด", "Start–end"),
                tr("วันที่ทำงาน", "Days"),
                tr("ตรวจสถานะ\n(นาที)", "Status check\n(min)"),
                tr("อ่านมิเตอร์\n(นาที)", "Meter read\n(min)"),
                "",
            ]
        )
        self.schedule_windows_table.setAccessibleName(tr("ตารางเวลาการอ่านข้อมูลแบบละเอียด", "Detailed reading schedule"))
        self.schedule_windows_table.verticalHeader().setVisible(False)
        self.schedule_windows_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.schedule_windows_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.schedule_windows_table.setMinimumHeight(230)
        self.schedule_windows_table.setMaximumHeight(330)
        self.schedule_windows_table.setAlternatingRowColors(True)
        self.schedule_windows_table.setShowGrid(False)
        self.schedule_windows_table.setFrameShape(QFrame.Shape.NoFrame)
        header = self.schedule_windows_table.horizontalHeader()
        header.setMinimumHeight(42)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column in (3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.schedule_windows_table.setColumnWidth(0, 126)
        self.schedule_windows_table.setColumnWidth(3, 72)
        self.schedule_windows_table.setColumnWidth(4, 72)
        self.schedule_windows_table.setColumnWidth(5, 40)
        self.schedule_windows_table.setStyleSheet(tables_styles.SCHEDULE)
        schedule_editor_layout.addWidget(self.schedule_windows_table)
        self.add_schedule_window_button = btn(
            tr("เพิ่มช่วงเวลา", "Add time window"),
            "outline",
        )
        self.add_schedule_window_button.clicked.connect(self.add_window)
        schedule_editor_layout.addWidget(self.add_schedule_window_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.row_controls: list[tuple[QLineEdit, ScheduleTimeRangeEditor, WeekdaySelector, QSpinBox, QSpinBox]] = []
        self.schedule_editor.hide()
        schedule_body.addWidget(self.schedule_editor)
        (
            self.schedule_save_status,
            schedule_actions,
            self.schedule_save_button,
        ) = editor_actions(
            "บันทึกเวลาและตรวจสอบ",
            on_save,
            on_cancel,
        )
        schedule_body.addLayout(schedule_actions)

    def toggle_editor(self, visible: bool) -> None:
        self.schedule_editor.setVisible(visible)
        self.advanced_schedule_button.setText(
            tr("ซ่อนการตั้งเวลาแบบละเอียด", "Hide detailed schedule")
            if visible
            else tr("ปรับเวลาแบบละเอียด", "Edit detailed schedule")
        )

    def refresh_summary(self) -> None:
        try:
            windows = self.values()
        except ValueError:
            windows = ()
        if windows:
            first_start = min(window.start for window in windows)
            last_end = max(window.end for window in windows)
            summary = tr(
                f"ตั้งเวลาอ่านข้อมูลไว้ {len(windows)} ช่วง · "
                f"ครอบคลุม {first_start:%H:%M}–{last_end:%H:%M}\n"
                "หากไม่แน่ใจ ไม่จำเป็นต้องเปลี่ยนค่ารายละเอียด",
                f"Reading schedule has {len(windows)} windows · "
                f"covering {first_start:%H:%M}–{last_end:%H:%M}\n"
                "If unsure, keep the recommended schedule.",
            )
        else:
            summary = tr(
                "ยังไม่ได้ตั้งเวลาอ่านข้อมูลอัตโนมัติ",
                "No automatic reading schedule is configured",
            )
        default_prefix = tr("ใช้ค่าแนะนำของระบบ · ", "Using recommended defaults · ") if self.using_defaults else ""
        self.schedule.setText(f"{default_prefix}{summary}")

    def replace_windows(self, windows: tuple[ScheduleWindow, ...]) -> None:
        signature = (windows, get_language())
        if self._rendered_windows == signature:
            return
        self.schedule_windows_table.setRowCount(0)
        self.row_controls.clear()
        for window in windows:
            self.append_window(window, mark_dirty=False)
        self._rendered_windows = signature
        self.refresh_summary()

    def append_window(self, window: ScheduleWindow, *, mark_dirty: bool) -> None:
        row = self.schedule_windows_table.rowCount()
        self.schedule_windows_table.insertRow(row)
        self.schedule_windows_table.setRowHeight(row, 56)
        display_labels = {
            "Lazyload": tr("นอกเวลางาน", "Off hours"),
            "Active": tr("ช่วงเร่งด่วน", "Active"),
            "Standard": tr("เวลาทำงาน", "Standard"),
        }
        name = QLineEdit(display_labels.get(window.label, window.label))
        name.setMinimumWidth(90)
        clock_range = ScheduleTimeRangeEditor(window.start, window.end)
        weekdays = WeekdaySelector(window.weekdays)
        snmp_interval = QSpinBox()
        snmp_interval.setRange(1, 1_440)
        snmp_interval.setValue(int((window.snmp_interval or timedelta(minutes=5)).total_seconds() // 60))
        web_interval = QSpinBox()
        web_interval.setRange(1, 1_440)
        web_interval.setValue(int(window.web_interval.total_seconds() // 60))
        # Keep the action column narrow without clipping a translated word.
        # The tooltip and accessible name retain the full action label.
        remove = btn("✕", "outline")
        remove.setAccessibleName(tr("ลบช่วงเวลานี้", "Remove this time window"))
        remove.setToolTip(tr("ลบช่วงเวลานี้", "Remove this time window"))
        remove.setMinimumWidth(30)
        remove.setMaximumWidth(34)
        remove.setStyleSheet(settings_styles.FLEET_SETTINGS_REMOVE)
        snmp_interval.setMaximumWidth(78)
        web_interval.setMaximumWidth(78)
        for control in (name, snmp_interval, web_interval):
            control.setMinimumHeight(32)
        self.schedule_windows_table.setCellWidget(row, 0, name)
        self.schedule_windows_table.setCellWidget(row, 1, clock_range)
        self.schedule_windows_table.setCellWidget(row, 2, weekdays)
        self.schedule_windows_table.setCellWidget(row, 3, snmp_interval)
        self.schedule_windows_table.setCellWidget(row, 4, web_interval)
        self.schedule_windows_table.setCellWidget(row, 5, remove)
        controls = (name, clock_range, weekdays, snmp_interval, web_interval)
        self.row_controls.append(controls)
        remove.clicked.connect(lambda _checked=False, row_controls=controls: self.remove_window(row_controls))
        name.textChanged.connect(self.mark_dirty)
        clock_range.changed.connect(self.mark_dirty)
        weekdays.changed.connect(self.mark_dirty)
        snmp_interval.valueChanged.connect(self.mark_dirty)
        web_interval.valueChanged.connect(self.mark_dirty)
        if mark_dirty:
            self.mark_dirty()

    def add_window(self) -> None:
        start = QTime.currentTime()
        start = QTime(start.hour(), 0)
        end = start.addSecs(60 * 60)
        self.append_window(
            ScheduleWindow(
                start=time(start.hour(), start.minute()),
                end=time(end.hour(), end.minute()),
                web_interval=timedelta(minutes=60),
                label=f"ช่วงที่ {len(self.row_controls) + 1}",
                snmp_interval=timedelta(minutes=15),
                weekdays=frozenset(range(5)),
            ),
            mark_dirty=True,
        )

    def remove_window(
        self,
        controls: tuple[QLineEdit, ScheduleTimeRangeEditor, WeekdaySelector, QSpinBox, QSpinBox],
    ) -> None:
        try:
            index = self.row_controls.index(controls)
        except ValueError:
            return
        self.schedule_windows_table.removeRow(index)
        self.row_controls.pop(index)
        self.mark_dirty()

    def mark_dirty(self, *_args) -> None:
        self.invalidate()
        self._on_dirty()

    def values(self) -> tuple[ScheduleWindow, ...]:
        windows: list[ScheduleWindow] = []
        for index, (name, clock_range, weekdays, snmp_interval, web_interval) in enumerate(self.row_controls, start=1):
            start_clock, end_clock = clock_range.values()
            label = name.text().strip() or f"ช่วงที่ {index}"
            if start_clock >= end_clock:
                raise ValueError(f"{label}: เวลาสิ้นสุดต้องอยู่หลังเวลาเริ่ม")
            selected_days = weekdays.values()
            if not selected_days:
                raise ValueError(f"{label}: เลือกอย่างน้อย 1 วันในสัปดาห์")
            windows.append(
                ScheduleWindow(
                    start=start_clock,
                    end=end_clock,
                    web_interval=timedelta(minutes=web_interval.value()),
                    label=label,
                    snmp_interval=timedelta(minutes=snmp_interval.value()),
                    weekdays=selected_days,
                )
            )
        ordered = tuple(sorted(windows, key=lambda item: item.start))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.end > current.start and previous.weekdays & current.weekdays:
                raise ValueError(f"ช่วงเวลา {previous.label} และ {current.label} ซ้อนกันในวันเดียวกัน กรุณาแก้ไขก่อนบันทึก")
        return ordered

    def invalidate(self) -> None:
        self._rendered_windows = None
