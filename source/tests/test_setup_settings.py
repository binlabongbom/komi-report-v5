from datetime import date
import json
import sqlite3

import pytest

import database
from komi_snmp_profiler.credential_store import SessionCredentialStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.peer_settings_history import SettingsHistory
from services.pricing import PriceList, PricingRepository
from services.setup_settings import SetupSettingsService


def state():
    with database._open(commit=False) as conn:
        return {table: list(conn.execute(f"SELECT * FROM {table} ORDER BY 1")) for table in (
            "settings", "devices", "price_history", "config_log", "peer_settings_state", "peer_settings_revisions")}


def make_preview(service, *, password="synthetic secret", amount=2):
    return service.preview([DeviceConfig(0, "Test", "192.0.2.10", serial="SYNTH-1", password=password)],
        {"company_name": "Test Company", "client_first_started_at": "2026-09-01",
         "installation_id": "local-only-identity", "billing_day": "15"},
        [(0, date(2026, 10, 1), PriceList(a4_bw=amount))])


def test_initial_setup_and_future_prices_are_atomic_audited_and_secret_free():
    vault = SessionCredentialStore()
    repo = DeviceConfigRepository(vault)
    service = SetupSettingsService(repo)
    before = state()
    preview = make_preview(service)
    assert state() == before
    revision = service.commit(preview)
    packet = SettingsHistory().export()
    payload = packet["revisions"][revision]["payload"]
    assert payload["format_version"] == 2
    assert payload["price_history"][0]["effective_date"] == "2026-10-01"
    assert payload["price_history"][0]["a4_bw"] == 2
    assert "prices" not in payload["devices"][0]
    assert "synthetic secret" not in json.dumps(state())
    assert "local-only-identity" not in json.dumps(packet)
    assert "credential" not in json.dumps(packet)
    assert repo.load_credential("192.0.2.10").password == "synthetic secret"
    assert PricingRepository().get_prices(0, date(2026, 9, 30)).a4_bw == 0
    assert PricingRepository().get_prices(0, date(2026, 10, 1)).a4_bw == 2
    assert SettingsHistory().observe_current() == revision


@pytest.mark.parametrize("failure", ["price", "journal", "head"])
def test_failed_related_save_restores_database_cache_and_vault(failure, monkeypatch):
    repo = DeviceConfigRepository(SessionCredentialStore())
    service = SetupSettingsService(repo)
    service.commit(make_preview(service, password="previous"))
    database.get_cfg("billing_day")
    preview = make_preview(service, password="new-password", amount=3)
    if failure == "journal":
        monkeypatch.setattr(SettingsHistory, "_append", lambda *_args: (_ for _ in ()).throw(RuntimeError("injected")))
    else:
        with database._open() as conn:
            sql = ("BEFORE INSERT ON price_history" if failure == "price" else
                   "BEFORE UPDATE ON peer_settings_state WHEN NEW.key='head'")
            conn.execute(f"CREATE TRIGGER fail_save {sql} BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = state()
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="injected"):
        service.commit(preview)
    assert state() == before
    assert database.get_cfg("billing_day") == "15"
    assert repo.load_credential("192.0.2.10").password == "previous"


def test_new_vault_entry_is_removed_if_initial_history_save_fails(monkeypatch):
    vault = SessionCredentialStore()
    repo = DeviceConfigRepository(vault)
    service = SetupSettingsService(repo)
    preview = make_preview(service)
    before = state()
    saved = []
    original = vault.save
    def save(reference, credential):
        saved.append(reference)
        original(reference, credential)
    monkeypatch.setattr(vault, "save", save)
    monkeypatch.setattr(SettingsHistory, "_append", lambda *_args: (_ for _ in ()).throw(RuntimeError("injected")))
    with pytest.raises(RuntimeError):
        service.commit(preview)
    assert state() == before
    assert saved and all(vault.load(key) is None for key in saved)


def test_stale_setup_does_not_overwrite_another_settings_save_or_vault():
    repo = DeviceConfigRepository(SessionCredentialStore())
    service = SetupSettingsService(repo)
    service.commit(make_preview(service, password="previous"))
    preview = make_preview(service, password="new")
    database.set_cfg("billing_day", "25")
    before = state()
    with pytest.raises(ValueError, match="เปลี่ยน"):
        service.commit(preview)
    assert state() == before
    assert repo.load_credential("192.0.2.10").password == "previous"


def test_snapshot_is_stable_across_calendar_change(monkeypatch):
    from services import secondary_setup
    service = SetupSettingsService(DeviceConfigRepository(SessionCredentialStore()))
    revision = service.commit(make_preview(service))
    class NextYear(date):
        @classmethod
        def today(cls):
            return cls(2027, 1, 1)
    monkeypatch.setattr(secondary_setup, "date", NextYear)
    assert SettingsHistory().observe_current() == revision


def test_past_future_and_removed_slot_prices_are_retained():
    service = SetupSettingsService(DeviceConfigRepository(SessionCredentialStore()))
    service.commit(make_preview(service))
    with database._open() as conn:
        conn.execute("INSERT INTO devices(slot,name,host,enabled,updated_at) VALUES(2,'Retired','192.0.2.12',0,'2025-01-01')")
    PricingRepository().set_prices(2, date(2025, 1, 1), PriceList(a4_bw=1))
    preview = service.preview([DeviceConfig(0, "Test", "192.0.2.10", serial="SYNTH-1")], {},
                              [(0, date(2027, 1, 1), PriceList(a4_bw=4))])
    revision = service.commit(preview)
    rows = SettingsHistory().export()["revisions"][revision]["payload"]["price_history"]
    assert [(r["slot"], r["effective_date"]) for r in rows] == [(0, "2026-10-01"), (0, "2027-01-01"), (2, "2025-01-01")]


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), -1, 10000, True])
def test_invalid_price_is_rejected_without_writes(amount):
    service = SetupSettingsService(DeviceConfigRepository(SessionCredentialStore()))
    before = state()
    with pytest.raises(ValueError, match="price"):
        make_preview(service, amount=amount)
    assert state() == before
