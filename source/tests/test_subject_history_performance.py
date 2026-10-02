"""Semantics protected by the subject loader's metadata reuse."""
import json
from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import date

import pytest

from services import subject_history as history


def _row(*, slot=0, day="2026-09-02", name="Original", closing=105, delta=5,
         source="{}", warnings="[]"):
    return (slot, day, "user", "u-1", name, 100, closing, delta, 0, False,
            2, day + "T08:00:00", day + "T09:00:00", False, warnings, source)


@pytest.fixture
def metadata_cache():
    history._subject_source_metadata.cache_clear()
    yield
    history._subject_source_metadata.cache_clear()


@pytest.mark.parametrize("missing_meters", [False, True])
def test_public_daily_record_roundtrip_and_private_projection_keep_every_field(missing_meters, metadata_cache):
    source = json.dumps({"device_identity": {"serial": "SER-A", "name": "Office"},
                         "report_amendment": {"remarks": ["Reviewed"]}})
    row = list(_row(slot="2", source=source, warnings='["retained"]'))
    row[5:11] = [None if missing_meters else "100", None if missing_meters else "104.25",
                 "4.25", "2", 1, "3"]
    row[13] = 1
    public = history.subject_record_from_row(row)
    compact = history._SubjectDay(*history._subject_row_values(row))
    expected = history.SubjectDailyRecord(
        device_slot=2, record_date=date(2026, 9, 2), subject_type='user',
        subject_id='u-1', subject_name='Original',
        opening_total=None if missing_meters else 100.0,
        closing_total=None if missing_meters else 104.25, delta_total=4.25,
        reset_count=2, missing_baseline=True, sample_count=3,
        first_success='2026-09-02T08:00:00', last_success='2026-09-02T09:00:00',
        incomplete=True, warnings=('retained', 'ฉบับแก้ไขจากหลักฐาน Web', 'Reviewed'),
        device_identity='serial:SER-A', device_name_snapshot='Office', device_serial_snapshot='SER-A',
    )
    assert public == expected
    assert type(public) is history.SubjectDailyRecord
    assert history.SubjectDailyRecord(**asdict(public)) == public
    assert compact._fields == tuple(field.name for field in fields(history.SubjectDailyRecord))
    assert compact._asdict() == asdict(expected)
    assert not hasattr(compact, "__dict__")
    with pytest.raises(AttributeError):
        compact.delta_total = 99


def test_loader_uses_compact_days_without_changing_public_period_results(tmp_path, metadata_cache, monkeypatch):
    import database
    from services import shared_report_history
    from services.device_config import DeviceConfig, DeviceConfigRepository

    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10", serial="SER-A")])
    source = json.dumps({"device_identity": {"serial": "SER-A", "name": "Office"},
                         "report_amendment": {"remarks": ["Reviewed"]}})
    rows = (
        _row(source=source, warnings='["first"]'),
        _row(source=source, day="2026-09-03", name="Renamed", closing=112, delta=7),
        _row(source=source, day="2026-09-04", name="Current", closing=114, delta=2),
    )
    with database._open() as conn:
        conn.executemany(
            "INSERT INTO daily_subject_records (" + ",".join(history.SUBJECT_COLUMNS) +
            ",created_at) VALUES (" + ",".join("?" for _ in range(len(history.SUBJECT_COLUMNS) + 1)) + ")",
            [(*row, "2026-09-04T10:00:00") for row in rows],
        )
    existing_days = []
    original = shared_report_history.subject_records

    def inspect_existing(conn, slots, **kwargs):
        existing_days.extend(kwargs["existing"])
        return original(conn, slots, **kwargs)

    monkeypatch.setattr(shared_report_history, "subject_records", inspect_existing)
    start, end = date(2026, 9, 1), date(2026, 9, 4)
    actual = history.load_subject_history(
        [0], today=date(2026, 9, 5), cache=history.SubjectDailyCacheStore(tmp_path / "subjects"),
        period_start=start, period_end=end,
    )
    public_days = [(history.subject_record_from_row(row), None) for row in rows]
    expected = history.subject_period_results(history.aggregate_subject_days(
        public_days, 1, period_start=start, period_end=end))
    assert actual == expected
    assert all(type(record) is history.SubjectPeriodUsage for record in actual)
    assert len(existing_days) == len(rows)
    assert all(type(record) is history._SubjectDay for record in existing_days)
    assert [record._asdict() for record in existing_days] == [asdict(record) for record, _ in public_days]


