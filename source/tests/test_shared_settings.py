from copy import deepcopy
import json
import sqlite3

import pytest

import database
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.peer_settings_history import SettingsHistory
from services.secondary_setup import primary_setup_snapshot, setup_snapshot_from_connection
from services.shared_settings import SharedSettingsService
from services.sync_schedule import default_schedule_windows, dump_schedule_windows


def configured(path=None):
    if path is not None:
        database.set_db_path(path)
        database.init_db()
    database.set_cfg("company_name", "Synthetic company")
    database.set_cfg("client_first_started_at", "2026-09-01")
    database.set_cfg("billing_day", "31")
    database.set_cfg("waste_paper_pct", "2")
    database.set_cfg("installation_id", str(database.get_db_path()))
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer", "192.0.2.10", serial="SYNTH-1")])
    return SharedSettingsService()


def state():
    with database._open(commit=False) as conn:
        return {
            "settings": list(conn.execute("SELECT * FROM settings ORDER BY key")),
            "head": list(conn.execute("SELECT * FROM peer_settings_state ORDER BY key")),
            "history": list(conn.execute("SELECT * FROM peer_settings_revisions ORDER BY revision")),
            "log": list(conn.execute("SELECT * FROM config_log ORDER BY id")),
        }


def test_transaction_snapshot_matches_setup_allowlist():
    configured()
    expected = primary_setup_snapshot()
    with database._open(commit=False) as conn:
        actual = setup_snapshot_from_connection(conn)
    expected.pop("generated_at")
    actual.pop("generated_at")
    assert actual == expected


def test_preview_and_cancel_do_not_write_and_save_is_audited():
    service = configured()
    before = state()
    preview = service.preview({"billing_day": 15, "waste_paper_pct": 3.5}, reason="billing_settings_saved")
    assert state() == before
    assert preview.changes["billing_day"] == (31, 15)
    revision = service.commit(preview)
    assert database.get_cfg("billing_day") == "15"
    assert database.get_cfg("waste_paper_pct") == "3.5"
    packet = SettingsHistory().export()
    doc = packet["revisions"][revision]
    assert packet["head"] == revision
    assert doc["payload"]["settings"]["billing_day"] == 15
    assert len(doc["parents"]) == 1
    assert len(packet["revisions"]) == 2
    assert doc["reason"] == "billing_settings_saved"
    assert "installation_id" not in json.dumps(packet)
    assert "credential" not in json.dumps(packet)
    assert state()["settings"] != before["settings"]
    unchanged = state()
    assert service.commit(service.preview({"billing_day": 15}, reason="same value")) == revision
    assert state() == unchanged


@pytest.mark.parametrize("stage", ["second_setting", "journal"])
def test_failure_rolls_back_all_settings_audit_and_cache(stage, monkeypatch):
    service = configured()
    database.get_cfg("billing_day")  # Prewarm the cache, including failure path.
    preview = service.preview({"billing_day": 15, "waste_paper_pct": 4.0}, reason="test_save")
    if stage == "second_setting":
        with database._open() as conn:
            conn.execute("CREATE TRIGGER fail_setting BEFORE INSERT ON settings "
                         "WHEN NEW.key='waste_paper_pct' BEGIN SELECT RAISE(ABORT,'injected'); END")
    else:
        original = SettingsHistory._append

        def fail(self, conn, payload, parents, reason):
            if reason == "test_save":
                raise RuntimeError("injected")
            return original(self, conn, payload, parents, reason)

        monkeypatch.setattr(SettingsHistory, "_append", fail)
    before = state()
    with pytest.raises((sqlite3.IntegrityError, RuntimeError), match="injected"):
        service.commit(preview)
    assert state() == before
    assert database.get_cfg("billing_day") == "31"
    assert float(database.get_cfg("waste_paper_pct")) == 2.0


def test_stale_preview_rejects_other_process_change_even_with_warm_cache():
    service = configured()
    database.get_cfg("billing_day")
    preview = service.preview({"billing_day": 15}, reason="test_save")
    with sqlite3.connect(database.get_db_path()) as conn:
        conn.execute("UPDATE settings SET value='20' WHERE key='billing_day'")
    before = state()
    with pytest.raises(ValueError, match="เปลี่ยน"):
        service.commit(preview)
    assert state() == before
    assert database.get_cfg("billing_day") == "20"


@pytest.mark.parametrize("changes", [
    {"installation_id": "other"}, {"company_name": "other"},
    {"billing_day": 0}, {"billing_day": 31.5}, {"billing_day": True},
    {"waste_paper_pct": float("nan")}, {"waste_paper_pct": float("inf")},
    {"sync_schedule_windows": "bad"},
])
def test_invalid_or_local_only_fields_never_write(changes):
    service = configured()
    before = state()
    with pytest.raises(ValueError):
        service.preview(changes, reason="bad input")
    assert state() == before


def test_schedule_disabling_and_selective_undo_are_new_revisions():
    service = configured()
    first = service.commit(service.preview({"billing_day": 15}, reason="first"))
    service.commit(service.preview({"sync_schedule_windows": "[]"}, reason="disable automatic reading"))
    preview = service.preview_undo(first, keys=["billing_day"], reason="Restore billing day")
    undo = service.commit(preview)
    assert undo != first
    assert database.get_cfg("billing_day") == "31"
    assert database.get_cfg("sync_schedule_windows") == "[]"
    assert SettingsHistory().export()["revisions"][undo]["reason"].startswith("undo:")
    with pytest.raises(ValueError, match="changed again"):
        service.preview_undo(first, keys=["billing_day"], reason="repeat")


