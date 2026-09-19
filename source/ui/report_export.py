"""One cancellable export worker with Qt updates collected on the GUI thread."""
from i18n import tr, translate_text
from concurrent.futures import CancelledError, ThreadPoolExecutor
from queue import Empty, SimpleQueue
from threading import Event
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout


class ExportProgressDialog(QDialog):
    """Keep progress visible until the worker has actually finished or cancelled."""
    canceled = pyqtSignal()

    def __init__(self, parent=None, *, title=None):
        super().__init__(parent)
        self.setObjectName('excel_export_progress')
        self.setWindowTitle(title or tr('ส่งออก Excel', 'Export Excel'))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(460)
        self._finished = False
        self._cancel_requested = False
        self._started = monotonic()
        self.setStyleSheet('''
            QDialog#excel_export_progress { background:#FFFFFF; }
            QLabel { color:#123262; background:transparent; }
            QProgressBar { border:1px solid #C9D8E6; border-radius:7px;
                background:#EEF4FA; color:#123262; min-height:24px; text-align:center; }
            QProgressBar::chunk { background:#1677C8; border-radius:6px; }
            QPushButton { background:#FFFFFF; color:#123262; border:1px solid #C9D8E6;
                border-radius:6px; padding:8px 20px; }
            QPushButton:hover { background:#EEF4FA; }
            QPushButton:disabled { color:#66788A; background:#F3F6F8; }
        ''')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        title = QLabel(title or tr('กำลังส่งออก Excel', 'Exporting Excel'))
        title.setStyleSheet('font-size:13.5pt;font-weight:700;')
        layout.addWidget(title)
        self.phase_label = QLabel(tr('กำลังเตรียมส่งออก…', 'Preparing export…'))
        self.phase_label.setWordWrap(True)
        status_row = QHBoxLayout()
        status_row.addWidget(self.phase_label, 1)
        self.percent_label = QLabel('0%')
        self.percent_label.setStyleSheet('color:#1677C8;font-size:13.5pt;font-weight:700;')
        status_row.addWidget(self.percent_label)
        layout.addLayout(status_row)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setAccessibleName(tr('ความคืบหน้าการส่งออก', 'Export progress'))
        layout.addWidget(self.progress_bar)
        self.elapsed_label = QLabel()
        self.elapsed_label.setStyleSheet('color:#66788A;')
        layout.addWidget(self.elapsed_label)
        self.hint_label = QLabel(tr('เปอร์เซ็นต์แสดงความคืบหน้าตามขั้นตอน\nสามารถใช้งานหน้ารายงานต่อได้ระหว่างรอ', 'Percentage indicates progress through the export stages.\nYou can continue using the report while waiting.'))
        self.hint_label.setStyleSheet('color:#66788A;')
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = QPushButton(tr('ยกเลิก', 'Cancel'))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.request_cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._update_elapsed)
        self._update_elapsed()
        self.elapsed_timer.start()

    def _update_elapsed(self):
        seconds = int(monotonic() - self._started)
        minutes, seconds = divmod(seconds, 60)
        self.elapsed_label.setText(tr('ใช้เวลา {time}', 'Elapsed {time}').format(time=f'{minutes:02d}:{seconds:02d}'))

    def set_progress(self, percent, message):
        if not self._cancel_requested:
            self.progress_bar.setValue(max(0, min(99, int(percent))))
            self.percent_label.setText(f'{self.progress_bar.value()}%')
            self.phase_label.setText(translate_text(message))

    def request_cancel(self):
        if self._finished or self._cancel_requested:
            return
        self._cancel_requested = True
        self.phase_label.setText(tr('กำลังยกเลิกการส่งออก…', 'Cancelling export…'))
        self.hint_label.setText(tr('โปรดรอจนยกเลิกเสร็จ ไฟล์เดิมจะยังคงอยู่', 'Please wait for cancellation to finish. Your original file is preserved.'))
        self.cancel_button.setText(tr('กำลังยกเลิก…', 'Cancelling…'))
        self.cancel_button.setEnabled(False)
        self.canceled.emit()

    def reject(self):
        self.request_cancel()

    def closeEvent(self, event):
        if self._finished:
            event.accept()
        else:
            self.request_cancel()
            event.ignore()

    def finish(self):
        self._finished = True
        self.elapsed_timer.stop()
        self.accept()


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

    def start(self, job, *, title=None):
        if self.busy or self.closed:
            return False
        self.cancelled.clear()
        self.messages = SimpleQueue()
        self.dialog = ExportProgressDialog(self.parent(), title=title)
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
            self.dialog.set_progress(latest[0], latest[1])
        if not self.future.done():
            return
        future, self.future = self.future, None
        self.timer.stop()
        self.dialog.finish()
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
        app = QApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self.shutdown)
            except (TypeError, RuntimeError):
                pass
        self.cancelled.set()
        self.timer.stop()
        if self.dialog is not None:
            self.dialog.finish()
            self.dialog.deleteLater()
            self.dialog = None
        if self.future:
            self.future.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)
