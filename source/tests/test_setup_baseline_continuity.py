"""Approved setup meter readings must seed the first real collection exactly once."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json

import pytest
from PyQt6.QtWidgets import QApplication

from database import _open
from komi_snmp_profiler.models import WebCounterValue
from services.background_polling import BackgroundPollingCoordinator
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfigRepository
from services.parser_mapping import ParserMappingRepository
from services.raw_counter_history import RawCounterHistoryStore
from services.setup_meter_baselines import SetupMeterBaselines
from services.slot_cache_bridge import bridge_device_state, bridge_subject_state
from services.slot_epoch_store import SlotEpochStore
from services.snmp_probe import SnmpProbeResult, SnmpTotalProbe
from services.subject_history import SubjectDailyCacheStore
from services.web_observations import WebObservationStore
from test_setup_meter_baselines import device, preview, reading, setup_service


TOTAL = "counter.total.total"
SCAN = "counter.scan_fax.document_read_total"
USER = "counter.user.total.total"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def meter(config, total, at):
    base = reading(config, total, at=at)
    return replace(base, counters=tuple(
        replace(counter, count=346 + total - 2475) if counter.canonical_field == SCAN else counter
        for counter in base.counters
    ) + (WebCounterValue(USER, "Bomb", 120 + total - 2475, "User", "User[123]/Total",
                         subject_type="user", subject_id="123", subject_name="Bomb"),))


def create_setup(config, at):
    baseline = meter(config, 2475, at)
    baselines = SetupMeterBaselines()
    plan = baselines.prepare([config], {config.slot: baselines.capture(config, baseline)}, {config.slot})
    service = setup_service()
    service.commit(preview(service, [config], plan=plan))
    return baseline, plan


class Probe:
    def __init__(self, config, state):
        self.config, self.state = config, state

    def read(self, host):
        assert host == self.config.host
        return SnmpProbeResult(self.state["total"], "Fixture", self.config.serial,
            total_oid=SnmpTotalProbe.PRIMARY_TOTAL_OID)


class Reader:
    def __init__(self, config, state):
        self.config, self.state = config, state

    def read(self, host):
        assert host == self.config.host
        return meter(self.config, self.state["total"], self.state["at"])


@pytest.mark.parametrize("mapped", [False, True])
def test_real_polling_counts_first_five_pages_from_setup_then_only_new_increment(app, tmp_path, mapped):
    config = device(2)
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=10)
    if mapped:
        ParserMappingRepository().replace_all(config.serial, {(SCAN, f"Fixture/{SCAN}"): "counter.original.total"})
    _baseline, plan = create_setup(config, at)
    state = {"total": 2480, "at": at + timedelta(seconds=1)}
    repo = DeviceConfigRepository()
    cache = DailyCacheStore(tmp_path / "daily")
    subjects = SubjectDailyCacheStore(tmp_path / "subjects")
    coordinator = BackgroundPollingCoordinator(repo, probe=Probe(config, state), reader=Reader(config, state),
        cache=cache, subject_cache=subjects, clock=lambda: state["at"])
    try:
        assert coordinator._poll_device(repo.get(2), force_web=True)
        local = cache.load(2, at.date())
        assert local["opening"][TOTAL] == 2475
        assert local["latest"][TOTAL] == 2480
        assert local["delta"][TOTAL] == 5
        assert local["slot_epoch"] == dict(plan.slot_epochs)[2]
        assert not local.get("unsafe_reconciliation_seen")
        scan_key = "counter.original.total" if mapped else SCAN
        assert local["delta"][scan_key] == 5
        assert ("+parser." in local["source"]["schema_version"]) is mapped
        subject = subjects.load(2, at.date())["subjects"]["user:123"]
        assert (subject["opening_total"], subject["latest_total"], subject["delta_total"]) == (120, 125, 5)
        assert not subject["missing_baseline"] and not subject["warnings"]
        with _open(commit=False) as conn:
            for key, opening in ((TOTAL, 2475), (SCAN, 346), (USER, 120)):
                raw = conn.execute("SELECT opening_value,closing_value,delta_value FROM daily_raw_counter_records WHERE device_slot=2 AND canonical_field=?", (key,)).fetchone()
                assert raw == (opening, opening + 5, 5)
        state.update(total=2483, at=at + timedelta(seconds=2))
        assert coordinator._poll_device(repo.get(2), force_web=True)
        assert cache.load(2, at.date())["delta"][TOTAL] == 8
        assert subjects.load(2, at.date())["subjects"]["user:123"]["delta_total"] == 8
        with _open(commit=False) as conn:
            assert conn.execute("SELECT delta_value FROM daily_raw_counter_records WHERE device_slot=2 AND canonical_field=?", (TOTAL,)).fetchone()[0] == 8
        # Process restart/replay cannot add the same five/eight pages again.
        coordinator.cache = DailyCacheStore(cache.root)
        assert coordinator._poll_device(repo.get(2), force_web=True)
        assert cache.load(2, at.date())["delta"][TOTAL] == 8
        assert subjects.load(2, at.date())["subjects"]["user:123"]["delta_total"] == 8
    finally:
        coordinator.stop()


def test_day_rollover_uses_last_assigned_observation_and_keeps_previous_day(app, tmp_path):
    config = device()
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=10)
    _baseline, plan = create_setup(config, at)
    head = dict(plan.slot_epochs)[0]
    cache, subjects = DailyCacheStore(tmp_path / "daily"), SubjectDailyCacheStore(tmp_path / "subjects")
    raw = RawCounterHistoryStore()

    def collect(total, stamp):
        sample = meter(config, total, stamp)
        WebObservationStore().record(0, sample, serial=config.serial, printer_name=config.name, at=stamp, epoch_id=head)
        subjects.update_reading(0, sample, at=stamp)
        raw.update_reading(0, sample, at=stamp)
        return cache.update_reading(0, sample, at=stamp)

    first = collect(2480, at + timedelta(seconds=1))
    previous_subjects = deepcopy(subjects.load(0, at.date()))
    tomorrow = at + timedelta(days=1)
    second = collect(2483, tomorrow)
    assert first["delta"][TOTAL] == 5
    assert second["opening"][TOTAL] == 2480
    assert second["delta"][TOTAL] == 3
    assert subjects.load(0, tomorrow.date())["subjects"]["user:123"]["delta_total"] == 3
    assert cache.load(0, at.date()) == first
    assert subjects.load(0, at.date()) == previous_subjects
    with _open(commit=False) as conn:
        rows = conn.execute("SELECT opening_value,delta_value FROM daily_raw_counter_records WHERE device_slot=0 AND canonical_field=? ORDER BY record_date", (TOTAL,)).fetchall()
    assert rows == [(2475, 5), (2480, 3)]


def test_first_poll_next_day_still_counts_from_setup_baseline(tmp_path):
    config = device()
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=10)
    create_setup(config, at)
    tomorrow = at + timedelta(days=1)
    cache = DailyCacheStore(tmp_path / "daily")
    state = cache.update_reading(0, meter(config, 2480, tomorrow), at=tomorrow)
    assert state["opening"][TOTAL] == 2475
    assert state["delta"][TOTAL] == 5


@pytest.mark.parametrize("marker", ["sample_count", "counter_review", "cache_corruption", "unsafe_reconciliation_seen"])
def test_initial_epoch_never_replaces_existing_or_held_cache(marker):
    config = device()
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=10)
    create_setup(config, at)
    later = at + timedelta(seconds=1)
    state = {"opening": {TOTAL: 2400}, "latest": {TOTAL: 2400}, "delta": {TOTAL: 0},
        "sample_count": 0, "subjects": {}, "device_identity": {"serial": config.serial, "host": config.host}}
    state[marker] = 1 if marker == "sample_count" else True
    original = deepcopy(state)
    bridge_device_state(0, state, meter(config, 2480, later), later)
    assert state == original
    bridge_subject_state(0, state, meter(config, 2480, later), later)
    assert state == original


def test_initial_epoch_never_replaces_legacy_sql_opening_or_existing_raw(tmp_path):
    config = device()
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=10)
    create_setup(config, at)
    with _open() as conn:
        conn.execute("""INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,created_at)
            VALUES(0,'2026-01-01','{}','{}','{}','2026-01-01')""")
    state = {"opening": {TOTAL: 2400}, "latest": {TOTAL: 2400}, "delta": {TOTAL: 0}, "sample_count": 0}
    original = deepcopy(state)
    later = at + timedelta(seconds=1)
    bridge_device_state(0, state, meter(config, 2480, later), later)
    assert state == original
    raw = RawCounterHistoryStore()
    # A pre-existing local raw row is left to its normal incremental collector.
    raw.update_reading(0, meter(config, 2400, at - timedelta(seconds=1)), at=at - timedelta(seconds=1))
    raw.update_reading(0, meter(config, 2480, later), at=later)
    with _open(commit=False) as conn:
        result = conn.execute("SELECT opening_value,delta_value,counter_resolutions_json FROM daily_raw_counter_records WHERE device_slot=0 AND canonical_field=?", (TOTAL,)).fetchone()
    assert result[:2] == (2400, 80)
    assert json.loads(result[2]) == []


def test_other_initial_epoch_actors_keep_existing_collector_behavior(tmp_path):
    config = device()
    DeviceConfigRepository().replace_all([config])
    at = datetime.now(UTC).replace(microsecond=0)
    baseline = WebObservationStore().record(0, meter(config, 2475, at), serial=config.serial,
                                           printer_name=config.name, at=at)
    store = SlotEpochStore()
    store.confirm(store.preview(0, baseline["id"], operation="initial", actor="existing_adoption", reason="reviewed"))
    later = at + timedelta(seconds=1)
    state = DailyCacheStore(tmp_path / "cache").update_reading(0, meter(config, 2480, later), at=later)
    assert state["delta"][TOTAL] == 0
    assert not state.get("initial_setup_baseline")


def test_confirming_added_slot_three_unblocks_enrolled_scope_without_rebasing_other_slots():
    from services.peer_settings_history import SettingsHistory
    from test_upgrade_baseline_routing import membership

    devices = [device(slot) for slot in range(3)]
    at = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=10)
    baselines = SetupMeterBaselines()
    initial = baselines.prepare(devices[:2], {
        item.slot: baselines.capture(item, meter(item, 2475, at)) for item in devices[:2]
    }, {0, 1})
    service = setup_service()
    service.commit(preview(service, devices[:2], plan=initial))
    original_heads = {slot: SlotEpochStore().head(slot) for slot in (0, 1)}
    access = membership()
    # Reproduce the existing defect: setup saved the third device's SNMP identity,
    # but no Web baseline was committed, so shared collection correctly refused it.
    DeviceConfigRepository().replace_all([*devices[:2], replace(devices[2], last_total=2475)])
    SettingsHistory().observe_current()
    with pytest.raises(PermissionError, match="reviewed setup and meter baseline"):
        access.current_scope(2)
    assert access.current_scope(0).epoch_id == original_heads[0]["id"]
    assert access.current_scope(1).epoch_id == original_heads[1]["id"]

    plan = baselines.prepare(devices, {2: baselines.capture(devices[2], meter(devices[2], 2475, at))}, {2})
    assert [entry.slot for entry in plan.entries] == [2]
    revision = service.commit(service.preview(devices, {}, [], baseline_plan=plan))
    scope = access.current_scope(2)
    assert scope.serial == devices[2].serial
    assert scope.settings_revision == revision
    assert scope.epoch_id == dict(plan.slot_epochs)[2]
    assert all(SlotEpochStore().head(slot) == original for slot, original in original_heads.items())

    # The next verified collection can commit under that exact enrolled scope.
    stamp = at + timedelta(seconds=1)
    WebObservationStore().record(2, meter(devices[2], 2480, stamp), serial=scope.serial,
        printer_name=devices[2].name, at=stamp, epoch_id=scope.epoch_id)
    projection = SlotEpochStore().current(2)
    counter = next(item for item in projection.counters if json.loads(item.key)[0] == TOTAL)
    assert counter.epoch_usage == 5
    assert all(SlotEpochStore().head(slot) == original for slot, original in original_heads.items())
