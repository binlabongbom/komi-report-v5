"""Selected daily history must equal filtering the complete reporting view."""
import json
from datetime import UTC, date, datetime

import pytest

import database
from services import monthly_history as history
from services.billing_ledger import approve_held_entry, post_daily_record, replace_entry
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import PriceList, PricingRepository


class EmptyCache:
    def load(self, _slot, _day):
        return None


def setup_devices():
    DeviceConfigRepository().replace_all([
        DeviceConfig(slot, f"Printer {slot}", f"192.0.2.{10 + slot}", serial=f"SER-{slot}")
        for slot in (0, 1)
    ])
    database.set_cfg("billing_day", "25")
    for slot in (0, 1):
        PricingRepository().set_prices(slot, date(2026, 1, 1), PriceList(a4_color=2))


def daily(day, *, slot=0, pages=10, safe=True, serial=None):
    stamp = day + "T10:00:00+00:00"
    deltas = {"counter.total.total": pages, "counter.print.full_color_total": pages,
              "billing.a4_color.pages": pages}
    source = {"reconciliation": {"billing_safe": safe}, "fixture_day": day,
              "device_identity": {"serial": serial or f"SER-{slot}", "name": f"Printer {slot}"}}
    with database._open() as conn:
        return conn.execute("""INSERT INTO daily_meter_records(
            device_slot,record_date,opening_json,closing_json,delta_json,category_json,
            source_json,first_success,last_success,sample_count,error_count,incomplete,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                slot, day, "{}", "{}", json.dumps(deltas), json.dumps({
                    key: "a4_color" if key == "billing.a4_color.pages" else "no_charge" for key in deltas}),
                json.dumps(source), stamp, stamp, 1, 0, 0, stamp,
            )).lastrowid


def assert_matches(*, start=None, end=None, slots=(0, 1), today=date(2026, 7, 20), cache=None, graph=False):
    kwargs = dict(granularity="daily", today=today, cache=cache or EmptyCache(), graph=graph)
    full = history.load_usage_history(list(slots), **kwargs)
    expected = tuple(row for row in full if (start is None or row.period_start >= start)
                     and (end is None or row.period_end <= end))
    bounded = history.load_usage_history(list(slots), period_start=start, period_end=end, **kwargs)
    assert bounded == expected
    return bounded


@pytest.mark.parametrize("bounds", ["start", "end", "both", "empty"])
def test_bounded_history_retains_amendment_money_holds_and_frozen_identity(bounds):
    setup_devices()
    for day in ("2026-07-15", "2026-07-17"):
        post_daily_record(daily(day))
    original = post_daily_record(daily("2026-07-16"))
    replace_entry(original, gross_cents=450, net_cents=430, reason="Reviewed correction")
    hold = post_daily_record(daily("2026-07-16", slot=1, safe=False))
    approve_held_entry(hold, gross_cents=700, net_cents=690, reason="Reviewed held day")
    with database._open() as conn:
        conn.execute("UPDATE devices SET serial='REPLACEMENT',name='Renamed' WHERE slot=0")
    PricingRepository().set_prices(0, date(2026, 1, 1), PriceList(a4_color=99))
    database.set_cfg("billing_day", "1")
    database.set_cfg("waste_paper_pct", "50")
    selected = date(2026, 7, 16)
    start = None if bounds == "end" else selected
    end = None if bounds == "start" else selected
    if bounds == "empty":
        start = end = date(2020, 1, 1)
    result = assert_matches(start=start, end=end)
    if bounds != "empty":
        amended = next(row for row in result if row.period_start == selected and row.device_slot == 0)
        approved = next(row for row in result if row.period_start == selected and row.device_slot == 1)
        assert (amended.gross_cost, amended.net_cost, amended.device_identity) == (4.5, 4.3, "serial:SER-0")
        assert (approved.gross_cost, approved.net_cost, approved.held_days) == (7, 6.9, 0)


@pytest.mark.parametrize("change", ["deleted", "moved_date", "moved_slot"])
def test_operational_changes_do_not_create_an_extra_bounded_held_day(change):
    setup_devices()
    source_id = daily("2026-07-16")
    post_daily_record(source_id)
    with database._open() as conn:
        if change == "deleted":
            conn.execute("DELETE FROM daily_meter_records WHERE id=?", (source_id,))
        elif change == "moved_date":
            conn.execute("UPDATE daily_meter_records SET record_date='2026-07-17' WHERE id=?", (source_id,))
        else:
            conn.execute("UPDATE daily_meter_records SET device_slot=1 WHERE id=?", (source_id,))
    for slots in ((0,), (1,), (0, 1)):
        for selected in (date(2026, 7, 16), date(2026, 7, 17)):
            assert_matches(start=selected, end=selected, slots=slots)


def test_bounded_reader_does_not_decode_outside_ledger_or_operational_payloads(monkeypatch):
    setup_devices()
    for day in ("2026-07-15", "2026-07-16", "2026-07-17"):
        post_daily_record(daily(day))
    daily("2020-01-01", safe=False)
    daily("2030-01-01", safe=False)
    parsed = []
    original = history._ledger_remarks

    def remarks(raw):
        parsed.append(raw)
        return original(raw)

    monkeypatch.setattr(history, "_ledger_remarks", remarks)
    monkeypatch.setattr(history, "_source_identity", lambda *args: pytest.fail("Decoded an excluded operational row"))
    result = history.load_usage_history([0], granularity="daily", today=date(2026, 7, 20),
        cache=EmptyCache(), period_start=date(2026, 7, 16), period_end=date(2026, 7, 16))
    assert len(result) == len(parsed) == 1


@pytest.mark.parametrize("graph", [False, True])
@pytest.mark.parametrize("closed_kind", ["operational", "ledger_only"])
def test_shared_gap_stays_blocked_by_closed_day_outside_selection(graph, closed_kind):
    from test_shared_report_history import setup, event_at, receive

    anchor, epoch = setup()
    receive(event_at(anchor, epoch, 401, datetime(2026, 9, 21, 9, tzinfo=UTC)), epoch)
    source_id = daily("2026-09-21", pages=301, serial="REPORT-A")
    if closed_kind == "ledger_only":
        post_daily_record(source_id)
        with database._open() as conn:
            conn.execute("DELETE FROM daily_meter_records WHERE id=?", (source_id,))
    result = assert_matches(start=date(2026, 9, 20), end=date(2026, 9, 20), slots=(0,),
                            today=date(2026, 9, 22), graph=graph)
    assert result and all(row.provisional_total == row.total == 0 for row in result)
    assert any("พบหลักฐาน Web เพิ่ม" in note for row in result for note in row.remarks)


@pytest.mark.parametrize("graph", [False, True])
def test_shared_bounds_keep_previous_high_and_next_read_across_months(graph):
    from test_shared_report_history import setup, event_at, receive

    anchor, epoch = setup(datetime(2026, 8, 31, 17, tzinfo=UTC))
    for at, amount in ((datetime(2026, 9, 2, 9, tzinfo=UTC), 130),
                       (datetime(2026, 9, 30, 9, tzinfo=UTC), 200),
                       (datetime(2026, 10, 2, 9, tzinfo=UTC), 260)):
        receive(event_at(anchor, epoch, amount, at), epoch)
    result = assert_matches(start=date(2026, 9, 1), end=date(2026, 9, 30), slots=(0,),
                            today=date(2026, 10, 3), graph=graph)
    assert result and sum(row.provisional_total for row in result) > 0


@pytest.mark.parametrize("safe", [False, True])
def test_current_provisional_usage_is_only_returned_inside_bounds(safe):
    setup_devices()

    class Cache:
        def load(self, slot, day):
            return {"first_success": "2026-07-20T08:00:00+00:00",
                    "delta": {"counter.total.total": 10, "counter.print.full_color_total": 10,
                              "counter.paper.full_color.a4": 10},
                    "source": {"reconciliation": {"billing_safe": safe}},
                    "device_identity": {"serial": f"SER-{slot}", "name": f"Printer {slot}"}}

    for selected in (date(2026, 7, 19), date(2026, 7, 20), date(2026, 7, 21)):
        result = assert_matches(start=selected, end=selected, cache=Cache())
        if selected == date(2026, 7, 20):
            assert len(result) == 2
            assert all(row.provisional_total == 10 for row in result) if safe else all(row.held_days == 1 for row in result)
        else:
            assert not result
    with database._open(commit=False) as conn:
        assert conn.execute("SELECT COUNT(*) FROM billing_ledger").fetchone()[0] == 0


@pytest.mark.parametrize("kwargs", [
    {"period_start": date(2026, 7, 1)},
    {"granularity": "daily", "period_start": date(2026, 7, 2), "period_end": date(2026, 7, 1)},
])
def test_invalid_bounds_are_rejected_before_loading(kwargs, monkeypatch):
    monkeypatch.setattr(history, "_load_ledger_days", lambda *a, **kw: pytest.fail("Read before validation"))
    with pytest.raises(ValueError):
        history.load_usage_history([0], **kwargs)
