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
