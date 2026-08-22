from __future__ import annotations

from database import _open, factory_reset_v5, init_db, reset_usage_data, set_db_path
from services.device_config import DatabaseCredentialStore, DeviceConfig, DeviceConfigRepository


def test_device_repository_persists_one_to_three_devices(tmp_path):
    set_db_path(tmp_path / "devices.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all(
        [
            DeviceConfig(0, "Office", "192.0.2.10", password="one"),
            DeviceConfig(1, "Finance", "192.0.2.11", password="two"),
        ]
    )

    devices = repository.list(enabled_only=True)

    assert [item.name for item in devices] == ["Office", "Finance"]
    assert devices[1].password == "two"
    assert repository.setup_complete() is True


def test_database_credential_store_uses_per_device_password(tmp_path):
    set_db_path(tmp_path / "credentials.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Office", "192.0.2.10", password="secret-a")])

    credential = DatabaseCredentialStore(repository).load("192.0.2.10")

    assert credential is not None
    assert credential.password == "secret-a"


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
