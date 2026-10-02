from concurrent.futures import CancelledError
from dataclasses import replace
from datetime import date, timedelta
from threading import Event
from types import SimpleNamespace

import pytest

from services.monthly_history import MonthlyUsage
from services.report_public_users import build_public_user_rows

DAY = date(2026, 9, 25)


def daily(**changes):
    record = MonthlyUsage(
        device_slot=0, period_start=DAY, period_end=DAY,
        total=12, a3_color=2, a3_bw=1, a4_color=3, a4_bw=6,
        scan=7, gross_cost=30, net_cost=29.4, day_count=1, incomplete_days=0,
        device_identity="serial:PRINTER-A", device_name_snapshot="Frozen printer name",
        print_a3_color=2, print_a3_bw=1, print_a4_color=3, print_a4_bw=4,
        copy_a4_bw=2, print_available=True, copy_available=True,
    )
    return replace(record, **changes)


def subject(record, **changes):
    return SimpleNamespace(**{
        "device_slot": record.device_slot, "device_identity": record.device_identity,
        "period_start": record.period_start, "period_end": record.period_end,
        "subject_type": "user", "period_usage": 0, **changes,
    })


def test_public_user_uses_daily_operation_breakdown_provisional_values_and_fixed_name():
    first = daily()
    second = daily(period_start=DAY + timedelta(days=1), period_end=DAY + timedelta(days=1),
                   provisional_total=4, provisional_print_a4_color=4,
                   provisional_gross_cost=10, provisional_net_cost=8, provisional_scan=2, provisional_days=1)
    rows = build_public_user_rows((first, second), (SimpleNamespace(slot=0, name="Renamed"),))
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Public User"
    assert row["key"] == "public:all"
    assert row["type"] == "public"
    assert row["virtual"] and row["usage_source"] == "printer_daily_usage"
    assert row["usage"] == 28  # Scan is separate, not added to printed pages.
    assert row["print"] == 24 and row["copy"] == 4
    slot = row["by_slot"][0]
    assert {field: slot[field] for field in ("print_a3_color", "print_a3_bw", "print_a4_color",
            "print_a4_bw", "copy_a4_bw", "scan", "total", "cost")} == {
        "print_a3_color": 4, "print_a3_bw": 2, "print_a4_color": 10,
        "print_a4_bw": 8, "copy_a4_bw": 4, "scan": 16, "total": 28, "cost": 66.8,
    }
    assert slot["cost_available"] and slot["scan_available"]
    assert slot["gross_cost"] == 70
    assert slot["net_cost"] == slot["cost"] == 66.8
    assert len(slot["available_fields"]) == 10
    with pytest.raises(TypeError):
        slot["cost"] = 0


def test_existing_daily_history_is_available_without_auth_history_and_months_are_not_split():
    first = daily()
    month = daily(period_start=DAY.replace(day=1), period_end=DAY)
    rows = build_public_user_rows((month, first), ())
    assert len(rows) == 1 and rows[0]["usage"] == 12


def test_real_users_block_overlapping_days_including_zero_usage_but_not_public_days():
    first = daily()
    next_day = DAY + timedelta(days=1)
    second = daily(period_start=next_day, period_end=next_day)
    rows = build_public_user_rows((first, second), (), subjects=(subject(second),))
    assert len(rows) == 1 and rows[0]["usage"] == 12
    assert build_public_user_rows((first, second), (), subjects=(subject(first, period_end=next_day),)) == ()


def test_subject_identity_does_not_block_other_device_but_unknown_identity_is_conservative():
    record = daily()
    assert len(build_public_user_rows((record,), (), subjects=(subject(record, device_identity="serial:OTHER"),))) == 1
    assert build_public_user_rows((record,), (), subjects=(subject(record, device_identity=""),)) == ()


def test_replacements_accumulate_in_same_slot_and_all_printers_form_one_public_user():
    first = daily()
    replacement = daily(device_identity="serial:NEW")
    second_slot = daily(device_slot=1, device_identity="serial:SECOND")
    rows = build_public_user_rows((first, replacement, second_slot), ())
    row, = rows
    assert row["key"] == "public:all" and row["name"] == "Public User"
    assert row["usage"] == 36
    assert row["printers"] == {"serial:printer-a": 12, "serial:new": 12, "serial:second": 12}
    assert row["by_slot"][0]["total"] == 24
    assert row["by_slot"][1]["total"] == 12
    assert row["by_slot"][0]["gross_cost"] == 60
    assert row["by_slot"][0]["net_cost"] == 58.8
    assert row["by_slot"][1]["gross_cost"] == 30
    assert row["by_slot"][1]["net_cost"] == 29.4


