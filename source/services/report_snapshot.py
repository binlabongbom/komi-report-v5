"""Read report data without touching Qt widgets; safe for background preparation."""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from datetime import date
from threading import Event
from typing import Any

from database import get_billing_day
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfigRepository
from services.legacy_history_import import load_imported_legacy_history
from services.monthly_history import history_period_range, load_usage_history
from services.raw_counter_history import load_raw_counter_history, load_usage_meter_baselines
from services.report_scope import report_slots
from services.subject_history import SubjectDailyCacheStore, load_subject_history


@dataclass(frozen=True)
class ReportSnapshot:
    periods: tuple[tuple[str, str], ...]
    data: dict[str, Any]


def load_report_snapshot(
    index: int,
    selected: tuple[str, str] | None,
    *,
    cache: DailyCacheStore,
    subject_cache: SubjectDailyCacheStore,
    repository: DeviceConfigRepository,
    cancelled: Event,
) -> ReportSnapshot:
    def checkpoint() -> None:
        if cancelled.is_set():
            raise CancelledError()

    def key(record) -> tuple[str, str]:
        return record.period_start.isoformat(), record.period_end.isoformat()

    checkpoint()
    slots = report_slots()
    monthly = tuple(load_usage_history(slots, granularity="monthly", cache=cache))
    checkpoint()
    periods = sorted({key(record) for record in monthly}, reverse=True)
    current = history_period_range(date.today(), get_billing_day(), "monthly")
    current_period = (current[0].isoformat(), current[1].isoformat())
    if selected is None:
        active = [period for period in periods if period[0] <= date.today().isoformat() <= period[1]]
        selected = current_period if current_period in periods else (active[0] if active else periods[0] if periods else current_period)
    canonical = selected in periods
    if not periods:
        periods = [current_period]
    needs_daily = index in {0, 3} or (index == 2 and not canonical)
    usage_daily = tuple(load_usage_history(slots, granularity="daily", cache=cache)) if needs_daily else ()
    checkpoint()
    start, end = map(date.fromisoformat, selected)
    daily = tuple(record for record in usage_daily if record.period_start <= end and record.period_end >= start)
    selected_monthly = tuple(record for record in monthly if key(record) == selected)
    subject_range = {"period_start": start, "period_end": end} if not canonical else {"only_period": (start, end)}
    subjects = tuple(
        record for record in load_subject_history(slots, cache=subject_cache, **subject_range)
        if record.period_start == start and record.period_end == end
    ) if index in {0, 1} else ()
    checkpoint()
    raw = load_raw_counter_history(slots, period_start=start, period_end=end) if index in {1, 4} else ()
    checkpoint()
    legacy = load_imported_legacy_history() if index in {3, 4} else ()
    baselines = load_usage_meter_baselines(slots) if index == 3 else ()
    devices = tuple(repository.list(enabled_only=False))
    checkpoint()
    last_sync = max((str(device.last_success_at) for device in devices if getattr(device, "last_success_at", None)), default=None)
    return ReportSnapshot(tuple(periods), dict(
        records=selected_monthly or daily, daily_records=daily, usage_daily_records=usage_daily,
        monthly_records=monthly, subjects=subjects, devices=devices, legacy_history=legacy,
        raw_counter_records=raw, usage_meter_baselines=baselines, period=selected, last_sync_at=last_sync,
    ))
