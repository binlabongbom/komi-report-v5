"""User and account names survive later ID-only meter observations."""

from dataclasses import replace
from datetime import UTC, date, datetime
from itertools import permutations

import pytest

from services.device_config import DeviceConfig, DeviceConfigRepository
from services.subject_history import (
    SubjectDailyCacheStore,
    SubjectDailyRecord,
    aggregate_subject_days,
    subject_period_results,
)
from test_subject_history import _reading


PERIOD = (date(2026, 9, 1), date(2026, 9, 30))


def _named_reading(total, stamp, name, *, subject_id="39"):
    reading = _reading(total, collected_at=stamp, subject_id=subject_id)
    return replace(
        reading,
        counters=tuple(replace(counter, subject_name=name) for counter in reading.counters),
    )


def _day(day, name, *, subject_id="39", closing=110, delta=5):
    stamp = datetime(2026, 9, day, 10, tzinfo=UTC).isoformat()
    return SubjectDailyRecord(
        device_slot=0,
        record_date=date(2026, 9, day),
        subject_type="user",
        subject_id=subject_id,
        subject_name=name,
        opening_total=closing - delta if closing is not None else None,
        closing_total=closing,
        delta_total=delta,
        reset_count=0,
        missing_baseline=False,
        sample_count=2,
        first_success=stamp,
        last_success=stamp,
        incomplete=False,
        warnings=(),
        device_identity="serial:SER-A",
        device_name_snapshot="Office",
        device_serial_snapshot="SER-A",
    )


def _aggregate(records, *, buckets=None):
    return aggregate_subject_days(
        [(record, PERIOD) for record in records], 1, buckets=buckets
    )


@pytest.mark.parametrize(
    ("subject_id", "placeholder"),
    [("39", "39"), ("039", "39"), ("39", "00039"), ("39", ""), ("39", None), ("39", "  ")],
)
def test_daily_cache_keeps_real_name_when_later_sample_only_has_an_id(
    tmp_path, subject_id, placeholder
):
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")]
    )
    cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
    first = datetime(2026, 9, 2, 8, tzinfo=UTC)
    latest = first.replace(hour=9)
    cache.update_reading(
        0, _named_reading(100, first, "Alice Example", subject_id=subject_id), at=first
    )
    cache.update_reading(
        0, _named_reading(125, latest, placeholder, subject_id=subject_id), at=latest
    )

    state = cache.load(0, first.date())
    subject = state["subjects"][f"user:{subject_id}"]
    assert subject["subject_name"] == "Alice Example"
    assert subject["opening_total"] == 100
    assert subject["latest_total"] == 125
    assert subject["delta_total"] == 25
    assert subject["sample_count"] == state["sample_count"] == 2
    assert subject["first_success"] == first.isoformat()
    assert subject["last_success"] == state["last_success"] == latest.isoformat()


def test_daily_cache_accepts_a_real_rename_after_placeholder_samples(tmp_path):
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")]
    )
    cache = SubjectDailyCacheStore(tmp_path / "subject-cache")
    first = datetime(2026, 9, 2, 8, tzinfo=UTC)
    for offset, name in enumerate(("39", "Alice Example", "39", "Alice Renamed", "")):
        stamp = first.replace(hour=first.hour + offset)
        cache.update_reading(0, _named_reading(100 + offset * 10, stamp, name), at=stamp)

    subject = cache.load(0, first.date())["subjects"]["user:39"]
    assert subject["subject_name"] == "Alice Renamed"
    assert (subject["opening_total"], subject["latest_total"], subject["delta_total"]) == (
        100, 140, 40
    )
    assert subject["sample_count"] == 5
    assert subject["last_success"] == first.replace(hour=12).isoformat()


@pytest.mark.parametrize(
    ("subject_id", "placeholder"),
    [("39", "39"), ("039", "39"), ("39", "00039"), ("39", "")],
)
def test_period_uses_latest_real_name_regardless_of_daily_row_order(subject_id, placeholder):
    records = (
        _day(1, "Original Name", subject_id=subject_id, closing=102, delta=2),
        _day(2, "Alice Example", subject_id=subject_id, closing=105, delta=3),
        _day(4, "Alice Renamed", subject_id=subject_id, closing=110, delta=5),
        _day(5, placeholder, subject_id=subject_id, closing=117, delta=7),
    )
    for ordered in permutations(records):
        result, = subject_period_results(_aggregate(ordered))
        assert result.subject_name == "Alice Renamed", tuple(row.record_date for row in ordered)
        assert result.subject_id == subject_id
        assert result.latest_total == 117
        assert result.latest_at == records[-1].last_success
        assert result.period_usage == 17
        assert result.sample_count == 8
        assert (result.reset_count, result.missing_baseline_days, result.incomplete_days) == (0, 0, 0)
        assert result.warnings == ()


