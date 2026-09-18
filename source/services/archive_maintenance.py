"""Idle, bounded archival owned and drained by the collection runtime."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import logging
from threading import Event

from PyQt6.QtCore import QObject, QTimer
from services.history_archive import HistoryArchive

log = logging.getLogger(__name__)


class ArchiveMaintenance(QObject):
    def __init__(self, parent=None, *, archive=None, busy=lambda: False, today=date.today):
        super().__init__(parent)
        self.archive = archive or HistoryArchive()
        self.busy = busy
        self.today = today
        self.future = None
        self.pool = None
        self.cancelled = Event()
        self.started = False
        self.completed_day = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)

    def start(self):
        if self.started or self.cancelled.is_set():
            return
        self.started = True
        # Give startup, catch-up and the first printer round priority.
        self.timer.start(60_000)

    def _one_batch(self, today):
        if self.cancelled.is_set() or self.busy():
            return {"deferred": True}
        result = self.archive.archive_batch(today=today)
        return {"batch": result}

    def tick(self):
        if self.cancelled.is_set() or not self.started:
            return
        today = self.today()
        if self.future is not None:
            if not self.future.done():
                self.timer.start(500)
                return
            future, self.future = self.future, None
            try:
                result = future.result()
            except Exception:
                # Avoid a repeated failure loop (disk full/corrupt media).
                log.exception("Automatic history archive failed; retry next day or manually")
                self.completed_day = today
                from services.pipeline_log import pipeline_log
                pipeline_log.append(stage="DB", action="History archive failed", target="archives",
                    value="ข้อมูลชุดที่ไม่ผ่านยังอยู่ในฐานข้อมูล", detail="ตรวจพื้นที่และสิทธิ์โฟลเดอร์ก่อนลองใหม่ในหน้าตั้งค่า", status="error")
            else:
                if not result.get("deferred") and result.get("batch") is None:
                    self.completed_day = today
        if self.completed_day == today:
            # Local maintenance only: no network, settings polling or old files.
            self.timer.start(60 * 60 * 1000)
            return
        if self.busy():
            self.timer.start(30_000)
            return
        if self.pool is None:
            self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-archive-idle")
        self.future = self.pool.submit(self._one_batch, today)
        self.timer.start(2000)

    def stop(self, *, wait=False):
        self.timer.stop()
        self.cancelled.set()
        remaining = int(self.future is not None and not self.future.done())
        if self.future is not None:
            self.future.cancel()
        if self.pool is not None:
            self.pool.shutdown(wait=wait, cancel_futures=True)
        return remaining
