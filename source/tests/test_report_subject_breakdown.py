"""Report categories from the real Auth/Track payload shape, with no network."""
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from komi_snmp_profiler.connectors import AuthenticatedWebConnectionCounterConnector
from services.report_models import build_user_rows
from services.report_operation_breakdown import breakdown_from_raw_records
from test_report_excel_export import _raw, _subject


def subject_rows(kind="user", *, zero=False):
    def counters(values):
        return {"Counter": [{"Type": key, "Count": str(0 if zero else value)}
                            for key, value in values.items()]}
    info = {"AuthNo": "7", "UserName": "Example", "TrackID": "7", "TrackName": "Example",
            "TotalCounterList": counters({"Total": 180}),
            "PrintCounterList": counters({"Total": 150, "FullColor": 100, "FullColorLarge": 20,
                                          "Bw": 50, "BwLarge": 5}),
            "CopyCounterList": counters({"Total": 30, "FullColor": 20, "FullColorLarge": 2,
                                         "Bw": 10, "BwLarge": 3}),
            "ScanFaxCounterList": counters({"DocumentReadTotal": 7, "DocumentReadLarge": 2,
                                            "PrintTotal": 900, "FaxSend": 500})}
    list_key, item_key = ("AuthCounterList", "AuthCounter") if kind == "user" else ("TrackCounterList", "TrackCounter")
    parsed = AuthenticatedWebConnectionCounterConnector._parse_attributed_payload(
        {"MFP": {list_key: {item_key: info}}}, kind)
    day = date(2026, 9, 25)
    return tuple(replace(_raw(day, slot=2, field=item.canonical_field, label=item.label,
                              delta=item.count, subject=True, serial="SYNTH-3"),
                         subject_type=kind, subject_id="7", subject_name="Example") for item in parsed)


@pytest.mark.parametrize("kind", ["user", "account", "track"])
def test_live_payload_shape_keeps_print_copy_paper_color_and_scan(kind):
    rows = subject_rows(kind)
    original = tuple(row.canonical_field for row in rows)
    result = breakdown_from_raw_records(rows)
    assert (result.print_a4_color, result.print_a3_color, result.print_a4_bw, result.print_a3_bw) == (80, 20, 45, 5)
    assert (result.copy_a4_color, result.copy_a3_color, result.copy_a4_bw, result.copy_a3_bw) == (18, 2, 7, 3)
    assert (result.print_total, result.copy_total, result.scan) == (150, 30, 7)
    assert result.print_available and result.copy_available and result.scan_available
    assert len(result.available_fields) == 11
    assert tuple(row.canonical_field for row in rows) == original


def test_verified_zero_remains_distinct_from_missing_paper_evidence():
    rows = subject_rows(zero=True)
    result = breakdown_from_raw_records(rows)
    assert result.print_available and result.copy_available and result.scan_available
    assert result.print_total == result.copy_total == result.scan == 0
    missing = tuple(row for row in rows if row.canonical_field != "counter.user.print.full_color_large")
    result = breakdown_from_raw_records(missing)
    assert "print_a4_color" not in result.available_fields
    assert "print_a3_color" not in result.available_fields
    assert "print_a4_bw" in result.available_fields
    assert "print_other" not in result.available_fields


def test_alias_totals_are_deduplicated_and_conflicting_aliases_stay_unknown():
    rows = subject_rows()
    bare = next(row for row in rows if row.canonical_field == "counter.user.print.full_color")
    duplicate = replace(bare, canonical_field=bare.canonical_field + "_total")
    assert breakdown_from_raw_records((*rows, duplicate)).print_total == 150
    result = breakdown_from_raw_records((*rows, replace(duplicate, delta_value=200)))
    assert "print_a4_color" not in result.available_fields
    assert "print_a3_color" not in result.available_fields
    assert result.print_a4_bw == 45


@pytest.mark.parametrize("change", [{"subject_type": "", "subject_id": ""}, {"subject_id": "8"}, {"device_slot": 0}])
def test_overlapping_device_or_another_subject_scope_cannot_be_added_to_user_usage(change):
    rows = subject_rows()
    result = breakdown_from_raw_records((*rows, replace(rows[0], **change)))
    assert not result.available_fields
    assert result.print_total == result.copy_total == result.scan == 0


def test_fax_prints_and_missing_scan_counter_do_not_invent_scanned_pages():
    rows = tuple(row for row in subject_rows() if row.canonical_field != "counter.user.scan_fax.document_read_total")
    result = breakdown_from_raw_records(rows)
    assert not result.scan_available and result.scan == 0
    assert result.print_total == 150


def test_user_presentation_model_uses_real_subject_mapping():
    rows = subject_rows()
    subject = replace(_subject(date(2026, 9, 25), slot=2, identity="serial:SYNTH-3", name="Printer", usage=180),
                      subject_id="7", subject_name="Example")
    model, = build_user_rows((subject,), rows)
    slot = model["by_slot"][2]
    assert model["usage"] == 180
    assert (slot["print_a4_color"], slot["print_a3_bw"], slot["copy_a4_bw"], slot["scan"]) == (80, 5, 7, 7)
    assert slot["print_available"] and slot["copy_available"]


def test_shared_subject_provenance_keeps_valid_zero_usage_and_cost():
    from services.raw_counter_history import load_raw_counter_history
    from services.shared_report_history import SHARED_REMARK
    from services.subject_history import load_subject_history
    from test_shared_report_history import event_at, receive, setup

    at = datetime(2026, 9, 25, 2, tzinfo=UTC)
    anchor, epoch = setup(at, value=0)
    receive(event_at(anchor, epoch, 0, at + timedelta(minutes=10)), epoch)
    subjects = load_subject_history([0], today=at.date(), period_start=at.date(), period_end=at.date())
    subject, = subjects
    assert subject.period_usage == 0
    assert subject.warnings == (SHARED_REMARK,)
    assert not subject.needs_review
    raw = load_raw_counter_history([0], period_start=at.date(), period_end=at.date())
    model, = build_user_rows(subjects, raw)
    assert not model["review"]
    assert model["by_slot"][0]["cost_available"]
    assert model["by_slot"][0]["cost"] == 0


@pytest.mark.parametrize("change", [
    {"reset_count": 1}, {"missing_baseline_days": 1},
    {"warnings": ("Unknown counter warning",)},
    {"warnings": ("ข้อมูลจากหลักฐาน Web ที่ใช้ร่วมกัน: unexpected issue",)},
])
def test_shared_provenance_does_not_hide_real_subject_warnings(change):
    from services.shared_report_history import SHARED_REMARK

    subject = replace(_subject(date(2026, 9, 25), slot=0, identity="serial:EXAMPLE", name="Printer", usage=0),
                      warnings=(SHARED_REMARK,))
    assert not subject.needs_review
    assert replace(subject, **change).needs_review
