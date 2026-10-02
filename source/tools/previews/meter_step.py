"""In-memory baseline review step for the setup design preview.

The fixture shows the relationship between a Meter label and a canonical field.
It does not call the production parser, read a printer, or persist a baseline.
"""

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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

from ui.styles.setup import CHOICE, DEVICE_TABLE


@dataclass(frozen=True)
class CounterFixture:
    category: str
    label: str
    source_path: str
    canonical_field: str
    value: int


@dataclass(frozen=True)
class DeviceFixture:
    slot: int
    name: str
    host: str
    serial: str
    total: int
    counters: tuple[CounterFixture, ...]


def _device(slot, name, total, counts, scan):
    """Use connector canonical names, with clearly synthetic source records."""
    records = []

    def add(category, group, counter_type, field, value):
        records.append(CounterFixture(
            category,
            f"{group}: {counter_type}",
            f"MFP.UserCounterInfo.{group}CounterList.Counter[Type={counter_type}]",
            field,
            value,
        ))

    add("Total Meter", "Total", "Total", "counter.total.total", total)
    for offset, operation in ((0, "Print"), (4, "Copy")):
        color_a4, color_a3, bw_a4, bw_a3 = counts[offset:offset + 4]
        prefix = f"counter.{operation.lower()}"
        add(operation, operation, "Total", f"{prefix}.total",
            color_a4 + color_a3 + bw_a4 + bw_a3)
        for category, counter_type, field, value in (
            (f"{operation} Color", "FullColorTotal", "full_color_total", color_a4 + color_a3),
            (f"{operation} Color", "FullColorLarge", "full_color_large", color_a3),
            (f"{operation} B&W", "BWTotal", "bw_total", bw_a4 + bw_a3),
            (f"{operation} B&W", "BWLarge", "bw_large", bw_a3),
        ):
            add(category, operation, counter_type, f"{prefix}.{field}", value)
    add("Scan", "ScanFax", "DocumentReadTotal", "counter.scan_fax.document_read_total", scan)
    return DeviceFixture(slot, name, f"192.0.2.{31 + slot}", f"DEMO-SLOT-{slot + 1:03d}",
                         total, tuple(records))


DEVICES = (
    _device(0, "KM bizhub C450i Test", 272_868,
            (140_000, 10_000, 80_000, 1_000, 20_000, 1_000, 20_000, 868), 19_230),
    _device(1, "KM bizhub C750i 2222", 449_875,
            (210_000, 10_000, 170_000, 9_875, 30_000, 2_000, 15_000, 3_000), 23_100),
    _device(2, "KM bizhub C450i DMS", 2_475,
            (1_400, 100, 600, 0, 250, 25, 100, 0), 346),
)


def _label(text, name=""):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    widget.setObjectName(name)
    return widget


