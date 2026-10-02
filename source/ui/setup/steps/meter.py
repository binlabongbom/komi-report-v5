"""Review verified printer counters before creating a new meter baseline.

This view never reads a printer or writes storage. The coordinating wizard
supplies verified evidence and decides which devices need a new baseline.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import isfinite

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from i18n import tr
from komi_snmp_profiler.models import MeterReading, WebCounterValue
from services.device_config import DeviceConfig
from ui.setup.appearance import style_wizard_combo
from ui.setup.controls import WizardComboBox
from ui.styles import setup as setup_styles
from ui.styles import text as text_styles
from ui.styles.tokens import C_ACCENT, C_TEXT2


@dataclass(frozen=True, slots=True)
class MeterReviewDevice:
    """Display evidence; ``error`` carries the service's validation failure.

    ``reading`` is the normalized Parser display/DailyCache view. If mapping
    overrides changed it, ``raw_reading`` supplies the original extracted source
    counters used for journal and baseline evidence. Neither is an unparsed
    HTTP response; the coordinating service owns persistence.
    """

    device: DeviceConfig
    reading: MeterReading | None
    requires_confirmation: bool = False
    error: str = ""
    raw_reading: MeterReading | None = None


def _device_counters(reading: MeterReading | None) -> tuple[WebCounterValue, ...]:
    if reading is None:
        return ()
    return tuple(counter for counter in reading.counters
                 if not counter.subject_type and not counter.subject_id)


def _total(reading: MeterReading | None) -> int | None:
    totals = [counter.count for counter in _device_counters(reading)
              if counter.canonical_field == "counter.total.total"]
    if len(totals) != 1:
        return None
    value = totals[0]
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not isfinite(value) or value < 0 or int(value) != value):
        return None
    return int(value)


def _source_key(counter: WebCounterValue) -> str:
    # Mapping overrides may rename both the canonical field and category.
    return counter.source_path


def _label(text: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    return widget


class MeterStep(QWidget):
    """All selected slots are visible; only new baselines require consent."""

    readiness_changed = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("setup_meter_step")
        self.devices: tuple[MeterReviewDevice, ...] = ()
        self._confirmed: set[int] = set()
        self._source_rows: dict[int, int] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(9)

        chooser = QHBoxLayout()
        self.chooser_label = _label()
        chooser.addWidget(self.chooser_label)
        self.device_combo = WizardComboBox()
        style_wizard_combo(self.device_combo, self.palette())
        chooser.addWidget(self.device_combo, 1)
        layout.addLayout(chooser)
        self.identity_label = _label()
        self.identity_label.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(self.identity_label)
        self.baseline_label = _label()
        layout.addWidget(self.baseline_label)
        self.empty_label = _label()
        self.empty_label.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(self.empty_label)

        self.views = QTabWidget()
        self.views.setObjectName("setup_meter_views")
        self.views.setStyleSheet(setup_styles.METER_VIEWS)
        self.raw_table = self._table(4)
        self.parser_table = self._table(3)
        self.views.addTab(self.raw_table, "")
        self.views.addTab(self.parser_table, "")
        self.parser_table.cellClicked.connect(self._show_source)
        self.parser_table.cellActivated.connect(self._show_source)
        self.views.currentChanged.connect(self._fit_rows)
        layout.addWidget(self.views, 1)

        self.view_hint = _label()
        self.view_hint.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(self.view_hint)
        self.confirmation = QCheckBox()
        self.confirmation.toggled.connect(self._set_confirmed)
        layout.addWidget(self.confirmation)
        self.next_hint = _label()
        self.next_hint.setStyleSheet(text_styles.label(C_TEXT2))
        layout.addWidget(self.next_hint)
        self.device_combo.currentIndexChanged.connect(self._select_device)
        self.retranslate()

    @property
    def ready(self) -> bool:
        return all(not item.requires_confirmation or (
            item.device.slot in self._confirmed and self._can_confirm(item)
        ) for item in self.devices)

    @property
    def confirmed_slots(self) -> tuple[int, ...]:
        return tuple(item.device.slot for item in self.devices
                     if item.requires_confirmation and item.device.slot in self._confirmed
                     and self._can_confirm(item))

    @staticmethod
    def _can_confirm(item: MeterReviewDevice) -> bool:
        baseline = item.raw_reading or item.reading
        return bool(item.reading and not item.error
                    and item.reading.host.strip().casefold() == item.device.host.strip().casefold()
                    and baseline.host.strip().casefold() == item.device.host.strip().casefold()
                    and _total(baseline) is not None)

    def set_devices(self, devices: Sequence[MeterReviewDevice]) -> None:
        """Preserve confirmation only while configuration and evidence match."""
        selected_slot = self.device_combo.currentData()
        previous = {item.device.slot: item for item in self.devices}
        updated = tuple(sorted((item for item in devices if item.device.enabled),
                               key=lambda item: item.device.slot))
        if len({item.device.slot for item in updated}) != len(updated):
            raise ValueError("Meter review requires one entry per slot")
        self._confirmed.intersection_update(
            item.device.slot for item in updated if previous.get(item.device.slot) == item
        )
        self.devices = updated
        self._populate_devices(selected_slot)
        self.readiness_changed.emit(self.ready)

    def invalidate(self, slot: int | None = None) -> None:
        """Discard invalidated evidence so it cannot be confirmed again."""
        self.set_devices(tuple(
            replace(item, reading=None, raw_reading=None, error="")
            if slot is None or item.device.slot == slot else item
            for item in self.devices
        ))

    def summary_lines(self) -> list[str]:
        lines = []
        for item in self.devices:
            prefix = f"Slot {item.device.slot + 1} · {item.device.name}"
            if not item.requires_confirmation:
                state = tr("ใช้ฐานเดิม · ไม่เปลี่ยนประวัติ", "Keep existing baseline and history")
            else:
                value = _total(item.raw_reading or item.reading)
                total = "—" if value is None else f"{value:,}"
                state = tr("ฐานใหม่", "New baseline") + f" · Total Meter {total} · "
                state += (tr("ยืนยันแล้ว", "Confirmed") if item.device.slot in self.confirmed_slots
                          else tr("ยังไม่ยืนยัน", "Not confirmed"))
            lines.append(f"{prefix} · {state}")
        return lines

    def retranslate(self) -> None:
        """Refresh UI captions without translating printer or counter data."""
        self.chooser_label.setText(tr("เลือกเครื่องพิมพ์", "Select printer"))
        self.device_combo.setAccessibleName(self.chooser_label.text())
        self.views.setAccessibleName(tr("มุมมองมิเตอร์เริ่มต้น", "Initial meter views"))
        self.raw_table.setHorizontalHeaderLabels((
            tr("ประเภท", "Category"), tr("ชื่อจาก Meter", "Meter name"),
            "Source path", tr("ค่า", "Value"),
        ))
        self.parser_table.setHorizontalHeaderLabels((
            "Canonical field", tr("ค่า", "Value"),
            tr("ที่มา · คลิกเพื่อดูค่าจาก Meter", "Source · select to view Meter value"),
        ))
        for index, table, title in (
            (0, self.raw_table, tr("ค่าจาก Meter", "Meter values")),
            (1, self.parser_table, tr("ค่าหลัง Parser", "Parser values")),
        ):
            self.views.setTabText(index, title)
            table.setAccessibleName(title)
        self.view_hint.setText(tr(
            "Meter แสดงค่า Counter ที่อ่านได้พร้อม Source path · Parser แสดงชื่อฟิลด์ที่โปรแกรมใช้",
            "Meter shows extracted counter values and source paths; Parser shows the fields used by the app.",
        ))
        self._populate_devices(self.device_combo.currentData())

    def _populate_devices(self, selected_slot: int | None) -> None:
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for item in self.devices:
            state = (tr("ฐานใหม่", "New baseline") if item.requires_confirmation
                     else tr("ใช้ฐานเดิม", "Existing baseline"))
            self.device_combo.addItem(f"Slot {item.device.slot + 1} · {item.device.name} · {state}",
                                      item.device.slot)
        index = self.device_combo.findData(selected_slot)
        if index < 0:
            index = next((row for row, item in enumerate(self.devices)
                          if item.requires_confirmation), 0)
        self.device_combo.setCurrentIndex(index if self.devices else -1)
        self.device_combo.setEnabled(bool(self.devices))
        self.device_combo.blockSignals(False)
        self._select_device(self.device_combo.currentIndex())

    def _table(self, columns: int) -> QTableWidget:
        result = QTableWidget(0, columns)
        result.setObjectName("setup_device_table")
        result.setStyleSheet(setup_styles.DEVICE_TABLE)
        result.verticalHeader().hide()
        result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        result.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        result.setWordWrap(True)
        result.setTextElideMode(Qt.TextElideMode.ElideNone)
        result.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result.setMinimumHeight(130)
        result.horizontalHeader().setMinimumSectionSize(65)
        result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        result.horizontalHeader().sectionResized.connect(result.resizeRowsToContents)
        return result

    def _select_device(self, index: int) -> None:
        self._source_rows.clear()
        self.raw_table.setRowCount(0)
        self.parser_table.setRowCount(0)
        self.confirmation.blockSignals(True)
        self.confirmation.setChecked(False)
        self.confirmation.setVisible(False)
        self.confirmation.setEnabled(False)
        self.confirmation.blockSignals(False)
        if not 0 <= index < len(self.devices):
            self.identity_label.clear()
            self.baseline_label.clear()
            self.empty_label.setText(tr("ยังไม่ได้เลือกเครื่องพิมพ์", "No printers selected"))
            self.empty_label.show()
            self._update_next_hint()
            return
        item = self.devices[index]
        device = item.device
        baseline = item.raw_reading or item.reading
        total = _total(baseline)
        total_text = "—" if total is None else f"{total:,}"
        collected = baseline.collected_at if baseline else "—"
        self.identity_label.setText(
            f"IP {device.host} · Serial {device.serial or '—'} · Total Meter {total_text} · "
            + tr("เวลาอ่าน", "Read at") + f" {collected}"
        )
        self.baseline_label.setText(tr(
            "ฐานใหม่ · ใช้ค่าที่อ่านได้เป็นจุดเริ่มนับ ยอดใช้งานเริ่มต้น 0 หน้า · Scan แยกจาก Total Meter",
            "New baseline: usage starts at 0 pages from this reading. Scan is separate from Total Meter.",
        ) if item.requires_confirmation else tr(
            "ใช้ฐานเดิม · แสดงค่าเพื่อดูข้อมูล ไม่เปลี่ยนฐานมิเตอร์หรือประวัติของเครื่องนี้",
            "Existing baseline: values are for review only; this printer's baseline and history are unchanged.",
        ))
        error = item.error
        if item.reading is None:
            error = error or tr("ยังไม่มีผลอ่าน Meter · ย้อนกลับไปตรวจสอบเครื่องพิมพ์",
                                "No Meter reading yet. Go back and verify the printer.")
        elif (item.reading.host.strip().casefold() != device.host.strip().casefold()
              or baseline.host.strip().casefold() != device.host.strip().casefold()):
            error = error or tr("ผลอ่านไม่ตรงกับ IP เครื่องที่เลือก · ย้อนกลับไปตรวจสอบเครื่องพิมพ์ใหม่",
                                "Reading host does not match this printer. Go back and verify it again.")
        elif total is None:
            error = error or tr("ผลอ่านไม่มี Total Meter ที่ใช้ตั้งฐานได้ · ย้อนกลับไปตรวจสอบเครื่องพิมพ์ใหม่",
                                "The reading has no valid Total Meter for a baseline. Go back and verify it again.")
        warnings = "\n".join(item.reading.warnings) if item.reading else ""
        self.empty_label.setText("\n".join(value for value in (error, warnings) if value))
        self.empty_label.setVisible(bool(error or warnings))
        self.confirmation.setText(tr("ยืนยันมิเตอร์เริ่มต้นของ Slot", "Confirm initial meter for Slot")
                                  + f" {device.slot + 1}")
        self.confirmation.setAccessibleName(self.confirmation.text())
        self.confirmation.blockSignals(True)
        self.confirmation.setChecked(device.slot in self._confirmed)
        self.confirmation.setEnabled(item.requires_confirmation and self._can_confirm(item))
        self.confirmation.setVisible(item.requires_confirmation)
        self.confirmation.blockSignals(False)

        raw_counters = _device_counters(item.raw_reading or item.reading)
        parsed_counters = _device_counters(item.reading)
        self.raw_table.setRowCount(len(raw_counters))
        self.parser_table.setRowCount(len(parsed_counters))
        sources: dict[str, list[int]] = {}
        for row, counter in enumerate(raw_counters):
            self._fill_row(self.raw_table, row, (counter.category, counter.label, counter.source_path, counter.count))
            sources.setdefault(_source_key(counter), []).append(row)
        for row, counter in enumerate(parsed_counters):
            self._fill_row(self.parser_table, row, (counter.canonical_field, counter.count, counter.source_path))
            candidates = sources.get(_source_key(counter), []) if counter.source_path else []
            if len(candidates) == 1:
                self._source_rows[row] = candidates[0]
                source_item = self.parser_table.item(row, 2)
                source_item.setForeground(QColor(C_ACCENT))
                font = source_item.font()
                font.setUnderline(True)
                source_item.setFont(font)
        self._update_next_hint()
        QTimer.singleShot(0, self._fit_rows)

    @staticmethod
    def _fill_row(table: QTableWidget, row: int, values: tuple) -> None:
        for column, value in enumerate(values):
            numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
            display = f"{value:,}" if numeric else str(value)
            # Allow long source paths and keys to wrap without losing characters.
            if not numeric:
                display = display.replace(".", ".\u200b").replace("[", "\u200b[")
            item = QTableWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setToolTip(str(value))
            if numeric:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, column, item)

    def _set_confirmed(self, confirmed: bool) -> None:
        index = self.device_combo.currentIndex()
        if not 0 <= index < len(self.devices):
            return
        item = self.devices[index]
        if confirmed and item.requires_confirmation and self._can_confirm(item):
            self._confirmed.add(item.device.slot)
        else:
            self._confirmed.discard(item.device.slot)
        self._update_next_hint()
        self.readiness_changed.emit(self.ready)

    def _update_next_hint(self) -> None:
        required = sum(item.requires_confirmation for item in self.devices)
        if not required:
            self.next_hint.setText(tr("เครื่องเดิมใช้ฐานเดิมทั้งหมด · ไม่ต้องยืนยันฐานใหม่",
                                      "All printers retain their existing baselines. No new confirmation is needed."))
        elif self.ready:
            self.next_hint.setText(tr("ยืนยันครบแล้ว · กดถัดไปเพื่อตั้งราคา · ยังไม่มีการบันทึกข้อมูล",
                                      "All baselines confirmed. Continue to pricing; nothing has been saved yet."))
        else:
            self.next_hint.setText(tr("ยืนยันฐานใหม่แล้ว", "New baselines confirmed")
                                   + f" {len(self.confirmed_slots)}/{required} · "
                                   + tr("เลือกตรวจและยืนยันทุกเครื่องที่ใช้ฐานใหม่", "Review and confirm each new baseline"))

    def _show_source(self, row: int, column: int) -> None:
        if column != 2 or row not in self._source_rows:
            return
        source_row = self._source_rows[row]
        self.views.setCurrentIndex(0)
        self.raw_table.selectRow(source_row)
        self.raw_table.scrollToItem(self.raw_table.item(source_row, 1))
        self.raw_table.setFocus()

    def _fit_rows(self, *_) -> None:
        for table, fractions in ((self.raw_table, (.14, .23, .51, .12)),
                                 (self.parser_table, (.43, .12, .45))):
            table.blockSignals(True)
            header = table.horizontalHeader()
            header.blockSignals(True)
            width = max(560, table.viewport().width() - 2)
            for column, fraction in enumerate(fractions):
                table.setColumnWidth(column, int(width * fraction))
            header.blockSignals(False)
            table.resizeRowsToContents()
            table.blockSignals(False)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_rows)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_rows)
