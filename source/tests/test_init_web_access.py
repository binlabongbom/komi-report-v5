from __future__ import annotations

from pathlib import Path

import pytest

from services.web_access import (
    ACCESS_CONFIGURED_KEY,
    ACCESS_HASH_KEY,
    AUTH_EPOCH_KEY,
    LEGACY_ACCESS_CODE_KEY,
    REPORT_PASSWORDLESS_KEY,
    SESSION_SECRET_KEY,
    USER_KEY,
    set_web_access_code,
    set_web_report_passwordless,
    verify_web_access_code,
    web_access_status,
)
from tools.init_web_access import ensure_web_access


def _read_values(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def test_web_access_is_created_outside_the_shared_source(tmp_path):
    runtime_env = tmp_path / "runtime" / ".env.local"

    values = ensure_web_access(runtime_env)

    assert runtime_env.is_file()
    assert values[USER_KEY] == "admin"
    assert values[ACCESS_HASH_KEY].startswith("scrypt:")
    assert values[ACCESS_CONFIGURED_KEY] == "0"
    assert values[SESSION_SECRET_KEY] != "komi-report-v5-local-session"
    assert len(values[SESSION_SECRET_KEY]) >= 32
    assert len(values[AUTH_EPOCH_KEY]) >= 32
    assert values[REPORT_PASSWORDLESS_KEY] == "1"
    assert LEGACY_ACCESS_CODE_KEY not in runtime_env.read_text(encoding="utf-8")
    assert not web_access_status(runtime_env).configured


def test_web_access_migrates_existing_values_once(tmp_path):
    legacy = tmp_path / "shared-web" / ".env.local"
    legacy.parent.mkdir()
    legacy.write_text(
        "KOMI_WEB_USER=bom\n"
        "KOMI_WEB_ACCESS_CODE=existing-code\n"
        "KOMI_WEB_SESSION_SECRET=existing-secret\n",
        encoding="utf-8",
    )
    runtime_env = tmp_path / "runtime" / ".env.local"

    first = ensure_web_access(runtime_env, migrate_from=legacy)
    legacy.write_text("KOMI_WEB_USER=changed\n", encoding="utf-8")
    second = ensure_web_access(runtime_env, migrate_from=legacy)

    assert first == second
    stored = _read_values(runtime_env)
    assert stored[USER_KEY] == "bom"
    assert stored[SESSION_SECRET_KEY] == "existing-secret"
    assert stored[ACCESS_CONFIGURED_KEY] == "1"
    assert LEGACY_ACCESS_CODE_KEY not in stored
    assert verify_web_access_code("existing-code", stored[ACCESS_HASH_KEY])
    assert web_access_status(runtime_env).configured


def test_web_access_migrates_short_legacy_code_without_locking_out_user(tmp_path):
    legacy = tmp_path / "shared-web" / ".env.local"
    legacy.parent.mkdir()
    legacy.write_text("KOMI_WEB_ACCESS_CODE=short\n", encoding="utf-8")
    runtime_env = tmp_path / "runtime" / ".env.local"

    values = ensure_web_access(runtime_env, migrate_from=legacy)

    assert values[ACCESS_CONFIGURED_KEY] == "1"
    assert verify_web_access_code("short", values[ACCESS_HASH_KEY])
    assert LEGACY_ACCESS_CODE_KEY not in runtime_env.read_text(encoding="utf-8")


def test_desktop_change_rotates_session_version_and_never_stores_plaintext(tmp_path):
    runtime_env = tmp_path / "runtime" / ".env.local"
    ensure_web_access(runtime_env)
    before = _read_values(runtime_env)

    status = set_web_access_code(runtime_env, "New-LAN-Code-2026")
    after = _read_values(runtime_env)

    assert status.configured
    assert after[ACCESS_CONFIGURED_KEY] == "1"
    assert after[AUTH_EPOCH_KEY] != before[AUTH_EPOCH_KEY]
    assert after[SESSION_SECRET_KEY] == before[SESSION_SECRET_KEY]
    assert verify_web_access_code("New-LAN-Code-2026", after[ACCESS_HASH_KEY])
    assert not verify_web_access_code("wrong-code", after[ACCESS_HASH_KEY])
    assert "New-LAN-Code-2026" not in runtime_env.read_text(encoding="utf-8")


def test_desktop_change_rejects_short_access_code(tmp_path):
    runtime_env = tmp_path / "runtime" / ".env.local"

    try:
        set_web_access_code(runtime_env, "short")
    except ValueError as error:
        assert "อย่างน้อย 12" in str(error)
    else:
        raise AssertionError("short Web access code must be rejected")


def test_desktop_change_rejects_ambiguous_outer_whitespace(tmp_path):
    runtime_env = tmp_path / "runtime" / ".env.local"

    with pytest.raises(ValueError, match="ช่องว่างที่ต้นหรือท้าย"):
        set_web_access_code(runtime_env, " Valid-LAN-Code-2026 ")


def test_password_lock_is_opt_in_and_rotates_sessions(tmp_path):
    runtime_env = tmp_path / "runtime" / ".env.local"
    ensure_web_access(runtime_env)
    set_web_access_code(runtime_env, "Configured-Password-2026")
    before = _read_values(runtime_env)

    disabled = set_web_report_passwordless(runtime_env, False)
    after_disabled = _read_values(runtime_env)
    assert not disabled.report_passwordless
    assert after_disabled[REPORT_PASSWORDLESS_KEY] == "0"
    assert after_disabled[AUTH_EPOCH_KEY] != before[AUTH_EPOCH_KEY]
    assert not web_access_status(runtime_env).report_passwordless
    ensure_web_access(runtime_env)
    assert not web_access_status(runtime_env).report_passwordless

    enabled = set_web_report_passwordless(runtime_env, True)
    after_enabled = _read_values(runtime_env)
    assert enabled.report_passwordless
    assert after_enabled[AUTH_EPOCH_KEY] != after_disabled[AUTH_EPOCH_KEY]


def test_old_unconfigured_install_opens_reports_after_migration(tmp_path):
    runtime_env = tmp_path / ".env.local"
    runtime_env.write_text("KOMI_WEB_ACCESS_CONFIGURED=0\nKOMI_WEB_ACCESS_HASH=unknown-generated-hash\nKOMI_WEB_REPORT_PASSWORDLESS=0\n")
    assert web_access_status(runtime_env).report_passwordless
    values = ensure_web_access(runtime_env)
    assert values[REPORT_PASSWORDLESS_KEY] == "1"
    assert values[ACCESS_CONFIGURED_KEY] == "0"


def test_cannot_lock_reports_without_setting_a_password(tmp_path):
    with pytest.raises(ValueError, match="ตั้งรหัสผ่าน"):
        set_web_report_passwordless(tmp_path / ".env.local", False)
    assert web_access_status(tmp_path / ".env.local").report_passwordless


def test_setting_staff_code_keeps_reports_open_with_partial_runtime_settings(tmp_path):
    env = tmp_path / ".env.local"
    env.write_text("KOMI_WEB_PORT=3443\n", encoding="utf-8")
    status = set_web_access_code(env, "Configured-Password-2026")
    assert status.configured and status.report_passwordless
    assert _read_values(env)[REPORT_PASSWORDLESS_KEY] == "1"
