import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from services.peer_settings_history import MAX_PACKET_BYTES, SettingsHistory, _revision, shared_settings
from test_peer_settings_history import journal
from test_secondary_setup import _valid_snapshot


def seed(history, count):
    payload = shared_settings(_valid_snapshot())
    with history._transaction() as conn:
        head = None
        for index in range(count):
            payload["settings"]["billing_day"] = index % 31 + 1
            head = history._append(conn, payload, [head] if head else [], "synthetic change")
    return head


def count(history):
    with sqlite3.connect(history.path) as conn:
        return conn.execute("SELECT count(*) FROM peer_settings_revisions").fetchone()[0]


def test_large_history_resumes_after_restart_and_duplicate_pages(tmp_path):
    sender, receiver = journal(tmp_path / "a.db"), journal(tmp_path / "b.db")
    head = seed(sender, 310)
    with pytest.raises(ValueError, match="paged"):
        sender.export()
    offset, received = 0, []
    while True:
        page = sender.export_page(head=head, offset=offset, limit=37)
        assert len(json.dumps(page, ensure_ascii=False).encode()) <= MAX_PACKET_BYTES
        result = receiver.receive_page(page)
        assert receiver.receive_page(page) == result
        received.extend(page["revisions"])
        with sqlite3.connect(receiver.path) as conn:
            assert receiver._state(conn, "head") is None
        if result["next_offset"] is None:
            assert result["status"] == "initial_review"
            break
        assert result["status"] == "incomplete"
        with sqlite3.connect(receiver.path) as conn:
            assert conn.execute("SELECT count(*) FROM peer_settings_state WHERE key LIKE 'review:%'").fetchone()[0] == 0
        offset = result["next_offset"]
        receiver = SettingsHistory(receiver.path)
    assert len(received) == len(set(received)) == count(receiver) == 310
    with sqlite3.connect(receiver.path) as conn:
        assert len(receiver._ancestors(conn, head)) == 310


def test_page_head_stays_pinned_while_sender_changes_settings(tmp_path):
    history = journal(tmp_path / "a.db")
    head = seed(history, 5)
    page = history.export_page(limit=2)
    newer = _valid_snapshot()
    newer["settings"]["billing_day"] = 30
    next_head = history.observe(newer)
    assert next_head != head
    rest = history.export_page(head=page["head"], offset=page["next_offset"])
    assert rest["head"] == head
    assert next_head not in rest["revisions"]
    assert rest["next_offset"] is None


def test_out_of_order_or_corrupt_page_cannot_partially_import(tmp_path):
    sender, receiver = journal(tmp_path / "a.db"), journal(tmp_path / "b.db")
    head = seed(sender, 5)
    missing_first = sender.export_page(head=head, offset=2, limit=2)
    with pytest.raises(ValueError, match="Missing"):
        receiver.receive_page(missing_first)
    assert count(receiver) == 0
    page = sender.export_page(limit=2)
    next(iter(page["revisions"].values()))["reason"] = "tampered"
    with pytest.raises(ValueError, match="revision"):
        receiver.receive_page(page)
    assert count(receiver) == 0


def test_byte_budget_splits_pages_without_dropping_revisions(tmp_path, monkeypatch):
    import services.peer_settings_history as module
    sender, receiver = journal(tmp_path / "a.db"), journal(tmp_path / "b.db")
    head = seed(sender, 10)
    monkeypatch.setattr(module, "MAX_PACKET_BYTES", 3500)
    cursor, received = 0, set()
    while True:
        page = sender.export_page(head=head, offset=cursor)
        assert len(module._json(page).encode()) <= 3500
        receiver.receive_page(page)
        received.update(page["revisions"])
        cursor = page["next_offset"]
        if cursor is None:
            break
    assert len(received) == 10


@pytest.mark.parametrize("offset,limit", [(-1, 2), (100, 2), (False, 2), (0, 0), (0, 257)])
def test_invalid_cursor_is_rejected(tmp_path, offset, limit):
    sender = journal(tmp_path / "a.db")
    seed(sender, 2)
    with pytest.raises(ValueError):
        sender.export_page(offset=offset, limit=limit)


def test_api_page_uses_authorization_and_preserves_document_hashes(monkeypatch, tmp_path):
    import web_api
    from services import peer_sync_authorization as auth
    from test_setup_settings import make_preview
    from services.setup_settings import SetupSettingsService
    from services.device_config import DeviceConfigRepository
    SetupSettingsService(DeviceConfigRepository()).commit(make_preview(SetupSettingsService(DeviceConfigRepository())))
    monkeypatch.setenv("KOMI_PEER_SYNC_STATE_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setattr(web_api, "get_cfg", lambda key, default="": "pc-a" if key == "installation_id" else default)
    client = TestClient(web_api.app)
    path = "/api/v2/peer/settings-history/page"
    assert client.get(path).status_code == 401
    auth.open_pairing_window("pc-a")
    token = "x" * 43
    assert client.post("/api/v1/peer/claim", json={"token": token}).status_code == 202
    headers = {"X-KOMI-Peer-Sync-Token": token}
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    for revision, document in response.json()["revisions"].items():
        assert revision == _revision(document)
    assert client.get(path, headers=headers).json() == response.json()
    assert client.get(path, headers=headers, params={"head": "f" * 64}).status_code == 401
    assert client.get("/api/v1/peer/setup-snapshot", headers=headers).status_code == 401
    auth.close_pairing_window()
    assert client.get(path, headers=headers).status_code == 401


def test_client_receives_all_pages_with_one_approval_despite_lost_first_reply(monkeypatch, tmp_path):
    import web_api
    from services import peer_sync_authorization as auth
    from services.secondary_setup import SecondaryPeerClient, SecondaryPeerCandidate
    from test_shared_settings import configured
    configured()
    sender = SettingsHistory()
    root = sender.observe_current()
    with sender._transaction() as conn:
        payload = sender._document(conn, root)["payload"]
        for index in range(70):
            payload["settings"]["billing_day"] = index % 31 + 1
            root = sender._append(conn, payload, [root], "synthetic")
    monkeypatch.setenv("KOMI_PEER_SYNC_STATE_FILE", str(tmp_path / "auth.json"))
    monkeypatch.setattr(web_api, "get_cfg", lambda key, default="": "pc-a" if key == "installation_id" else default)
    auth.open_pairing_window("pc-a")
    api, client = TestClient(web_api.app), SecondaryPeerClient()
    lost, claims = [], []
    def request(_host, method, path, **kwargs):
        if method == "POST":
            claims.append(path)
        response = api.request(method, path, headers=kwargs.get("headers"), content=kwargs.get("body"))
        if method == "GET" and not lost:
            lost.append(response.json()["head"])
            assert response.status_code == 200
            # The first reply was lost after the server committed its grant.
            raise OSError("synthetic lost reply")
        return response.status_code, response.json(), "a" * 64, []
    monkeypatch.setattr(client, "_request", request)
    receiver = journal(tmp_path / "receiver.db")
    candidate = SecondaryPeerCandidate("https://192.0.2.20:3000", "Synthetic", 1, "test", "a" * 64)
    pages = 0
    for page in client.iter_settings_history_pages(candidate):
        outcome = receiver.receive_page(page)
        assert page["head"] == lost[0]
        pages += 1
    assert pages >= 2
    assert len(claims) == 1
    assert outcome["status"] == "initial_review"
    assert count(receiver) == count(sender)