def test_measured_zero_is_preserved_and_held_only_day_is_not_fabricated_as_zero():
    zero = daily(total=0, a3_color=0, a3_bw=0, a4_color=0, a4_bw=0, scan=0,
                 gross_cost=0, net_cost=0, print_a3_color=0, print_a3_bw=0,
                 print_a4_color=0, print_a4_bw=0, copy_a4_bw=0)
    rows = build_public_user_rows((zero,), ())
    assert len(rows) == 1 and rows[0]["usage"] == 0
    slot = rows[0]["by_slot"][0]
    assert slot["print_available"] and slot["cost_available"] and slot["cost"] == 0
    held = replace(zero, day_count=0, held_days=1)
    assert build_public_user_rows((held,), ()) == ()


def test_unknown_provisional_cost_remains_unavailable_and_marks_review():
    record = daily(provisional_days=1, provisional_cost_available=False, provisional_total=5)
    row, = build_public_user_rows((record,), ())
    assert row["usage"] == 17 and row["review"]
    assert not row["by_slot"][0]["cost_available"]


def test_missing_operation_is_unavailable_instead_of_zero_and_partial_days_stay_partial():
    known = daily()
    next_day = DAY + timedelta(days=1)
    missing = daily(period_start=next_day, period_end=next_day, copy_available=False, copy_a4_bw=0)
    row, = build_public_user_rows((known, missing), ())
    slot = row["by_slot"][0]
    assert slot["print_available"] and not slot["copy_available"]
    assert "copy_a4_bw" not in slot["available_fields"]
    assert slot["copy_a4_bw"] == 2  # Partial evidence is retained but not shown as a complete total.


def test_public_rows_support_cancellation():
    cancelled = Event()
    cancelled.set()
    with pytest.raises(CancelledError):
        build_public_user_rows((daily(),), (), cancelled=cancelled)


def test_three_printers_show_public_slots_one_and_two_with_named_users_only_on_slot_three():
    first = daily(device_name_snapshot="KM bizhub C450i Test")
    second = daily(device_slot=1, device_identity="serial:PRINTER-B",
                   device_name_snapshot="KM bizhub C750i 2222")
    third = daily(device_slot=2, device_identity="serial:PRINTER-C", device_name_snapshot="KM bizhub C450i DMS")
    rows = build_public_user_rows((first, second, third), (), subjects=(subject(third),))
    row, = rows
    assert row["name"] == "Public User"
    assert tuple(row["by_slot"]) == (0, 1)
    assert row["by_slot"][0]["total"] == row["by_slot"][1]["total"] == 12
    assert row["usage"] == 24
    assert "serial:printer-c" not in row["printers"]


def test_serial_case_changes_do_not_split_public_rows_or_double_count_named_users():
    first = daily()
    next_day = DAY + timedelta(days=1)
    lower = daily(device_identity="serial:printer-a", period_start=next_day, period_end=next_day)
    row, = build_public_user_rows((first, lower), ())
    assert row["usage"] == 24
    assert build_public_user_rows((first,), (), subjects=(subject(first, device_identity="serial:printer-a"),)) == ()
    assert build_public_user_rows((lower,), (), subjects=(subject(lower, device_identity="SERIAL:PRINTER-A"),)) == ()


@pytest.mark.parametrize("identity", ("", "slot:0", "unattributed:slot:0"))
def test_legacy_identity_uses_serial_or_suppresses_overlapping_same_slot_users(identity):
    record = daily(device_identity=identity, device_serial_snapshot="PRINTER-A")
    assert build_public_user_rows((record,), (), subjects=(subject(record, device_identity="serial:printer-a"),)) == ()
    unknown = replace(record, device_serial_snapshot="")
    assert build_public_user_rows((unknown,), (), subjects=(subject(record, device_identity="serial:printer-a"),)) == ()
    row, = build_public_user_rows((unknown,), ())
    assert row["usage"] == 12


def test_public_availability_and_cost_flags_remain_independent_for_each_slot():
    known = daily()
    partial = daily(device_slot=1, device_identity="serial:PARTIAL", copy_available=False,
                    copy_a4_bw=0, provisional_days=1, provisional_cost_available=False)
    row, = build_public_user_rows((known, partial), ())
    assert row["review"]
    complete_slot, partial_slot = row["by_slot"][0], row["by_slot"][1]
    assert complete_slot["copy_available"] and complete_slot["cost_available"]
    assert "copy_a4_bw" in complete_slot["available_fields"]
    assert not partial_slot["copy_available"] and not partial_slot["cost_available"]
    assert "copy_a4_bw" not in partial_slot["available_fields"]
    assert complete_slot["print_available"] and partial_slot["print_available"]


def test_unidentified_printers_keep_slot_contributions_within_single_public_user():
    first = daily(device_identity="")
    second = daily(device_slot=1, device_identity="")
    row, = build_public_user_rows((first, second), ())
    assert row["name"] == "Public User" and row["usage"] == 24
    assert row["printers"] == {"slot:0": 12, "slot:1": 12}
