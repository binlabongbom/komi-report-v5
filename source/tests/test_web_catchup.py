from datetime import date
import sqlite3

import pytest

import database
from services.web_catchup import WebCatchup
from services.web_observations import WebObservationStore
from services.web_observation_archive import WebObservationArchive
from test_web_observations import store, record


def authorize(member, event):
    return member in {"A", "B", "C"} and (event is None or event["payload"]["slot"] == 0)


@pytest.fixture
def peers(tmp_path):
    original = database.get_db_path()
    paths = {"A": original}
    try:
        for member in ("B", "C"):
            paths[member] = tmp_path / (member + ".sqlite3")
            database.set_db_path(paths[member])
            database.init_db()
        database.set_db_path(original)
        yield paths, {key: WebCatchup(path=path, authorize=authorize) for key, path in paths.items()}
    finally:
        database.set_db_path(original)


def begin(source, receiver, *, member="A"):
    previous = receiver.progress(member)
    return receiver.begin(member, source.manifest("B", after=previous["after"] if previous else 0))


def drain(source, receiver, *, member="A", limit=2):
    state = begin(source, receiver, member=member)
    while not state["complete"]:
        page = source.export_page("B", state, limit=limit)
        receiver.receive_page(member, page)
        state = receiver.progress(member)
    return state


def test_restart_continues_pinned_history_and_only_next_wake_gets_new_reads(peers):
    paths, nodes = peers
    source = store()
    expected = [record(source, minute) for minute in range(5)]
    state = begin(nodes["A"], nodes["B"])
    page = nodes["A"].export_page("B", state, limit=2)
    assert nodes["B"].receive_page("A", page) == tuple(e["id"] for e in expected[:2])
    assert nodes["B"].receive_page("A", page) == tuple(e["id"] for e in expected[:2])
    extra = record(source, 10)
    restarted = WebCatchup(path=paths["B"], authorize=authorize)
    result = drain(nodes["A"], restarted)
    assert result["through"] == state["through"]
    assert WebObservationStore(paths["B"]).page()["events"] == expected
    drain(nodes["A"], restarted)
    assert WebObservationStore(paths["B"]).page()["events"] == [*expected, extra]
    assert WebObservationStore(paths["B"]).pending("A") == []
    # A third member recovers the same evidence from B, although it was imported
    # rather than created by B. No real HTTP or Host credential in this fixture.
    drain(restarted, nodes["C"], member="B")
    assert WebObservationStore(paths["C"]).page()["events"] == [*expected, extra]


