from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from datetime import timedelta

from services.polling import PollingPolicy, ScheduleWindow


WEEKDAY_CODES = ("M", "T", "W", "TH", "F", "SA", "SU")
WORKDAYS = frozenset(range(5))


@dataclass(frozen=True)
class DailyTimelineEntry:
    time_range: str
    mode: str
    snmp: str
    web: str
    ram: str
    database: str
    note: str


def _clock(value: object) -> time | None:
    if not isinstance(value, str):
        return None
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour, minute)
    except (TypeError, ValueError):
        return None


def _weekdays(value: object) -> frozenset[int] | None:
    if value is None:
        return frozenset(range(7))
    if not isinstance(value, list) or not value:
        return None
    try:
        parsed = frozenset(int(item) for item in value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed and all(0 <= item <= 6 for item in parsed) else None


def default_schedule_windows() -> tuple[ScheduleWindow, ...]:
    """Weekday policy used when an administrator starts the new table."""
    return (
        ScheduleWindow(time(0, 0), time(8, 0), timedelta(minutes=240), "นอกเวลางาน", timedelta(minutes=60), WORKDAYS),
        ScheduleWindow(time(8, 0), time(8, 30), timedelta(minutes=10), "ช่วงเร่งด่วน", timedelta(minutes=5), WORKDAYS),
        ScheduleWindow(time(8, 30), time(16, 30), timedelta(minutes=60), "เวลาทำงาน", timedelta(minutes=15), WORKDAYS),
        ScheduleWindow(time(16, 30), time(17, 0), timedelta(minutes=10), "ช่วงเร่งด่วน", timedelta(minutes=5), WORKDAYS),
        ScheduleWindow(time(17, 0), time(23, 59), timedelta(minutes=240), "นอกเวลางาน", timedelta(minutes=60), WORKDAYS),
    )


def load_schedule_windows(raw: str) -> tuple[ScheduleWindow, ...] | None:
    """Read a persisted user schedule and fail closed on malformed entries."""
    if not raw or not raw.strip():
        return None
    try:
        values = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(values, list):
        return None
    windows: list[ScheduleWindow] = []
    for index, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            return None
        start = _clock(value.get("start"))
        end = _clock(value.get("end"))
        try:
            web_minutes = int(value.get("web_interval_minutes"))
        except (TypeError, ValueError):
            return None
        try:
            snmp_raw = value.get("snmp_interval_minutes")
            snmp_minutes = None if snmp_raw is None else int(snmp_raw)
        except (TypeError, ValueError):
            return None
        weekdays = _weekdays(value.get("weekdays"))
        if (
            start is None
            or end is None
            or start >= end
            or not 1 <= web_minutes <= 1_440
            or (snmp_minutes is not None and not 1 <= snmp_minutes <= 1_440)
            or weekdays is None
        ):
            return None
        label = str(value.get("label") or f"ช่วงที่ {index}").strip()
        windows.append(
            ScheduleWindow(
                start=start,
                end=end,
                web_interval=timedelta(minutes=web_minutes),
                label=label or f"ช่วงที่ {index}",
                snmp_interval=(timedelta(minutes=snmp_minutes) if snmp_minutes is not None else None),
                weekdays=weekdays,
            )
        )
    ordered = tuple(sorted(windows, key=lambda item: item.start))
    if any(
        previous.end > current.start and previous.weekdays & current.weekdays
        for previous, current in zip(ordered, ordered[1:])
    ):
        return None
    return ordered


def dump_schedule_windows(windows: tuple[ScheduleWindow, ...] | list[ScheduleWindow]) -> str:
    """Persist only the user-editable scheduling fields."""
    return json.dumps(
        [
            {
                "label": window.label,
                "start": window.start.strftime("%H:%M"),
                "end": window.end.strftime("%H:%M"),
                "web_interval_minutes": int(window.web_interval.total_seconds() // 60),
                "weekdays": sorted(window.weekdays),
                **(
                    {"snmp_interval_minutes": int(window.snmp_interval.total_seconds() // 60)}
                    if window.snmp_interval is not None
                    else {}
                ),
            }
            for window in windows
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def schedule_mode_at(clock: time, policy: PollingPolicy) -> str:
    stamp = datetime.combine(date.today(), clock).astimezone()
    window = policy.window_at(stamp)
    if window is not None:
        return window.label
    return "Peak" if policy.is_peak(stamp) else "Normal"


def _minute_of_day(value: time) -> int:
    return value.hour * 60 + value.minute


def _format_minute(value: int) -> str:
    bounded = max(0, min(1_439, value))
    return f"{bounded // 60:02d}:{bounded % 60:02d}"


def _time_range(start: int, end: int) -> str:
    return _format_minute(start) if start == end else f"{_format_minute(start)}–{_format_minute(end)}"


def _legacy_peak_windows(policy: PollingPolicy) -> tuple[ScheduleWindow, ...]:
    margin = int(policy.peak_margin.total_seconds() // 60)
    start = _minute_of_day(policy.work_start)
    end = _minute_of_day(policy.work_end)
    return (
        ScheduleWindow(
            start=time(max(0, start - margin) // 60, max(0, start - margin) % 60),
            end=time(min(1_439, start + margin) // 60, min(1_439, start + margin) % 60),
            web_interval=policy.peak_web_interval,
            label="Peak",
        ),
        ScheduleWindow(
            start=time(max(0, end - margin) // 60, max(0, end - margin) % 60),
            end=time(min(1_439, end + margin) // 60, min(1_439, end + margin) % 60),
            web_interval=policy.peak_web_interval,
            label="Peak",
        ),
    )


def build_daily_timeline(policy: PollingPolicy, *, snmp_minutes: int) -> tuple[DailyTimelineEntry, ...]:
    """Describe the scheduler's real daily phases without promising conditional Web calls."""
    snmp_text = f"ทุก {max(1, int(snmp_minutes))} นาที · Status / Total / Toner"
    windows = policy.schedule_windows if policy.schedule_windows is not None else _legacy_peak_windows(policy)
    boundaries = {0, 1_440}
    for window in windows:
        boundaries.add(_minute_of_day(window.start))
        boundaries.add(min(1_440, _minute_of_day(window.end) + 1))
    ordered_boundaries = sorted(boundaries)
    segments: list[tuple[int, int, str, timedelta, str]] = []
    for start, end in zip(ordered_boundaries, ordered_boundaries[1:]):
        midpoint = time((start + (end - start) // 2) // 60, (start + (end - start) // 2) % 60)
        matched = next((window for window in windows if window.contains(midpoint)), None)
        if matched is None:
            segments.append((start, end - 1, "Normal", policy.web_interval, "Background ทำงานต่อเมื่อยุบไว้ใน System Tray"))
        else:
            segments.append((start, end - 1, matched.label, matched.web_interval, "ช่วงที่ผู้ใช้กำหนดเอง"))
    expanded: list[tuple[int, int, str, timedelta, str]] = []
    noon = 12 * 60
    for start, end, mode, web_interval, note in segments:
        if mode == "Normal" and start < noon <= end:
            expanded.append((start, noon - 1, mode, web_interval, note))
            expanded.append((noon, end, mode, web_interval, "12:00 ทำงานตาม Normal schedule ต่อเนื่อง"))
        else:
            expanded.append((start, end, mode, web_interval, note))

    rows = [
        DailyTimelineEntry(
            time_range="00:00",
            mode="Daily rollover",
            snmp="รอบถัดไปตาม Timer",
            web="ไม่บังคับอ่านเพิ่ม",
            ram="ตรวจ Cache ของวันก่อน",
            database="แพ็ก 1 Daily Record / เครื่อง แล้วลบ Cache เมื่อ commit สำเร็จ",
            note="เกิดเมื่อโปรแกรมทำงานและตรวจพบว่าเปลี่ยนวัน",
        )
    ]
    for segment_start, segment_end, mode, web_interval, note in expanded:
        rows.append(
            DailyTimelineEntry(
                time_range=_time_range(segment_start, segment_end),
                mode=mode,
                snmp=snmp_text,
                web=f"เมื่อ Total เพิ่ม · throttle {int(web_interval.total_seconds() // 60)} นาที",
                ram="ทุก SNMP เก็บ heartbeat/toner · เมื่อ Web สำเร็จเก็บ Counter/User snapshot",
                database="พักใน Daily Cache",
                note=note,
            )
        )
    return tuple(rows)
