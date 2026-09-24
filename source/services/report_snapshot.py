"""Read report data without touching Qt widgets; safe for background preparation."""
from __future__ import annotations

from concurrent.futures import CancelledError
from dataclasses import dataclass
from datetime import date
from threading import Event, Lock
from collections import OrderedDict
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from database import get_db_path, report_read_database
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfigRepository
from services.legacy_history_import import load_imported_legacy_history
from services.monthly_history import load_usage_history
from services.raw_counter_history import load_raw_counter_history, load_usage_meter_baselines
from services.report_scope import report_slots
from services.subject_history import SubjectDailyCacheStore, load_subject_history
from services.report_models import build_legacy_raw_tables, build_user_rows, build_printer_rows
from services.report_period_policy import current_preview_period, validate_preview_period


@dataclass(frozen=True)
class ReportSnapshot:
    periods: tuple[tuple[str, str], ...]
    data: Mapping[str, Any]


class SnapshotDataCache:
    """One bounded component cache per UI data revision, shared across tabs."""
    def __init__(self, max_entries=16):
        self.entries = OrderedDict()
        self.lock = Lock()
        self.max_entries = max_entries

    def read(self, key, loader, cancelled):
        # Only workers wait on the lock. A cancelled speculative read must not
        # delay the user's next selection behind another large database read.
        while not self.lock.acquire(timeout=.025):
            if cancelled.is_set():
                raise CancelledError()
        try:
            if cancelled.is_set():
                raise CancelledError()
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key]
            result = loader()
            if cancelled.is_set():
                raise CancelledError()
            self.entries[key] = result
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)
            return result
        finally:
            self.lock.release()


def load_report_snapshot(
    index: int,
    selected: tuple[str, str] | None,
    *,
    cache: DailyCacheStore,
    subject_cache: SubjectDailyCacheStore,
    repository: DeviceConfigRepository,
    cancelled: Event,
    shared: SnapshotDataCache | None = None,
    database_path=None,
) -> ReportSnapshot:
    if cancelled.is_set():
        raise CancelledError()
    # Reject oversized requests before opening the DB or populating caches.
    selected = selected or current_preview_period()
    validate_preview_period(selected)
    path = database_path or get_db_path()
    with report_read_database(path, cancelled=cancelled):
        return _load_report_snapshot(index, selected, cache=cache, subject_cache=subject_cache,
                                     repository=repository, cancelled=cancelled, shared=shared)


def _load_report_snapshot(index, selected, *, cache, subject_cache, repository, cancelled, shared):
    def checkpoint() -> None:
        if cancelled.is_set():
            raise CancelledError()

    def key(record) -> tuple[str, str]:
        return record.period_start.isoformat(), record.period_end.isoformat()

    def read(name, loader, period=None):
        checkpoint()
        if shared is None:
            return loader()
        return shared.read((str(get_db_path()), name, period), loader, cancelled)

    checkpoint()
    slots = read("slots", lambda: tuple(report_slots()))
    monthly = read("monthly", lambda: tuple(load_usage_history(slots, granularity="monthly", cache=cache)))
    checkpoint()
    periods = sorted({key(record) for record in monthly}, reverse=True)
    current_period = current_preview_period()
    canonical = selected in periods
    if not periods:
        periods = [current_period]
    # Printers uses posted monthly totals for its table, but its timeline
    # always needs daily points even when the billing period is canonical.
    needs_daily = index in {0, 1, 2, 3}
    usage_daily = read("daily", lambda: tuple(load_usage_history(slots, granularity="daily", cache=cache))) if needs_daily else ()
    checkpoint()
    start, end = map(date.fromisoformat, selected)
    daily = tuple(record for record in usage_daily if record.period_start <= end and record.period_end >= start)
    chart_daily = read('daily_graph', lambda: tuple(load_usage_history(
        slots, granularity='daily', cache=cache, graph=True))) if index in {0, 2, 3} else usage_daily
    selected_monthly = tuple(record for record in monthly if key(record) == selected)
    subject_range = {"period_start": start, "period_end": end} if not canonical else {"only_period": (start, end)}
    subjects = read("subjects", lambda: tuple(
        record for record in load_subject_history(slots, cache=subject_cache, **subject_range)
        if record.period_start == start and record.period_end == end
    ), selected) if index in {0, 1} else ()
    checkpoint()
    raw = read("raw", lambda: load_raw_counter_history(slots, period_start=start, period_end=end), selected) if index in {1, 4} else ()
    checkpoint()
    legacy = read("legacy", lambda: tuple(load_imported_legacy_history())) if index in {3, 4} else ()
    baselines = read("baselines", lambda: tuple(load_usage_meter_baselines(slots))) if index == 3 else ()
    devices = read("devices", lambda: tuple(repository.list(enabled_only=False)))
    category_costs = ()
    if index == 1 and subjects:
        from services.report_excel_export import build_daily_category_costs
        category_costs = read("user_costs", lambda: build_daily_category_costs(daily), selected)
    models = {}
    if index in {0, 2}:
        models["printers"] = read("printer_model", lambda: build_printer_rows(selected_monthly or daily, devices), selected)
    if index in {0, 1}:
        models["users"] = read(("user_model", index), lambda: build_user_rows(subjects, raw, category_costs=category_costs, cancelled=cancelled), selected)
    if index == 4:
        models["legacy_raw"] = read("raw_model", lambda: build_legacy_raw_tables(raw, devices, cancelled=cancelled), selected)
    checkpoint()
    last_sync = max((str(device.last_success_at) for device in devices if getattr(device, "last_success_at", None)), default=None)
    return ReportSnapshot(tuple(periods), MappingProxyType(dict(
        records=selected_monthly or daily, daily_records=daily, usage_daily_records=usage_daily,
        chart_daily_records=chart_daily,
        monthly_records=monthly, subjects=subjects, devices=devices, legacy_history=legacy,
        category_costs=category_costs, raw_counter_records=raw, usage_meter_baselines=baselines, period=selected, last_sync_at=last_sync,
        prepared_models=MappingProxyType(models),
    )))