def test_reused_metadata_is_immutable_and_keeps_slot_and_row_values_separate(metadata_cache, monkeypatch):
    source = json.dumps({"report_amendment": {"remarks": ["Reviewed evidence"]}})
    calls = []
    original = history._identity_snapshot

    def capture(value, slot):
        calls.append(slot)
        return original(value, slot)

    monkeypatch.setattr(history, "_identity_snapshot", capture)
    first = history.subject_record_from_row(_row(source=source, warnings='["first"]'))
    latest = history.subject_record_from_row(_row(
        source=source, day="2026-09-03", name="Renamed", closing=117, delta=12,
        warnings='["latest"]'))
    other_slot = history.subject_record_from_row(_row(slot=1, source=source))
    assert calls == [0, 1]
    assert first.device_identity == latest.device_identity == "unattributed:slot:0"
    assert other_slot.device_identity == "unattributed:slot:1"
    assert (latest.subject_name, latest.closing_total, latest.delta_total) == ("Renamed", 117, 12)
    assert first.warnings == ("first", "ฉบับแก้ไขจากหลักฐาน Web", "Reviewed evidence")
    assert latest.warnings == ("latest", "ฉบับแก้ไขจากหลักฐาน Web", "Reviewed evidence")
    metadata = history._subject_source_metadata(source, 0)
    with pytest.raises(TypeError):
        metadata[0] = "changed"
    with pytest.raises(TypeError):
        metadata[3][0] = "changed"
    with pytest.raises(FrozenInstanceError):
        first.subject_name = "changed"
    assert history._subject_source_metadata.cache_info().maxsize == 4096


@pytest.mark.parametrize("source", [
    None, "not-json", "[]", "null", '{"device_identity": []}',
    '{"report_amendment": null}', {"device_identity": {"serial": "ignored"}},
])
def test_malformed_or_missing_source_keeps_existing_fallback(source, metadata_cache):
    row = history.subject_record_from_row(_row(slot=3, source=source, warnings='["retained"]'))
    assert (row.device_identity, row.device_name_snapshot, row.device_serial_snapshot) == (
        "unattributed:slot:3", "", "")
    assert row.warnings == ("retained",)


@pytest.mark.parametrize(("source", "error"), [
    ('{"report_amendment": {"remarks": null}}', TypeError),
    ('{"report_amendment": ["invalid"]}', AttributeError),
])
def test_malformed_amendment_still_raises(source, error, metadata_cache):
    with pytest.raises(error):
        history.subject_record_from_row(_row(source=source))


def test_amendment_metadata_does_not_hide_malformed_row_warnings(metadata_cache):
    source = '{"device_identity": {"serial": "SER-A"}}'
    history.subject_record_from_row(_row(source=source))
    with pytest.raises(json.JSONDecodeError):
        history.subject_record_from_row(_row(source=source, warnings="not-json"))


def test_aggregation_preserves_seed_latest_amended_names_warnings_and_totals(metadata_cache):
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    key = (start, end, 0, "serial:SER-A", "user", "u-1")
    seeded = {key: {
        "name": "Archived", "device_name_snapshot": "Previous printer name",
        "device_serial_snapshot": "SER-A", "latest_total": 100.0,
        "period_usage": 20.0, "reset_count": 0, "missing_baseline_days": 0,
        "incomplete_days": 0, "sample_count": 1, "latest_at": "2026-09-01T09:00:00",
        "warnings": {"archived"}, "latest_date": start,
    }}
    source = json.dumps({"device_identity": {"name": "Office", "serial": " SER-A "},
                         "report_amendment": {"remarks": ["Reviewed"]}})
    first = history.subject_record_from_row(_row(source=source, warnings='["first"]'))
    latest = replace(history.subject_record_from_row(_row(
        source=source, day="2026-09-03", name="Renamed", closing=112, delta=7)),
        reset_count=1, missing_baseline=True, incomplete=True, sample_count=3)
    older = replace(first, record_date=start, subject_name="Older", closing_total=101,
                    delta_total=1, sample_count=1)
    without_closing = replace(latest, record_date=date(2026, 9, 4), subject_name="Missing",
                              closing_total=None, delta_total=2, reset_count=0,
                              missing_baseline=False, incomplete=False, sample_count=0)
    replacement = replace(first, device_identity="serial:SER-B", device_serial_snapshot="SER-B",
                          subject_name="Replacement", closing_total=2005, delta_total=5)
    daily = [(record, (start, end)) for record in (first, latest, older, without_closing, replacement)]
    buckets = history.aggregate_subject_days(daily, 1, only_period=(start, end), buckets=seeded)
    assert buckets is seeded and len(buckets) == 2
    assert buckets[key] == {
        "name": "Renamed", "device_name_snapshot": "Office", "device_serial_snapshot": "SER-A",
        "latest_total": 112.0, "period_usage": 35.0, "reset_count": 1,
        "missing_baseline_days": 1, "incomplete_days": 1, "sample_count": 7,
        "latest_at": "2026-09-03T09:00:00", "latest_date": date(2026, 9, 3),
        "_name_date": "2026-09-03",
        "warnings": {"archived", "first", "ฉบับแก้ไขจากหลักฐาน Web", "Reviewed"},
    }
    period = next(item for item in history.subject_period_results(buckets)
                  if item.device_identity == "serial:SER-A")
    assert (period.subject_name, period.latest_total, period.period_usage) == ("Renamed", 112, 35)
    assert period.warnings == tuple(sorted(buckets[key]["warnings"]))
    assert period.needs_review