def test_period_name_does_not_cross_device_or_subject_boundaries():
    named = _day(1, "Alice Example")
    unnamed = _day(2, "39", closing=120, delta=10)
    others = (
        replace(unnamed, device_slot=1),
        replace(unnamed, device_identity="serial:SER-B", device_serial_snapshot="SER-B"),
        replace(unnamed, subject_type="account"),
        replace(unnamed, subject_type="track"),
        replace(unnamed, subject_id="039"),
    )
    results = subject_period_results(_aggregate((named, unnamed, *others)))
    by_identity = {
        (row.device_slot, row.device_identity, row.subject_type, row.subject_id): row
        for row in results
    }
    assert len(by_identity) == 6
    original = by_identity.pop((0, "serial:SER-A", "user", "39"))
    assert original.subject_name == "Alice Example"
    assert (original.latest_total, original.period_usage, original.sample_count) == (120, 15, 4)
    assert all(row.subject_name == row.subject_id for row in by_identity.values())
    assert all(row.period_usage == 10 and row.sample_count == 2 for row in by_identity.values())


def _archive_bucket(name):
    key = (*PERIOD, 0, "serial:SER-A", "user", "39")
    return {key: {
        "name": name,
        "device_name_snapshot": "Office",
        "device_serial_snapshot": "SER-A",
        "latest_total": 150.0,
        "period_usage": 50.0,
        "reset_count": 0,
        "missing_baseline_days": 0,
        "incomplete_days": 0,
        "sample_count": 10,
        "latest_at": "2026-09-05T10:00:00+00:00",
        "latest_date": date(2026, 9, 5),
        "warnings": {"archived"},
    }}


def test_seeded_archive_name_survives_placeholders_and_later_real_renames():
    buckets = _archive_bucket("Archived Alice")
    placeholder = _day(6, "39", closing=160, delta=10)
    assert _aggregate((placeholder,), buckets=buckets) is buckets
    result, = subject_period_results(buckets)
    assert result.subject_name == "Archived Alice"
    assert (result.latest_total, result.period_usage, result.latest_at) == (
        160, 60, placeholder.last_success
    )

    # A newer total with no name must not hide which real rename is newest
    # when another group of daily records is subsequently merged.
    _aggregate(
        (_day(7, "First Rename", closing=170, delta=10),
         _day(9, "39", closing=190, delta=10)),
        buckets=buckets,
    )
    _aggregate((_day(8, "Latest Rename", closing=180, delta=10),), buckets=buckets)
    result, = subject_period_results(buckets)
    assert result.subject_name == "Latest Rename"
    assert (result.latest_total, result.period_usage, result.sample_count) == (190, 90, 18)
    assert result.latest_at == "2026-09-09T10:00:00+00:00"
    assert result.warnings == ("archived",)


def test_older_real_name_enriches_numeric_archive_without_rolling_back_meter():
    buckets = _archive_bucket("39")
    _aggregate((_day(3, "Alice Example", closing=130, delta=10),), buckets=buckets)

    result, = subject_period_results(buckets)
    assert result.subject_name == "Alice Example"
    assert (result.latest_total, result.period_usage, result.sample_count) == (150, 60, 12)
    assert result.latest_at == "2026-09-05T10:00:00+00:00"


def test_record_without_closing_counter_does_not_replace_a_known_name():
    buckets = _archive_bucket("Archived Alice")
    _aggregate((_day(6, "Unconfirmed Rename", closing=None, delta=2),), buckets=buckets)

    result, = subject_period_results(buckets)
    assert result.subject_name == "Archived Alice"
    assert result.latest_total == 150
    assert result.period_usage == 52
    assert result.latest_at == "2026-09-05T10:00:00+00:00"
