from __future__ import annotations

import plistlib
from pathlib import Path

from services import autostart


def test_macos_autostart_is_written_only_when_explicitly_applied(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "darwin")
    monkeypatch.setattr(autostart.Path, "home", classmethod(lambda _cls: tmp_path))

    planned = autostart.configure_autostart(True, apply=False)
    assert planned == tmp_path / "Library" / "LaunchAgents" / "com.komiminolta.komireportv5.plist"
    assert not planned.exists()

    written = autostart.configure_autostart(True, apply=True)
    payload = plistlib.loads(written.read_bytes())
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is False
    assert Path(payload["ProgramArguments"][-1]).parts[-2:] == ("services", "background_agent.py")
    assert "--background" not in payload["ProgramArguments"]

    autostart.configure_autostart(False, apply=True)
    assert not written.exists()
