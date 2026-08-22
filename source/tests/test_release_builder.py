from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib

import pytest

from tools.build_local_release import (
    EXCLUDED_PARTS,
    PROJECT_ROOT,
    _included_files,
    build_source_archive,
)
from tools.package_windows_test_kit import (
    SETUP_CMD,
    START_CMD,
    START_DEBUG_CMD,
    build_kit,
)
from tools.release_safety import ReleaseSafetyError, assert_release_safe


def test_source_release_excludes_runtime_data_dependencies_and_secrets():
    files = _included_files()
    relative_paths = [path.relative_to(PROJECT_ROOT).as_posix() for path in files]

    assert files
    assert any(path.name == "RELEASE_RUNBOOK.md" for path in files)
    assert any(path.name == "KOMI_Report_V5.iss" for path in files)
    for path in files:
        assert not any(part in EXCLUDED_PARTS for part in path.parts)
        assert not path.name.startswith(".env")
        assert path.suffix.casefold() not in {
            ".csv",
            ".db",
            ".key",
            ".log",
            ".p12",
            ".pem",
            ".sqlite",
            ".sqlite3",
            ".xls",
            ".xlsx",
        }
    assert all("node_modules" not in relative for relative in relative_paths)
    assert "web/app/status.css" not in relative_paths
    assert "web/next-env.d.ts" not in relative_paths
    assert "source/overview-v2-preview.png" not in relative_paths
    assert not any(relative.startswith(("outputs/", "exports/")) for relative in relative_paths)
    assert "source/komi-billing-audit-2026-08-21.csv" not in relative_paths


def test_release_safety_gate_proves_forbidden_file_and_secret_failures(tmp_path):
    export = tmp_path / "outputs" / "customer-report.csv"
    export.parent.mkdir()
    export.write_text("customer,data\n", encoding="utf-8")
    with pytest.raises(ReleaseSafetyError) as forbidden_error:
        assert_release_safe([export], root=tmp_path)
    assert {item.category for item in forbidden_error.value.findings} >= {
        "forbidden-path",
        "forbidden-file-type",
    }

    secret = tmp_path / "safe" / "settings.txt"
    secret.parent.mkdir()
    fake_token = "gh" + "p_" + ("A" * 32)
    secret.write_text(f"token={fake_token}\n", encoding="utf-8")
    with pytest.raises(ReleaseSafetyError) as secret_error:
        assert_release_safe([secret], root=tmp_path)
    assert [item.category for item in secret_error.value.findings] == ["github-token"]


def test_release_versions_are_aligned_to_5_1_0():
    expected = "5.1.0"
    config_text = (PROJECT_ROOT / "source" / "config.py").read_text(encoding="utf-8")
    spec_text = (PROJECT_ROOT / "source" / "app.spec").read_text(encoding="utf-8")
    project = tomllib.loads(
        (PROJECT_ROOT / "source" / "pyproject.toml").read_text(encoding="utf-8")
    )
    web_package = json.loads(
        (PROJECT_ROOT / "web" / "package.json").read_text(encoding="utf-8")
    )
    web_lock = json.loads(
        (PROJECT_ROOT / "web" / "package-lock.json").read_text(encoding="utf-8")
    )

    assert re.search(r'APP_VER\s*=\s*"5\.1\.0"', config_text)
    assert re.search(r'PACKAGE_VERSION\s*=\s*"5\.1\.0"', config_text)
    assert project["project"]["version"] == expected
    assert web_package["version"] == expected
    assert web_lock["version"] == expected
    assert web_lock["packages"][""]["version"] == expected
    assert 'CFBundleShortVersionString": "5.1.0"' in spec_text
    assert 'CFBundleVersion": "50100"' in spec_text
    assert "KOMI Report V5.1.app" not in spec_text


