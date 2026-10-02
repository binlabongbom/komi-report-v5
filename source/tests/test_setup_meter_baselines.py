from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
import sqlite3

import pytest

import database
from komi_snmp_profiler.credential_store import SessionCredentialStore
from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.peer_settings_history import SettingsHistory
from services.pricing import PriceList
from services.setup_meter_baselines import SetupMeterBaselines
from services.setup_settings import SetupSettingsService
from services.slot_epoch_store import SlotEpochStore
from services.web_observations import WebObservationStore


def device(slot=0, *, serial=None, **kwargs):
    return DeviceConfig(slot, f"Fixture {slot + 1}", f"192.0.2.{10 + slot}",
        serial=serial or f"SYNTHETIC-{slot}", **kwargs)


def reading(config, total=2475, *, at=None):
    values = {"counter.total.total": total, "counter.print.total": total - 10,
        "counter.print.full_color_total": total - 110, "counter.print.full_color_large": 100,
        "counter.print.bw_total": 100, "counter.print.bw_large": 0,
        "counter.copy.total": 10, "counter.copy.full_color_total": 5,
        "counter.copy.full_color_large": 0, "counter.copy.bw_total": 5,
        "counter.copy.bw_large": 0, "counter.scan_fax.document_read_total": 346}
    return MeterReading(config.host, (at or datetime.now(UTC)).isoformat(),
        tuple(WebCounterValue(key, key, value, "fixture", f"Fixture/{key}") for key, value in values.items()),
        "synthetic-web", WebAuthState.ADMIN)


def setup_service():
    return SetupSettingsService(DeviceConfigRepository(SessionCredentialStore()))


def preview(service, devices, *, plan=None):
    return service.preview(devices,
        {"company_name": "Synthetic Company", "client_first_started_at": "2026-09-01"},
        [(item.slot, date(2026, 9, 1), PriceList(a4_color=2, a4_bw=.2)) for item in devices],
        baseline_plan=plan)


def plan_for(devices):
    baselines = SetupMeterBaselines()
    return baselines.prepare(devices,
        {item.slot: baselines.capture(item, reading(item)) for item in devices},
        {item.slot for item in devices})


def state():
    with database._open(commit=False) as conn:
        return {table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in (
            "devices", "settings", "price_history", "config_log", "web_observations",
            "web_observation_state", "web_observation_outbox", "slot_meter_epochs", "slot_meter_heads",
            "slot_meter_epoch_state", "slot_meter_assignments", "slot_meter_maxima", "slot_meter_epoch_outbox",
            "shared_report_days", "shared_report_months", "shared_report_events", "peer_settings_revisions",
            "peer_settings_state")}


def total(projection):
    return next(item for item in projection.counters if json.loads(item.key)[0] == "counter.total.total")


def test_three_new_slots_commit_evidence_epochs_prices_and_one_revision_atomically():
    devices = [device(slot) for slot in range(3)]
    before = state()
    plan = plan_for(devices)
    service = setup_service()
    reviewed = preview(service, devices, plan=plan)
    assert state() == before
    revision = service.commit(reviewed)
    after = state()
    for table in ("web_observations", "web_observation_outbox", "slot_meter_epochs",
                  "slot_meter_heads", "slot_meter_epoch_outbox", "shared_report_days"):
        assert len(after[table]) == 3
    payload = SettingsHistory().export()["revisions"][revision]["payload"]
    assert payload["format_version"] == 3
    assert payload["slot_epochs"] == [{"slot": slot, "epoch_id": head} for slot, head in plan.slot_epochs]
    for slot in range(3):
        assert total(SlotEpochStore().current(slot)).epoch_usage == 0
        assert total(SlotEpochStore().current(slot)).slot_total == 2475


def test_first_post_setup_read_counts_only_increment():
    config = device()
    service = setup_service()
    plan = plan_for([config])
    service.commit(preview(service, [config], plan=plan))
    WebObservationStore().record(config.slot, reading(config, 2480,
        at=datetime.now(UTC) + timedelta(seconds=1)), serial=config.serial,
        printer_name=config.name, epoch_id=dict(plan.slot_epochs)[0])
    assert total(SlotEpochStore().current(0)).epoch_usage == 5
    assert total(SlotEpochStore().current(0)).slot_total == 2480


def test_configured_slot_three_with_snmp_total_but_no_web_history_is_initial():
    devices = [device(slot) for slot in range(3)]
    service = setup_service()
    old = plan_for(devices[:2])
    service.commit(preview(service, devices[:2], plan=old))
    # Reproduce the previously saved but blocked Slot 3: total from SNMP only.
    DeviceConfigRepository().replace_all([*devices[:2], replace(devices[2], last_total=2475)])
    before_heads = dict(old.slot_epochs)
    baselines = SetupMeterBaselines()
    requirements = baselines.classify(devices)
    assert [item.operation for item in requirements] == ["preserve", "preserve", "initial"]
    evidence = baselines.capture(devices[2], reading(devices[2]))
    plan = baselines.prepare(devices, {2: evidence}, {2})
    assert [item.slot for item in plan.entries] == [2]
    service.commit(preview(service, devices, plan=plan))
    assert all(SlotEpochStore().head(slot)["id"] == head for slot, head in before_heads.items())
    assert SlotEpochStore().head(2) is not None