class MeterStep(QWidget):
    """Review all three fixtures; only the new Slot 3 requires confirmation."""

    readiness_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("meter_step_preview")
        self.setStyleSheet(Path(__file__).with_suffix(".qss").read_text(encoding="utf-8"))
        self.devices = DEVICES
        self._confirmed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        layout.addWidget(_label(
            "ข้อมูลจำลอง · ทั้งสองมุมมองใช้ค่าตัวอย่างชุดเดียวกัน ไม่ได้อ่านเครื่องหรือรัน Parser จริง",
            "meter_preview_notice",
        ))

        chooser = QHBoxLayout()
        chooser.addWidget(_label("เลือกเครื่องพิมพ์"))
        self.device_combo = QComboBox()
        self.device_combo.setAccessibleName("เลือกเครื่องพิมพ์")
        self.device_combo.setStyleSheet(CHOICE)
        self.device_combo.setMinimumHeight(38)
        for device in self.devices:
            state = "ฐานใหม่" if device.slot == 2 else "ใช้ฐานเดิม"
            self.device_combo.addItem(f"Slot {device.slot + 1} · {device.name} · {state}")
        chooser.addWidget(self.device_combo, 1)
        layout.addLayout(chooser)

        self.identity_label = _label("", "meter_identity")
        layout.addWidget(self.identity_label)
        self.baseline_label = _label("", "meter_baseline_status")
        layout.addWidget(self.baseline_label)

        self.views = QTabWidget()
        self.views.setAccessibleName("มุมมองมิเตอร์เริ่มต้น")
        self.raw_table = self._table(
            ("ประเภท", "ชื่อจาก Meter", "Source path (ตัวอย่าง)", "ค่า"),
            "ค่าจาก Meter",
        )
        self.parser_table = self._table(
            ("Canonical field", "ค่า", "ที่มา · คลิกเพื่อดูค่าจาก Meter"),
            "ค่าหลัง Parser",
        )
        self.views.addTab(self.raw_table, "ค่าจาก Meter")
        self.views.addTab(self.parser_table, "ค่าหลัง Parser")
        self.parser_table.cellClicked.connect(self._show_source)
        self.parser_table.cellActivated.connect(self._show_source)
        self.views.currentChanged.connect(self._fit_rows)
        layout.addWidget(self.views, 1)

        self.view_hint = _label(
            "ชื่อและ Source path เป็นตัวอย่างตามโครงสร้าง Counter · Scan แยกจาก Total Meter",
            "meter_hint",
        )
        layout.addWidget(self.view_hint)
        self.confirmation = QCheckBox("ยืนยันมิเตอร์เริ่มต้นของ Slot 3")
        self.confirmation.setAccessibleName("ยืนยันมิเตอร์เริ่มต้นของ Slot 3")
        self.confirmation.toggled.connect(self._set_confirmed)
        layout.addWidget(self.confirmation)
        self.next_hint = _label(
            "ยืนยัน Slot 3 แล้วกดถัดไปเพื่อตั้งราคาใน Wizard หลัก · ยังไม่มีการบันทึกข้อมูล",
            "meter_hint",
        )
        layout.addWidget(self.next_hint)

        self.device_combo.currentIndexChanged.connect(self._select_device)
        self.device_combo.setCurrentIndex(2)
        self._select_device(2)

    @property
    def ready(self):
        return self._confirmed

    def summary_lines(self):
        return [
            "Slot 1 · ใช้ฐานเดิม — ไม่มีการเปลี่ยนฐาน",
            "Slot 2 · ใช้ฐานเดิม — ไม่มีการเปลี่ยนฐาน",
            "Slot 3 · ฐานใหม่จากข้อมูลจำลอง · Total Meter 2,475 หน้า · "
            + ("ยืนยันแล้ว" if self.ready else "ยังไม่ยืนยัน"),
            "ยอดใช้งานเริ่มต้น 0 หน้า · Scan ไม่รวมใน Total Meter",
        ]

    def reset_readings(self):
        self.confirmation.setChecked(False)

    def _table(self, headings, name):
        result = QTableWidget(0, len(headings))
        result.setObjectName("setup_device_table")
        result.setAccessibleName(name)
        result.setStyleSheet(DEVICE_TABLE)
        result.setHorizontalHeaderLabels(headings)
        result.verticalHeader().hide()
        result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        result.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        result.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        result.setWordWrap(True)
        result.setTextElideMode(Qt.TextElideMode.ElideNone)
        result.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        result.setMinimumHeight(130)
        result.horizontalHeader().setMinimumSectionSize(70)
        result.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        result.horizontalHeader().setStretchLastSection(False)
        return result

    def _select_device(self, index):
        device = self.devices[index]
        self.identity_label.setText(
            f"IP ตัวอย่าง {device.host} · Serial {device.serial} · "
            f"Total Meter {device.total:,} หน้า · เวลาอ่านตัวอย่าง 25/09/2026 08:38:24"
        )
        self.baseline_label.setText(
            "ฐานใหม่ · ใช้ค่าชุดนี้เป็นจุดเริ่มนับ ยอดใช้งานเริ่มต้น 0 หน้า"
            if device.slot == 2 else
            "ใช้ฐานเดิม · ดูค่าตัวอย่างได้ แต่ไม่สร้างฐานใหม่หรือเปลี่ยนฐานของเครื่องนี้"
        )
        self.confirmation.setVisible(device.slot == 2)
        self.next_hint.setText(
            "ยืนยัน Slot 3 แล้วกดถัดไปเพื่อตั้งราคาใน Wizard หลัก · ยังไม่มีการบันทึกข้อมูล"
            if not self.ready else
            "ยืนยัน Slot 3 แล้ว · กดถัดไปเพื่อตั้งราคาใน Wizard หลัก · ยังไม่มีการบันทึกข้อมูล"
        )
        self.raw_table.setRowCount(len(device.counters))
        self.parser_table.setRowCount(len(device.counters))
        for row, counter in enumerate(device.counters):
            raw_values = (counter.category, counter.label, counter.source_path, counter.value)
            parsed_values = (counter.canonical_field, counter.value, counter.label)
            for table, values in ((self.raw_table, raw_values), (self.parser_table, parsed_values)):
                for column, value in enumerate(values):
                    display = f"{value:,}" if isinstance(value, int) else value
                    if (table is self.raw_table and column == 2) or (table is self.parser_table and column == 0):
                        display = display.replace(".", ".\u200b").replace("[", "\u200b[")
                    item = QTableWidgetItem(display)
                    item.setToolTip(str(value))
                    if isinstance(value, int):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    table.setItem(row, column, item)
            source = self.parser_table.item(row, 2)
            source.setForeground(QColor("#0065A3"))
            font = source.font()
            font.setUnderline(True)
            source.setFont(font)
            source.setToolTip(f"เปิดค่าจาก Meter: {counter.source_path}")
        QTimer.singleShot(0, self._fit_rows)

    def _set_confirmed(self, confirmed):
        if confirmed == self._confirmed:
            return
        self._confirmed = confirmed
        self.next_hint.setText(
            "ยืนยัน Slot 3 แล้ว · กดถัดไปเพื่อตั้งราคาใน Wizard หลัก · ยังไม่มีการบันทึกข้อมูล"
            if confirmed else
            "ยืนยัน Slot 3 แล้วกดถัดไปเพื่อตั้งราคาใน Wizard หลัก · ยังไม่มีการบันทึกข้อมูล"
        )
        self.readiness_changed.emit(confirmed)

    def _show_source(self, row, column):
        if column != 2:
            return
        self.views.setCurrentIndex(0)
        self.raw_table.selectRow(row)
        self.raw_table.scrollToItem(self.raw_table.item(row, 1))
        self.raw_table.setFocus()

    def _fit_rows(self, *_):
        for table, fractions in ((self.raw_table, (.13, .24, .52, .11)),
                                 (self.parser_table, (.46, .11, .43))):
            width = max(600, table.viewport().width() - 2)
            for column, fraction in enumerate(fractions):
                table.setColumnWidth(column, int(width * fraction))
            table.resizeRowsToContents()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_rows)

    def showEvent(self, event):
        super().showEvent(event)
        # Stacked pages acquire their viewport size after becoming visible.
        QTimer.singleShot(0, self._fit_rows)
