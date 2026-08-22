from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, date, datetime

import pytest

from database import _open, init_db, set_db_path
from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pipeline_log import pipeline_log
from services.pricing import PriceList, PricingRepository
from services.reconciliation import KONICA_DEVICE_METER_V2, ReconciliationReport


def _reading(value: int, at: datetime) -> MeterReading:
    return MeterReading(
        host="192.0.2.10",
        collected_at=at.astimezone(UTC).isoformat(),
        counters=(
            WebCounterValue(
                canonical_field="counter.paper.full_color.a4",
                label="A4 Full Color",
                count=value,
                category="Paper size full color",
                source_path="fixture",
                confidence=Confidence.VERIFIED,
            ),
        ),
        source="fixture",
        auth_state=WebAuthState.ADMIN,
    )


def test_daily_cache_accumulates_delta_and_rolls_up_once(tmp_path):
    set_db_path(tmp_path / "daily.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    cache = DailyCacheStore(tmp_path / "cache")
    first = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    second = datetime(2026, 7, 16, 17, 0, tzinfo=UTC)

    cache.update_reading(0, _reading(100, first), at=first)
    state = cache.update_reading(0, _reading(135, second), at=second)
    record = cache.finalize(0, date(2026, 7, 16))

    assert state["delta"]["counter.paper.full_color.a4"] == 35
    assert record is not None
    assert record.delta["counter.paper.full_color.a4"] == 35
    assert cache.path(0, date(2026, 7, 16)).exists() is False


def test_daily_rollup_preserves_counter_sources_and_reconciliation_audit(tmp_path):
    set_db_path(tmp_path / "audit.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    cache = DailyCacheStore(tmp_path / "cache")
    stamp = datetime(2026, 7, 16, 17, 0, tzinfo=UTC)
    reconciliation = ReconciliationReport(
        checked_count=16,
        issues=(),
        profile_id=KONICA_DEVICE_METER_V2.profile_id,
    )

    cache.update_reading(0, _reading(135, stamp), at=stamp, reconciliation=reconciliation)
    cache.finalize(0, stamp.date())

    with _open(commit=False) as conn:
        row = conn.execute(
            "SELECT source_json FROM daily_meter_records WHERE device_slot=? AND record_date=?",
            (0, stamp.date().isoformat()),
        ).fetchone()
    source = json.loads(row[0])

    assert source["counter_sources"]["counter.paper.full_color.a4"]["source_path"] == "fixture"
    assert source["reconciliation"] == {
        "billing_safe": True,
        "checked_count": 16,
        "issues": [],
        "needs_review": False,
        "profile_id": KONICA_DEVICE_METER_V2.profile_id,
    }


def test_counter_reset_creates_segment_without_negative_usage(tmp_path):
    set_db_path(tmp_path / "reset.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    cache = DailyCacheStore(tmp_path / "cache")
    first = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)

    cache.update_reading(0, _reading(100, first), at=first)
    state = cache.update_reading(0, _reading(7, first.replace(hour=9)), at=first.replace(hour=9))

    assert state["delta"]["counter.paper.full_color.a4"] == 7
    assert len(state["resets"]) == 1


def test_snmp_heartbeat_persists_latest_toner_without_clearing_last_known_value(tmp_path):
    set_db_path(tmp_path / "heartbeat.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    cache = DailyCacheStore(tmp_path / "cache")
    stamp = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)

    state = cache.record_heartbeat(0, total=100, toner={"C": 61, "Y": 74, "M": 80, "K": 57}, at=stamp)
    retained = cache.record_heartbeat(0, total=101, toner={}, at=stamp.replace(minute=5))

    assert state["snmp_toner"] == {"C": 61, "Y": 74, "M": 80, "K": 57}
    assert retained["snmp_toner"] == state["snmp_toner"]


def test_snmp_heartbeat_persists_paper_telemetry_separately_from_billing_data(tmp_path):
    set_db_path(tmp_path / "heartbeat-paper.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    cache = DailyCacheStore(tmp_path / "cache")
    stamp = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)

    state = cache.record_heartbeat(
        0,
        total=100,
        paper=[{"name": "Tray 1", "level": 0, "capacity": 500, "status": 6}],
        paper_alerts=["Paper empty"],
        at=stamp,
    )

    assert state["snmp_paper"] == [{"name": "Tray 1", "level": 0, "capacity": 500, "status": 6}]
    assert state["snmp_paper_alerts"] == ["Paper empty"]
    assert "snmp_paper" not in state["latest"]

    unavailable = cache.record_heartbeat(
        0,
        total=101,
        paper=[],
        paper_alerts=[],
        at=stamp.replace(minute=5),
    )

    assert unavailable["snmp_paper"] == []
    assert unavailable["snmp_paper_alerts"] == []


@pytest.mark.parametrize("with_heartbeat", [True, False], ids=["heartbeat-and-web-error", "offline-only"])
def test_rollover_finalizes_observed_day_without_web_success_as_zero_usage_hold(
    tmp_path,
    with_heartbeat,
):
    set_db_path(tmp_path / "missing-web-success.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
    cache = DailyCacheStore(tmp_path / "cache")
    stamp = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    if with_heartbeat:
        cache.record_heartbeat(0, total=100, toner={"K": 57}, at=stamp)
    state = cache.record_error(0, stamp.date(), "Web Connection timeout", at=stamp)

    assert state["first_success"] is None
    records = cache.finalize_before(date(2026, 7, 17))

    assert len(records) == 1
    assert records[0].delta == {}
    assert records[0].sample_count == 0
    assert records[0].error_count == 1
    assert records[0].incomplete is True
    assert cache.path(0, stamp.date()).exists() is False
    assert cache.finalize_before(date(2026, 7, 17)) == []

    with _open(commit=False) as conn:
        daily = conn.execute(
            """SELECT opening_json,closing_json,delta_json,source_json,first_success,last_success,
                      sample_count,error_count,incomplete
               FROM daily_meter_records"""
        ).fetchone()
        ledger = conn.execute(
            """SELECT entry_kind,hold_reason,delta_json,gross_cents,net_cents,source_daily_record_id
               FROM billing_ledger"""
        ).fetchone()
        counts = conn.execute(
            """SELECT (SELECT COUNT(*) FROM daily_meter_records),
                      (SELECT COUNT(*) FROM billing_ledger)"""
        ).fetchone()

    source = json.loads(daily[3])
    assert json.loads(daily[0]) == {}
    assert json.loads(daily[1]) == {}
    assert json.loads(daily[2]) == {}
    assert daily[4:] == (None, None, 0, 1, 1)
    assert source["billing_ledger_expected"] == "komi.billing.v1"
    assert source["missing_web_success"] is True
    assert source["heartbeat_count"] == int(with_heartbeat)
    assert source["last_error"]["message"] == "Web Connection timeout"
    if with_heartbeat:
        assert source["last_snmp_total"] == 100
        assert source["snmp_toner"] == {"K": 57}
    assert ledger[:2] == ("hold", "missing_web_success")
    assert json.loads(ledger[2]) == {}
    assert ledger[3:5] == (0, 0)
    assert ledger[5] is not None
    assert counts == (1, 1)


def test_missing_web_success_rollover_repairs_crash_gap_idempotently(tmp_path, monkeypatch):
    import services.billing_ledger as billing_ledger

    set_db_path(tmp_path / "missing-web-crash.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")]
    )
    cache = DailyCacheStore(tmp_path / "cache")
    stamp = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    cache.record_error(0, stamp.date(), "offline", at=stamp)
    real_post = billing_ledger.post_daily_record

    def crash_after_source_insert(_record_id: int):
        raise RuntimeError("simulated missing-web crash gap")

    monkeypatch.setattr(billing_ledger, "post_daily_record", crash_after_source_insert)
    with pytest.raises(RuntimeError, match="simulated missing-web crash gap"):
        cache.finalize_before(date(2026, 7, 17))
    assert cache.path(0, stamp.date()).exists()

    monkeypatch.setattr(billing_ledger, "post_daily_record", real_post)
    assert cache.finalize_before(date(2026, 7, 17)) == []
    assert cache.path(0, stamp.date()).exists() is False
    with _open(commit=False) as conn:
        counts = conn.execute(
            """SELECT (SELECT COUNT(*) FROM daily_meter_records),
                      (SELECT COUNT(*) FROM billing_ledger)"""
        ).fetchone()
        ledger = conn.execute(
            "SELECT entry_kind,gross_cents,net_cents FROM billing_ledger"
        ).fetchone()
    assert counts == (1, 1)
    assert ledger == ("hold", 0, 0)


def test_late_reading_is_rejected_without_inflating_delta(tmp_path):
    set_db_path(tmp_path / "late.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    cache = DailyCacheStore(tmp_path / "cache")
    first = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    latest = first.replace(hour=10)
    late = first.replace(hour=9)

    cache.update_reading(0, _reading(100, first), at=first)
    cache.update_reading(0, _reading(125, latest), at=latest)
    state = cache.update_reading(0, _reading(110, late), at=late)

    assert state["latest"]["counter.paper.full_color.a4"] == 125
    assert state["delta"]["counter.paper.full_color.a4"] == 25
    assert state["last_success"] == latest.isoformat(timespec="seconds")
    assert state["out_of_order"] is True
    assert state["ordering_issues"][-1]["reason"] == "late_sample"


def test_finalize_retry_repairs_crash_gap_and_keeps_capture_time_identity(tmp_path, monkeypatch):
    import services.billing_ledger as billing_ledger

    set_db_path(tmp_path / "crash.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Office A", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    cache = DailyCacheStore(tmp_path / "cache")
    stamp = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    reconciliation = ReconciliationReport(checked_count=1, issues=())
    cache.update_reading(0, _reading(100, stamp), at=stamp, reconciliation=reconciliation)
    real_post = billing_ledger.post_daily_record

    def crash_after_source_insert(_record_id: int):
        raise RuntimeError("simulated crash gap")

    monkeypatch.setattr(billing_ledger, "post_daily_record", crash_after_source_insert)
    with pytest.raises(RuntimeError, match="simulated crash gap"):
        cache.finalize(0, stamp.date())
    assert cache.path(0, stamp.date()).exists()

    repository.replace_all([DeviceConfig(0, "Office B", "192.0.2.11", serial="SER-B")])
    monkeypatch.setattr(billing_ledger, "post_daily_record", real_post)
    assert cache.repair_pending_ledger() == 1
    assert cache.finalize(0, stamp.date()) is None
    assert cache.path(0, stamp.date()).exists() is False
    with _open(commit=False) as conn:
        identity, serial = conn.execute(
            "SELECT device_identity,device_serial_snapshot FROM billing_ledger"
        ).fetchone()
    assert (identity, serial) == ("serial:SER-A", "SER-A")


def test_late_same_day_cache_is_retained_when_finalized_source_differs(tmp_path):
    set_db_path(tmp_path / "late-finalize.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    cache = DailyCacheStore(tmp_path / "cache")
    reconciliation = ReconciliationReport(checked_count=1, issues=())
    first = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    latest = first.replace(hour=10)
    cache.update_reading(0, _reading(100, first), at=first, reconciliation=reconciliation)
    cache.update_reading(0, _reading(125, latest), at=latest, reconciliation=reconciliation)
    assert cache.finalize(0, first.date()) is not None

    heartbeat_at = first.replace(hour=11)
    cache.record_heartbeat(0, total=125, at=heartbeat_at)
    cache.update_reading(0, _reading(150, first.replace(hour=12)), at=first.replace(hour=12), reconciliation=reconciliation)

    assert cache.finalize(0, first.date()) is None
    conflict = cache.load(0, first.date())
    assert conflict is not None
    assert conflict["finalization_conflict"]["reason"] == "same_day_source_evidence_differs"
    with _open(commit=False) as conn:
        closing_json, delta_json = conn.execute(
            "SELECT closing_json,delta_json FROM daily_meter_records"
        ).fetchone()
    assert json.loads(closing_json)["counter.paper.full_color.a4"] == 125
    assert json.loads(delta_json)["counter.paper.full_color.a4"] == 25


def test_pending_repair_isolates_corrupt_source_and_continues(tmp_path):
    set_db_path(tmp_path / "corrupt-repair.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _open() as conn:
        for record_day, delta_json in (("2026-07-15", "{broken"), ("2026-07-16", json.dumps({"counter.total.total": 1}))):
            conn.execute(
                """INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,
                       category_json,source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    record_day,
                    "{}",
                    "{}",
                    delta_json,
                    json.dumps({"counter.total.total": "no_charge"}),
                    json.dumps(
                        {
                            "billing_ledger_expected": "komi.billing.v1",
                            "reconciliation": {"billing_safe": True},
                        }
                    ),
                    now,
                    now,
                    1,
                    0,
                    0,
                    now,
                ),
            )

    assert DailyCacheStore(tmp_path / "cache").repair_pending_ledger() == 2
    with _open(commit=False) as conn:
        rows = conn.execute(
            "SELECT record_date,entry_kind,hold_reason FROM billing_ledger ORDER BY record_date"
        ).fetchall()
    assert rows == [
        ("2026-07-15", "hold", "invalid_source_json"),
        ("2026-07-16", "posting", None),
    ]


def test_pending_repair_skips_legacy_rows_without_explicit_marker(tmp_path):
    set_db_path(tmp_path / "migration-gate.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _open() as conn:
        for record_day, marked in (("2026-07-15", False), ("2026-07-16", True)):
            source = {"reconciliation": {"billing_safe": True}}
            if marked:
                source["billing_ledger_expected"] = "komi.billing.v1"
            conn.execute(
                """INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,
                       category_json,source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    record_day,
                    "{}",
                    "{}",
                    json.dumps({"counter.total.total": 1}),
                    json.dumps({"counter.total.total": "no_charge"}),
                    json.dumps(source),
                    now,
                    now,
                    1,
                    0,
                    0,
                    now,
                ),
            )

    assert DailyCacheStore(tmp_path / "cache").repair_pending_ledger() == 1
    with _open(commit=False) as conn:
        ledger_days = conn.execute("SELECT record_date FROM billing_ledger ORDER BY record_date").fetchall()
        pending_days = conn.execute(
            """SELECT record_date FROM daily_meter_records d WHERE NOT EXISTS
               (SELECT 1 FROM billing_ledger l WHERE l.source_daily_record_id=d.id)"""
        ).fetchall()
    assert ledger_days == [("2026-07-16",)]
    assert pending_days == [("2026-07-15",)]


def test_next_day_slot_reuse_does_not_carry_prior_device_or_reject_first_web_sample(tmp_path):
    set_db_path(tmp_path / "next-day-slot-reuse.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Office A", "192.0.2.10", serial="SER-A")])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    cache = DailyCacheStore(tmp_path / "cache")
    reconciliation = ReconciliationReport(checked_count=1, issues=())
    day_one = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    cache.update_reading(0, _reading(100, day_one), at=day_one, reconciliation=reconciliation)
    cache.update_reading(
        0,
        _reading(125, day_one.replace(hour=10)),
        at=day_one.replace(hour=10),
        reconciliation=reconciliation,
    )
    assert cache.finalize(0, day_one.date()) is not None

    repository.replace_all([DeviceConfig(0, "Office B", "192.0.2.11", serial="SER-B")])
    day_two = day_one.replace(day=17)
    cache.record_heartbeat(0, total=200, at=day_two)
    state = cache.update_reading(0, _reading(200, day_two), at=day_two, reconciliation=reconciliation)

    assert state["opening"]["counter.paper.full_color.a4"] == 200
    assert state["latest"]["counter.paper.full_color.a4"] == 200
    assert state["delta"]["counter.paper.full_color.a4"] == 0
    assert state["sample_count"] == 1
    assert state.get("out_of_order") is not True
    assert state["identity_baseline_mismatch"]["previous"]["serial"] == "SER-A"
    assert state["identity_baseline_mismatch"]["current"]["serial"] == "SER-B"

    assert cache.finalize(0, day_two.date()) is not None
    with _open(commit=False) as conn:
        kind, reason, identity = conn.execute(
            "SELECT entry_kind,hold_reason,device_identity FROM billing_ledger ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert (kind, reason, identity) == ("hold", "device_identity_conflict", "serial:SER-B")


def test_corrupt_cache_is_quarantined_and_rolls_over_as_visible_hold(tmp_path):
    set_db_path(tmp_path / "corrupt-cache.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")]
    )
    cache = DailyCacheStore(tmp_path / "cache")
    day = date(2026, 7, 16)
    path = cache.path(0, day)
    path.parent.mkdir(parents=True)
    raw = b'{"schema_version": "komi.daily.cache.v2", broken'
    path.write_bytes(raw)
    pipeline_log.clear()

    records = cache.finalize_before(date(2026, 7, 17))

    assert len(records) == 1
    assert records[0].incomplete is True
    assert path.exists() is False
    quarantined = list(path.parent.glob(f"{path.name}.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == raw
    with _open(commit=False) as conn:
        source_json = conn.execute("SELECT source_json FROM daily_meter_records").fetchone()[0]
        ledger = conn.execute(
            "SELECT entry_kind,hold_reason FROM billing_ledger"
        ).fetchone()
    source = json.loads(source_json)
    assert source["missing_web_success"] is True
    assert source["cache_corruption"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert source["cache_corruption"]["quarantine_path"] == str(quarantined[0])
    assert ledger == ("hold", "missing_web_success")
    event = next(
        event
        for event in pipeline_log.snapshot()
        if event.action == "Daily cache corruption quarantined"
    )
    assert event.device_slot == 0
    assert event.target == str(quarantined[0])
    assert event.status == "error"


def test_valid_web_samples_after_corrupt_cache_remain_held_for_manual_review(tmp_path):
    set_db_path(tmp_path / "corrupt-then-web.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    cache = DailyCacheStore(tmp_path / "cache")
    first = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    path = cache.path(0, first.date())
    path.parent.mkdir(parents=True)
    raw = b"not-json-at-all"
    path.write_bytes(raw)
    reconciliation = ReconciliationReport(checked_count=1, issues=())

    first_state = cache.update_reading(
        0,
        _reading(100, first),
        at=first,
        reconciliation=reconciliation,
    )
    cache.record_heartbeat(0, total=125, at=first.replace(hour=17))
    final_state = cache.update_reading(
        0,
        _reading(125, first.replace(hour=17)),
        at=first.replace(hour=17),
        reconciliation=reconciliation,
    )
    assert cache.finalize(0, first.date()) is not None

    assert first_state["cache_corruption"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert final_state["delta"]["counter.paper.full_color.a4"] == 25
    quarantined = list(path.parent.glob(f"{path.name}.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == raw
    with _open(commit=False) as conn:
        ledger = conn.execute(
            "SELECT entry_kind,hold_reason,delta_json FROM billing_ledger"
        ).fetchone()
    assert ledger[:2] == ("hold", "unsafe_attestation_seen_during_day")
    assert json.loads(ledger[2])["counter.paper.full_color.a4"] == 25


def test_midnight_finalize_waits_for_inflight_cache_write_and_posts_once(tmp_path, monkeypatch):
    set_db_path(tmp_path / "midnight-race.db")
    init_db()
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))
    cache = DailyCacheStore(tmp_path / "cache")
    first = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    reconciliation = ReconciliationReport(checked_count=1, issues=())
    cache.update_reading(0, _reading(100, first), at=first, reconciliation=reconciliation)
    cache.record_heartbeat(0, total=125, at=first.replace(hour=17))

    writer_entered = threading.Event()
    release_writer = threading.Event()
    finalizer_started = threading.Event()
    finalizer_done = threading.Event()
    failures: list[Exception] = []
    finalized: list = []
    real_atomic_write = cache._atomic_write

    def blocking_atomic_write(path, data):
        if (
            threading.current_thread().name == "midnight-poll"
            and int(data.get("sample_count", 0)) == 2
        ):
            writer_entered.set()
            if not release_writer.wait(timeout=5):
                raise TimeoutError("test did not release in-flight cache writer")
        real_atomic_write(path, data)

    monkeypatch.setattr(cache, "_atomic_write", blocking_atomic_write)

    def write_last_sample() -> None:
        try:
            cache.update_reading(
                0,
                _reading(125, first.replace(hour=17)),
                at=first.replace(hour=17),
                reconciliation=reconciliation,
            )
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    def finalize_next_day() -> None:
        finalizer_started.set()
        try:
            finalized.extend(cache.finalize_before(date(2026, 7, 17)))
        except Exception as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            finalizer_done.set()

    writer = threading.Thread(target=write_last_sample, name="midnight-poll")
    writer.start()
    assert writer_entered.wait(timeout=5)
    finalizer = threading.Thread(target=finalize_next_day, name="midnight-finalize")
    finalizer.start()
    assert finalizer_started.wait(timeout=5)
    assert finalizer_done.wait(timeout=0.1) is False
    release_writer.set()
    writer.join(timeout=5)
    finalizer.join(timeout=5)

    assert failures == []
    assert writer.is_alive() is False
    assert finalizer.is_alive() is False
    assert len(finalized) == 1
    assert finalized[0].delta["counter.paper.full_color.a4"] == 25
    with _open(commit=False) as conn:
        counts = conn.execute(
            """SELECT (SELECT COUNT(*) FROM daily_meter_records),
                      (SELECT COUNT(*) FROM billing_ledger)"""
        ).fetchone()
        row = conn.execute(
            "SELECT delta_json,entry_kind FROM billing_ledger"
        ).fetchone()
    assert counts == (1, 1)
    assert json.loads(row[0])["counter.paper.full_color.a4"] == 25
    assert row[1] == "posting"
