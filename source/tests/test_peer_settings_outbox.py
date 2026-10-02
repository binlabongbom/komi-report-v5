import sqlite3

import pytest

import database
from services.peer_settings_outbox import PeerSettingsOutbox
from services.peer_settings_history import SettingsHistory
from test_shared_settings import configured, state


def save(service, day):
    return service.commit(service.preview({"billing_day": day}, reason="billing_settings_saved"))


def test_settings_and_event_commit_together_and_survive_restart():
    service = configured()
    revision = save(service, 15)
    queue = PeerSettingsOutbox()
    expected = {"revision": revision, "attempts": 0}
    assert queue.next_delivery("authenticated-a", now=100) == expected
    assert PeerSettingsOutbox().next_delivery("authenticated-a", now=100) == expected
    queue.acknowledge("authenticated-a", revision, now=101)
    assert queue.next_delivery("authenticated-a", now=102) is None
    assert queue.next_delivery("authenticated-b", now=102) == expected
    queue.acknowledge("authenticated-a", revision, now=103)  # Duplicate ACK is harmless.
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT count(*) FROM peer_settings_deliveries WHERE peer_id='authenticated-a'").fetchone()[0] == 2


def test_outbox_failure_rolls_back_settings_and_history():
    service = configured()
    with database._open() as conn:
        conn.execute("CREATE TRIGGER fail_event BEFORE INSERT ON peer_settings_events BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = state()
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        save(service, 15)
    assert state() == before
    assert database.get_cfg("billing_day") == "31"
    assert PeerSettingsOutbox().next_delivery("a") is None


def test_newer_edits_coalesce_but_old_ack_never_hides_a_new_edit():
    service = configured()
    old = save(service, 15)
    new = save(service, 20)
    queue = PeerSettingsOutbox()
    queue.acknowledge("a", old, now=100)
    assert queue.next_delivery("a", now=101)["revision"] == new
    queue.acknowledge("a", new, now=102)
    assert queue.next_delivery("a", now=103) is None
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT count(*) FROM peer_settings_deliveries WHERE acknowledged_at IS NULL").fetchone()[0] == 0


def test_failure_retry_is_durable_and_reconnect_does_not_clear_ack():
    service = configured()
    revision = save(service, 15)
    queue = PeerSettingsOutbox()
    queue.failed("a", revision, error_code="offline", now=100)
    assert PeerSettingsOutbox().next_delivery("a", now=101) is None
    assert queue.next_delivery("a", now=101, reconnect=True) == {"revision": revision, "attempts": 1}
    assert queue.next_delivery("a", now=102)["revision"] == revision
    queue.acknowledge("a", revision, now=103)
    queue.failed("a", revision, error_code="timeout", now=104)
    assert queue.next_delivery("a", now=105, reconnect=True) is None


def test_incoming_history_does_not_queue_until_reviewed_application():
    from copy import deepcopy
    from services.peer_settings_history import _revision
    service = configured()
    local = save(service, 15)
    packet = SettingsHistory().export()
    document = deepcopy(packet["revisions"][local])
    document["parents"] = [local]
    document["payload"]["settings"]["billing_day"] = 20
    remote = _revision(document)
    packet["head"] = remote
    packet["revisions"][remote] = document
    queue = PeerSettingsOutbox()
    queue.acknowledge("a", local)
    SettingsHistory().receive(packet)
    assert queue.next_delivery("a") is None
    assert service.commit(service.preview_choice(remote, chosen_head=remote, reason="accept")) == remote
    assert queue.next_delivery("a")["revision"] == remote


def test_usage_reset_keeps_events_factory_reset_clears_them():
    from services.registration_vault import SessionRegistrationSecretStore
    service = configured()
    revision = save(service, 15)
    queue = PeerSettingsOutbox()
    queue.acknowledge("a", revision)
    database.reset_usage_data()
    assert queue.next_delivery("b")["revision"] == revision
    database.factory_reset_v5(registration_secret_store=SessionRegistrationSecretStore())
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT count(*) FROM peer_settings_events").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM peer_settings_deliveries").fetchone()[0] == 0


def test_upgrading_old_history_queues_current_head(tmp_path):
    from migrations import _migration_020_peer_settings_history, _migration_021_peer_settings_outbox
    path = tmp_path / "v20.db"
    with sqlite3.connect(path) as conn:
        _migration_020_peer_settings_history(conn)
        conn.execute("INSERT INTO peer_settings_revisions VALUES('old-head','{}')")
        conn.execute("INSERT INTO peer_settings_state VALUES('head','old-head')")
        _migration_021_peer_settings_outbox(conn)
    assert PeerSettingsOutbox(path).next_delivery("a")["revision"] == "old-head"


def test_unknown_ack_and_unbounded_errors_are_rejected():
    queue = PeerSettingsOutbox()
    with pytest.raises(ValueError):
        queue.acknowledge("a", "unknown")
    with pytest.raises(ValueError):
        queue.failed("a", "unknown", error_code="raw secret or exception")
    with pytest.raises(ValueError):
        queue.next_delivery("", now=100)
    with pytest.raises(ValueError):
        queue.next_delivery("a", now=float("nan"))
