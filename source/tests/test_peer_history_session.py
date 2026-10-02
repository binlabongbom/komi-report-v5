from datetime import datetime, UTC
import sqlite3

import pytest

from services.peer_history_session import PeerHistorySession
from services.slot_epoch_exchange import SlotEpochExchange
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore
from test_web_catchup import peers, authorize
from test_web_observations import store, record
from test_slot_epoch_exchange import allow, device
from test_slot_epoch_store import fixture, read, confirm
from test_slot_meter_continuity import total
from test_subject_history import _reading


class Remote:
    def __init__(self, path, history, requester):
        self.history, self.requester = history, requester
        self.exchange = SlotEpochExchange(path=path, authorize=allow)
        self.epoch_requests = []

    def manifest(self, *, after):
        return self.history.manifest(self.requester, after=after)

    def page(self, request, *, limit):
        return self.history.export_page(self.requester, request, limit=limit)

    def epoch(self, epoch_id):
        self.epoch_requests.append(epoch_id)
        return self.exchange.export(self.requester, epoch_id)


def session(paths, nodes, receiver="B", sender="A", **kwargs):
    remote = Remote(paths[sender], nodes[sender], receiver)
    result = PeerHistorySession(member=sender, transport=remote, path=paths[receiver],
        authorize_session=kwargs.pop("authorize_session", lambda member: member == sender),
        authorize_event=authorize, authorize_epoch=allow, **kwargs)
    return result, remote


def test_startup_session_fetches_reviewed_ancestry_and_recovers_via_another_peer(peers):
    paths, nodes = peers
    epochs, _, first = fixture()
    second = confirm(epochs, read("USED", 50000, 18), "replacement")
    at = datetime(2026, 9, 19, 10, tzinfo=UTC)
    event = WebObservationStore().record(0, _reading(50100, collected_at=at), at=at,
        serial="USED", printer_name="Fixture", epoch_id=second)
    target, remote = session(paths, nodes)
    outcome = target.run(page_size=1)
    assert outcome.status == "complete" and outcome.observations == 3 and outcome.imported_epochs == 2
    assert remote.epoch_requests == [second, first]
    assert SlotEpochStore(paths["B"]).head(0) is None  # Import is not a reviewed settings choice.
    third, third_remote = session(paths, nodes, receiver="C", sender="B")
    assert third.run().status == "complete"
    for member in ("B", "C"):
        device(paths[member], "USED")
        exchange = SlotEpochExchange(path=paths[member], authorize=allow)
        exchange.adopt("A", second, expected_head=None)
        assert total(SlotEpochStore(paths[member]).current(0)).slot_total == 2100
        assert WebObservationStore(paths[member]).pending("A") == []
    assert target.run().observations == 0


def test_work_budget_and_restart_resume_without_chasing_new_observations(peers):
    paths, nodes = peers
    source = store()
    expected = [record(source, minute) for minute in range(5)]
    worker, _ = session(paths, nodes)
    result = worker.run(page_size=2, max_pages=1)
    assert result.status == "pending" and result.after == 2 and result.through == 5
    extra = record(source, 6)
    restarted, _ = session(paths, nodes)
    assert restarted.run(page_size=2).through == 5
    assert WebObservationStore(paths["B"]).page()["events"] == expected
    assert restarted.run().observations == 1
    assert WebObservationStore(paths["B"]).page()["events"] == [*expected, extra]


def test_revocation_between_network_response_and_commit_does_not_store_data(peers):
    paths, nodes = peers
    record(store(), 1)
    valid = [True]
    worker, remote = session(paths, nodes, authorize_session=lambda member: valid[0])
    original = remote.page
    def revoked(*args, **kwargs):
        page = original(*args, **kwargs)
        valid[0] = False
        return page
    remote.page = revoked
    with pytest.raises(PermissionError):
        worker.run()
    assert nodes["B"].progress("A")["after"] == 0
    assert WebObservationStore(paths["B"]).page()["events"] == []


def test_cancel_and_lost_transport_resume_only_after_durable_pages(peers):
    paths, nodes = peers
    source = store()
    for minute in range(3):
        record(source, minute)
    worker, remote = session(paths, nodes)
    assert worker.run(cancelled=lambda: True).status == "cancelled"
    assert nodes["B"].progress("A") is None
    original = remote.page
    def fail_second(request, **kwargs):
        if request["after"]:
            raise TimeoutError("synthetic offline peer")
        return original(request, **kwargs)
    remote.page = fail_second
    with pytest.raises(TimeoutError):
        worker.run(page_size=1)
    assert nodes["B"].progress("A")["after"] == 1
    remote.page = original
    assert worker.run(page_size=1).observations == 2


def test_wrong_epoch_response_never_advances_page_or_adopts_settings(peers):
    paths, nodes = peers
    epochs, _, first = fixture()
    second = confirm(epochs, read("USED", 50000, 18), "replacement")
    at = datetime(2026, 9, 19, 10, tzinfo=UTC)
    WebObservationStore().record(0, _reading(50100, collected_at=at), at=at,
        serial="USED", printer_name="Fixture", epoch_id=second)
    worker, remote = session(paths, nodes)
    original = remote.epoch
    remote.epoch = lambda requested: original(first)
    with pytest.raises(ValueError, match="different requested"):
        worker.run()
    assert nodes["B"].progress("A")["after"] == 0
    assert WebObservationStore(paths["B"]).page()["events"] == []


def test_page_storage_failure_keeps_cursor_and_replay_is_safe(peers):
    paths, nodes = peers
    source = store()
    record(source, 1)
    worker, _ = session(paths, nodes)
    with sqlite3.connect(paths["B"]) as conn:
        conn.execute("CREATE TRIGGER fail_progress BEFORE UPDATE ON web_catchup_progress BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.Error):
        worker.run()
    assert nodes["B"].progress("A")["after"] == 0
    with sqlite3.connect(paths["B"]) as conn:
        conn.execute("DROP TRIGGER fail_progress")
    assert worker.run().status == "complete"
    assert worker.run().observations == 0
