import json
import pytest
from datetime import UTC, date, datetime

import database
from komi_snmp_profiler.models import Confidence, MeterReading, WebAuthState, WebCounterValue
from services.billing_ledger import post_daily_record
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository
from services.report_scope import report_slots
from services.subject_history import SubjectDailyCacheStore, extract_subject_totals, load_subject_history


@pytest.mark.parametrize("bounds", ["start", "end", "both"])
def test_requested_range_does_not_parse_unrelated_old_or_future_rows(tmp_path, bounds):
    original = database.get_db_path()
    try:
        _setup_database(tmp_path)
        cache = SubjectDailyCacheStore(tmp_path / "subjects")
        at = datetime(2026, 7, 16, 8, tzinfo=UTC)
        cache.update_reading(0, _reading(100, collected_at=at), at=at)
        later = at.replace(hour=9)
        cache.update_reading(0, _reading(110, collected_at=later), at=later)
        cache.finalize(0, at.date())
        # A damaged row outside the requested window must not be decoded.
        excluded = "2020-01-01" if bounds != "end" else "2030-01-01"
        with database._open() as conn:
            conn.execute("""INSERT INTO daily_subject_records
                (device_slot,record_date,subject_type,subject_id,subject_name,opening_total,closing_total,
                 delta_total,warnings_json,created_at) VALUES(0,?,'user','old','old',0,0,0,'invalid-json',?)""",
                (excluded, at.isoformat()))
        kwargs = {}
        if bounds != "end":
            kwargs["period_start"] = at.date()
        if bounds != "start":
            kwargs["period_end"] = at.date()
        rows = load_subject_history([0], today=at.date(), cache=cache, **kwargs)
        assert len(rows) == 1 and rows[0].period_usage == 10
    finally:
        database.set_db_path(original)


def _reading(total: int, *, collected_at: datetime, subject_id: str = "u-1") -> MeterReading:
    return MeterReading(
        host="192.0.2.10",
        collected_at=collected_at.isoformat(),
        counters=(
            WebCounterValue(
                "counter.user.total.total",
                "Total Counter",
                total,
                "User",
                "fixture.user[1].total",
                Confidence.VERIFIED,
                "user",
                subject_id,
                "alice",
            ),
            WebCounterValue(
                "counter.user.print.bw_total",
                "Print B&W",
                total // 2,
                "User",
                "fixture.user[1].print_bw",
                Confidence.VERIFIED,
                "user",
                subject_id,
                "alice",
            ),
        ),
        source="fixture",
        auth_state=WebAuthState.ADMIN,
    )


def _setup_database(tmp_path) -> DeviceConfigRepository:
    database.set_db_path(tmp_path / "subject-history.sqlite3")
    database.init_db()
    repository = DeviceConfigRepository()
    repository.replace_all([DeviceConfig(0, "Office", "192.0.2.10")])
    return repository


def test_extract_subject_totals_keeps_only_exact_total_counter(tmp_path):
    original = database.get_db_path()
    try:
        _setup_database(tmp_path)
        reading = _reading(100, collected_at=datetime(2026, 7, 16, 8, tzinfo=UTC))

        totals = extract_subject_totals(reading)

        assert len(totals) == 1
        assert totals[0].total_counter == 100
        assert totals[0].canonical_field == "counter.user.total.total"
    finally:
        database.set_db_path(original)


def test_subject_daily_cache_accumulates_every_delta_in_the_day(tmp_path):
    original = database.get_db_path()
    try:
        _setup_database(tmp_path)
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        for hour, total in ((8, 100), (9, 110), (10, 125)):
            stamp = datetime(2026, 7, 16, hour, tzinfo=UTC)
            state = cache.update_reading(0, _reading(total, collected_at=stamp), at=stamp)

        subject = state["subjects"]["user:u-1"]
        assert subject["opening_total"] == 100
        assert subject["latest_total"] == 125
        assert subject["delta_total"] == 25
        assert subject["sample_count"] == 3

        history = load_subject_history([0], today=date(2026, 7, 16), cache=cache)
        assert history[0].period_usage == 25
        assert history[0].latest_total == 125
    finally:
        database.set_db_path(original)