def test_schedule_undo_can_restore_legacy_empty_value():
    service = configured()
    revision = service.commit(service.preview({"sync_schedule_windows": dump_schedule_windows(default_schedule_windows())}, reason="schedule"))
    service.commit(service.preview_undo(revision, keys=["sync_schedule_windows"], reason="restore"))
    assert database.get_cfg("sync_schedule_windows") == ""


def test_two_databases_conflict_choice_is_atomic_preserves_identity_and_deduplicates(tmp_path):
    a_path, b_path = tmp_path / "a.sqlite3", tmp_path / "b.sqlite3"
    a = configured(a_path)
    # Same initial revision, as established by setup pairing.
    root = SettingsHistory().observe_current()
    initial = SettingsHistory().export()
    configured(b_path)
    SettingsHistory().receive(initial)
    with database._open() as conn:
        conn.execute("INSERT INTO peer_settings_state VALUES('head', ?)", (root,))
    b = SharedSettingsService()
    remote = b.commit(b.preview({"billing_day": 20}, reason="B edited offline"))
    packet = SettingsHistory().export()
    database.set_db_path(a_path)
    local = a.commit(a.preview({"billing_day": 15}, reason="A edited offline"))
    assert SettingsHistory().receive(packet)["status"] == "conflict"
    choice = a.preview_choice(remote, chosen_head=remote, reason="Choose B")
    assert database.get_cfg("billing_day") == "15"
    resolved = a.commit(choice)
    assert database.get_cfg("billing_day") == "20"
    assert database.get_cfg("installation_id") == str(a_path)
    record = SettingsHistory().export()["revisions"][resolved]
    assert set(record["parents"]) == {local, remote}
    before = state()
    assert a.commit(a.preview_choice(remote, chosen_head=remote, reason="Duplicate delivery")) == resolved
    assert state() == before
    resolved_packet = SettingsHistory().export()
    database.set_db_path(b_path)
    assert SettingsHistory().receive(resolved_packet)["status"] == "incoming_newer"
    assert b.commit(b.preview_choice(resolved, chosen_head=resolved, reason="Accept resolution")) == resolved
    assert database.get_cfg("billing_day") == "20"
    assert database.get_cfg("installation_id") == str(b_path)
    final_packet = SettingsHistory().export()
    database.set_db_path(a_path)
    assert SettingsHistory().receive(final_packet)["status"] == "in_sync"


def test_preview_cannot_write_to_another_database_with_identical_values(tmp_path):
    service = configured(tmp_path / "first.sqlite3")
    preview = service.preview({"billing_day": 15}, reason="A edit")
    configured(tmp_path / "second.sqlite3")
    before = state()
    with pytest.raises(ValueError, match="เปลี่ยน"):
        service.commit(preview)
    assert state() == before


def test_peer_printer_change_cannot_bypass_replacement_workflow(tmp_path):
    configured()
    SettingsHistory().observe_current()
    other_path = tmp_path / "journal.sqlite3"
    from migrations import _migration_020_peer_settings_history, _migration_021_peer_settings_outbox
    with sqlite3.connect(other_path) as conn:
        _migration_020_peer_settings_history(conn)
        _migration_021_peer_settings_outbox(conn)
    other = SettingsHistory(other_path)
    snapshot = deepcopy(primary_setup_snapshot())
    snapshot["devices"][0]["serial"] = "REPLACED"
    remote = other.observe(snapshot)
    SettingsHistory().receive(other.export())
    before = state()
    with pytest.raises(ValueError, match="workflow"):
        SharedSettingsService().preview_choice(remote, chosen_head=remote, reason="must not bypass")
    assert state() == before


def test_usage_reset_preserves_settings_history_but_factory_reset_removes_it():
    from services.registration_vault import SessionRegistrationSecretStore
    service = configured()
    revision = service.commit(service.preview({"billing_day": 15}, reason="before reset"))
    database.reset_usage_data()
    assert SettingsHistory().export()["head"] == revision
    database.factory_reset_v5(registration_secret_store=SessionRegistrationSecretStore())
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT count(*) FROM peer_settings_revisions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM peer_settings_state").fetchone()[0] == 0


def test_peer_apply_failure_cannot_commit_values_without_the_new_head():
    from services.peer_settings_history import _revision
    service = configured()
    root = SettingsHistory().observe_current()
    packet = SettingsHistory().export()
    incoming = deepcopy(packet["revisions"][root])
    incoming["parents"] = [root]
    incoming["actor"] = "other-computer"
    incoming["payload"]["settings"]["billing_day"] = 15
    remote = _revision(incoming)
    packet["revisions"][remote] = incoming
    packet["head"] = remote
    SettingsHistory().receive(packet)
    preview = service.preview_choice(remote, chosen_head=remote, reason="accept")
    with database._open() as conn:
        conn.execute("CREATE TRIGGER fail_head BEFORE UPDATE ON peer_settings_state "
                     "WHEN NEW.key='head' BEGIN SELECT RAISE(ABORT,'head failure'); END")
    before = state()
    with pytest.raises(sqlite3.IntegrityError, match="head failure"):
        service.commit(preview)
    assert state() == before
    assert database.get_cfg("billing_day") == "31"
