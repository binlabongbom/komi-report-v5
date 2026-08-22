from __future__ import annotations

import os
import plistlib
import shlex
import sys
from pathlib import Path


def launch_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--background"]
    return [sys.executable, str(Path(__file__).resolve().parents[1] / "app.py"), "--background"]


def configure_autostart(enabled: bool, *, apply: bool = True) -> Path | None:
    """Return the planned OS registration path.

    Tests may pass ``apply=False`` to inspect the intended registration without
    touching the OS. Real registration remains available only at an explicit
    setup/save action, never as an app-start side effect.
    """
    if sys.platform == "darwin":
        path = Path.home() / "Library" / "LaunchAgents" / "com.komiminolta.komireportv5.plist"
        if not enabled and apply:
            path.unlink(missing_ok=True)
            return path
        if not apply:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "Label": "com.komiminolta.komireportv5",
            "ProgramArguments": launch_command(),
            "RunAtLoad": True,
            "KeepAlive": False,
            "ProcessType": "Background",
        }
        path.write_bytes(plistlib.dumps(payload, sort_keys=True))
        return path
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        path = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "KOMI Report V5.cmd"
        if not enabled and apply:
            path.unlink(missing_ok=True)
            return path
        if not apply:
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        command = " ".join(f'"{part}"' for part in launch_command())
        path.write_text(f"@echo off\r\nstart \"\" {command}\r\n", encoding="utf-8")
        return path
    path = Path.home() / ".config" / "autostart" / "komi-report-v5.desktop"
    if not enabled and apply:
        path.unlink(missing_ok=True)
        return path
    if not apply:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    command = " ".join(shlex.quote(part) for part in launch_command())
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=KOMI Report V5\n"
        f"Exec={command}\nX-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    return path
