from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication

from services.instance_guard import SingleInstanceGuard


def test_second_launch_notifies_the_running_instance(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "komi.instance.lock"
    primary = SingleInstanceGuard(path)
    secondary = SingleInstanceGuard(path)
    spy = QSignalSpy(primary.activation_requested)
    try:
        assert primary.acquire() is True
        assert secondary.acquire() is False
        assert spy.wait(500)
        assert len(spy) == 1
    finally:
        secondary.release()
        primary.release()
        app.processEvents()


def test_lock_can_be_acquired_after_clean_release(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "komi.instance.lock"
    first = SingleInstanceGuard(path)
    second = SingleInstanceGuard(path)
    assert first.acquire() is True
    first.release()
    app.processEvents()
    try:
        assert second.acquire() is True
    finally:
        second.release()
