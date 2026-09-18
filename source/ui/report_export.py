"""One cancellable export worker with Qt updates collected on the GUI thread."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from queue import Empty, SimpleQueue
from threading import Event

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QProgressDialog


class ReportExportController(QObject):
    busy_changed = pyqtSignal(bool)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.future = None
        self.dialog = None
        self.cancelled = Event()
        self.messages = SimpleQueue()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='komi-excel')
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._collect)
        # Cleanup must not dereference a deleted widget or wait on its worker.
        cancelled, pool = self.cancelled, self.pool
        self.destroyed.connect(lambda: (cancelled.set(), pool.shutdown(wait=False, cancel_futures=True)))
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    @property
    def busy(self):
        return self.future is not None

    def start(self, job):
        if self.busy or self.closed:
            return False
        self.cancelled.clear()
        self.messages = SimpleQueue()
        self.dialog = QProgressDialog('กำลังเตรียมส่งออก…', 'ยกเลิก', 0, 100, self.parent())
        self.dialog.setWindowTitle('ส่งออก Excel')
        self.dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.dialog.setMinimumDuration(0)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.canceled.connect(self.cancelled.set)
        self.dialog.show()
        self.busy_changed.emit(True)
        queue = self.messages
        self.future = self.pool.submit(job, cancelled=self.cancelled,
                                       progress=lambda percent, text: queue.put((percent, text)))
        self.timer.start()
        return True

    def _collect(self):
        if not self.future or self.closed:
            return
        latest = None
        while True:
            try:
                latest = self.messages.get_nowait()
            except Empty:
                break
        if latest and not self.cancelled.is_set():
            self.dialog.setValue(latest[0])
            self.dialog.setLabelText(latest[1])
        if not self.future.done():
            return
        future, self.future = self.future, None
        self.timer.stop()
        self.dialog.close()
        self.dialog.deleteLater()
        self.dialog = None
        self.busy_changed.emit(False)
        try:
            result = future.result()
        except CancelledError:
            return
        except Exception as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.cancelled.set()
        self.timer.stop()
        if self.future:
            self.future.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)
