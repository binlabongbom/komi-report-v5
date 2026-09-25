"""Overview filters must plot their actual time scale without inventing readings."""

import json
from datetime import date, datetime
from unittest.mock import patch

import pytest

import database
from services import summary_service
from services.billing_ledger import post_daily_record
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository


@pytest.fixture
def overview_db(tmp_path):
    original = database.get_db_path()
    database.set_db_path(tmp_path / "overview-trend.sqlite3")
    database.init_db()
    database.set_cfg("billing_day", "31")
    yield tmp_path
    database.set_db_path(original)


def configure(*slots):
    DeviceConfigRepository().replace_all([
        DeviceConfig(slot, f"Printer {slot + 1}", f"192.0.2.{slot + 1}",
                     serial=f"SER-{slot + 1}")
        for slot in slots
    ])
    for slot in slots:
        PricingRepository().set_prices(slot, date(2020, 1, 1), PriceList())


def post(day, slot, total, *, safe=True, name=None, serial=None):
    stamp = f"{day}T12:00:00+07:00"
    source = {
        "reconciliation": {"billing_safe": safe},
        "device_identity": {"name": name or f"Printer {slot + 1}",
                            "serial": serial or f"SER-{slot + 1}"},
    }
    with database._open() as conn:
        record_id = conn.execute(
            """INSERT INTO daily_meter_records(
                device_slot,record_date,opening_json,closing_json,delta_json,category_json,
                source_json,first_success,last_success,sample_count,error_count,incomplete,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (slot, day, "{}", "{}", json.dumps({"counter.total.total": total}),
             json.dumps({"counter.total.total": "no_charge"}), json.dumps(source),
             stamp, stamp, 1, 0, 0, stamp),
        ).fetchone()[0]
    post_daily_record(record_id)


def cache_today(root, slot, total):
    target = root / "runtime-cache" / f"device-{slot + 1}" / "2026-09-25.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "device_slot": slot, "record_date": "2026-09-25",
        "opening": {}, "latest": {}, "delta": {"counter.total.total": total},
        "source": {"reconciliation": {"billing_safe": True}},
        "first_success": "2026-09-25T08:00:00+07:00",
        "last_success": "2026-09-25T11:00:00+07:00",
        "sample_count": 2, "error_count": 0,
        "device_identity": {"name": f"Printer {slot + 1}", "serial": f"SER-{slot + 1}"},
    }), encoding="utf-8")


def test_today_trend_uses_14_days_but_cards_only_today_and_keeps_gaps(overview_db):
    configure(0, 1, 2)
    post("2026-09-11", 0, 900)  # Outside the inclusive 14-day chart.
    post("2026-09-12", 0, 5)
    post("2026-09-14", 0, 0)  # A measured zero is not a missing observation.
    post("2026-09-22", 0, 10)
    post("2026-09-23", 1, 99, safe=False)
    post("2026-09-24", 2, 20)
    cache_today(overview_db, 2, 7)
    with patch.object(summary_service, "load_usage_history",
                      wraps=summary_service.load_usage_history) as load:
        result = summary_service.build_overview_summary("day", now=datetime(2026, 9, 25, 12))

    trend = result["trend"]
    assert trend["granularity"] == "day"
    assert trend["available"] is True
    assert trend["slots"] == [0, 1, 2]
    assert list(trend["buckets"])[0] == "2026-09-12"
    assert list(trend["buckets"])[-1] == "2026-09-25"
    assert len(trend["buckets"]) == 14
    assert trend["buckets"]["2026-09-12"]["machines"] == [5, None, None]
    assert trend["buckets"]["2026-09-14"]["machines"] == [0, None, None]
    assert trend["buckets"]["2026-09-13"]["machines"] == [None, None, None]
    assert trend["buckets"]["2026-09-23"]["machines"] == [None, None, None]
    assert trend["buckets"]["2026-09-25"]["provisional_machines"] == [None, None, 7]
    assert sum(value or 0 for bucket in trend["buckets"].values()
               for value in bucket["machines"]) == 35
    assert result["metrics"]["display_total"] == 7
    assert result["metrics"]["total"] == 0
    daily_calls = [call for call in load.call_args_list if call.kwargs["granularity"] == "daily"]
    assert len(daily_calls) == 1
    assert daily_calls[0].kwargs["period_start"] == date(2026, 9, 12)
    assert daily_calls[0].kwargs["period_end"] == date(2026, 9, 25)


def test_trend_labels_follow_frozen_history_and_explicit_noncontiguous_slots(overview_db):
    configure(1, 2)
    post("2026-09-22", 1, 10, name="Old printer", serial="OLD")
    post("2026-09-23", 1, 20, name="Replacement", serial="NEW")
    post("2026-09-24", 2, 30, name="Retired printer", serial="RETIRED")
    DeviceConfigRepository().replace_all([
        DeviceConfig(1, "Current name", "192.0.2.2", serial="NEW"),
        DeviceConfig(2, "Disabled current name", "192.0.2.3", serial="RETIRED", enabled=False),
    ])
    trend = summary_service.build_overview_summary("day", now=datetime(2026, 9, 25))["trend"]

    assert trend["slots"] == [1, 2]
    assert "Old printer (OLD)" in trend["machine_names"][0]
    assert "Replacement (NEW)" in trend["machine_names"][0]
    assert trend["machine_names"][1] == "Retired printer (RETIRED)"
    assert trend["buckets"]["2026-09-22"]["machines"] == [10, None]
    assert trend["buckets"]["2026-09-24"]["machines"] == [None, 30]


def test_month_year_and_all_trends_keep_distinct_monthly_windows(overview_db):
    configure(0)
    periods = [f"2025-{month:02}" for month in range(7, 13)]
    periods += [f"2026-{month:02}" for month in range(1, 10)]
    for amount, period in enumerate(periods, start=1):
        post(f"{period}-10", 0, amount)

    for mode, count in (("month", 6), ("year", 12), ("all", 15)):
        trend = summary_service.build_overview_summary(mode, now=datetime(2026, 9, 25))["trend"]
        assert trend["granularity"] == "month"
        assert list(trend["buckets"]) == periods[-count:]
        assert [bucket["machines"][0] for bucket in trend["buckets"].values()] == list(range(16 - count, 16))


def test_legacy_monthly_import_is_not_presented_as_today(overview_db):
    database.save_reading(0, {
        "machine_name": "Legacy", "serial": "OLD", "date": "2026/09/20",
        "mode": "summary", "total_counter": 100,
        "summary": {"total_color": 40, "total_bw": 60, "total": 100},
        "paper_color": {"a4_color": 40, "a4_bw": 60, "a3_color": 0, "a3_bw": 0},
        "detail": {}, "warnings": [],
    }, "legacy.txt")

    daily = summary_service.build_overview_summary("day", now=datetime(2026, 9, 25))
    assert daily["metrics_available"] is False
    assert daily["metrics"] == {}
    assert daily["trend"]["available"] is False
    assert daily["trend"]["buckets"] == {}
    monthly = summary_service.build_overview_summary("month", now=datetime(2026, 9, 25))
    assert monthly["metrics"]["total"] == 100
    assert monthly["trend"]["buckets"]["2026-09"]["machines"] == [100, 0, 0]
