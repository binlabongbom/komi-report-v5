from __future__ import annotations

import os
import plistlib

from services import desktop_shortcuts


def _project(tmp_path):
    root = tmp_path / "shared source"
    (root / "source").mkdir(parents=True)
    for filename in (
        "Open KOMI Report V5.command",
        "Open KOMI Report Web.command",
        "START_KOMI_REPORT.cmd",
        "START_KOMI_REPORT_WEB.cmd",
        "Open KOMI Report V5 Linux.sh",
        "Open KOMI Report Web Linux.sh",
    ):
        (root / filename).write_text("launcher", encoding="utf-8")
    for filename in ("Logo.icns", "Logo.ico", "logo.png"):
        (root / "source" / filename).write_bytes(b"icon")
    return root


def test_macos_shortcuts_are_app_bundles_pointing_to_shared_launchers(tmp_path):
    root = _project(tmp_path)
    desktop = tmp_path / "Desktop"
    result = desktop_shortcuts.create_desktop_shortcuts(root, desktop=desktop, platform_name="darwin")

    assert [path.name for path in result.created_paths] == ["KOMI Report V5.app", "KOMI Report Web.app"]
    executable = result.created_paths[0] / "Contents" / "MacOS" / "launch"
    assert str(root / "Open KOMI Report V5.command") in executable.read_text(encoding="utf-8")
    with (result.created_paths[0] / "Contents" / "Info.plist").open("rb") as handle:
        assert plistlib.load(handle)["CFBundleIconFile"] == "Logo.icns"


def test_linux_shortcuts_are_executable_and_point_to_shared_launchers(tmp_path):
    root = _project(tmp_path)
    result = desktop_shortcuts.create_desktop_shortcuts(
        root, desktop=tmp_path / "Desktop", platform_name="linux"
    )

    desktop_entry = result.created_paths[0]
    content = desktop_entry.read_text(encoding="utf-8")
    expected_launcher = str(root / "Open KOMI Report V5 Linux.sh").replace("\\", "\\\\")
    assert expected_launcher in content
    if os.name != "nt":
        assert desktop_entry.stat().st_mode & 0o111


def test_windows_shortcuts_use_canonical_cmd_launchers(tmp_path, monkeypatch):
    root = _project(tmp_path)
    calls = []

    def fake_link(link, launcher, icon, working_dir, arguments=""):
        calls.append((link, launcher, icon, working_dir, arguments))
        link.write_text("synthetic link", encoding="utf-8")

    monkeypatch.setattr(desktop_shortcuts, "_write_windows_link", fake_link)
    result = desktop_shortcuts.create_desktop_shortcuts(
        root, desktop=tmp_path / "Desktop", platform_name="win32"
    )

    assert [path.name for path in result.created_paths] == ["KOMI Report V5.lnk", "KOMI Report Web.lnk"]
    assert calls[0][1] == root / "START_KOMI_REPORT.cmd"
    assert calls[1][1] == root / "START_KOMI_REPORT.cmd"
    assert calls[1][4] == "web"
    assert all(call[3] == root for call in calls)


def test_installed_windows_shortcuts_use_bundled_runtime_without_cmd_files(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "pythonw.exe").touch()
    (root / "source").mkdir()
    (root / "source" / "app.py").touch()
    calls = []
    monkeypatch.setattr(desktop_shortcuts, "_write_windows_link", lambda *args: calls.append(args))
    desktop_shortcuts.create_desktop_shortcuts(root, desktop=tmp_path / "Desktop", platform_name="win32")
    assert all(call[1] == root / "runtime" / "pythonw.exe" for call in calls)
    assert "--open-web" not in calls[0][4]
    assert calls[1][4].endswith(" --open-web")
    assert str(root / "source" / "app.py") in calls[1][4]
