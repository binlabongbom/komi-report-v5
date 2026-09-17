from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
from time import monotonic

from PyQt6.QtCore import QLockFile
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
import pytest

from services import agent_handoff
from services.background_agent import desktop_lock_path


CHILD = r'''
import os
from pathlib import Path
from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import QSystemTrayIcon
from services import background_agent
QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)
def start(self):
    Path(os.environ['TEST_STARTED']).write_text('started')
    QTimer.singleShot(100, QCoreApplication.instance().quit)
background_agent.BackgroundAgent.start = start
raise SystemExit(background_agent.main())
'''


def wait_until(condition, seconds=15):
    deadline = monotonic() + seconds
    while not condition() and monotonic() < deadline:
        QTest.qWait(20)
    assert condition()


@pytest.mark.parametrize("commit", [True, False])
def test_real_child_waits_for_commit_and_desktop_drain(monkeypatch, tmp_path, commit):
    app = QApplication.instance() or QApplication([])
    database = tmp_path / "isolated.sqlite3"
    marker = tmp_path / "started"
    monkeypatch.setattr(agent_handoff, "get_db_path", lambda: database)
    monkeypatch.setattr(agent_handoff, "launch_command", lambda: [sys.executable, "-c", CHILD])
    monkeypatch.setenv("TEST_STARTED", str(marker))
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    desktop = QLockFile(str(desktop_lock_path(database)))
    assert desktop.tryLock(0)
    handoff = agent_handoff.AgentHandoff()
    ready, failures = [], []
    handoff.ready.connect(lambda: ready.append(True))
    handoff.failed.connect(failures.append)
    try:
        handoff.start()
        wait_until(lambda: ready or failures)
        assert ready and not failures
        assert not marker.exists()
        if commit:
            assert handoff.commit()
            QTest.qWait(250)
            assert not marker.exists(), "child started before old desktop released ownership"
            desktop.unlock()
            wait_until(marker.exists)
        else:
            handoff.cancel()
        wait_until(lambda: handoff.process.poll() is not None)
        assert handoff.process.returncode == 0
        assert marker.exists() == commit
        assert not handoff.directory.exists()
    finally:
        desktop.unlock()
        handoff.timer.stop()
        if handoff.process is not None and handoff.process.poll() is None:
            handoff.process.kill()
            handoff.process.wait(timeout=5)
        agent_handoff.clean_rendezvous(handoff.directory)
        app.processEvents()


def test_launch_failure_reports_failure_without_committing(monkeypatch):
    app = QApplication.instance() or QApplication([])
    handoff = agent_handoff.AgentHandoff()
    failures = []
    handoff.failed.connect(failures.append)
    def fail(*args, **kwargs):
        raise OSError("synthetic launch failure")
    monkeypatch.setattr(agent_handoff.subprocess, "Popen", fail)
    handoff.start()
    assert failures == ["launch_failed"]
    assert not handoff.committed
    assert not handoff.directory.exists()
    app.processEvents()


def test_cancelled_or_unready_handoff_cannot_be_committed(monkeypatch):
    from types import SimpleNamespace
    app = QApplication.instance() or QApplication([])
    handoff = agent_handoff.AgentHandoff()
    process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(agent_handoff.subprocess, "Popen", lambda *a, **kw: process)
    ready = []
    handoff.ready.connect(lambda: ready.append(True))
    try:
        handoff.start()
        assert not handoff.commit()
        (handoff.directory / "ready").touch()
        handoff.cancel()
        handoff.check()
        assert not ready
        assert not handoff.commit()
        assert not (handoff.directory / "commit").exists()
    finally:
        handoff.timer.stop()
        agent_handoff.clean_rendezvous(handoff.directory)
        app.processEvents()