def test_finalized_subject_history_uses_frozen_device_billing_period(tmp_path):
    original = database.get_db_path()
    try:
        repository = _setup_database(tmp_path)
        repository.replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")])
        database.set_cfg("billing_day", "25")
        PricingRepository().set_prices(0, date(2026, 7, 1), PriceList())
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        first = datetime(2026, 7, 16, 8, tzinfo=UTC)
        cache.update_reading(0, _reading(100, collected_at=first), at=first)
        cache.update_reading(
            0,
            _reading(125, collected_at=first.replace(hour=10)),
            at=first.replace(hour=10),
        )
        assert len(cache.finalize(0, first.date())) == 1

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with database._open() as conn:
            record_id = conn.execute(
                """INSERT INTO daily_meter_records(
                       device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                       source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    0,
                    "2026-07-16",
                    "{}",
                    "{}",
                    json.dumps({"counter.total.total": 25}),
                    json.dumps({"counter.total.total": "no_charge"}),
                    json.dumps({"reconciliation": {"billing_safe": True}}),
                    now,
                    now,
                    2,
                    0,
                    0,
                    now,
                ),
            ).lastrowid
        post_daily_record(record_id)

        database.set_cfg("billing_day", "1")
        history = load_subject_history([0], today=first.date(), cache=cache)

        assert len(history) == 1
        assert history[0].period_start == date(2026, 6, 26)
        assert history[0].period_end == date(2026, 7, 25)
        assert history[0].period_usage == 25
        with database._open() as conn:
            conn.execute("""INSERT INTO daily_subject_records
                (device_slot,record_date,subject_type,subject_id,subject_name,opening_total,closing_total,
                 delta_total,warnings_json,created_at) VALUES(0,'2000-01-01','user','excluded','excluded',0,0,0,'invalid-json',?)""",
                (now,))
        bounded = load_subject_history([0], today=first.date(), cache=cache,
                                      only_period=(date(2026, 6, 26), date(2026, 7, 25)))
        assert bounded == history
    finally:
        database.set_db_path(original)


def test_subject_counter_reset_preserves_usage_and_requires_review(tmp_path):
    original = database.get_db_path()
    try:
        _setup_database(tmp_path)
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        for hour, total in ((8, 100), (9, 125), (10, 5)):
            stamp = datetime(2026, 7, 16, hour, tzinfo=UTC)
            state = cache.update_reading(0, _reading(total, collected_at=stamp), at=stamp)

        subject = state["subjects"]["user:u-1"]
        assert subject["delta_total"] == 25
        assert subject["reset_count"] == 1
        assert subject["resets"] == [
            {
                "before": 125.0,
                "after": 5.0,
                "at": "2026-07-16T10:00:00+00:00",
            }
        ]
        history = load_subject_history([0], today=date(2026, 7, 16), cache=cache)
        assert history[0].needs_review is True
        assert history[0].reset_count == 1
    finally:
        database.set_db_path(original)


def test_daily_subject_record_is_append_only_and_becomes_next_day_baseline(tmp_path):
    original = database.get_db_path()
    try:
        _setup_database(tmp_path)
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        for hour, total in ((8, 100), (10, 125)):
            stamp = datetime(2026, 7, 16, hour, tzinfo=UTC)
            cache.update_reading(0, _reading(total, collected_at=stamp), at=stamp)

        records = cache.finalize(0, date(2026, 7, 16))
        assert len(records) == 1
        assert records[0].delta_total == 25

        duplicate_day = datetime(2026, 7, 16, 12, tzinfo=UTC)
        cache.update_reading(0, _reading(999, collected_at=duplicate_day), at=duplicate_day)
        assert cache.finalize(0, date(2026, 7, 16)) == ()

        next_day = datetime(2026, 7, 17, 8, tzinfo=UTC)
        state = cache.update_reading(0, _reading(140, collected_at=next_day), at=next_day)
        subject = state["subjects"]["user:u-1"]
        assert subject["opening_total"] == 125
        assert subject["delta_total"] == 15
        assert subject["missing_baseline"] is False

        with database._open(commit=False) as conn:
            row = conn.execute(
                "SELECT opening_total,closing_total,delta_total FROM daily_subject_records"
            ).fetchone()
        assert row == (100.0, 125.0, 25.0)
    finally:
        database.set_db_path(original)


def test_subject_cache_rejects_late_sample_without_treating_it_as_reset(tmp_path):
    original = database.get_db_path()
    try:
        _setup_database(tmp_path)
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        first = datetime(2026, 7, 16, 8, tzinfo=UTC)
        latest = first.replace(hour=10)
        late = first.replace(hour=9)
        cache.update_reading(0, _reading(100, collected_at=first), at=first)
        cache.update_reading(0, _reading(125, collected_at=latest), at=latest)
        state = cache.update_reading(0, _reading(110, collected_at=late), at=late)

        subject = state["subjects"]["user:u-1"]
        assert subject["latest_total"] == 125
        assert subject["delta_total"] == 25
        assert subject["reset_count"] == 0
        assert subject["last_success"] == latest.isoformat(timespec="seconds")
        assert "out_of_order_sample" in subject["warnings"]
        assert state["ordering_issues"][-1]["reason"] == "late_sample"
    finally:
        database.set_db_path(original)


def test_subject_late_same_day_evidence_is_retained_after_finalization(tmp_path):
    original = database.get_db_path()
    try:
        _setup_database(tmp_path)
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        first = datetime(2026, 7, 16, 8, tzinfo=UTC)
        cache.update_reading(0, _reading(100, collected_at=first), at=first)
        cache.update_reading(0, _reading(125, collected_at=first.replace(hour=10)), at=first.replace(hour=10))
        assert len(cache.finalize(0, first.date())) == 1

        late = first.replace(hour=12)
        cache.update_reading(0, _reading(150, collected_at=late), at=late)
        assert cache.finalize(0, first.date()) == ()

        conflict = cache.load(0, first.date())
        assert conflict is not None
        assert conflict["finalization_conflict"]["reason"] == "same_day_subject_evidence_differs"
        with database._open(commit=False) as conn:
            row = conn.execute(
                "SELECT opening_total,closing_total,delta_total FROM daily_subject_records"
            ).fetchone()
        assert row == (100.0, 125.0, 25.0)
    finally:
        database.set_db_path(original)


def test_subject_next_day_baseline_is_not_carried_across_slot_reuse(tmp_path):
    original = database.get_db_path()
    try:
        repository = _setup_database(tmp_path)
        repository.replace_all([DeviceConfig(0, "Office A", "192.0.2.10", serial="SER-A")])
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        day_one = datetime(2026, 7, 16, 8, tzinfo=UTC)
        cache.update_reading(0, _reading(100, collected_at=day_one), at=day_one)
        cache.update_reading(
            0,
            _reading(125, collected_at=day_one.replace(hour=10)),
            at=day_one.replace(hour=10),
        )
        assert len(cache.finalize(0, day_one.date())) == 1

        repository.replace_all([DeviceConfig(0, "Office B", "192.0.2.11", serial="SER-B")])
        day_two = day_one.replace(day=17)
        state = cache.update_reading(0, _reading(200, collected_at=day_two), at=day_two)
        subject = state["subjects"]["user:u-1"]

        assert subject["opening_total"] == 200
        assert subject["latest_total"] == 200
        assert subject["delta_total"] == 0
        assert subject["missing_baseline"] is True
        assert "device_identity_baseline_mismatch" in subject["warnings"]
    finally:
        database.set_db_path(original)


def test_subject_history_keeps_reused_slot_identities_as_separate_rows(tmp_path):
    original = database.get_db_path()
    try:
        repository = _setup_database(tmp_path)
        database.set_cfg("billing_day", "31")
        repository.replace_all(
            [DeviceConfig(0, "Printer A", "192.0.2.10", serial="SER-A")]
        )
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        day_a = datetime(2026, 7, 15, 8, tzinfo=UTC)
        cache.update_reading(0, _reading(100, collected_at=day_a), at=day_a)
        cache.update_reading(
            0,
            _reading(125, collected_at=day_a.replace(hour=10)),
            at=day_a.replace(hour=10),
        )
        assert len(cache.finalize(0, day_a.date())) == 1

        repository.replace_all(
            [DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")]
        )
        day_b = datetime(2026, 7, 16, 8, tzinfo=UTC)
        cache.update_reading(0, _reading(200, collected_at=day_b), at=day_b)
        cache.update_reading(
            0,
            _reading(220, collected_at=day_b.replace(hour=10)),
            at=day_b.replace(hour=10),
        )
        assert len(cache.finalize(0, day_b.date())) == 1

        history = load_subject_history([0], today=date(2026, 7, 17), cache=cache)

        assert len(history) == 2
        assert {
            (
                item.device_identity,
                item.device_name_snapshot,
                item.device_serial_snapshot,
                item.period_usage,
            )
            for item in history
        } == {
            ("serial:SER-A", "Printer A", "SER-A", 25),
            ("serial:SER-B", "Printer B", "SER-B", 20),
        }

        selected_day = load_subject_history(
            [0],
            today=date(2026, 7, 17),
            cache=cache,
            period_start=date(2026, 7, 16),
            period_end=date(2026, 7, 16),
        )
        assert len(selected_day) == 1
        assert selected_day[0].period_start == date(2026, 7, 16)
        assert selected_day[0].period_end == date(2026, 7, 16)
        assert selected_day[0].device_identity == "serial:SER-B"
        assert selected_day[0].period_usage == 20
    finally:
        database.set_db_path(original)


def test_subject_cache_rejects_same_day_sample_after_device_identity_changes(tmp_path):
    original = database.get_db_path()
    try:
        repository = _setup_database(tmp_path)
        repository.replace_all(
            [DeviceConfig(0, "Printer A", "192.0.2.10", serial="SER-A")]
        )
        cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
        first = datetime(2026, 7, 16, 8, tzinfo=UTC)
        cache.update_reading(0, _reading(100, collected_at=first), at=first)
        cache.update_reading(
            0,
            _reading(125, collected_at=first.replace(hour=9)),
            at=first.replace(hour=9),
        )

        repository.replace_all(
            [DeviceConfig(0, "Printer B", "192.0.2.20", serial="SER-B")]
        )
        state = cache.update_reading(
            0,
            _reading(200, collected_at=first.replace(hour=10)),
            at=first.replace(hour=10),
        )

        subject = state["subjects"]["user:u-1"]
        assert subject["latest_total"] == 125
        assert subject["delta_total"] == 25
        assert "device_identity_changed_during_day" in subject["warnings"]
        assert state["identity_conflict"]["current"]["serial"] == "SER-B"
    finally:
        database.set_db_path(original)


def test_subject_history_remains_in_report_scope_after_slot_is_disabled(tmp_path):
    original = database.get_db_path()
    try:
        repository = _setup_database(tmp_path)
        database.set_cfg("billing_day", "31")
        repository.replace_all(
            [
                DeviceConfig(0, "Current Printer", "192.0.2.10", serial="SER-CURRENT"),
                DeviceConfig(1, "Retired Printer", "192.0.2.11", serial="SER-OLD"),
            ]
        )
        stamp = datetime(2026, 7, 16, 10, tzinfo=UTC).isoformat(timespec="seconds")
        with database._open() as conn:
            conn.execute(
                """INSERT INTO daily_subject_records(
                       device_slot,record_date,subject_type,subject_id,subject_name,
                       opening_total,closing_total,delta_total,reset_count,missing_baseline,
                       sample_count,first_success,last_success,incomplete,warnings_json,
                       source_json,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    1,
                    "2026-07-16",
                    "user",
                    "u-1",
                    "alice",
                    100,
                    125,
                    25,
                    0,
                    0,
                    2,
                    stamp,
                    stamp,
                    0,
                    "[]",
                    json.dumps(
                        {
                            "device_identity": {
                                "name": "Retired Printer",
                                "host": "192.0.2.11",
                                "serial": "SER-OLD",
                            }
                        }
                    ),
                    stamp,
                ),
            )
        repository.replace_all(
            [DeviceConfig(0, "Current Printer", "192.0.2.10", serial="SER-CURRENT")]
        )

        slots = report_slots()
        history = load_subject_history(slots, today=date(2026, 7, 17))

        assert slots == [0, 1]
        assert len(history) == 1
        assert history[0].device_slot == 1
        assert history[0].device_identity == "serial:SER-OLD"
        assert history[0].device_name_snapshot == "Retired Printer"
        assert history[0].period_usage == 25
    finally:
        database.set_db_path(original)
