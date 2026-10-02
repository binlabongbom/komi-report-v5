"""Separate V5.2 window for inspecting and correcting counter mappings."""

from __future__ import annotations
from ui.styles import surfaces as surfaces_styles
from ui.styles import buttons as buttons_styles
from ui.styles import text as text_styles
from services.support_diagnostics import with_diagnostic

from collections.abc import Callable

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from services.device_config import DeviceConfigRepository
from services.parser_mapping import (
    DEFAULT_TARGET,
    TARGET_OPTIONS,
    ParserMappingRepository,
    raw_counter_key,
)
from services.raw_counter_history import load_raw_counter_history


def _button(text: str, *, primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumHeight(38)
    button.setStyleSheet(
        buttons_styles.parser_action(primary=primary)
    )
    return button


class ParserMappingInspector(QDialog):
    """Show Raw → Mapping → normalized DB preview for one configured slot."""

    def __init__(
        self,
        parent=None,
        *,
        read_requested: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ตรวจสอบ Parser Mapping · KOMI Report V5.2")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1120, 700)
        self.setMinimumSize(900, 560)
        self._read_requested = read_requested
        self._repository = ParserMappingRepository()
        self._devices = ()
        self._rows: list[tuple[object, QComboBox]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        title = QLabel("ตรวจสอบ Parser Mapping")
        title.setStyleSheet(text_styles.label('#102A43', font_size='24px', font_weight='800'))
        layout.addWidget(title)
        note = QLabel(
            "เปรียบเทียบชื่อ Counter ที่เครื่องส่งจริงกับช่องที่จะบันทึกใน Database · "
            "การแก้ไขมีผลกับการอ่านครั้งถัดไปเท่านั้น และไม่แก้ Raw Data, ประวัติ หรือ Billing เดิม"
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            surfaces_styles.INFO_BOX
        )
        layout.addWidget(note)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("เลือกเครื่อง"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(420)
        self.device_combo.currentIndexChanged.connect(self.refresh)
        toolbar.addWidget(self.device_combo)
        self.device_detail = QLabel()
        self.device_detail.setStyleSheet(text_styles.label('#52677D'))
        toolbar.addWidget(self.device_detail, 1)
        self.read_button = _button("อ่าน / ทดสอบอีกครั้ง")
        self.read_button.clicked.connect(self._read_again)
        toolbar.addWidget(self.read_button)
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ("Raw Data จากเครื่อง", "ค่าล่าสุด", "Mapping", "ตัวอย่างที่จะเข้า Database")
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(46)
        layout.addWidget(self.table, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet(text_styles.label('#52677D'))
        layout.addWidget(self.status)

        actions = QHBoxLayout()
        reset = _button("คืนค่า Mapping เริ่มต้น")
        reset.clicked.connect(self._reset_defaults)
        actions.addWidget(reset)
        actions.addStretch()
        cancel = _button("ยกเลิก")
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        save = _button("บันทึกและทดสอบ", primary=True)
        save.clicked.connect(self._save_and_test)
        actions.addWidget(save)
        layout.addLayout(actions)

        self._load_devices()

    def _load_devices(self) -> None:
        self._devices = tuple(DeviceConfigRepository().list())
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self._devices:
            self.device_combo.addItem(
                f"Slot {int(device.slot) + 1} · {device.name} · {device.host}",
                int(device.slot),
            )
        self.device_combo.blockSignals(False)
        self.refresh()

    def _current_device(self):
        slot = self.device_combo.currentData()
        return next((item for item in self._devices if int(item.slot) == slot), None)

    @staticmethod
    def _target_label(value: str) -> str:
        return next((label for target, label in TARGET_OPTIONS if target == value), value)

    def refresh(self) -> None:
        device = self._current_device()
        self.table.setRowCount(0)
        self._rows.clear()
        if device is None:
            self.device_detail.setText("ยังไม่มีเครื่องพิมพ์ที่ตั้งค่าไว้")
            self.status.setText("เพิ่มเครื่องพิมพ์จาก Setup Wizard ก่อนเปิดเครื่องมือนี้")
            return
        serial = str(device.serial or "").strip()
        self.device_detail.setText(
            f"Model: {device.model or '—'} · Serial: {serial or '—'}"
        )
        records = [
            item
            for item in load_raw_counter_history([int(device.slot)])
            if not item.subject_type
            and (not serial or not item.device_serial_snapshot or item.device_serial_snapshot == serial)
        ]
        if records:
            latest_day = max(item.record_date for item in records)
            records = [item for item in records if item.record_date == latest_day]
        overrides = self._repository.load(serial)
        records.sort(key=lambda item: (item.label.casefold(), item.canonical_field, item.source_path))
        for row, record in enumerate(records):
            self.table.insertRow(row)
            raw_text = str(record.label or record.canonical_field or "Unknown")
            if record.source_path:
                raw_text += f"\n{record.source_path}"
            raw_item = QTableWidgetItem(raw_text)
            raw_item.setToolTip(
                f"Canonical เดิม: {record.canonical_field}\nSource: {record.source_path or '—'}"
            )
            self.table.setItem(row, 0, raw_item)
            value = QTableWidgetItem(f"{record.closing_value:,.0f}" if record.closing_value is not None else '—')
            value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 1, value)
            combo = QComboBox()
            for target, label in TARGET_OPTIONS:
                combo.addItem(label, target)
            key = raw_counter_key(record.canonical_field, record.source_path)
            selected = overrides.get(key)
            target = selected.target_field if selected else DEFAULT_TARGET
            index = combo.findData(target)
            combo.setCurrentIndex(max(0, index))
            combo.currentIndexChanged.connect(
                lambda _index, row_no=row: self._refresh_preview(row_no)
            )
            self.table.setCellWidget(row, 2, combo)
            self.table.setItem(row, 3, QTableWidgetItem())
            self._rows.append((record, combo))
            self._refresh_preview(row)
        latest = records[0].last_success if records else ""
        self.status.setText(
            f"พบ Raw Counter {len(records)} รายการ"
            + (f" · อ่านล่าสุด {latest}" if latest else " · ยังไม่มีข้อมูล กรุณากดอ่าน / ทดสอบอีกครั้ง")
        )

    def _refresh_preview(self, row: int) -> None:
        if row >= len(self._rows):
            return
        record, combo = self._rows[row]
        target = str(combo.currentData() or DEFAULT_TARGET)
        if target == DEFAULT_TARGET:
            preview = f"เดิม: {record.canonical_field or 'ไม่พบชื่อช่อง'}"
        elif target == "none":
            preview = "ไม่บันทึกในข้อมูลแบบ Mapping"
        elif target == "legacy_only":
            preview = "เก็บเฉพาะ Legacy Raw Data"
        else:
            preview = self._target_label(target)
        self.table.item(row, 3).setText(preview)

    def _reset_defaults(self) -> None:
        for _record, combo in self._rows:
            combo.setCurrentIndex(combo.findData(DEFAULT_TARGET))
        self.status.setText("คืนค่าบนหน้าจอแล้ว · กดบันทึกและทดสอบเพื่อยืนยัน")

    def _read_again(self) -> None:
        device = self._current_device()
        if device is None or self._read_requested is None:
            return
        self.status.setText("กำลังขออ่านข้อมูลใหม่… หน้าต่างนี้จะรีเฟรชอัตโนมัติ")
        self._read_requested(int(device.slot))
        QTimer.singleShot(1800, self.refresh)

    def _save_and_test(self) -> None:
        device = self._current_device()
        if device is None:
            return
        mappings = {
            (str(record.canonical_field), str(record.source_path)): str(combo.currentData())
            for record, combo in self._rows
        }
        try:
            changed = self._repository.replace_all(str(device.serial or ""), mappings)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "บันทึก Mapping ไม่สำเร็จ", with_diagnostic(str(error), error, "บันทึก Mapping ไม่สำเร็จ"))
            return
        self.status.setText(
            f"บันทึกแล้ว {changed} การเปลี่ยนแปลง · มีผลกับข้อมูลที่อ่านใหม่หลังจากนี้"
        )
        if self._read_requested is not None:
            self._read_requested(int(device.slot))
            QTimer.singleShot(1800, self.refresh)
