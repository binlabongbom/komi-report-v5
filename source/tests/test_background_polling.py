from __future__ import annotations

import json
from datetime import UTC, date, datetime

from PyQt6.QtCore import QCoreApplication

from database import _open, get_cfg, init_db, set_db_path
from komi_snmp_profiler.connectors import WebConnectionSessionBusyError
from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.background_polling import BackgroundPollingCoordinator
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pipeline_log import pipeline_log
from services.pricing import PriceList, PricingRepository
from services.reconciliation import ReconciliationReport
from services.runtime_snapshots import runtime_snapshots
from services.snmp_probe import PaperTrayStatus, SnmpProbeResult, SnmpTotalProbe
from services.subject_history import SubjectDailyCacheStore


class FakeProbe:
    def read(self, _host: str) -> SnmpProbeResult:
        return SnmpProbeResult(
            101,
            "bizhub C450i",
            "SERIAL-1",
            total_oid=SnmpTotalProbe.PRIMARY_TOTAL_OID,
            total_candidates=((SnmpTotalProbe.PRIMARY_TOTAL_OID, 101),),
            toner=(("C", 61), ("Y", 74), ("M", 80), ("K", 57)),
            paper_trays=(PaperTrayStatus("Tray 1", 0, 500, 6),),
            paper_alerts=("Paper empty",),
        )


class FakeReader:
    def read(self, host: str) -> MeterReading:
        return MeterReading(
            host=host,
            collected_at=datetime.now(UTC).isoformat(),
            counters=(
                WebCounterValue(
                    "counter.total.total",
                    "Total",
                    101,
                    "Total",
                    "fixture",
                    Confidence.VERIFIED,
                ),
                WebCounterValue(
                    "counter.user.total.total",
                    "User Total",
                    42,
                    "User",
                    "fixture.user[1].total",
                    Confidence.VERIFIED,
                    "user",
                    "1",
                    "User 1",
                ),
                WebCounterValue(
                    "counter.user.print.bw_total",
                    "User Print B&W",
                    40,
                    "User",
                    "fixture.user[1]",
                    Confidence.VERIFIED,
                    "user",
                    "1",
                    "User 1",
                ),
            ),
            source="fixture",
            auth_state=WebAuthState.ADMIN,
        )


class MismatchedReader:
    def read(self, host: str) -> MeterReading:
        def counter(field: str, value: int) -> WebCounterValue:
            return WebCounterValue(
                field,
                field,
                value,
                "Meter",
                "fixture",
                Confidence.VERIFIED,
            )

        return MeterReading(
            host=host,
            collected_at=datetime.now(UTC).isoformat(),
            counters=(
                counter("counter.total.total", 101),
                counter("counter.print.total", 80),
                counter("counter.print.full_color_total", 50),
                counter("counter.print.bw_total", 20),
                counter("counter.copy.total", 20),
                counter("counter.copy.full_color_total", 5),
                counter("counter.copy.bw_total", 15),
            ),
            source="fixture",
            auth_state=WebAuthState.ADMIN,
        )


class SessionBusyReader:
    def read(self, _host: str) -> MeterReading:
        raise WebConnectionSessionBusyError("legacy session busy")


