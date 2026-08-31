"""Build a clean, self-contained Windows x64 test kit.

The kit bundles the official CPython 3.11 embeddable runtime and Windows wheels,
so the target computer does not need Python, pip, or internet access.  This is a
portable source/runtime bundle, not a cross-built Windows executable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from services.v5_2_contract_metadata import CONTRACT_SHA256, CONTRACT_VERSION
from tools.release_safety import assert_release_safe, assert_tree_safe, assert_zip_safe, git_identity
from tools.version_gate import assert_v5_2_version_alignment

SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SOURCE_ROOT.parent
VERSION = tomllib.loads((SOURCE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
RELEASE_ROOT = PROJECT_ROOT / "release"
WINDOWS_REQUIREMENTS = SOURCE_ROOT / "requirements-windows-x64.lock.txt"
KIT_NAME = "KOMI Report V5 Windows Portable"
ARCHIVE_NAME = f"KOMI_Report_V{VERSION.replace('.', '_')}_Windows_x64_Portable.zip"
PYTHON_VERSION = "3.11.9"
PYTHON_EMBED_ARCHIVE = f"python-{PYTHON_VERSION}-embed-amd64.zip"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{PYTHON_EMBED_ARCHIVE}"
)

ROOT_FILES = (
    "app.py",
    "config.py",
    "database.py",
    "i18n.py",
    "komi_version.py",
    "live_meter_page.py",
    "migrations.py",
    "observability.py",
    "pages.py",
    "parser.py",
    "parser_profiles.py",
    "runtime_config.py",
    "ui_consistency.py",
    "v5_pages.py",
    "web_api.py",
    "widgets.py",
    "requirements.txt",
    "requirements.lock.txt",
    "requirements-windows-x64.lock.txt",
    "pyproject.toml",
    "logo.png",
    "Logo.ico",
    "RELEASE_NOTES.txt",
)
PACKAGE_DIRS = ("services", "komi_snmp_profiler", "ui")
TOOL_FILES = (
    "__init__.py",
    "check_parser.py",
    "db_recovery.py",
    "default_profiles.json",
)
DOC_FILES = (
    "PILOT_RELEASE_CHECKLIST.md",
    "RELEASE_RUNBOOK.md",
    "data-storage-overview.png",
    "sync-rule-flowchart.png",
)

SETUP_CMD = r"""@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" >nul 2>&1 || (
  echo [ERROR] Unable to open the KOMI Report V5 folder.
  echo Copy the complete folder to a local drive and try again.
  pause
  exit /b 1
)
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"

echo ============================================================
echo   KOMI Report V5 - Portable Windows
echo ============================================================
echo.
echo Python and program libraries are already included.
call "START_KOMI_REPORT.cmd"
set "KOMI_EXIT_CODE=%errorlevel%"
popd
exit /b %KOMI_EXIT_CODE%
"""

START_CMD = r"""@echo off
setlocal
chcp 65001 >nul
set "KOMI_UNC_LAUNCH=0"
set "KOMI_LAUNCH_DIR=%~dp0"
if "%KOMI_LAUNCH_DIR:~0,2%"=="\\" set "KOMI_UNC_LAUNCH=1"
pushd "%~dp0" >nul 2>&1 || (
  echo [ERROR] Unable to open the KOMI Report V5 folder.
  echo Copy the complete folder to a local drive and try again.
  pause
  exit /b 1
)
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"

if not exist "runtime\pythonw.exe" (
  echo [ERROR] Portable Python runtime was not found.
  echo Copy or extract the complete KOMI Report V5 folder and try again.
  pause
  popd
  exit /b 1
)

if "%KOMI_UNC_LAUNCH%"=="1" (
  rem Keep the temporary drive created by PUSHD alive while the app is running.
  start "" /wait "runtime\pythonw.exe" "app.py"
) else (
  start "" "runtime\pythonw.exe" "app.py"
)
set "KOMI_EXIT_CODE=%errorlevel%"
popd
exit /b %KOMI_EXIT_CODE%
"""

START_DEBUG_CMD = r"""@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" >nul 2>&1 || (
  echo [ERROR] Unable to open the KOMI Report V5 folder.
  echo Copy the complete folder to a local drive and try again.
  pause
  exit /b 1
)
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"

if not exist "runtime\python.exe" (
  echo [ERROR] Portable Python runtime was not found.
  pause
  popd
  exit /b 1
)

"runtime\python.exe" "app.py"
set "KOMI_EXIT_CODE=%errorlevel%"
echo.
echo KOMI Report V5 closed. Press any key to close this window.
pause >nul
popd
exit /b %KOMI_EXIT_CODE%
"""

README = """KOMI Report V5 — Windows Portable Test Kit
วันที่แพ็ก: {built_date}