def test_page_and_cursor_rollback_together_on_disk_failure(peers):
    paths, nodes = peers
    source = store()
    expected = [record(source, minute) for minute in range(3)]
    state = begin(nodes["A"], nodes["B"])
    page = nodes["A"].export_page("B", state)
    with sqlite3.connect(paths["B"]) as conn:
        conn.execute("CREATE TRIGGER fail_cursor BEFORE UPDATE ON web_catchup_progress BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.Error):
        nodes["B"].receive_page("A", page)
    assert WebObservationStore(paths["B"]).page()["events"] == []
    assert nodes["B"].progress("A") == state
    with sqlite3.connect(paths["B"]) as conn:
        conn.execute("DROP TRIGGER fail_cursor")
    assert nodes["B"].receive_page("A", page) == tuple(event["id"] for event in expected)


def test_unknown_member_or_partial_authorization_cannot_receive_or_advance(peers):
    paths, nodes = peers
    source = store()
    events = [record(source, minute) for minute in range(2)]
    state = begin(nodes["A"], nodes["B"])
    page = nodes["A"].export_page("B", state)
    with pytest.raises(PermissionError):
        nodes["A"].manifest("unknown")
    restricted = WebCatchup(path=paths["B"], authorize=lambda member, event:
        member == "A" and (event is None or event["id"] == events[0]["id"]))
    with pytest.raises(PermissionError):
        restricted.receive_page("A", page)
    assert WebObservationStore(paths["B"]).page()["events"] == []
    assert nodes["B"].progress("A") == state


@pytest.mark.parametrize("change", ["reorder", "cursor", "complete", "stream"])
def test_invalid_or_out_of_order_page_is_not_acknowledged(peers, change):
    paths, nodes = peers
    source = store()
    for minute in range(3):
        record(source, minute)
    state = begin(nodes["A"], nodes["B"])
    page = nodes["A"].export_page("B", state, limit=2)
    if change == "reorder":
        page["items"].reverse()
    elif change == "cursor":
        page["after"] = 1
    elif change == "complete":
        page["complete"] = True
    else:
        page["stream"] = "unknown-stream"
    with pytest.raises(ValueError):
        nodes["B"].receive_page("A", page)
    assert nodes["B"].progress("A") == state
    assert WebObservationStore(paths["B"]).page()["events"] == []


def test_archive_is_recovered_on_demand_and_missing_file_cannot_advance(peers):
    paths, nodes = peers
    source = store()
    expected = [record(source, minute) for minute in range(3)]
    archive = WebObservationArchive()
    while archive.archive_batch(today=date(2028, 1, 1)):
        pass
    drain(nodes["A"], nodes["B"])
    assert WebObservationStore(paths["B"]).page()["events"] == expected
    state = begin(nodes["A"], nodes["C"])
    with sqlite3.connect(paths["A"]) as conn:
        relative = conn.execute("SELECT relative_path FROM web_observation_archives LIMIT 1").fetchone()[0]
    (paths["A"].parent / "archives" / "web-observations" / relative).unlink()
    with pytest.raises((ValueError, OSError, sqlite3.Error)):
        nodes["A"].export_page("C", state)
    assert nodes["C"].progress("A") == state


def test_sender_reset_rotates_stream_and_receiver_reset_discards_resume_cursor(peers):
    paths, nodes = peers
    source = store()
    old = record(source, 0)
    before = drain(nodes["A"], nodes["B"])
    database.reset_usage_data()
    new = record(source, 5)
    state = begin(nodes["A"], nodes["B"])
    assert state["stream"] != before["stream"] and state["after"] == 0
    page = nodes["A"].export_page("B", state)
    nodes["B"].receive_page("A", page)
    assert WebObservationStore(paths["B"]).page()["events"] == [old, new]
    database.set_db_path(paths["B"])
    database.reset_usage_data()
    assert nodes["B"].progress("A") is None


def test_sender_backup_rollback_detected_by_anchor_even_with_same_stream(peers, tmp_path):
    paths, nodes = peers
    source = store()
    first = record(source, 0)
    nodes["A"].manifest("B")  # Create stream before taking the older backup.
    backup = tmp_path / "source-before.sqlite3"
    with sqlite3.connect(paths["A"]) as conn, sqlite3.connect(backup) as target:
        conn.backup(target)
    record(source, 1)
    record(source, 2)
    original = drain(nodes["A"], nodes["B"])
    with sqlite3.connect(backup) as conn, sqlite3.connect(paths["A"]) as target:
        conn.backup(target)
    state = begin(nodes["A"], nodes["B"])
    assert state["stream"] == original["stream"] and state["after"] == 0
    nodes["B"].receive_page("A", nodes["A"].export_page("B", state))
    assert len(WebObservationStore(paths["B"]).page()["events"]) == 3
    assert nodes["B"].progress("A")["anchor"] == first["id"]


def test_missing_reviewed_epoch_stalls_whole_page_until_ancestry_received(peers):
    from datetime import datetime, UTC
    from test_slot_epoch_store import fixture
    from test_subject_history import _reading
    from services.slot_epoch_exchange import SlotEpochExchange
    paths, nodes = peers
    _, _, epoch = fixture()
    at = datetime(2026, 9, 18, 10, tzinfo=UTC)
    event = WebObservationStore().record(0, _reading(2010, collected_at=at), at=at,
        serial="OLD", printer_name="Fixture", epoch_id=epoch)
    state = begin(nodes["A"], nodes["B"])
    page = nodes["A"].export_page("B", state)
    with pytest.raises(ValueError, match="Unknown reviewed"):
        nodes["B"].receive_page("A", page)
    assert nodes["B"].progress("A") == state
    assert WebObservationStore(paths["B"]).page()["events"] == []
    source = SlotEpochExchange(path=paths["A"], authorize=lambda member, decision: member == "B")
    receiver = SlotEpochExchange(path=paths["B"], authorize=lambda member, decision: member == "A")
    receiver.receive("A", source.export("B", epoch))
    assert event["id"] in nodes["B"].receive_page("A", page)
    assert nodes["B"].progress("A")["complete"]
    with sqlite3.connect(paths["B"]) as conn:
        assert conn.execute("SELECT epoch_id FROM slot_meter_assignments WHERE event_id=?", (event["id"],)).fetchone()[0] == epoch
