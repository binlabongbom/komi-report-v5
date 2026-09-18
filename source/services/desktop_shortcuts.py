"""Create Desktop launch shortcuts that always target the shared project source."""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShortcutResult:
    desktop_path: Path
    created_paths: tuple[Path, ...]


def desktop_directory() -> Path:
    """Return the current user's Desktop without assuming an English home layout."""
    if sys.platform.startswith("win"):
        profile = Path(os.environ.get("USERPROFILE", Path.home()))
        onedrive = os.environ.get("OneDrive")
        candidates = [Path(onedrive) / "Desktop"] if onedrive else []
        candidates.extend((profile / "Desktop", profile / "OneDrive" / "Desktop"))
        return next((path for path in candidates if path.is_dir()), profile / "Desktop")
    return Path.home() / "Desktop"


def _write_macos_app(bundle: Path, launcher: Path, icon: Path) -> None:
    contents = bundle / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    executable = macos / "launch"
    executable.write_text(
        # LaunchServices can deny a bare Desktop .app direct read access to a
        # OneDrive script.  Hand the canonical launcher to Terminal instead;
        # no source is copied into the shortcut bundle.
        "#!/bin/sh\nexec /usr/bin/open -a Terminal " + shlex.quote(str(launcher)) + "\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    if icon.is_file():
        shutil.copy2(icon, resources / "Logo.icns")
    identifier = "th.co.konicaminolta." + bundle.stem.lower().replace(" ", "-")
    payload = {
        "CFBundleDisplayName": bundle.stem,
        "CFBundleExecutable": "launch",
        "CFBundleIconFile": "Logo.icns",
        "CFBundleIdentifier": identifier,
        "CFBundleName": bundle.stem,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "5",
    }
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(payload, handle)


def _powershell_quote(value: Path | str) -> str:
    return str(value).replace("'", "''")


def _write_windows_link(
    link: Path, launcher: Path, icon: Path, working_dir: Path, arguments: str = ""
) -> None:
    command = (
        "$w=New-Object -ComObject WScript.Shell;"
        f"$s=$w.CreateShortcut('{_powershell_quote(link)}');"
        f"$s.TargetPath='{_powershell_quote(launcher)}';"
        f"$s.Arguments='{_powershell_quote(arguments)}';"
        f"$s.WorkingDirectory='{_powershell_quote(working_dir)}';"
        f"$s.IconLocation='{_powershell_quote(icon)},0';"
        "$s.Save()"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _write_linux_entry(entry: Path, launcher: Path, icon: Path, name: str) -> None:
    # Desktop Entry Exec uses its own double-quote grammar, not POSIX shell
    # single quotes.  Escape the small set interpreted inside quoted args.
    executable = (
        str(launcher)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    entry.write_text(
        "\n".join(
            (
                "[Desktop Entry]",
                "Type=Application",
                f"Name={name}",
                f'Exec="{executable}"',
                f"Icon={icon}",
                "Terminal=false",
                "Categories=Office;Utility;",
                "",
            )
        ),
        encoding="utf-8",
    )
    entry.chmod(0o755)


def create_desktop_shortcuts(
    project_root: Path | None = None,
    *,
    desktop: Path | None = None,
    platform_name: str | None = None,
) -> ShortcutResult:
    """Create Desktop and Web shortcuts without copying application source code."""
    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    target_desktop = (desktop or desktop_directory()).expanduser()
    target_desktop.mkdir(parents=True, exist_ok=True)
    platform_id = platform_name or sys.platform
    created: list[Path] = []

    if platform_id == "darwin":
        items = (
            ("KOMI Report V5.app", root / "Open KOMI Report V5.command"),
            ("KOMI Report Web.app", root / "Open KOMI Report Web.command"),
        )
        for filename, launcher in items:
            destination = target_desktop / filename
            _write_macos_app(destination, launcher, root / "source" / "Logo.icns")
            created.append(destination)
    elif platform_id.startswith("win"):
        # Customer installations omit source .cmd launchers. Both shortcuts
        # use the same runtime and Desktop controller to avoid duplicate ports.
        candidates = (root / "runtime" / "pythonw.exe", root / ".venv" / "Scripts" / "pythonw.exe")
        python = next((path for path in candidates if path.is_file()), None)
        app_script = root / "source" / "app.py"
        if python is not None and app_script.is_file():
            launcher = python
            desktop_args = subprocess.list2cmdline([str(app_script)])
            web_args = subprocess.list2cmdline([str(app_script), "--open-web"])
        else:
            launcher = root / "START_KOMI_REPORT.cmd"
            if not launcher.is_file():
                raise FileNotFoundError(f"ไม่พบตัวเปิดโปรแกรม: {launcher}")
            desktop_args, web_args = "", "web"
        items = (
            ("KOMI Report V5.lnk", desktop_args),
            ("KOMI Report Web.lnk", web_args),
        )
        for filename, arguments in items:
            destination = target_desktop / filename
            _write_windows_link(destination, launcher, root / "source" / "Logo.ico", root, arguments)
            created.append(destination)
    else:
        items = (
            ("komi-report-v5.desktop", root / "Open KOMI Report V5 Linux.sh", "KOMI Report V5"),
            ("komi-report-web.desktop", root / "Open KOMI Report Web Linux.sh", "KOMI Report Web"),
        )
        for filename, launcher, label in items:
            destination = target_desktop / filename
            _write_linux_entry(destination, launcher, root / "source" / "logo.png", label)
            created.append(destination)

    return ShortcutResult(desktop_path=target_desktop, created_paths=tuple(created))
