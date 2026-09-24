from datetime import date
from threading import Event
from types import SimpleNamespace
from concurrent.futures import CancelledError

import pytest
from ui.reports import page as report_page
from services import report_snapshot


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("selected", [("2026-09-01", "2026-09-30"), ("2026-09-05", "2026-09-10")])
def test_background_payload_matches_existing_report_semantics(monkeypatch, index, selected):
    monthly = [SimpleNamespace(period_start=date(2026,9,1),period_end=date(2026,9,30))]
    daily = [SimpleNamespace(period_start=date(2026,9,7),period_end=date(2026,9,7))]
    subjects = [SimpleNamespace(period_start=date.fromisoformat(selected[0]),period_end=date.fromisoformat(selected[1]))]
    devices = [SimpleNamespace(last_success_at="2026-09-08T12:00:00")]
    for module in (report_page, report_snapshot):
        monkeypatch.setattr(module, "report_slots", lambda: [0])
        monkeypatch.setattr(module, "load_usage_history", lambda slots,granularity,cache,**kwargs: monthly if granularity=="monthly" else daily)
        monkeypatch.setattr(module, "load_subject_history", lambda *args, **kwargs: subjects)
        monkeypatch.setattr(module, "load_raw_counter_history", lambda *args, **kwargs: ("raw",))
        monkeypatch.setattr(module, "load_imported_legacy_history", lambda: ("legacy",))
        monkeypatch.setattr(module, "load_usage_meter_baselines", lambda *args: ("baseline",))
    monkeypatch.setattr(report_snapshot, "build_user_rows", lambda *a, **kw: ("users-model",))
    monkeypatch.setattr(report_snapshot, "build_legacy_raw_tables", lambda *a, **kw: ("raw-model",))
    monkeypatch.setattr(report_snapshot, "build_printer_rows", lambda *a, **kw: ("printer-model",))
    monkeypatch.setattr(report_snapshot, "build_report_chart_models", lambda *a, **kw: ("chart-model",))
    monkeypatch.setattr(report_page, "apply_language", lambda *args: None)
    monkeypatch.setattr("services.report_excel_export.build_daily_category_costs", lambda *args: ("costs",))
    captured = {}
    center = SimpleNamespace(tabs=SimpleNamespace(currentIndex=lambda:index), current_period=lambda:selected,
                             set_periods=lambda *args:None, set_data=lambda **kwargs:captured.update(kwargs))
    original = SimpleNamespace(report_center=center,_report_records=monthly,cache=None,subject_cache=None,
                               _historical_devices=lambda:devices,_period_key=report_page.PageHistoryV5._period_key)
    report_page.PageHistoryV5._refresh_report_center(original, selected)
    result=report_snapshot.load_report_snapshot(index,selected,cache=None,subject_cache=None,
          repository=SimpleNamespace(list=lambda **kwargs:devices),cancelled=Event())
    # Original monthly list is intentionally normalized to immutable tuple by the worker.
    captured["monthly_records"]=tuple(captured["monthly_records"])
    assert {key: value for key, value in result.data.items() if key != "prepared_models"} == captured
    expected = {"users": ("users-model",)} if index in {0, 1} else {"legacy_raw": ("raw-model",)} if index == 4 else {}
    if index in {0, 2}:
        expected['printers'] = ('printer-model',)
        expected['charts'] = ('chart-model',)
    assert result.data["prepared_models"] == expected


def test_cancelled_snapshot_does_not_start_database_reads(monkeypatch):
    cancelled=Event();cancelled.set()
    monkeypatch.setattr(report_snapshot,"report_slots",lambda:pytest.fail("Cancelled load queried database"))
    with pytest.raises(CancelledError):
        report_snapshot.load_report_snapshot(0,None,cache=None,subject_cache=None,repository=None,cancelled=cancelled)
