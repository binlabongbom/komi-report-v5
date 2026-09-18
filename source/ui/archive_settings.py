"""Bounded background archive maintenance with metadata-only initial display."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import logging

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from i18n import tr
from services.web_observation_archive import WebObservationArchive, run_archive_batches
from ui.counter_review import plain


class ArchiveSettingsPanel(QWidget):
    def __init__(self, parent=None, *, archive=None, today=None):
        super().__init__(parent)
        self.archive = archive or WebObservationArchive()
        self.today = today
        self.future = None
        self.cancelled = Event()
        self.pool = None
        layout = QVBoxLayout(self)
        layout.addWidget(plain(tr("จัดเก็บประวัติ Web รายรอบ", "Archive individual Web readings")))
        layout.addWidget(plain(tr(
            "ระบบจัดเก็บผลอ่านเกิน 12 เดือนอัตโนมัติเมื่อว่าง หรือกดจัดเก็บได้ที่นี่ ข้อมูลบีบอัดแยกตามปีและเปิดเมื่อเรียกประวัติ สำรองโฟลเดอร์ archives ควบคู่กับฐานข้อมูล",
            "Readings older than 12 months are archived automatically when idle, or on request here. Compressed yearly files load on demand. Keep the archives folder with database backups.")))
        self.status = plain("")
        layout.addWidget(self.status)
        self.message = plain("")
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.start_button = QPushButton(tr("จัดเก็บข้อมูลเก่า", "Archive older readings"))
        self.cancel_button = QPushButton(tr("หยุดหลังจบชุดนี้", "Stop after this batch"))
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self.cancelled.set)
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._collect)
        self.refresh()

    def refresh(self):
        try:
            state = self.archive.stats(today=self.today)
        except Exception:
            logging.getLogger(__name__).exception("Cannot load archive metadata")
            self.status.setText(tr("อ่านรายการ Archive ไม่สำเร็จ กรุณาตรวจฐานข้อมูล", "Archive metadata is unavailable. Check the database."))
            self.start_button.setEnabled(False)
            return
        self.status.setText(tr(
            f"รอจัดเก็บ {state['eligible']:,} รอบ · จัดเก็บแล้ว {state['archived']:,} รอบ ใน {state['files']:,} ไฟล์",
            f"Pending: {state['eligible']:,} readings · Archived: {state['archived']:,} readings in {state['files']:,} files"))
        self.start_button.setEnabled(bool(state["eligible"]) and self.future is None)

    def start(self):
        if self.future is not None:
            return
        if self.pool is None:
            self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-archive")
            pool, cancelled = self.pool, self.cancelled
            self.destroyed.connect(lambda: (cancelled.set(), pool.shutdown(wait=False, cancel_futures=True)))
        self.cancelled.clear()
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.message.setText(tr("กำลังตรวจสอบและจัดเก็บข้อมูล…", "Verifying and archiving readings…"))
        self.future = self.pool.submit(run_archive_batches, self.archive, self.cancelled, today=self.today)
        self.timer.start()

    def _collect(self):
        if self.future is None or not self.future.done():
            return
        self.timer.stop()
        try:
            result = self.future.result()
        except Exception:
            logging.getLogger(__name__).exception("Archive maintenance failed")
            self.message.setText(tr("จัดเก็บไม่สำเร็จ ข้อมูลชุดที่ไม่ผ่านยังอยู่ในฐานข้อมูล กรุณาตรวจพื้นที่และสิทธิ์โฟลเดอร์",
                "Archiving failed. The failed batch remains in the database. Check storage and folder permissions."))
        else:
            self.message.setText(tr(f"จัดเก็บแล้ว {result['events']:,} รอบในครั้งนี้", f"Archived {result['events']:,} readings in this run"))
        self.future = None
        self.cancel_button.setEnabled(False)
        self.refresh()
