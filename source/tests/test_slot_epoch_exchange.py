from copy import deepcopy
from datetime import datetime, UTC
import hashlib
import sqlite3

import pytest

import database
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.slot_epoch_store import SlotEpochStore
from services.slot_epoch_exchange import SlotEpochExchange
from services.web_observations import WebObservationStore, _json
from test_slot_epoch_store import fixture, read, confirm
from test_slot_meter_continuity import total
from test_subject_history import _reading


def allow(member, epoch):
    return member in {"A", "B", "C"} and epoch["document"]["baseline_event"]["payload"]["slot"] == 0


@pytest.fixture
def peers(tmp_path):
    original = database.get_db_path()
    paths = {"A": original}
    try:
        for name in ("B", "C"):
            paths[name] = tmp_path / (name + ".sqlite3")
            database.set_db_path(paths[name])
            database.init_db()
        database.set_db_path(original)
        yield paths, {key: SlotEpochExchange(path=path, authorize=allow) for key, path in paths.items()}
    finally:
        database.set_db_path(original)


def device(path, serial):
    original = database.get_db_path()
    try:
        database.set_db_path(path)
        DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial=serial)])
    finally:
        database.set_db_path(original)


def test_three_databases_receive_ancestry_then_converge_without_echo(peers):
    paths, exchanges = peers
    store, _, first = fixture()
    second = confirm(store, read("USED", 50000, 18), "replacement")
    events = WebObservationStore()
    at = datetime(2026, 9, 19, 10, tzinfo=UTC)
    event = events.record(0, _reading(50100, collected_at=at), at=at, serial="USED", printer_name="Fixture", epoch_id=second)
    for member in ("B", "C"):
        exchange = exchanges[member]
        with pytest.raises(ValueError, match="Unknown"):
            exchange.receive("A", exchanges["A"].export(member, second))
        assert WebObservationStore(paths[member]).page()["events"] == []
        for head in (first, second):
            bundle = exchanges["A"].export(member, head)
            assert exchange.receive("A", bundle) == head
            assert exchange.receive("A", bundle) == head
        assert SlotEpochStore(paths[member]).head(0) is None
        with pytest.raises(ValueError, match="settings"):
            exchange.adopt("A", second, expected_head=None)
        device(paths[member], "USED")
        exchange.adopt("A", second, expected_head=None)
        target = WebObservationStore(paths[member])
        target.receive([event], expected_slot=0, expected_serial="USED", expected_epoch=second)
        target.receive([event], expected_slot=0, expected_serial="USED", expected_epoch=second)
        assert total(SlotEpochStore(paths[member]).current(0)).slot_total == 2100
        assert target.pending("A") == []
        with sqlite3.connect(paths[member]) as conn:
            assert conn.execute("SELECT COUNT(*) FROM slot_meter_epoch_outbox").fetchone()[0] == 0
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert total(store.current(0)).slot_total == 2100


def test_unauthorized_or_forged_carry_leaves_receiver_empty(peers):
    paths, exchanges = peers
    store, _, first = fixture()
    baseline = exchanges["A"].export("B", first)
    with pytest.raises(PermissionError):
        exchanges["B"].receive("stranger", baseline)
    with pytest.raises(PermissionError):
        exchanges["A"].export("stranger", first)
    exchanges["B"].receive("A", baseline)
    second = confirm(store, read("USED", 50000, 18), "replacement")
    forged = deepcopy(exchanges["A"].export("B", second))
    key = next(iter(forged["epoch"]["document"]["carried"]))
    forged["epoch"]["document"]["carried"][key][0] += 999
    forged["epoch"]["id"] = hashlib.sha256(_json(forged["epoch"]["document"]).encode()).hexdigest()
    before = WebObservationStore(paths["B"]).page()
    with pytest.raises(ValueError, match="carried"):
        exchanges["B"].receive("A", forged)
    assert WebObservationStore(paths["B"]).page() == before


