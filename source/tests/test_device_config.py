from __future__ import annotations

import secrets
from datetime import UTC, datetime

import pytest

from database import _open, factory_reset_v5, init_db, reset_usage_data, set_db_path
from komi_snmp_profiler.credential_store import CredentialStoreError, SessionCredentialStore
from services.device_config import DatabaseCredentialStore, DeviceConfig, DeviceConfigRepository
from services.registration_data_notice import REGISTRATION_NOTICE_VERSION
from services.registration_envelope import build_registration_envelope
from services.registration_repository import RegistrationRepository
from services.registration_vault import SessionRegistrationSecretStore
from services.v5_2_runtime_state import V52RuntimeStateRepository


def test_device_repository_persists_one_to_three_devices(tmp_path):
    set_db_path(tmp_path / "devices.db")
    init_db()
    repository = DeviceConfigRepository()
    first_password = secrets.token_urlsafe(18)
    second_password = secrets.token_urlsafe(18)
    repository.replace_all(
        [
            DeviceConfig(0, "Office", "192.0.2.10", password=first_password),
            DeviceConfig(1, "Finance", "192.0.2.11", password=second_password),
        ]
    )

    devices = repository.list(enabled_only=True)

    assert [item.name for item in devices] == ["Office", "Finance"]
    assert devices[1].password == second_password
    assert repository.setup_complete() is True
    with _open(commit=False) as connection:
        stored = connection.execute("SELECT password,credential_ref FROM devices ORDER BY slot").fetchall()
    assert [row[0] for row in stored] == ["", ""]
    assert all(row[1].startswith("komi-report-v5:") for row in stored)


def test_database_credential_store_uses_per_device_password(tmp_path):
    set_db_path(tmp_path / "credentials.db")
    init_db()
    repository = DeviceConfigRepository()
    password = secrets.token_urlsafe(18)
    repository.replace_all([DeviceConfig(0, "Office", "192.0.2.10", password=password)])

    credential = DatabaseCredentialStore(repository).load("192.0.2.10")

    assert credential is not None
    assert credential.password == password


def test_device_edit_updates_registration_inventory_in_the_same_transaction(tmp_path):
    set_db_path(tmp_path / "atomic-inventory.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Old", "192.0.2.10")])
    state = V52RuntimeStateRepository()
    state.configure(
        "offline",
        "Synthetic Company",
        "atomic-installation",
        "2026-08-31",
        REGISTRATION_NOTICE_VERSION,
        "2026-08-31T08:00:00+07:00",
        registration_devices=[
            {
                "serial_number": "OLD-SERIAL",
                "model": "Old Printer",
                "selected": True,
                "device_slot": 1,
            }
        ],
    )

    repository.replace_all(
        [DeviceConfig(0, "New", "192.0.2.11")],
        registration_devices=[
            {
                "serial_number": "NEW-SERIAL",
                "model": "New Printer",
                "selected": True,
                "device_slot": 1,
            }
        ],
    )

    assert [device.name for device in repository.list()] == ["New"]
    assert state.registration_devices()[0]["serial_number"] == "NEW-SERIAL"
    assert state.internal()["mode"] == "offline"


def test_device_edit_rolls_back_when_registration_state_is_missing(tmp_path):
    set_db_path(tmp_path / "atomic-inventory-failure.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Old", "192.0.2.10")])

    with pytest.raises(ValueError, match="runtime is not configured"):
        repository.replace_all(
            [DeviceConfig(0, "New", "192.0.2.11")],
            registration_devices=[
                {
                    "serial_number": "NEW-SERIAL",
                    "model": "New Printer",
                    "selected": True,
                    "device_slot": 1,
                }
            ],
        )

    devices = repository.list()
    assert [(device.name, device.host) for device in devices] == [
        ("Old", "192.0.2.10")
    ]


def test_printer_tls_policy_defaults_to_system_and_persists_explicit_pin(tmp_path):
    set_db_path(tmp_path / "tls-policy.db")
    init_db()
    fingerprint = "ab" * 32
    repository = DeviceConfigRepository()
    repository.replace_all(
        [
            DeviceConfig(
                0,
                "Office",
                "192.0.2.10",
                tls_mode="fingerprint",
                tls_fingerprint=fingerprint,
            )
        ]
    )

    assert repository.tls_policy("192.0.2.10").fingerprint_sha256 == fingerprint
    assert repository.tls_policy("192.0.2.99").mode == "system"


def test_legacy_plaintext_migration_is_rollback_safe_when_vault_fails(tmp_path):
    set_db_path(tmp_path / "legacy-failure.db")
    init_db()
    legacy_password = secrets.token_urlsafe(18)
    with _open() as connection:
        connection.execute(
            """INSERT INTO devices(slot,name,host,username,password,enabled,updated_at)
               VALUES(0,'Office','192.0.2.10','administrator',?,1,'2026-08-22')""",
            (legacy_password,),
        )

    class FailingVault(SessionCredentialStore):
        def save(self, host, credential):
            raise CredentialStoreError("vault unavailable")

    repository = DeviceConfigRepository(FailingVault())

    try:
        repository.migrate_legacy_plaintext_credentials()
    except CredentialStoreError:
        pass
    else:
        raise AssertionError("vault failure must block migration")

    with _open(commit=False) as connection:
        row = connection.execute("SELECT password,credential_ref FROM devices WHERE slot=0").fetchone()
    assert row == (legacy_password, "")


