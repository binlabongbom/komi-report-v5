"""Open the LAN report once the Desktop-owned Web service is ready."""

from __future__ import annotations

import time
import webbrowser

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class WebReportLauncher(QObject):
    failed = pyqtSignal(str)
    opened = pyqtSignal(str)

    def __init__(self, service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._check)
        self._deadline = 0.0

    def open(self) -> None:
        if self.timer.isActive():
            return
        self.service.start()
        # Source launches may need a first Web build. The UI remains responsive.
        self._deadline = time.monotonic() + 300
        self.timer.start()
        self._check()

    def _check(self) -> None:
        status = self.service.status()
        if status.state in {"running", "external"}:
            self.timer.stop()
            webbrowser.open(status.lan_url)
            self.opened.emit(status.lan_url)
        elif status.state in {"failed", "stopped"} or time.monotonic() >= self._deadline:
            self.timer.stop()
            self.failed.emit(f"{status.detail}\n\nLog: {status.log_path}")