รองรับ
- Windows 10 หรือ Windows 11 แบบ 64-bit
- เครื่องทดสอบต้องอยู่ในเครือข่ายเดียวกับเครื่องพิมพ์
- รวม Python {python_version} x64 และ Library ที่จำเป็นไว้แล้ว
- ไม่ต้องติดตั้ง Python, pip หรือเชื่อมต่ออินเทอร์เน็ต

วิธีใช้
1. คัดลอกโฟลเดอร์นี้จาก SSD ไปไว้บน Desktop ของเครื่อง Windows
2. ดับเบิลคลิก START_KOMI_REPORT.cmd
3. โปรแกรมจะเปิด Setup Wizard และสร้าง Database ใหม่ใน
   C:\\Users\\<ชื่อผู้ใช้>\\KOMI Report V5\\

หากโปรแกรมปิดหรือไม่แสดงหน้าต่าง
- ดับเบิลคลิก START_DEBUG.cmd แล้วถ่ายภาพข้อความในหน้าต่าง Command Prompt
- Log อยู่ที่ C:\\Users\\<ชื่อผู้ใช้>\\KOMI Report V5\\logs\\

ข้อควรทราบ
- ชุดนี้เป็น Portable Runtime Test Kit ไม่ใช่ไฟล์ EXE เดี่ยว
- ต้องเก็บโฟลเดอร์ runtime และไฟล์โปรแกรมไว้ด้วยกัน ห้ามย้ายเฉพาะ app.py
- Python ที่รวมไว้เป็น official CPython embeddable package สำหรับ Windows x64
- ชุดนี้ไม่มี Database, Log, Runtime Cache หรือ Password จากเครื่องพัฒนา
- โปรแกรมไม่มี SNMP write และ Web Connection ใช้การอ่าน Meter เท่านั้น
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_python_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.suffix not in {".py", ".json"}:
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def download_wheelhouse(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(destination),
        "--only-binary=:all:",
        "--platform",
        "win_amd64",
        "--implementation",
        "cp",
        "--python-version",
        "3.11",
        "--abi",
        "cp311",
        "--require-hashes",
        "-r",
        str(WINDOWS_REQUIREMENTS),
    ]
    subprocess.run(command, check=True)


def download_python_runtime(destination: Path) -> str:
    """Download and extract the official CPython embeddable x64 runtime."""
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="komi-python-runtime-") as temp_dir:
        archive = Path(temp_dir) / PYTHON_EMBED_ARCHIVE
        urllib.request.urlretrieve(PYTHON_EMBED_URL, archive)
        runtime_sha256 = sha256(archive)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(destination)

    pth_file = destination / "python311._pth"
    if not pth_file.exists():
        raise RuntimeError("official Python runtime is missing python311._pth")
    pth_file.write_text(
        "python311.zip\n.\n..\nLib/site-packages\nimport site\n",
        encoding="utf-8",
        newline="\r\n",
    )
    return runtime_sha256


def install_windows_dependencies(wheelhouse: Path, destination: Path) -> None:
    """Unpack Windows CPython 3.11 wheels into the portable runtime."""
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        str(destination),
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--only-binary=:all:",
        "--platform",
        "win_amd64",
        "--implementation",
        "cp",
        "--python-version",
        "3.11",
        "--abi",
        "cp311",
        "--ignore-installed",
        "--no-warn-conflicts",
        "--upgrade",
        "--require-hashes",
        "-r",
        str(WINDOWS_REQUIREMENTS),
    ]
    subprocess.run(command, check=True)


