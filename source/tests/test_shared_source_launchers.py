from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.launch_doctor import DESKTOP_FILES, _source_fingerprint

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "source"


def _text(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def test_launchers_execute_the_canonical_onedrive_source():
    mac = _text("Open KOMI Report V5.command")
    windows = _text("START_KOMI_REPORT.cmd")
    linux = _text("Open KOMI Report V5 Linux.sh")

    assert 'SOURCE_ROOT="$PROJECT_ROOT/source"' in mac
    assert '"$SOURCE_ROOT/app.py"' in mac
    assert '"$SOURCE_ROOT/tools/setup_lab.py"' in mac
    assert "Library/Application Support/KOMI Report V5/runtime-macos" in mac
    assert 'exec "$PROJECT_ROOT/Open KOMI Report V5.command" lab' in _text(
        "Open KOMI Setup Lab.command"
    )

    assert 'set "SOURCE_ROOT=%PROJECT_ROOT%\\source"' in windows
    assert '"%SOURCE_ROOT%\\app.py"' in windows
    assert "%LOCALAPPDATA%\\KOMI Report V5\\runtime-windows" in windows
    assert 'pushd "%~dp0"' in windows
    assert '"%SOURCE_ROOT%\\tools\\setup_lab.py"' in windows
    assert 'call "%~dp0START_KOMI_REPORT.cmd" lab' in _text("START_KOMI_SETUP_LAB.cmd")

    assert 'SOURCE_ROOT="$PROJECT_ROOT/source"' in linux
    assert '"$SOURCE_ROOT/app.py"' in linux
    assert "${XDG_DATA_HOME:-$HOME/.local/share}" in linux

    for launcher in (mac, windows, linux):
        assert "source/.venv" not in launcher
        assert "release/" not in launcher
        assert "launch_doctor.py" in launcher


def test_launch_doctor_reports_the_real_canonical_source():
    result = subprocess.run(
        [sys.executable, str(SOURCE_ROOT / "tools" / "launch_doctor.py"), "desktop", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert Path(payload["source_root"]).samefile(SOURCE_ROOT)
    assert payload["version"] == "5.2.1"
    assert len(payload["source_id"]) == 64


def test_launch_doctor_fingerprint_includes_service_and_ui_code(tmp_path):
    source = tmp_path / "source"
    for name in DESKTOP_FILES:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(name, encoding="utf-8")
    for directory in ("services", "ui", "komi_snmp_profiler", "tools"):
        target = source / directory / "sample.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")

    before = _source_fingerprint(source, DESKTOP_FILES)
    (source / "services" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
    after_service_change = _source_fingerprint(source, DESKTOP_FILES)
    (source / "ui" / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
    after_ui_change = _source_fingerprint(source, DESKTOP_FILES)

    assert before != after_service_change
    assert after_service_change != after_ui_change


def test_web_launchers_execute_the_canonical_onedrive_source():
    mac = _text("Open KOMI Report Web.command")
    windows = _text("START_KOMI_REPORT_WEB.cmd")
    linux = _text("Open KOMI Report Web Linux.sh")

    assert 'WEB_SOURCE="$PROJECT_ROOT/web"' in mac
    assert '"$SOURCE_ROOT/tools/prepare_web_runtime.py"' in mac
    assert "Library/Application Support/KOMI Report V5/web-runtime" in mac

    assert 'set "WEB_SOURCE=%PROJECT_ROOT%\\web"' in windows
    assert '"%SOURCE_ROOT%\\tools\\prepare_web_runtime.py"' in windows
    assert "%LOCALAPPDATA%\\KOMI Report V5\\web-runtime" in windows
    assert 'pushd "%~dp0"' in windows

    assert 'WEB_SOURCE="$PROJECT_ROOT/web"' in linux
    assert '"$SOURCE_ROOT/tools/prepare_web_runtime.py"' in linux
    assert "${XDG_DATA_HOME:-$HOME/.local/share}" in linux

    for launcher in (mac, windows, linux):
        assert "source/.venv" not in launcher
        assert "release/" not in launcher
        assert "launch_doctor.py" in launcher
        assert "run_web_servers.py" in launcher