def test_new_credential_fails_without_writing_plaintext_when_vault_is_unavailable(tmp_path):
    set_db_path(tmp_path / "new-failure.db")
    init_db()

    class FailingVault(SessionCredentialStore):
        def save(self, host, credential):
            raise CredentialStoreError("vault unavailable")

    repository = DeviceConfigRepository(FailingVault())
    password = secrets.token_urlsafe(18)

    try:
        repository.replace_all([DeviceConfig(0, "Office", "192.0.2.10", password=password)])
    except CredentialStoreError:
        pass
    else:
        raise AssertionError("new save must fail closed when vault is unavailable")

    with _open(commit=False) as connection:
        assert connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0


def test_legacy_plaintext_migrates_to_fake_vault_and_is_removed_from_sqlite(tmp_path):
    set_db_path(tmp_path / "legacy-success.db")
    init_db()
    legacy_password = secrets.token_urlsafe(18)
    with _open() as connection:
        connection.execute(
            """INSERT INTO devices(slot,name,host,username,password,enabled,updated_at)
               VALUES(0,'Office','192.0.2.10','administrator',?,1,'2026-08-22')""",
            (legacy_password,),
        )
    vault = SessionCredentialStore()
    repository = DeviceConfigRepository(vault)

    assert repository.migrate_legacy_plaintext_credentials() == 1
    credential = repository.load_credential("192.0.2.10")

    assert credential is not None and credential.password == legacy_password
    with _open(commit=False) as connection:
        password, reference = connection.execute(
            "SELECT password,credential_ref FROM devices WHERE slot=0"
        ).fetchone()
    assert password == ""
    assert reference.startswith("komi-report-v5:")


def test_data_only_reset_keeps_completed_setup(tmp_path):
    set_db_path(tmp_path / "data-reset.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Office", "192.0.2.10")])

    with _open() as conn:
        conn.execute(
            """INSERT INTO readings(slot,machine_name,serial,read_date,read_date_iso,billing_month,mode,data_json,imported_at,file_name)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (0, "Office", "SERIAL", "2026-07-23", "2026-07-23", "2026-07", "import", "{}", "2026-07-23", "sample.txt"),
        )

    reset_usage_data()

    assert repository.setup_complete() is True
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 0


def test_factory_reset_removes_setup_and_restores_first_run_state(tmp_path):
    database_path = tmp_path / "factory-reset.db"
    set_db_path(database_path)
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    runtime_file = tmp_path / "runtime-cache" / "device-1" / "2026-07-23.json"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text("{}", encoding="utf-8")

    factory_reset_v5()

    assert repository.setup_complete() is False
    assert repository.list() == []
    assert not runtime_file.exists()
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 0
        trigger = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='billing_ledger_no_delete'"
        ).fetchone()
    assert trigger is not None


def test_factory_reset_removes_registration_state_and_scoped_vault_token(tmp_path):
    set_db_path(tmp_path / "factory-reset-registration.db")
    init_db()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    repository = RegistrationRepository()
    payload = build_registration_envelope(
        installation_id="install-factory-reset",
        company_name="KOMI-UAT-RESET",
        first_started_at="2026-08-22",
        app_version="5.1.0",
        devices=[
            {"serial_number": "SYNTHETIC-1", "model": "bizhub UAT", "selected": True, "device_slot": 1}
        ],
        created_at=now.isoformat(),
    )
    repository.upsert_profile_and_enqueue_register(
        payload, notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    operation = repository.claim_due(now=now)
    assert operation is not None
    token_ref = "registration-token-reference"
    repository.complete_success(
        operation,
        http_status=201,
        duration_ms=1,
        token_ref=token_ref,
        next_heartbeat_after_seconds=3600,
        now=now,
    )
    vault = SessionRegistrationSecretStore()
    vault.save(token_ref, "synthetic-token")

    factory_reset_v5(registration_secret_store=vault)

    assert vault.load(token_ref) is None
    assert RegistrationRepository().profile() is None
    with _open(commit=False) as connection:
        assert connection.execute("SELECT COUNT(*) FROM registration_outbox").fetchone()[0] == 0


def test_factory_reset_fails_closed_when_registration_vault_is_unavailable(tmp_path):
    set_db_path(tmp_path / "factory-reset-vault-failure.db")
    init_db()
    now = datetime(2026, 8, 22, 1, tzinfo=UTC)
    repository = RegistrationRepository()
    payload = build_registration_envelope(
        installation_id="install-vault-reset",
        company_name="KOMI-UAT-RESET",
        first_started_at="2026-08-22",
        app_version="5.1.0",
        devices=[
            {"serial_number": "SYNTHETIC-1", "model": "bizhub UAT", "selected": True, "device_slot": 1}
        ],
        created_at=now.isoformat(),
    )
    repository.upsert_profile_and_enqueue_register(
        payload, notice_version="notice-1", notice_accepted_at=now.isoformat(), now=now
    )
    operation = repository.claim_due(now=now)
    assert operation is not None
    repository.complete_success(
        operation,
        http_status=201,
        duration_ms=1,
        token_ref="registration-token-reference",
        next_heartbeat_after_seconds=3600,
        now=now,
    )

    class FailingVault(SessionRegistrationSecretStore):
        def delete(self, reference: str) -> None:
            raise CredentialStoreError("synthetic vault unavailable")

    vault = FailingVault()
    vault.save("registration-token-reference", "synthetic-token")
    with pytest.raises(CredentialStoreError):
        factory_reset_v5(registration_secret_store=vault)

    assert RegistrationRepository().profile() is not None
