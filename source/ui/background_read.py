"""Latest-request-only reads; worker functions never receive a Qt widget."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from threading import Event

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication
from database import get_db_path, report_read_database


def _read(path, cancelled, loader, args, kwargs):
    if cancelled.is_set():
        raise CancelledError()
    try:
        with report_read_database(path, cancelled=cancelled):
            result = loader(*args, **kwargs)
        if cancelled.is_set():
            raise CancelledError()
        return result
    except Exception:
        if cancelled.is_set():
            raise CancelledError() from None
        raise


class _Resources:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="komi-ui-read")
        self.jobs = {}

    def cancel(self):
        for future, (_, _, cancelled) in self.jobs.items():
            cancelled.set()
            future.cancel()

    def shutdown(self, *_):
        self.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)


class LatestRead(QObject):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self._resources = _Resources()
        self.destroyed.connect(self._resources.shutdown)
        self._generation = 0
        self.future = None
        self.closed = False
        self.timer = QTimer(self)
        self.timer.setInterval(25)
        self.timer.timeout.connect(self._collect)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    @property
    def busy(self):
        return self.future is not None

    def request(self, loader, *args, **kwargs):
        if self.closed:
            return
        self.cancel()
        path = str(get_db_path().resolve())
        cancelled = Event()
        self.future = self._resources.pool.submit(_read, path, cancelled, loader, args, kwargs)
        self._resources.jobs[self.future] = (self._generation, path, cancelled)
        self.timer.start()

    def cancel(self):
        self._generation += 1
        self._resources.cancel()
        self.future = None

    def _collect(self):
        for future, (generation, path, cancelled) in tuple(self._resources.jobs.items()):
            if not future.done():
                continue
            self._resources.jobs.pop(future)
            if future is self.future:
                self.future = None
            if cancelled.is_set() or generation != self._generation or path != str(get_db_path().resolve()):
                continue
            try:
                result = future.result()
            except CancelledError:
                continue
            except Exception as error:
                self.failed.emit(f"{type(error).__name__}: {error}")
            else:
                self.ready.emit(result)
        if not self._resources.jobs:
            self.timer.stop()

    def shutdown(self):
        if self.closed:
            return
        self.closed = True
        self.cancel()
        self.timer.stop()
        self._resources.shutdown()
        app = QApplication.instance()
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self.shutdown)
            except (TypeError, RuntimeError):
                pass
