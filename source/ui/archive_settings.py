"""Bounded background archive maintenance with metadata-only initial display."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import date
from pathlib import Path
import logging

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton
from i18n import tr
from services.web_observation_archive import run_archive_batches
from services.history_archive import HistoryArchive
from ui.counter_review import plain
from ui.background_read import LatestRead
from database import get_db_path


class ArchiveSettingsPanel(QWidget):
    def __init__(self, parent=None, *, archive=None, today=None):
        super().__init__(parent)
        self._default_archive = archive is None
        self.archive = archive or HistoryArchive()
        self.today = today
        self.future = None
        self.job = 'archive'
        self.cancelled = Event()
        self.pool = None
        self._metadata_cache = None
        self._metadata_revision = None
        self._requested_revision = None
        self.metadata_reader = LatestRead(self)
        self.metadata_reader.ready.connect(self._metadata_ready)
        self.metadata_reader.failed.connect(self._metadata_failed)
        layout = QVBoxLayout(self)
        layout.addWidget(plain(tr("จัดเก็บรายละเอียดประวัติเก่า", "Archive older history details")))
        layout.addWidget(plain(tr(
            "ระบบเก็บรายละเอียดเกิน 12 เดือนแยกตามปีเมื่อว่าง รายเดือนอ่านจากสรุป รายละเอียดเก่าเปิดเมื่อเรียกดู ค่าตั้งต้นและค่าล่าสุดยังอยู่ให้อ่านต่อได้ สำรองโฟลเดอร์ archives ควบคู่กับฐานข้อมูล",
            "Details older than 12 months are archived by year when idle. Monthly summaries stay available; old details load on request. First and latest baselines remain ready for collection. Keep the archives folder with database backups.")))
        self.status = plain("")
        layout.addWidget(self.status)
        self.message = plain("")
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.start_button = QPushButton(tr("จัดเก็บข้อมูลเก่า", "Archive older readings"))
        self.start_button.setEnabled(False)
        self.refresh_button = QPushButton(tr("ตรวจจำนวนใหม่", "Refresh counts"))
        self.index_button = QPushButton(tr('เติมรายงานจากประวัติที่จัดเก็บแล้ว', 'Fill reports from archived history'))
        self.index_button.setEnabled(False)
        self.index_button.setToolTip(tr('อ่านประวัติที่จัดเก็บไว้เพื่อเติมรายงานที่ขาด โดยคงยอดที่ปิดแล้วและหลักฐานเดิม',
            'Read archived history to fill missing reports while preserving closed totals and original evidence.'))
        self.cancel_button = QPushButton(tr("หยุดหลังจบชุดนี้", "Stop after this batch"))
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.refresh_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addWidget(self.index_button)
        self.start_button.clicked.connect(self.start)
        self.index_button.clicked.connect(self.index_archived)
        self.cancel_button.clicked.connect(self.cancelled.set)
        self.refresh_button.clicked.connect(lambda: self.refresh(force=True))
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._collect)
        self.status.setText(tr("เปิดส่วนนี้เพื่อตรวจจำนวนข้อมูลเก่า", "Open this section to count older records."))

    def _revision(self):
        path = Path(get_db_path()).resolve()
        stamps = []
        for file in (path, Path(str(path) + "-wal")):
            try:
                stat = file.stat()
                stamps.append((stat.st_size, stat.st_mtime_ns))
            except FileNotFoundError:
                stamps.append(None)
        return (str(path), self.today or date.today(), *stamps)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def hideEvent(self, event):
        self.metadata_reader.cancel()
        super().hideEvent(event)

    def refresh(self, *, force=False):
        revision = self._revision()
        if self.future is not None:
            return
        if not force and revision == self._metadata_revision and self._metadata_cache is not None:
            self._show_metadata(self._metadata_cache)
            return
        if not force and self.metadata_reader.busy and revision == self._requested_revision:
            return
        if self._default_archive:
            self.archive = HistoryArchive(revision[0])
        self._requested_revision = revision
        self.start_button.setEnabled(False)
        self.index_button.setEnabled(False)
        self.status.setText(tr("กำลังตรวจจำนวนข้อมูลเก่า…", "Counting older records…"))
        self.metadata_reader.request(self.archive.stats, today=self.today)

    def _metadata_failed(self, error):
        self.status.setText(tr("อ่านรายการ Archive ไม่สำเร็จ · กดตรวจจำนวนใหม่เพื่อลองอีกครั้ง", "Archive metadata is unavailable. Refresh counts to retry."))
        self.status.setToolTip(error)
        self.start_button.setEnabled(False)
        self.index_button.setEnabled(False)

    def _metadata_ready(self, state):
        if self._requested_revision != self._revision():
            self.refresh(force=True)
            return
        self._metadata_revision = self._requested_revision
        self._metadata_cache = state
        self.status.setToolTip("")
        self._show_metadata(state)

    def _show_metadata(self, state):
        self.status.setText(tr(
            f"รอจัดเก็บ {state['eligible']:,} รายการ · จัดเก็บแล้ว {state['archived']:,} รายการ ใน {state['files']:,} ไฟล์",
            f"Pending: {state['eligible']:,} records · Archived: {state['archived']:,} records in {state['files']:,} files"))
        self.start_button.setEnabled(bool(state["eligible"]) and self.future is None)
        self.index_button.setEnabled(bool(state['archived']) and self.future is None)

    def start(self):
        self._start_job('archive')

    def index_archived(self):
        self._start_job('index')

    def _start_job(self, job):
        if self.future is not None or self.metadata_reader.busy:
            return
        if job == 'index' and (self._metadata_revision is None or self._metadata_revision[0] != str(Path(get_db_path()).resolve())):
            self.refresh(force=True)
            return
        if self.pool is None:
            self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-archive")
            pool, cancelled = self.pool, self.cancelled
            self.destroyed.connect(lambda: (cancelled.set(), pool.shutdown(wait=False, cancel_futures=True)))
        self.cancelled.clear()
        self.job = job
        self.start_button.setEnabled(False)
        self.index_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.refresh_button.setEnabled(False)
        self.message.setText(tr("กำลังตรวจสอบและจัดเก็บข้อมูล…", "Verifying and archiving readings…"))
        if job == 'index':
            from services.shared_report_index import index_archived_reports
            self.message.setText(tr('กำลังเติมรายงานจากประวัติที่จัดเก็บไว้ หยุดได้เมื่อจบชุดข้อมูลปัจจุบัน…',
                'Filling reports from archived history. You can stop after the current batch…'))
            self.future = self.pool.submit(index_archived_reports, Path(get_db_path()).resolve(), self.cancelled)
        else:
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
            if self.job == 'index':
                self.message.setText(tr('เติมรายงานไม่สำเร็จ กรุณาตรวจไฟล์ archives และสิทธิ์อ่าน หลักฐานเดิมยังอยู่ครบ กดเติมรายงานอีกครั้งเพื่อทำต่อได้',
                    'Reports could not be filled. Check the archives files and read permissions. Original evidence is preserved; retry to continue.'))
            else:
                self.message.setText(tr("จัดเก็บไม่สำเร็จ ข้อมูลชุดที่ไม่ผ่านยังอยู่ในฐานข้อมูล กรุณาตรวจพื้นที่และสิทธิ์โฟลเดอร์",
                    "Archiving failed. The failed batch remains in the database. Check storage and folder permissions."))
        else:
            if self.job == 'index':
                self.message.setText(tr(f"เติมหลักฐานในรายงานแล้ว {result['indexed']:,} รายการ · รีเฟรชรายงานเพื่อดูข้อมูล",
                    f"Added {result['indexed']:,} evidence records to reports. Refresh reports to see the results."))
            else:
                self.message.setText(tr(f"จัดเก็บแล้ว {result['events']:,} รายการในครั้งนี้", f"Archived {result['events']:,} records in this run"))
        self.future = None
        self.cancel_button.setEnabled(False)
        self.refresh_button.setEnabled(True)
        self.refresh(force=True)