def test_source_release_manifest_contains_traceability_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("tools.build_local_release.RELEASE_DIR", tmp_path)

    archive, digest, count = build_source_archive()
    manifest = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))

    assert count > 0
    assert count == manifest["file_count"]
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert manifest["version"] == "5.1.0"
    assert manifest["artifact"] == archive.name
    assert manifest["artifact_identity"].startswith("komi-report-v5-source-5.1.0-")
    assert manifest["git_commit"]
    assert manifest["source_state"] in {"clean", "dirty", "uncommitted"}
    assert manifest["build_time"]
    assert manifest["sha256"] == digest


def test_release_builder_uses_semantic_version_bumps():
    from build import bump

    assert bump("5.1.0", "patch") == "5.1.1"
    assert bump("5.1.0", "minor") == "5.2.0"
    assert bump("5.1.0", "major") == "6.0.0"


def test_macos_bundle_disables_runtime_bytecode_writes():
    spec = (PROJECT_ROOT / "source" / "app.spec").read_text(encoding="utf-8")
    hook = PROJECT_ROOT / "source" / "runtime_hooks" / "no_bytecode.py"

    assert "runtime_hooks=['runtime_hooks/no_bytecode.py']" in spec
    assert "'distutils'" not in spec
    assert "FORBIDDEN_SUFFIXES" in spec
    assert "a.datas = [" in spec
    assert "sys.dont_write_bytecode = True" in hook.read_text(encoding="utf-8")


def test_macos_archive_keeps_secret_scanning_enabled():
    packager = (PROJECT_ROOT / "source" / "tools" / "package_macos_release.py").read_text(
        encoding="utf-8"
    )

    assert "assert_zip_safe(ARCHIVE)" in packager
    assert "scan_secrets=False" not in packager


def test_windows_portable_launchers_support_unc_redirected_folders():
    for launcher in (SETUP_CMD, START_CMD, START_DEBUG_CMD):
        assert 'pushd "%~dp0"' in launcher
        assert 'cd /d "%~dp0"' not in launcher
        assert "popd" in launcher

    assert 'set "KOMI_LAUNCH_DIR=%~dp0"' in START_CMD
    assert 'if "%KOMI_LAUNCH_DIR:~0,2%"=="\\\\"' in START_CMD
    assert 'start "" /wait "runtime\\pythonw.exe" "app.py"' in START_CMD


def test_windows_portable_build_removes_macos_metadata(tmp_path, monkeypatch):
    def fake_runtime(destination):
        destination.mkdir(parents=True)
        (destination / "python.exe").write_bytes(b"runtime")
        (destination / ".DS_Store").write_bytes(b"metadata")
        return "runtime-sha"

    def fake_wheelhouse(destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "dependency.whl").write_bytes(b"wheel")

    def fake_install(_wheelhouse, destination):
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "._dependency.py").write_bytes(b"metadata")
        (destination / "dependency.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "tools.package_windows_test_kit.download_python_runtime", fake_runtime
    )
    monkeypatch.setattr(
        "tools.package_windows_test_kit.download_wheelhouse", fake_wheelhouse
    )
    monkeypatch.setattr(
        "tools.package_windows_test_kit.install_windows_dependencies", fake_install
    )

    kit_root, _archive, manifest = build_kit(tmp_path)

    assert manifest["file_count"] > 0
    assert not list(kit_root.rglob(".DS_Store"))
    assert not [path for path in kit_root.rglob("*") if path.name.startswith("._")]
    for required in (
        "i18n.py",
        "migrations.py",
        "observability.py",
        "runtime_config.py",
        "ui_consistency.py",
        "requirements.lock.txt",
        "requirements-windows-x64.lock.txt",
        "ui/cloud_reports.py",
        "ui/common_dialogs.py",
    ):
        assert (kit_root / required).is_file()

    environment = os.environ.copy()
    environment.update(
        {
            "KOMI_APP_HOME": str(tmp_path / "runtime-home"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(kit_root),
            "QT_QPA_PLATFORM": "offscreen",
        }
    )
    subprocess.run(
        [sys.executable, "-c", "import app; import web_api"],
        cwd=kit_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
