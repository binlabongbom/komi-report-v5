from __future__ import annotations

import json
import sqlite3

import pytest

from tools.build_windows_rc import INNO_SCRIPT, RUNTIME_TOOL_FILES, START_CMD, source_identity
from tools.db_recovery import backup_database, inspect_database, restore_database
from tools.release_evidence import (
    ReleaseContractError,
    assert_native_payload_safe,
    assert_no_update_runtime_paths,
    assert_registration_fail_closed_payload,
    build_environment_label,
    cyclonedx_sbom,
    file_inventory,
    require_windows_x64,
)
from tools.release_safety import ReleaseSafetyError


def test_windows_rc_requires_target_native_x64_environment():
    assert require_windows_x64(platform_name="win32", machine="AMD64") == {
        "platform": "win32",
        "machine": "amd64",
        "evidence_level": "target-native-build",
    }

    with pytest.raises(ReleaseContractError, match="Windows x64"):
        require_windows_x64(platform_name="win32", machine="ARM64")
    with pytest.raises(ReleaseContractError, match="Windows x64"):
        require_windows_x64(platform_name="darwin", machine="arm64")


def test_environment_labels_never_promote_vm_or_arm_to_native():
    assert (
        build_environment_label(platform_name="win32", machine="AMD64", virtualized=False)
        == "windows-x64-native"
    )
    assert (
        build_environment_label(platform_name="win32", machine="AMD64", virtualized=True)
        == "windows-x64-vm-preflight"
    )
    assert (
        build_environment_label(platform_name="win32", machine="ARM64", virtualized=True)
        == "windows-arm64-vm-preflight"
    )


def test_update_runtime_gate_is_specific_and_fail_closed(tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "model.py").write_text("updated_at = '2026-08-22'\n", encoding="utf-8")
    assert_no_update_runtime_paths(safe)

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "update_client.py").write_text("KOMI_UPDATE_URL = 'https://invalid'\n", encoding="utf-8")
    with pytest.raises(ReleaseContractError, match="Phase 3 Update"):
        assert_no_update_runtime_paths(unsafe)


def test_registration_policy_artefact_is_never_packaged(tmp_path):
    (tmp_path / "source").mkdir()
    assert_registration_fail_closed_payload(tmp_path)

    (tmp_path / "registration-policy.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseContractError, match="must not enable Registration"):
        assert_registration_fail_closed_payload(tmp_path)


def test_inventory_is_sorted_and_hashes_each_payload_file(tmp_path):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "b.txt").write_text("b", encoding="utf-8")
    (payload / "a.txt").write_text("a", encoding="utf-8")

    inventory = file_inventory(payload)

    assert [item["path"] for item in inventory] == ["a.txt", "b.txt"]
    assert all(len(str(item["sha256"])) == 64 for item in inventory)


def test_sbom_covers_locked_python_and_web_dependencies(tmp_path):
    requirements = tmp_path / "requirements.lock.txt"
    requirements.write_text(
        "fastapi==0.141.1 \\\n+    --hash=sha256:abc\nPyQt6==6.10.2 \\\n+    --hash=sha256:def\n",
        encoding="utf-8",
    )
    package_lock = tmp_path / "package-lock.json"
    package_lock.write_text(
        json.dumps(
            {
                "packages": {
                    "": {"version": "5.1.0"},
                    "node_modules/next": {"version": "16.3.2"},
                    "node_modules/react": {"version": "19.2.8"},
                }
            }
        ),
        encoding="utf-8",
    )

    sbom = cyclonedx_sbom(
        version="5.1.0",
        source_commit="a" * 40,
        requirements_lock=requirements,
        package_lock=package_lock,
    )

    components = {(item["name"], item["version"]) for item in sbom["components"]}
    assert ("fastapi", "0.141.1") in components
    assert ("PyQt6", "6.10.2") in components
    assert ("next", "16.3.2") in components
    assert ("react", "19.2.8") in components


def test_offline_backup_and_restore_preserve_critical_counts(tmp_path):
    database = tmp_path / "KOMI_Report_V5.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE devices(id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("CREATE TABLE price_snapshot(id INTEGER PRIMARY KEY, cents INTEGER)")
        connection.execute("CREATE TABLE readings(id INTEGER PRIMARY KEY, total INTEGER)")
        connection.execute("CREATE TABLE billing_ledger(id INTEGER PRIMARY KEY, gross_cents INTEGER)")
        connection.execute("INSERT INTO devices(name) VALUES ('Synthetic device')")
        connection.execute("INSERT INTO price_snapshot(cents) VALUES (125)")
        connection.execute("INSERT INTO readings(total) VALUES (1000)")
        connection.execute("INSERT INTO billing_ledger(gross_cents) VALUES (125)")
        connection.execute("PRAGMA user_version=9")

    backup = tmp_path / "backup.db"
    backup_result = backup_database(database, backup)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM devices")
        connection.execute("DELETE FROM billing_ledger")

    restored = restore_database(backup, database)

    assert backup_result["integrity"] == "ok"
    assert restored["critical_counts_match_backup"] is True
    assert restored["after"]["critical_counts"] == {
        "devices": 1,
        "price_snapshot": 1,
        "readings": 1,
        "billing_ledger": 1,
    }
    assert inspect_database(database)["user_version"] == 9
    assert restored["rollback_backup"]


def test_native_payload_allows_only_traced_dependency_roots(tmp_path):
    payload = tmp_path / "payload"
    dependency = payload / "web-runtime-seed" / "node_modules" / "next" / "dist" / "server.js"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("export const version = 'synthetic';\n", encoding="utf-8")
    assert_native_payload_safe(payload)

    credential = payload / "web-runtime-seed" / "node_modules" / "next" / "test.pem"
    credential.write_text("synthetic", encoding="utf-8")
    with pytest.raises(ReleaseSafetyError, match="forbidden-file-type"):
        assert_native_payload_safe(payload)


def test_installer_is_per_user_stable_and_preserves_user_data():
    script = INNO_SCRIPT.read_text(encoding="utf-8")

    assert "AppId={{9C32D937-21A5-4A3A-90AE-F0662E60F24A}" in script
    assert "PrivilegesRequired=lowest" in script
    assert "DefaultDirName={localappdata}\\Programs\\KOMI Report V5" in script
    assert "UsePreviousAppDir=yes" in script
    assert "[UninstallDelete]" not in script
    assert "KOMI Report V5\\KOMI_Report_V5.db" not in script


def test_rc_launcher_seeds_web_runtime_and_runs_canonical_source_layout():
    assert 'set "KOMI_PROJECT_ROOT=%~dp0"' in START_CMD
    assert 'set "PATH=%~dp0node-runtime;%PATH%"' in START_CMD
    assert 'robocopy "web-runtime-seed"' in START_CMD
    assert '"runtime\\pythonw.exe" "source\\app.py"' in START_CMD
    assert "db_recovery.py" in RUNTIME_TOOL_FILES


def test_archived_source_commit_must_match_explicit_identity(tmp_path, monkeypatch):
    commit = "a" * 40
    (tmp_path / "SOURCE_COMMIT.txt").write_text(commit + "\n", encoding="ascii")
    monkeypatch.setattr("tools.build_windows_rc.PROJECT_ROOT", tmp_path)

    assert source_identity(commit) == (commit, "archive-clean")
    with pytest.raises(ReleaseContractError, match="does not match"):
        source_identity("b" * 40)
