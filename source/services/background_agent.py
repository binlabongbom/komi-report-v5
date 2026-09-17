"""Lightweight headless runtime used by OS Auto-start.

This entry point deliberately uses QCoreApplication and never imports app.py,
pages.py, v5_pages.py, QtWidgets, charts, or report views.  It owns scheduled
printer collection only while the desktop GUI is closed.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from PyQt6.QtCore import QCoreApplication, QLockFile, QObject, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from database import get_cfg, get_db_path, init_db
from services.background_polling import BackgroundPollingCoordinator
from services.build_edition import is_offline_edition
from services.device_config import DeviceConfigRepository
from services.peer_sync_authorization import PeerSyncAuthorizationError, ensure_pairing_default
from services.v5_2_client import V52ContractClient, V52RuntimeConfig
from services.v5_2_runtime import V52RuntimeCoordinator
from services.web_service import web_service_manager

log = logging.getLogger(__name__)


def _identity(path: Path) -> str:
    canonical = str(path.expanduser().resolve(strict=False))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def agent_server_name(database_path: Path | None = None) -> str:
    path = database_path or Path(get_db_path())
    return f"komi-report-v5-agent-{_identity(path)}"


def agent_lock_path(database_path: Path | None = None) -> Path:
    path = database_path or Path(get_db_path())
    return path.with_suffix(".background-agent.lock")


def desktop_lock_path(database_path: Path | None = None) -> Path:
    path = database_path or Path(get_db_path())
    return path.with_suffix(".instance.lock")


def stop_running_background_agent(database_path: Path | None = None) -> bool:
    """Ask the headless agent to stop before the full desktop starts."""

    socket = QLocalSocket()
    socket.connectToServer(agent_server_name(database_path))
    if not socket.waitForConnected(350):
        return False
    socket.write(b"stop")
    socket.flush()
    socket.waitForBytesWritten(350)
    socket.waitForReadyRead(1_500)
    acknowledged = bytes(socket.readAll()).strip() == b"ok"
    socket.disconnectFromServer()
    socket.waitForDisconnected(500)
    return acknowledged


class BackgroundAgent(QObject):
    """Coordinate collection services without constructing any desktop UI."""

    def __init__(self, server: QLocalServer, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.server.newConnection.connect(self._on_connection)
        self.repository = DeviceConfigRepository()
        self.registration = V52RuntimeCoordinator(
            None
            if is_offline_edition()
            else V52ContractClient(
                V52RuntimeConfig(
                    base_url="https://www.dmskm.com",
                    environment="production",
                )
            ),
            device_repository=self.repository,
            parent=self,
        )
        self.polling = BackgroundPollingCoordinator(repository=self.repository, parent=self)
        self.web_service = web_service_manager()
        self.polling.reading_saved.connect(self.registration.meter_observed)
        self.registration.status_changed.connect(self._apply_collection_gate)
        self._stopping = False

    def start(self) -> None:
        self.polling.pause("registration_status_pending")
        self.registration.start()
        self.registration.configuration_changed()
        self.polling.start()
        self._apply_collection_gate()
        if get_cfg("web_service_enabled", "1") != "0":
            try:
                ensure_pairing_default(
                    get_cfg("installation_id", ""),
                    primary=get_cfg("desktop_role", "primary") != "secondary",
                )
            except PeerSyncAuthorizationError:
                log.warning("Peer Sync authorization requires local review")
            self.web_service.start()
        log.info("headless background agent started")

    def _apply_collection_gate(self, _status: str = "") -> None:
        eligible, reason = self.registration.usage_eligibility()
        if eligible:
            self.polling.resume()
        else:
            self.polling.pause(reason or "registration_ineligible")

    def _on_connection(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            socket.waitForReadyRead(250)
            command = bytes(socket.read(32)).strip()
            socket.write(b"ok")
            socket.flush()
            socket.waitForBytesWritten(250)
            socket.disconnectFromServer()
            if command == b"stop":
                QTimer.singleShot(0, self.stop)

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.polling.stop()
        self.registration.stop()
        self.web_service.stop()
        self.server.close()
        QLocalServer.removeServer(self.server.serverName())
        log.info("headless background agent stopped")
        QCoreApplication.instance().quit()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    application = QCoreApplication(sys.argv)
    application.setApplicationName("KOMI Report V5 Background Agent")
    init_db()

    # Do not start beside an already-running full desktop.
    desktop_lock = QLockFile(str(desktop_lock_path()))
    desktop_lock.setStaleLockTime(30_000)
    if not desktop_lock.tryLock(0):
        return 0
    desktop_lock.unlock()

    lock = QLockFile(str(agent_lock_path()))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(0):
        return 0

    server_name = agent_server_name()
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    if not server.listen(server_name):
        lock.unlock()
        return 1

    agent = BackgroundAgent(server)
    application.aboutToQuit.connect(agent.stop)
    QTimer.singleShot(0, agent.start)
    try:
        return application.exec()
    finally:
        server.close()
        QLocalServer.removeServer(server_name)
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
