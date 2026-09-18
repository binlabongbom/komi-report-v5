from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
import json
import sqlite3

import pytest

from database import _open, get_db_path
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.web_observations import WebObservationStore
from test_subject_history import _reading

STAMP = datetime(2026, 9, 18, 10, tzinfo=UTC)


def store():
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Printer", "192.0.2.10", serial="SER-A")])
    return WebObservationStore()


def record(target, minute=0, value=100, read_id=None):
    at = STAMP.replace(minute=minute)
    return target.record(0, _reading(value, collected_at=at), serial="SER-A", printer_name="Printer",
                         at=at, read_id=read_id)


def test_rounds_are_individual_points_and_receipts_are_per_member():
    target = store()
    events = [record(target, minute, 100 + minute) for minute in (0, 10, 15, 30)]
    assert target.page()["events"] == events
    assert target.pending("PC-B") == events
    # Restart or reading a pending page is not an ACK.
    target = WebObservationStore()
    assert target.pending("PC-B") == events
    target.acknowledge("PC-B", [events[0]["id"], events[1]["id"]])
    target.acknowledge("PC-B", [events[0]["id"]])
    assert target.pending("PC-B") == events[2:]
    assert target.pending("PC-C") == events
    assert "password" not in json.dumps(events)
    assert "snmp" not in json.dumps(events)


def test_same_round_retry_deduplicates_but_new_round_with_same_counters_is_retained():
    target = store()
    first = record(target, read_id="job-1")
    assert record(target, read_id="job-1") == first
    second = record(target, read_id="job-2")
    assert first["id"] != second["id"]
    assert target.page()["events"] == [first, second]
    with pytest.raises(ValueError, match="Conflicting results"):
        record(target, value=999, read_id="job-1")
    assert target.page()["events"] == [first, second]


def test_outbox_failure_rolls_back_observation_and_origin():
    target = store()
    with _open() as conn:
        conn.execute("""CREATE TRIGGER fail_event_queue BEFORE INSERT ON web_observation_outbox
            BEGIN SELECT RAISE(ABORT,'injected queue failure'); END""")
    with pytest.raises(sqlite3.Error):
        record(target)
    assert target.page()["events"] == []
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM web_observation_state").fetchone()[0] == 0


def test_history_pages_pin_a_snapshot_and_allow_reconnect_replay():
    target = store()
    expected = [record(target, minute) for minute in range(5)]
    first = target.page(limit=2)
    later = record(target, 20)
    assert target.page(limit=2, through=first["through"]) == first
    second = target.page(after=first["next"], through=first["through"], limit=2)
    third = target.page(after=second["next"], through=first["through"], limit=2)
    assert first["events"] + second["events"] + third["events"] == expected
    assert third["complete"] and not first["complete"]
    assert target.page(after=third["next"])["events"] == [later]


def test_two_databases_import_reversed_duplicates_without_rewriting_usage(tmp_path):
    target = store()
    events = [record(target, minute, 100 + minute) for minute in (0, 15, 30)]
    destination = tmp_path / "peer.sqlite3"
    with sqlite3.connect(get_db_path()) as source, sqlite3.connect(destination) as receiver:
        source.backup(receiver)
        receiver.execute("DELETE FROM web_observation_outbox")
        receiver.execute("DELETE FROM web_observations")
    receiver = WebObservationStore(destination)
    reverse = list(reversed(events))
    assert receiver.receive(reverse, expected_slot=0, expected_serial="SER-A") == tuple(e["id"] for e in reverse)
    receiver.receive(events, expected_slot=0, expected_serial="SER-A")
    assert len(receiver.page()["events"]) == 3
    assert receiver.pending("PC-A") == []  # Imports do not create an echo queue.
    with sqlite3.connect(destination) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_meter_records").fetchone()[0] == 0
        assert conn.execute("SELECT last_success_at FROM devices WHERE slot=0").fetchone()[0] in (None, "")


@pytest.mark.parametrize("change", ["hash", "slot", "serial"])
def test_invalid_batch_cannot_partially_import(change):
    target = store()
    event = record(target)
    bad = deepcopy(event)
    if change == "hash":
        bad["payload"]["reading"]["counters"][0]["count"] = 999
    kwargs = {"expected_slot": 1 if change == "slot" else 0,
              "expected_serial": "SER-B" if change == "serial" else "SER-A"}
    with pytest.raises(ValueError):
        target.receive([event, bad], **kwargs)
    assert len(target.page()["events"]) == 1


@pytest.mark.parametrize("count", [float("nan"), float("inf"), -1, True])
def test_invalid_counter_cannot_be_recorded(count):
    target = store()
    reading = _reading(10, collected_at=STAMP)
    reading = replace(reading, counters=(replace(reading.counters[0], count=count),))
    with pytest.raises(ValueError):
        target.record(0, reading, serial="SER-A", printer_name="Printer", at=STAMP)
    assert not target.page()["events"]


def test_identity_changed_during_read_cannot_be_queued():
    target = store()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Replacement", "192.0.2.10", serial="SER-B")])
    with pytest.raises(ValueError):
        record(target)
    assert not target.page()["events"]


def test_mixed_known_unknown_receipt_rolls_back_entire_batch():
    target = store()
    event = record(target)
    with pytest.raises(ValueError):
        target.acknowledge("PC-B", [event["id"], "not-an-event"])
    assert target.pending("PC-B") == [event]


def test_usage_reset_clears_evidence_and_queue_without_reusing_cursor():
    from database import reset_usage_data
    target = store()
    record(target)
    before = target.page()["through"]
    reset_usage_data()
    assert not target.page()["events"]
    assert not target.pending("PC-B")
    record(target, 15)
    assert target.page()["through"] > before


def test_pages_respect_byte_limit_without_dropping_the_next_event(monkeypatch):
    import services.web_observations as observations
    target = store()
    events = [record(target, minute) for minute in (0, 10, 15)]
    encoded_size = len(observations.validate_event(events[0]).encode("utf-8"))
    monkeypatch.setattr(observations, "MAX_PAGE_BYTES", encoded_size + 1)
    first = target.page()
    assert first["events"] == events[:1] and not first["complete"]
    second = target.page(after=first["next"], through=first["through"])
    assert second["events"] == events[1:2]
    assert target.pending("PC-B") == events[:1]