def build_kit(output_root: Path) -> tuple[Path, Path, dict[str, object]]:
    assert_v5_2_version_alignment()
    output_root.mkdir(parents=True, exist_ok=True)
    kit_root = output_root / KIT_NAME
    if kit_root.exists():
        shutil.rmtree(kit_root)
    kit_root.mkdir(parents=True)

    for filename in ROOT_FILES:
        source = SOURCE_ROOT / filename
        if source.exists():
            shutil.copy2(source, kit_root / filename)

    for directory in PACKAGE_DIRS:
        copy_python_tree(SOURCE_ROOT / directory, kit_root / directory)

    tools_root = kit_root / "tools"
    tools_root.mkdir()
    for filename in TOOL_FILES:
        shutil.copy2(SOURCE_ROOT / "tools" / filename, tools_root / filename)

    docs_root = kit_root / "docs"
    docs_root.mkdir()
    for filename in DOC_FILES:
        shutil.copy2(PROJECT_ROOT / "docs" / filename, docs_root / filename)

    assert_release_safe(
        (path for path in kit_root.rglob("*") if path.is_file()),
        root=kit_root,
    )

    (kit_root / "SETUP_AND_START.cmd").write_text(SETUP_CMD, encoding="utf-8", newline="\r\n")
    (kit_root / "START_KOMI_REPORT.cmd").write_text(START_CMD, encoding="utf-8", newline="\r\n")
    (kit_root / "START_DEBUG.cmd").write_text(START_DEBUG_CMD, encoding="utf-8", newline="\r\n")

    built_at = datetime.now().astimezone()
    (kit_root / "README-WINDOWS.txt").write_text(
        README.format(
            built_date=built_at.strftime("%d/%m/%Y %H:%M"),
            python_version=PYTHON_VERSION,
        ),
        encoding="utf-8-sig",
        newline="\r\n",
    )

    runtime_root = kit_root / "runtime"
    runtime_sha256 = download_python_runtime(runtime_root)
    with tempfile.TemporaryDirectory(prefix="komi-wheelhouse-") as wheelhouse_dir:
        wheelhouse = Path(wheelhouse_dir)
        download_wheelhouse(wheelhouse)
        wheel_count = sum(1 for path in wheelhouse.glob("*.whl"))
        install_windows_dependencies(
            wheelhouse,
            runtime_root / "Lib" / "site-packages",
        )
    for cache_dir in sorted(runtime_root.rglob("__pycache__"), reverse=True):
        shutil.rmtree(cache_dir)
    for bytecode in runtime_root.rglob("*.py[co]"):
        bytecode.unlink()
    for metadata in kit_root.rglob("*"):
        if metadata.is_file() and (
            metadata.name == ".DS_Store" or metadata.name.startswith("._")
        ):
            metadata.unlink()

    forbidden = {
        ".env",
        ".env.local",
        "KOMI_Report_V5.db",
        "runtime-cache",
        "logs",
        "__pycache__",
        ".DS_Store",
    }
    found_forbidden = [
        str(path.relative_to(kit_root))
        for path in kit_root.rglob("*")
        if any(part in forbidden or part.startswith("._") for part in path.parts)
        or path.suffix in {".pyc", ".pyo"}
    ]
    if found_forbidden:
        raise RuntimeError(f"unsafe files in kit: {found_forbidden[:10]}")
    assert_tree_safe(kit_root, scan_secrets=False)

    archive = output_root / ARCHIVE_NAME
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(kit_root.rglob("*")):
            if path.is_file():
                zipped.write(path, Path(KIT_NAME) / path.relative_to(kit_root))
    assert_zip_safe(archive, scan_secrets=False)

    commit, source_state = git_identity(PROJECT_ROOT)
    manifest = {
        "version": VERSION,
        "contract_version": CONTRACT_VERSION,
        "contract_sha256": CONTRACT_SHA256,
        "package": KIT_NAME,
        "artifact": ARCHIVE_NAME,
        "artifact_identity": f"komi-report-v5-windows-x64-{VERSION}-{commit[:12]}",
        "git_commit": commit,
        "source_state": source_state,
        "target_os": "Windows 10/11 x64",
        "runtime": f"Official CPython {PYTHON_VERSION} embeddable x64",
        "package_type": "portable-python-runtime",
        "requires_python_install": False,
        "requires_internet": False,
        "python_runtime_source": PYTHON_EMBED_URL,
        "python_runtime_archive_sha256": runtime_sha256,
        "archive_sha256": sha256(archive),
        "file_count": sum(1 for path in kit_root.rglob("*") if path.is_file()),
        "bundled_wheel_count": wheel_count,
        "build_time": built_at.isoformat(timespec="seconds"),
        "contains_database": False,
        "contains_logs": False,
        "contains_runtime_cache": False,
        "contains_credentials": False,
    }
    manifest_path = output_root / "WINDOWS_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_root / f"{ARCHIVE_NAME}.sha256").write_text(
        f"{manifest['archive_sha256']}  {ARCHIVE_NAME}\n",
        encoding="ascii",
    )
    return kit_root, archive, manifest


def copy_to_drive(output_root: Path, drive: Path) -> Path:
    package_date = datetime.now().astimezone().strftime("%Y-%m-%d")
    destination = drive / f"KOMI Report V5 Windows Portable - {package_date}"
    with tempfile.TemporaryDirectory(dir=drive, prefix=".komi-windows-stage-") as temp_dir:
        staged = Path(temp_dir) / destination.name
        shutil.copytree(output_root, staged)
        if destination.exists():
            shutil.rmtree(destination)
        staged.rename(destination)
    if sys.platform == "darwin":
        subprocess.run(
            ["dot_clean", "-m", str(destination)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for metadata in list(destination.rglob("*")):
            if metadata.is_file() and (
                metadata.name == ".DS_Store" or metadata.name.startswith("._")
            ):
                metadata.unlink()
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive", type=Path, help="Optional mounted drive, e.g. /Volumes/KINGSTON")
    args = parser.parse_args()

    output_root = RELEASE_ROOT / "windows-portable"
    kit_root, archive, manifest = build_kit(output_root)
    print(f"kit={kit_root}")
    print(f"archive={archive}")
    print(f"sha256={manifest['archive_sha256']}")
    print(f"files={manifest['file_count']}")
    print(f"bundled_wheels={manifest['bundled_wheel_count']}")

    if args.drive:
        destination = copy_to_drive(output_root, args.drive)
        print(f"drive_destination={destination}")


if __name__ == "__main__":
    main()
