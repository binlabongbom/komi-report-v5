from __future__ import annotations

import hashlib
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QLockFile, QObject, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceGuard(QObject):
    """Keep one collector process and raise it when launched a second time."""

    activation_requested = pyqtSignal()
    web_open_requested = pyqtSignal()

    def __init__(self, path: Path) -> None:
        super().__init__()
        canonical = str(path.expanduser().resolve())
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
        self.server_name = f"komi-report-v5-{digest}"
        self.lock = QLockFile(str(path))
        self.server: QLocalServer | None = None
        self._acquired = False
        # A crash must recover; a new process may remove a lock older than the
        # bounded startup window, but a concurrent launch is rejected.
        self.lock.setStaleLockTime(30_000)

    def acquire(self, *, command: str = "activate") -> bool:
        if command not in {"activate", "open-web"}:
            raise ValueError("Unknown launch command")
        if not self.lock.tryLock(0):
            self._notify_primary(command)
            return False
        self._acquired = True
        QLocalServer.removeServer(self.server_name)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        if not self.server.listen(self.server_name):
            # The file lock still guarantees safety.  Keep running even when
            # the convenience "bring to front" channel cannot be created.
            self.server.deleteLater()
            self.server = None
        return True

    def _notify_primary(self, command: str) -> None:
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if socket.waitForConnected(250):
            # Windows named pipes can drop data when the client exits before
            # the primary reads it. Keep the connection until acknowledgement.
            loop = QEventLoop()
            deadline = QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(loop.quit)
            socket.readyRead.connect(loop.quit)
            socket.write(command.encode("ascii"))
            socket.flush()
            deadline.start(1000)
            loop.exec()
            deadline.stop()
            socket.disconnectFromServer()

    def _on_new_connection(self) -> None:
        if self.server is None:
            return
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            # Read asynchronously: a connection can arrive before its command.
            timer = QTimer(socket)
            timer.setSingleShot(True)
            socket.readyRead.connect(lambda client=socket: self._handle_request(client))
            timer.timeout.connect(lambda client=socket: self._handle_request(client))
            timer.start(250)
            if socket.bytesAvailable():
                self._handle_request(socket)

    def _handle_request(self, socket: QLocalSocket) -> None:
        if socket.property("handled"):
            return
        socket.setProperty("handled", True)
        command = bytes(socket.read(64) or b"").strip()
        socket.write(b"ok")
        socket.flush()
        socket.disconnectFromServer()
        socket.deleteLater()
        if command == b"open-web":
            self.web_open_requested.emit()
        else:
            self.activation_requested.emit()

    def release(self) -> None:
        if self.server is not None:
            self.server.close()
            self.server.deleteLater()
            self.server = None
            QLocalServer.removeServer(self.server_name)
        if self._acquired:
            self.lock.unlock()
            self._acquired = False
