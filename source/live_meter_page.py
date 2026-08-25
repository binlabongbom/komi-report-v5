from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from config import C_GREEN, C_RED, C_TEXT2, F_2XL, F_MD, F_SM, SLOT_NAMES
from komi_snmp_profiler.credential_store import AdminCredential
from komi_snmp_profiler.meter import MeterReader
from services.device_config import DatabaseCredentialStore, DeviceConfigRepository
from services.live_meter_service import LiveMeterPreview, LiveMeterService
from widgets import btn, fnt, make_table, tbl_item


class LiveMeterReadWorker(QObject):
    success = pyqtSignal(object)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, service: LiveMeterService, host: str, machine_name: str, model: str = "") -> None:
        super().__init__()
        self.service = service
        self.host = host
        self.machine_name = machine_name
        self.model = model

    @pyqtSlot()
    def run(self) -> None:
        try:
            preview = self.service.read(
                self.host,
                machine_name=self.machine_name or None,
                model=self.model,
            )
            self.success.emit(preview)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class PageLiveMeter(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.device_repository = DeviceConfigRepository()
        self.credential_store = DatabaseCredentialStore(self.device_repository)
        self.service = LiveMeterService(MeterReader(self.credential_store))
        self.preview: LiveMeterPreview | None = None
        self._thread: QThread | None = None
        self._worker: LiveMeterReadWorker | None = None
        self._build()
        devices = self.device_repository.list(enabled_only=True)
        if devices:
            self.host_input.setText(devices[0].host)
            self.name_input.setText(devices[0].name)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        title = QLabel("Read Meter")
        title.setFont(fnt(F_2XL, True))
        root.addWidget(title)

        subtitle = QLabel("อ่าน Counter จาก bizhub แบบ read-only แล้วบันทึกเข้า Report workflow เดียวกับไฟล์ Import")
        subtitle.setFont(fnt(F_MD))
        subtitle.setStyleSheet(f"color:{C_TEXT2};")
        root.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("card")
        form = QGridLayout(card)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setColumnMinimumWidth(0, 92)
        form.setColumnMinimumWidth(2, 92)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        form.addWidget(QLabel("IP / Host"), 0, 0)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("เช่น 192.168.1.50")
        form.addWidget(self.host_input, 0, 1)

        form.addWidget(QLabel("ชื่อเครื่อง"), 0, 2)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("ไม่กรอกจะใช้ bizhub @ IP")
        form.addWidget(self.name_input, 0, 3)

        form.addWidget(QLabel("Admin password"), 1, 0)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("ไม่กรอก = อ่าน public counter")
        form.addWidget(self.password_input, 1, 1)

        self.credential_btn = btn("บันทึกรหัสของเครื่องนี้", "outline")
        self.credential_btn.clicked.connect(self._set_credential)
        form.addWidget(self.credential_btn, 1, 2)

        self.auth_label = QLabel("Public read-only")
        self.auth_label.setFont(fnt(F_SM, True))
        self.auth_label.setStyleSheet(f"color:{C_TEXT2};")
        form.addWidget(self.auth_label, 1, 3)

        actions = QHBoxLayout()
        self.read_btn = btn("อ่าน Meter", "primary")
        self.read_btn.setMinimumWidth(120)
        self.read_btn.clicked.connect(self._read)
        actions.addWidget(self.read_btn)

        actions.addSpacing(18)
        slot_label = QLabel("บันทึกลงช่อง")
        slot_label.setMinimumWidth(80)
        actions.addWidget(slot_label)
        self.slot_combo = QComboBox()
        self.slot_combo.setMinimumWidth(120)
        self.slot_combo.addItems(SLOT_NAMES)
        actions.addWidget(self.slot_combo)

        self.save_btn = btn("บันทึกเข้า Report", "success")
        self.save_btn.setMinimumWidth(155)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(self.save_btn)
        actions.addStretch()
        form.addLayout(actions, 2, 0, 1, 4)

        self.status_label = QLabel("พร้อมอ่านข้อมูล")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color:{C_TEXT2};")
        form.addWidget(self.status_label, 3, 0, 1, 4)
        root.addWidget(card)

        self.summary_label = QLabel("ยังไม่มี Meter preview")
        self.summary_label.setFont(fnt(F_MD, True))
        root.addWidget(self.summary_label)

        self.table = make_table(
            ["Counter", "Value", "Category", "Source", "Confidence"],
            stretch_cols=[0, 3],
            fixed_cols={1: 110, 2: 150, 4: 110},
        )
        root.addWidget(self.table, 1)

        note = QLabel("Credential ถูกจำไว้ในฐานข้อมูล local ตาม Device Settings และไม่ถูกใส่ใน log หรือ export")
        note.setFont(fnt(F_SM))
        note.setStyleSheet(f"color:{C_TEXT2};")
        root.addWidget(note)

    def _set_credential(self) -> None:
        host = self.host_input.text().strip()
        password = self.password_input.text()
        if not host:
            QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณาระบุ IP / Host ก่อน")
            return
        try:
            if password:
                self.credential_store.save(host, AdminCredential(password=password))
                self.auth_label.setText("บันทึก Administrator credential แล้ว")
                self.auth_label.setStyleSheet(f"color:{C_GREEN};")
            else:
                self.credential_store.delete(host)
                self.auth_label.setText("Public read-only")
                self.auth_label.setStyleSheet(f"color:{C_TEXT2};")
            self.password_input.clear()
        except Exception as exc:
            QMessageBox.warning(self, "ตั้งค่า credential ไม่สำเร็จ", str(exc))

    def _read(self) -> None:
        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "ข้อมูลไม่ครบ", "กรุณาระบุ IP / Host")
            return
        if self._thread is not None:
            return

        self.preview = None
        self.save_btn.setEnabled(False)
        self.read_btn.setEnabled(False)
        self.status_label.setText("กำลังอ่าน Meter แบบ read-only...")

        thread = QThread(self)
        configured = next(
            (device for device in self.device_repository.list(enabled_only=False) if device.host == host),
            None,
        )
        worker = LiveMeterReadWorker(
            self.service,
            host,
            self.name_input.text().strip(),
            configured.model if configured is not None else "",
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.success.connect(self._show_preview)
        worker.error.connect(self._show_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._read_finished)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _show_preview(self, preview: LiveMeterPreview) -> None:
        self.preview = preview
        parsed = preview.parsed
        self.summary_label.setText(
            f"{parsed['machine_name']} · Total {parsed['total_counter']:,} · "
            f"A4 Color {parsed['paper_color']['a4_color']:,} · A4 BW {parsed['paper_color']['a4_bw']:,} · "
            f"A3 Color {parsed['paper_color']['a3_color']:,} · A3 BW {parsed['paper_color']['a3_bw']:,}"
        )
        self.table.setRowCount(len(preview.reading.counters))
        for row, item in enumerate(preview.reading.counters):
            values = (
                item.canonical_field,
                f"{item.count:,}",
                item.category,
                item.source_path,
                item.confidence.value,
            )
            for column, value in enumerate(values):
                self.table.setItem(row, column, tbl_item(value))
        self.status_label.setText(
            f"อ่านสำเร็จจาก {preview.reading.source} · auth={preview.reading.auth_state.value} · "
            f"พบ {len(preview.reading.counters)} counters"
        )
        self.status_label.setStyleSheet(f"color:{C_GREEN};")
        self.save_btn.setEnabled(True)

    def _show_error(self, message: str) -> None:
        self.status_label.setText(f"อ่าน Meter ไม่สำเร็จ: {message}")
        self.status_label.setStyleSheet(f"color:{C_RED};")

    def _read_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.read_btn.setEnabled(True)

    def _save(self) -> None:
        if self.preview is None:
            return
        try:
            saved = self.service.save(self.slot_combo.currentIndex(), self.preview)
        except Exception as exc:
            QMessageBox.warning(self, "บันทึกไม่สำเร็จ", str(exc))
            return
        self.save_btn.setEnabled(False)
        self.status_label.setText(f"บันทึก Meter #{saved.reading_id} เข้า {SLOT_NAMES[saved.slot]} แล้ว")
        self.status_label.setStyleSheet(f"color:{C_GREEN};")
        self.changed.emit()
