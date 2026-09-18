from datetime import time, timedelta

from services.polling import PollingPolicy, ScheduleWindow
from services.sync_schedule import (
    build_daily_timeline,
    default_schedule_windows,
    dump_schedule_windows,
    load_schedule_windows,
    schedule_mode_at,
)


def test_default_schedule_has_five_weekday_collection_policies():
    windows = default_schedule_windows()

    assert [(item.label, item.start, item.end) for item in windows] == [
        ("นอกเวลางาน", time(0, 0), time(8, 0)),
        ("ช่วงเร่งด่วน", time(8, 0), time(8, 30)),
        ("เวลาทำงาน", time(8, 30), time(16, 30)),
        ("ช่วงเร่งด่วน", time(16, 30), time(17, 0)),
        ("นอกเวลางาน", time(17, 0), time(23, 59)),
    ]
    assert [int(item.snmp_interval.total_seconds() // 60) for item in windows] == [60, 5, 15, 5, 60]
    assert [int(item.web_interval.total_seconds() // 60) for item in windows] == [240, 10, 60, 10, 240]
    assert all(item.weekdays == frozenset(range(5)) for item in windows)


def test_daily_timeline_explains_midnight_work_start_noon_and_work_end():
    policy = PollingPolicy(work_start=time(8, 0), work_end=time(17, 0))

    rows = build_daily_timeline(policy, snmp_minutes=5)

    assert rows[0].time_range == "00:00"
    assert "Daily Record" in rows[0].database
    assert any(row.time_range == "07:30–08:30" and row.mode == "Peak" for row in rows)
    assert any("12:00" in row.time_range and row.mode == "Normal" for row in rows)
    assert any(row.time_range == "16:30–17:30" and row.mode == "Peak" for row in rows)
    assert all("ทุก 5 นาที" in row.snmp for row in rows[1:])


def test_schedule_mode_matches_peak_windows():
    policy = PollingPolicy(work_start=time(8, 0), work_end=time(17, 0))

    assert schedule_mode_at(time(8, 0), policy) == "Peak"
    assert schedule_mode_at(time(12, 0), policy) == "Normal"
    assert schedule_mode_at(time(17, 0), policy) == "Peak"


def test_custom_schedule_builds_only_user_added_windows_and_round_trips():
    windows = (
        ScheduleWindow(time(9, 0), time(10, 0), timedelta(minutes=3), "ช่วงเปิดงาน"),
        ScheduleWindow(time(16, 0), time(16, 30), timedelta(minutes=4), "ช่วงปิดงาน"),
    )
    policy = PollingPolicy(schedule_windows=windows)

    rows = build_daily_timeline(policy, snmp_minutes=5)
    stored = load_schedule_windows(dump_schedule_windows(windows))

    assert schedule_mode_at(time(9, 30), policy) == "ช่วงเปิดงาน"
    assert schedule_mode_at(time(12, 0), policy) == "Normal"
    assert any(row.time_range == "09:00–10:00" and row.mode == "ช่วงเปิดงาน" for row in rows)
    assert any(row.time_range == "16:00–16:30" and row.mode == "ช่วงปิดงาน" for row in rows)
    assert stored == windows


def test_overlapping_or_invalid_persisted_schedule_falls_back_to_legacy_policy():
    assert load_schedule_windows(
        '[{"label":"A","start":"09:00","end":"10:30","web_interval_minutes":5},'
        '{"label":"B","start":"10:00","end":"11:00","web_interval_minutes":5}]'
    ) is None


def test_overlapping_times_are_valid_when_their_weekdays_do_not_intersect():
    stored = load_schedule_windows(
        '[{"label":"Weekday","start":"09:00","end":"10:30","web_interval_minutes":5,"snmp_interval_minutes":5,"weekdays":[0]},'
        '{"label":"Weekend","start":"10:00","end":"11:00","web_interval_minutes":5,"snmp_interval_minutes":5,"weekdays":[5]}]'
    )

    assert stored is not None