@pytest.mark.parametrize("legacy_proof", ["daily", "last_success", "imported"])
def test_upgrade_without_epochs_never_requires_or_replaces_legacy_baselines(legacy_proof):
    config = device()
    service = setup_service()
    service.commit(preview(service, [config]))
    with database._open() as conn:
        if legacy_proof == "daily":
            conn.execute("""INSERT INTO daily_meter_records(device_slot,record_date,opening_json,
                closing_json,delta_json,created_at) VALUES(0,'2026-08-01','{"total":2400}',
                '{"total":2470}','{"total":70}','2026-08-01')""")
        elif legacy_proof == "last_success":
            conn.execute("UPDATE devices SET last_success_at='2026-08-01T00:00:00+00:00',last_total=2470 WHERE slot=0")
        else:
            conn.execute("INSERT INTO readings(slot,serial,data_json) VALUES(0,?,?)", (config.serial, '{"total":2470}'))
        protected = {table: conn.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("daily_meter_records", "readings")}
    baselines = SetupMeterBaselines()
    requirement, = baselines.classify([config])
    assert requirement.operation == "legacy" and not requirement.requires_confirmation
    plan = baselines.prepare([config], {}, set())
    assert not plan.entries and not plan.slot_epochs
    service.commit(preview(service, [replace(config, name="Renamed")], plan=plan))
    assert SlotEpochStore().head(0) is None
    assert baselines.classify([config])[0].operation == "legacy"
    with database._open(commit=False) as conn:
        assert protected == {table: conn.execute(f"SELECT * FROM {table}").fetchall() for table in protected}


def test_replacement_carries_old_slot_total_and_records_only_new_machine_increment():
    old = device()
    service = setup_service()
    old_plan = plan_for([old])
    service.commit(preview(service, [old], plan=old_plan))
    new = replace(old, serial="REPLACEMENT")
    baselines = SetupMeterBaselines()
    evidence = baselines.capture(new, reading(new, 50000))
    with pytest.raises(ValueError, match="ยืนยัน"):
        baselines.prepare([new], {0: evidence}, set())
    plan = baselines.prepare([new], {0: evidence}, {0})
    assert plan.entries[0].operation == "replacement"
    service.commit(preview(service, [new], plan=plan))
    current = total(SlotEpochStore().current(0))
    assert current.physical_maximum == 50000 and current.slot_total == 2475
    WebObservationStore().record(0, reading(new, 50005, at=datetime.now(UTC) + timedelta(seconds=1)),
        serial=new.serial, printer_name=new.name, epoch_id=dict(plan.slot_epochs)[0])
    assert total(SlotEpochStore().current(0)).slot_total == 2480


@pytest.mark.parametrize("failure", ["observation", "epoch", "settings"])
def test_setup_failure_rolls_back_configuration_evidence_epochs_prices_and_vault(failure, monkeypatch):
    config = device(password="synthetic-secret")
    plan = plan_for([config])
    service = setup_service()
    reviewed = preview(service, [config], plan=plan)
    if failure == "settings":
        monkeypatch.setattr(SettingsHistory, "_append", lambda *args: (_ for _ in ()).throw(RuntimeError("injected")))
    else:
        table = "web_observation_outbox" if failure == "observation" else "slot_meter_epoch_outbox"
        with database._open() as conn:
            conn.execute(f"CREATE TRIGGER fail_before_save BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected'); END")
    before = state()
    with pytest.raises((RuntimeError, sqlite3.IntegrityError), match="injected"):
        service.commit(reviewed)
    assert state() == before
    assert not service.repository.list()


@pytest.mark.parametrize("field,value", [("host", "192.0.2.99"), ("serial", "OTHER"),
    ("password", "changed"), ("username", "changed"), ("tls_mode", "insecure")])
def test_connection_change_invalidates_retained_evidence(field, value):
    config = device()
    baselines = SetupMeterBaselines()
    evidence = baselines.capture(config, reading(config))
    updated = replace(config, **{field: value})
    with pytest.raises(ValueError):
        baselines.validate_evidence(updated, evidence)


def test_name_change_is_allowed_but_stale_or_partial_reading_is_not():
    config = device()
    baselines = SetupMeterBaselines()
    evidence = baselines.capture(config, reading(config))
    baselines.validate_evidence(replace(config, name="Changed label"), evidence)
    with pytest.raises(ValueError, match="30"):
        baselines.capture(config, reading(config, at=datetime.now(UTC) - timedelta(minutes=31)))
    original = reading(config)
    with pytest.raises(ValueError, match="ผลรวม"):
        baselines.capture(config, replace(original, counters=original.counters[:1]))
    with pytest.raises(ValueError, match="Counter"):
        baselines.capture(config, replace(original,
            counters=(replace(original.counters[0], confidence=Confidence.INFERRED), *original.counters[1:])))


def test_new_read_after_review_prevents_stale_replacement_commit():
    old = device()
    service = setup_service()
    initial = plan_for([old])
    service.commit(preview(service, [old], plan=initial))
    new = replace(old, serial="NEW")
    plan = plan_for([new])
    reviewed = preview(service, [new], plan=plan)
    WebObservationStore().record(0, reading(old, 2490), serial=old.serial,
        printer_name=old.name, epoch_id=dict(initial.slot_epochs)[0])
    before = state()
    with pytest.raises(ValueError, match="หลังตรวจ"):
        service.commit(reviewed)
    assert state() == before
