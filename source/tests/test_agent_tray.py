from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QMessageBox
import pytest

from ui import agent_tray


@pytest.mark.parametrize("approved", [False, True])
def test_stop_confirmation_and_duplicate_actions(monkeypatch, approved):
    app = QApplication.instance() or QApplication([])
    stopped = []
    tray = agent_tray.AgentTray(lambda: stopped.append(True))
    prompts = []
    def question(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.Yes if approved else QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "question", question)
    try:
        tray.confirm_stop()
        assert len(stopped) == int(approved)
        assert prompts[0][-1] == QMessageBox.StandardButton.Cancel
        assert tray.open_action.isEnabled() != approved
        if approved:
            tray.confirm_stop()
            assert len(stopped) == len(prompts) == 1
    finally:
        tray.close()
        app.processEvents()


def test_open_does_not_stop_agent_and_deduplicates_double_click():
    app = QApplication.instance() or QApplication([])
    opened, stopped = [], []
    tray = agent_tray.AgentTray(lambda: stopped.append(True), open_desktop=lambda: opened.append(True))
    try:
        tray.open()
        tray.open()
        assert opened == [True]
        assert stopped == []
    finally:
        tray.close()
        app.processEvents()


def test_failed_launch_keeps_agent_available(monkeypatch):
    app = QApplication.instance() or QApplication([])
    stopped, warnings = [], []
    def fail():
        raise OSError("test failure")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    tray = agent_tray.AgentTray(lambda: stopped.append(True), open_desktop=fail)
    try:
        tray.open()
        assert warnings
        assert not stopped
        assert tray.open_action.isEnabled()
    finally:
        tray.close()
        app.processEvents()


def test_desktop_launch_preserves_database_and_uses_no_shell(monkeypatch, tmp_path):
    calls = []
    database = tmp_path / "isolated.sqlite3"
    monkeypatch.setattr(agent_tray, "get_db_path", lambda: database)
    monkeypatch.setattr(agent_tray.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    agent_tray.launch_desktop()
    args, kwargs = calls[0]
    assert args[0][-1].endswith("app.py")
    assert kwargs["env"]["KOMI_DB_PATH"] == str(database.resolve())
    assert not kwargs.get("shell", False)
    if os.name == "nt":
        assert kwargs["creationflags"] == agent_tray.subprocess.CREATE_NO_WINDOW


def test_agent_tray_import_does_not_load_desktop_or_charts(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import services.background_agent; import ui.agent_tray; "
         "assert not {'app', 'pages', 'v5_pages', 'PyQt6.QtCharts', 'matplotlib.pyplot'}.intersection(sys.modules)"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "KOMI_DB_PATH": str(tmp_path / "isolated.sqlite3")},
        capture_output=True, text=True, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == 0, result.stderr
