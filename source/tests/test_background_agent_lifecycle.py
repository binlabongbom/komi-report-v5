"""Cross-process ownership checks, without printers or Host connections."""
from __future__ import annotations

import os
import subprocess
import sys
from time import monotonic, sleep
from threading import Event, Timer

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
import pytest

from services.background_agent import (
    BackgroundAgent,
    agent_lock_path,
    agent_server_name,
    stop_running_background_agent,
)


CHILD = r'''
import sys
from pathlib import Path
from PyQt6.QtCore import QCoreApplication, QLockFile, QTimer
from PyQt6.QtNetwork import QLocalServer
app = QCoreApplication([])
lock = QLockFile(sys.argv[1])
assert lock.tryLock(0)
server = QLocalServer()
assert server.listen(sys.argv[2])
sockets = []
def connected():
    sock = server.nextPendingConnection()
    sockets.append(sock)
    def request():
        if bytes(sock.readAll()).strip() == b'stop':
            sock.write(b'ok')
            sock.flush()
            # Receipt is immediate, but a simulated write is still running.
            QTimer.singleShot(700, finished)
    sock.readyRead.connect(request)
def finished():
    lock.unlock()
    app.quit()
server.newConnection.connect(connected)
Path(sys.argv[3]).write_text('ready')
QTimer.singleShot(10000, app.quit)
app.exec()
'''


def test_takeover_waits_for_release_after_acknowledgement(tmp_path):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / "isolated.sqlite3"
    ready = tmp_path / "ready"
    child = subprocess.Popen(
        [sys.executable, "-c", CHILD, str(agent_lock_path(database)),
         agent_server_name(database), str(ready)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = monotonic() + 8
        while not ready.exists() and monotonic() < deadline and child.poll() is None:
            sleep(0.02)
        assert ready.exists(), "isolated agent did not start"
        started = monotonic()
        assert stop_running_background_agent(database, timeout_ms=3000)
        assert monotonic() - started >= 0.5
        child.communicate(timeout=5)
        assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        app.processEvents()


@pytest.mark.parametrize("operation", ["stop", "pause"])
def test_shutdown_cancels_queued_polls_without_mutating_iteration(monkeypatch, operation):
    from concurrent.futures import ThreadPoolExecutor
    from services.background_polling import BackgroundPollingCoordinator
    from services.device_config import DeviceConfig
    app = QApplication.instance() or QApplication([])
    coordinator = BackgroundPollingCoordinator()
    coordinator.executor.shutdown()
    coordinator.executor = ThreadPoolExecutor(max_workers=1)
    started, release = Event(), Event()
    def poll(*args):
        started.set()
        assert release.wait(3)
        return False
    monkeypatch.setattr(coordinator, "_poll_device", poll)
    try:
        coordinator._submit(DeviceConfig(0, "Test", "192.0.2.1"), force_web=False)
        assert started.wait(1)
        for slot in (1, 2):
            coordinator._submit(DeviceConfig(slot, "Test", "192.0.2.1"), force_web=False)
        getattr(coordinator, operation)()
        assert coordinator.active == {0}
        coordinator.tick()
        coordinator._submit(DeviceConfig(2, "Test", "192.0.2.1"), force_web=True)
        assert coordinator.active == {0}
    finally:
        release.set()
        coordinator.stop(wait=True)
        app.processEvents()
    assert not coordinator.active


def test_registration_ignores_queued_events_after_shutdown(monkeypatch):
    from services.v5_2_runtime import V52RuntimeCoordinator
    app = QApplication.instance() or QApplication([])
    coordinator = V52RuntimeCoordinator(None)
    coordinator.stop()
    def unexpected(*args, **kwargs):
        pytest.fail("a shutdown runtime must not access state or schedule work")
    monkeypatch.setattr(coordinator, "snapshot", unexpected)
    monkeypatch.setattr(coordinator.state_repository, "internal", unexpected)
    coordinator.tick()
    coordinator.configuration_changed()
    coordinator._after_work()
    assert coordinator.retry_now() == 0
    assert coordinator.network_recovered() == 0
    assert not coordinator.timer.isActive()
    app.processEvents()


@pytest.mark.parametrize("chunks,accepted", [([b"st", b"op"], True), ([b"ping"], False)])
def test_agent_pipe_handles_split_commands_and_rejects_unknown(tmp_path, chunks, accepted):
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    server = QLocalServer()
    assert server.listen(agent_server_name(tmp_path / "protocol.sqlite3"))
    agent = BackgroundAgent(server)
    stops = []
    agent.stop = lambda: stops.append(True)
    client = QLocalSocket()
    try:
        client.connectToServer(server.serverName())
        assert client.waitForConnected(1000)
        for index, chunk in enumerate(chunks):
            client.write(chunk)
            client.flush()
            QTest.qWait(30)
            if index < len(chunks) - 1:
                assert not stops
                assert client.bytesAvailable() == 0
        deadline = monotonic() + 2
        while client.bytesAvailable() == 0 and monotonic() < deadline:
            QTest.qWait(10)
        assert bytes(client.readAll()) == (b"ok" if accepted else b"error")
        QTest.qWait(10)
        assert bool(stops) == accepted
    finally:
        client.abort()
        agent.polling.stop(wait=True)
        agent.registration.stop(wait=True)
        server.close()
        QLocalServer.removeServer(server.serverName())
        app.processEvents()


def test_unresponsive_owner_blocks_takeover_but_absent_agent_does_not(tmp_path):
    from PyQt6.QtCore import QLockFile
    app = QApplication.instance() or QApplication([])
    database = tmp_path / "isolated.sqlite3"
    lock = QLockFile(str(agent_lock_path(database)))
    assert lock.tryLock(0)
    try:
        assert not stop_running_background_agent(database, timeout_ms=50)
    finally:
        lock.unlock()
    assert stop_running_background_agent(database, timeout_ms=50)
    app.processEvents()


@pytest.mark.parametrize("kind", ["polling", "registration"])
def test_drain_waits_for_running_worker_after_nonblocking_stop(kind):
    from services.background_polling import BackgroundPollingCoordinator
    from services.v5_2_runtime import V52RuntimeCoordinator
    app = QApplication.instance() or QApplication([])
    coordinator = BackgroundPollingCoordinator() if kind == "polling" else V52RuntimeCoordinator(None)
    started, release = Event(), Event()

    def write():
        started.set()
        assert release.wait(3)
        return "transaction completed"

    future = coordinator.executor.submit(write)
    assert started.wait(2)
    coordinator.stop()
    assert not future.done()
    timer = Timer(0.15, release.set)
    timer.start()
    try:
        coordinator.stop(wait=True)
        assert future.done()
        assert future.result() == "transaction completed"
    finally:
        release.set()
        timer.join()
        coordinator.stop(wait=True)
        app.processEvents()