def test_poll_device_updates_identity_and_persistent_cache(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    set_db_path(tmp_path / "polling.db")
    init_db()
    repository = DeviceConfigRepository()
    device = DeviceConfig(0, "Office", "192.0.2.10", last_total=100)
    repository.replace_all([device])
    cache = DailyCacheStore(tmp_path / "cache")
    subject_cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
    pipeline_log.clear()
    runtime_snapshots.clear()
    coordinator = BackgroundPollingCoordinator(
        repository,
        probe=FakeProbe(),
        reader=FakeReader(),
        cache=cache,
        subject_cache=subject_cache,
    )

    saved = coordinator._poll_device(device, force_web=True)
    updated = repository.get(0)

    assert saved is True
    assert updated is not None
    assert updated.model == "bizhub C450i"
    assert updated.serial == "SERIAL-1"
    cached = cache.load(0, datetime.now().date())
    assert cached["sample_count"] == 1
    assert cached["snmp_toner"] == {"C": 61, "Y": 74, "M": 80, "K": 57}
    assert cached["snmp_paper"] == [{"name": "Tray 1", "level": 0, "capacity": 500, "status": 6}]
    assert get_cfg("snmp_total_oid_0") == SnmpTotalProbe.PRIMARY_TOTAL_OID
    assert len(runtime_snapshots.get(0).web_rows) == 1
    assert len(runtime_snapshots.get(0).subject_rows) == 2
    subject_state = subject_cache.load(0, datetime.now().date())
    assert subject_state["subjects"]["user:1"]["latest_total"] == 42
    stages = {event.stage for event in pipeline_log.snapshot()}
    assert {"SNMP", "WEB", "RAM", "POLICY"}.issubset(stages)
    assert any(event.action == "Toner response" and "C=61%" in str(event.value) for event in pipeline_log.snapshot())
    assert any(event.action == "Paper status response" and "state=empty" in str(event.value) for event in pipeline_log.snapshot())
    coordinator.stop()


def test_poll_device_logs_web_reconciliation_warning(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    set_db_path(tmp_path / "polling-warning.db")
    init_db()
    repository = DeviceConfigRepository()
    device = DeviceConfig(0, "Office", "192.0.2.10", last_total=100)
    repository.replace_all([device])
    pipeline_log.clear()
    cache = DailyCacheStore(tmp_path / "cache")
    coordinator = BackgroundPollingCoordinator(
        repository,
        probe=FakeProbe(),
        reader=MismatchedReader(),
        cache=cache,
    )

    assert coordinator._poll_device(device, force_web=True) is True

    warnings = [event for event in pipeline_log.snapshot() if event.action == "Reconciliation warning"]
    assert {event.target for event in warnings} >= {"print_total_by_color", "device_total_by_operation"}
    assert all(event.status == "warning" for event in warnings)
    state = cache.load(0, datetime.now().date())
    assert state["schema_version"] == "komi.daily.cache.v2"
    assert state["source"]["reconciliation"]["billing_safe"] is False
    assert state["source"]["reconciliation"]["profile_id"] == "konica.web_connection.device_meter.v2"
    assert state["source"]["counter_sources"]["counter.total.total"]["source_path"] == "fixture"
    assert any(event.action == "Billing evidence held for review" for event in pipeline_log.snapshot())
    coordinator.stop()


def test_session_busy_keeps_snmp_online_and_does_not_increment_web_failure(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    set_db_path(tmp_path / "session-busy.db")
    init_db()
    repository = DeviceConfigRepository()
    device = DeviceConfig(0, "Office", "192.0.2.10", last_total=100)
    repository.replace_all([device])
    pipeline_log.clear()
    coordinator = BackgroundPollingCoordinator(
        repository,
        probe=FakeProbe(),
        reader=SessionBusyReader(),
        cache=DailyCacheStore(tmp_path / "cache"),
    )

    assert coordinator._poll_device(device, force_web=True) is False

    updated = repository.get(0)
    assert updated is not None and updated.connection_status == "online"
    assert coordinator.states[0].web_failures == 0
    assert any(event.action == "Web Connection session busy" for event in pipeline_log.snapshot())
    coordinator.stop()


def test_start_repairs_pending_daily_ledger_before_scheduler_runs(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    set_db_path(tmp_path / "startup-repair.db")
    init_db()
    repository = DeviceConfigRepository()
    repository.replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A", enabled=False)]
    )
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with _open() as conn:
        record_ids = []
        for record_day, marked in (("2026-07-15", False), ("2026-07-16", True)):
            source = {
                "device_identity": {"name": "Office", "host": "192.0.2.10", "serial": "SER-A"},
                "reconciliation": {"billing_safe": True},
            }
            if marked:
                source["billing_ledger_expected"] = "komi.billing.v1"
            record_ids.append(
                conn.execute(
                    """INSERT INTO daily_meter_records(device_slot,record_date,opening_json,closing_json,delta_json,
                           category_json,source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
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
                ).fetchone()[0]
            )
    pipeline_log.clear()
    coordinator = BackgroundPollingCoordinator(
        repository,
        probe=FakeProbe(),
        reader=FakeReader(),
        cache=DailyCacheStore(tmp_path / "cache"),
    )

    coordinator.start()
    coordinator.stop()

    with _open(commit=False) as conn:
        ledger = conn.execute(
            "SELECT source_daily_record_id,entry_kind,device_identity FROM billing_ledger"
        ).fetchone()
        legacy_pending = conn.execute(
            "SELECT COUNT(*) FROM billing_ledger WHERE source_daily_record_id=?",
            (record_ids[0],),
        ).fetchone()[0]
    assert ledger == (record_ids[1], "posting", "serial:SER-A")
    assert legacy_pending == 0
    assert any(event.action == "Pending billing ledger repaired" for event in pipeline_log.snapshot())


def test_midnight_rollover_defers_active_slot_until_poll_finishes(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    set_db_path(tmp_path / "active-midnight.db")
    init_db()
    repository = DeviceConfigRepository()
    device = DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")
    repository.replace_all([device])
    PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
    cache = DailyCacheStore(tmp_path / "cache")
    subject_cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
    stamp = datetime(2026, 7, 16, 17, 0, tzinfo=UTC)
    reconciliation = ReconciliationReport(checked_count=1, issues=())
    cache.update_reading(0, FakeReader().read(device.host), at=stamp, reconciliation=reconciliation)
    cache.record_heartbeat(0, total=101, at=stamp)
    pipeline_log.clear()
    coordinator = BackgroundPollingCoordinator(
        repository,
        probe=FakeProbe(),
        reader=FakeReader(),
        cache=cache,
        subject_cache=subject_cache,
    )

    coordinator.active.add(0)
    coordinator._finalize_before(date(2026, 7, 17))
    with _open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM daily_meter_records").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 0
    assert cache.path(0, stamp.date()).exists()

    coordinator.active.remove(0)
    coordinator._finalize_before(date(2026, 7, 17))
    coordinator._finalize_before(date(2026, 7, 17))
    coordinator.stop()

    with _open(commit=False) as conn:
        counts = conn.execute(
            """SELECT (SELECT COUNT(*) FROM daily_meter_records),
                      (SELECT COUNT(*) FROM billing_ledger)"""
        ).fetchone()
    assert counts == (1, 1)
    assert cache.path(0, stamp.date()).exists() is False
    saved = [event for event in pipeline_log.snapshot() if event.action == "Daily rollup saved"]
    assert len(saved) == 1
