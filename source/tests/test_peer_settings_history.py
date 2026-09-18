from copy import deepcopy
import sqlite3

import pytest
from fastapi.testclient import TestClient

from migrations import _migration_020_peer_settings_history
from services.peer_settings_history import SettingsHistory
from services import peer_sync_authorization
from test_secondary_setup import _valid_snapshot
import web_api


def journal(path):
    with sqlite3.connect(path) as conn:
        _migration_020_peer_settings_history(conn)
    return SettingsHistory(path)


def pair(tmp_path):
    a, b = journal(tmp_path / "a.db"), journal(tmp_path / "b.db")
    root = a.observe(_valid_snapshot())
    assert b.receive(a.export())["status"] == "initial_review"
    b.resolve(root, expected_local_head=None, chosen_head=root, reason="Accepted setup")
    a.receive(b.export())
    return a, b


def test_snapshot_time_and_installation_id_do_not_create_shared_edits(tmp_path):
    history = journal(tmp_path / "a.db")
    snapshot = _valid_snapshot()
    first = history.observe(snapshot)
    snapshot["generated_at"] = "2099-01-01T00:00:00Z"
    snapshot["organization"]["primary_installation_id"] = "OTHER-PC"
    assert history.observe(snapshot) == first
    assert "primary_installation_id" not in str(history.export())
    assert SettingsHistory(history.path).export() == history.export()


def test_offline_edit_is_newer_and_repeated_delivery_does_not_apply_settings(tmp_path):
    a, b = pair(tmp_path)
    snapshot = _valid_snapshot()
    snapshot["settings"]["billing_day"] = 15
    b.observe(snapshot)
    original = a.export()
    result = a.receive(b.export())
    assert result["status"] == "incoming_newer"
    assert a.receive(b.export()) == result
    assert a.export() == original  # Receiving does not silently choose/apply.
    assert b.receive(a.export())["status"] == "local_newer"


def test_concurrent_edits_require_choice_and_resolution_keeps_both_parents(tmp_path):
    a, b = pair(tmp_path)
    one, two = _valid_snapshot(), _valid_snapshot()
    one["settings"]["billing_day"] = 15
    two["settings"]["billing_day"] = 20
    local, remote = a.observe(one), b.observe(two)
    assert a.receive(b.export())["status"] == "conflict"
    resolved = a.resolve(remote, expected_local_head=local, chosen_head=remote, reason="Choose 20th")
    record = a.export()["revisions"][resolved]
    assert set(record["parents"]) == {local, remote}
    assert record["payload"]["settings"]["billing_day"] == 20
    assert b.receive(a.export())["status"] == "incoming_newer"


def test_stale_choice_is_rejected(tmp_path):
    a, b = pair(tmp_path)
    result = a.receive(b.export())
    snapshot = _valid_snapshot()
    snapshot["settings"]["billing_day"] = 3
    a.observe(snapshot)
    original = a.export()
    with pytest.raises(ValueError, match="changed"):
        a.resolve(result["remote_head"], expected_local_head=result["local_head"],
                  chosen_head=result["remote_head"], reason="Old preview")
    assert a.export() == original


def test_independent_histories_are_not_mistaken_for_newer(tmp_path):
    a, b = journal(tmp_path / "a.db"), journal(tmp_path / "b.db")
    snapshot = _valid_snapshot()
    a.observe(snapshot)
    b.observe(snapshot)
    assert a.receive(b.export())["status"] == "same_values"
    snapshot["settings"]["billing_day"] = 5
    b.observe(snapshot)
    assert a.receive(b.export())["status"] == "unrelated_history"


def test_clock_skew_does_not_reverse_ancestry(tmp_path):
    from services.peer_settings_history import _revision
    a, b = pair(tmp_path)
    packet = b.export()
    document = packet["revisions"].pop(packet["head"])
    document["created_at"] = "1900-01-01T00:00:00Z"
    packet["head"] = _revision(document)
    packet["revisions"][packet["head"]] = document
    assert a.receive(packet)["status"] == "incoming_newer"


@pytest.mark.parametrize("damage", ["tamper", "missing_parent", "secret"])
def test_bad_history_is_rejected_atomically(tmp_path, damage):
    from services.peer_settings_history import _revision
    a, b = pair(tmp_path)
    packet = deepcopy(b.export())
    head = packet["head"]
    record = packet["revisions"][head]
    if damage == "tamper":
        record["payload"]["settings"]["billing_day"] = 29
    else:
        if damage == "secret":
            record["payload"]["settings"]["password"] = "must-not-transfer"
        else:
            record["parents"] = ["missing"]
        del packet["revisions"][head]
        packet["head"] = _revision(record)
        packet["revisions"][packet["head"]] = record
    with sqlite3.connect(a.path) as conn:
        count = conn.execute("SELECT count(*) FROM peer_settings_revisions").fetchone()[0]
    with pytest.raises((ValueError, RuntimeError)):
        a.receive(packet)
    with sqlite3.connect(a.path) as conn:
        assert conn.execute("SELECT count(*) FROM peer_settings_revisions").fetchone()[0] == count


def test_history_endpoint_keeps_single_use_authorization(monkeypatch, tmp_path):
    from database import set_cfg
    from services.device_config import DeviceConfig, DeviceConfigRepository
    from services.shared_settings import SharedSettingsService
    set_cfg("company_name", "Synthetic endpoint company")
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer", "192.0.2.10")])
    service = SharedSettingsService()
    expected_head = service.commit(service.preview({"billing_day": 15}, reason="newer committed edit"))
    monkeypatch.setenv("KOMI_PEER_SYNC_STATE_FILE", str(tmp_path / "auth.json"))
    # This legacy snapshot is stale. A v2 history read must use the DB transaction.
    monkeypatch.setattr(web_api, "primary_setup_snapshot", _valid_snapshot)
    monkeypatch.setattr(web_api, "get_cfg", lambda key, default="": "pc-a" if key == "installation_id" else default)
    client = TestClient(web_api.app)
    path = "/api/v2/peer/settings-history"
    assert client.get(path).status_code == 401
    peer_sync_authorization.open_pairing_window("pc-a")
    token = "a" * 43
    assert client.post("/api/v1/peer/claim", json={"token": token}).status_code == 202
    headers = {"X-KOMI-Peer-Sync-Token": token}
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["head"] == expected_head
    assert response.json()["revisions"][expected_head]["payload"]["settings"]["billing_day"] == 15
    receiver = journal(tmp_path / "receiver.db")
    assert receiver.receive(response.json())["status"] == "initial_review"
    assert "primary_installation_id" not in response.text
    assert "password" not in response.text
    assert client.get(path, headers=headers).status_code == 401