def test_local_higher_parent_evidence_holds_adoption(peers):
    paths, exchanges = peers
    store, _, first = fixture()
    exchanges["B"].receive("A", exchanges["A"].export("B", first))
    device(paths["B"], "OLD")
    exchanges["B"].adopt("A", first, expected_head=None)
    at = datetime(2026, 9, 17, 10, tzinfo=UTC)
    WebObservationStore(paths["B"]).record(0, _reading(2050, collected_at=at), at=at,
        serial="OLD", printer_name="Fixture", epoch_id=first)
    second = confirm(store, read("USED", 50000, 18), "replacement")
    exchanges["B"].receive("A", exchanges["A"].export("B", second))
    device(paths["B"], "USED")
    with pytest.raises(ValueError, match="evidence needs review"):
        exchanges["B"].adopt("A", second, expected_head=first)
    assert SlotEpochStore(paths["B"]).head(0)["id"] == first
    assert total(SlotEpochStore(paths["B"]).current(0)).slot_total == 2050


def test_partial_reset_boundary_transfers_with_exact_parent_binding(peers):
    paths, exchanges = peers
    store, _, first = fixture()
    exchanges["B"].receive("A", exchanges["A"].export("B", first))
    at = datetime(2026, 9, 18, 10, tzinfo=UTC)
    boundary = WebObservationStore().record(0, _reading(50, collected_at=at), at=at,
        serial="OLD", printer_name="Fixture", epoch_id=first)
    second = confirm(store, boundary, "reset")
    exchanges["B"].receive("A", exchanges["A"].export("B", second))
    device(paths["B"], "OLD")
    exchanges["B"].adopt("A", second, expected_head=None)
    assert total(SlotEpochStore(paths["B"]).current(0)).slot_total == 2000
    with sqlite3.connect(paths["B"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_assignments WHERE event_id=?", (boundary["id"],)).fetchone()[0] == 2


def test_failure_mid_receive_rolls_back_evidence_and_definition(peers):
    paths, exchanges = peers
    store, _, first = fixture()
    exchanges["B"].receive("A", exchanges["A"].export("B", first))
    second = confirm(store, read("USED", 50000, 18), "replacement")
    before = WebObservationStore(paths["B"]).page()
    with sqlite3.connect(paths["B"]) as conn:
        conn.execute("CREATE TRIGGER fail_import BEFORE INSERT ON slot_meter_epoch_state BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.Error):
        exchanges["B"].receive("A", exchanges["A"].export("B", second))
    assert WebObservationStore(paths["B"]).page() == before
    with sqlite3.connect(paths["B"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM slot_meter_epochs").fetchone()[0] == 1


def test_conflicting_sibling_cannot_be_selected_by_arrival_time(peers):
    from services.slot_meter_continuity import reviewed_epoch
    paths, exchanges = peers
    store, _, first = fixture()
    first_bundle = exchanges["A"].export("B", first)
    exchanges["B"].receive("A", first_bundle)
    parent = store.head(0)
    second = confirm(store, read("USED", 50000, 18), "replacement")
    second_bundle = exchanges["A"].export("B", second)
    exchanges["B"].receive("A", second_bundle)
    device(paths["B"], "USED")
    exchanges["B"].adopt("A", second, expected_head=None)
    third_candidate = read("OTHER", 9000, 19)
    sibling = reviewed_epoch(third_candidate, parent=parent, operation="replacement", actor="C", reason="Concurrent review")
    sibling_bundle = {"epoch": sibling, "parent_evidence": [parent["document"]["baseline_event"]]}
    exchanges["B"].receive("C", sibling_bundle)
    device(paths["B"], "OTHER")
    with pytest.raises(ValueError, match="Conflicting"):
        exchanges["B"].adopt("C", sibling["id"], expected_head=second)
    target = SlotEpochStore(paths["B"])
    assert target.head(0)["id"] == second
    assert "competing_epoch_decisions" in target.current(0).issues


def test_imported_initial_does_not_discard_unreviewed_legacy_printer(peers):
    paths, exchanges = peers
    _, _, first = fixture()
    device(paths["B"], "LEGACY")
    WebObservationStore(paths["B"]).record(0, _reading(777, collected_at=datetime(2026, 9, 17, 10, tzinfo=UTC)),
        serial="LEGACY", printer_name="Legacy")
    exchanges["B"].receive("A", exchanges["A"].export("B", first))
    device(paths["B"], "OLD")
    with pytest.raises(ValueError, match="migration review"):
        exchanges["B"].adopt("A", first, expected_head=None)
