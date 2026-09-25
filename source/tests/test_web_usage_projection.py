from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
from fractions import Fraction
import hashlib

import pytest

from services.web_usage_projection import CounterIdentity, project_counter
from services.web_observations import WebObservationStore, _json
from services.device_config import DeviceConfig, DeviceConfigRepository
from test_subject_history import _reading

BANGKOK = timezone(timedelta(hours=7))


def events_for(*pairs):
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Fixture", "192.0.2.10", serial="SER-A")])
    store = WebObservationStore()
    events = []
    for stamp, value in pairs:
        at = datetime.fromisoformat(stamp).replace(tzinfo=BANGKOK)
        events.append(store.record(0, _reading(value, collected_at=at), at=at, serial="SER-A", printer_name="Fixture"))
    return events


def project(events, **kwargs):
    return project_counter(events, slot=0, serial="SER-A", epoch_id="reviewed-epoch-1",
                           counter=CounterIdentity("counter.user.total.total", "user", "u-1"),
                           calendar_timezone=BANGKOK, **kwargs)


@pytest.mark.parametrize("total, average", [(1300, Fraction(150)), (1301, Fraction(301, 2)), (1000, Fraction())])
def test_weekend_allocation_and_average_replace_each_other(total, average):
    events = events_for(("2026-09-18T17:00", 1000), ("2026-09-21T08:00", total))
    result = project(events)
    interval, = result.intervals
    assert interval.allocation_day == date(2026, 9, 20)
    assert interval.empty_days == (date(2026, 9, 19), date(2026, 9, 20))
    assert interval.estimated_per_day == average
    assert interval.holds == ()
    assert "ไม่ใช่ยอดที่ยืนยัน" in interval.remark
    bars = result.daily_graph()
    assert [(row.day.day, row.total, row.estimated) for row in bars] == [(19, average, True), (20, average, True)]
    assert sum(row.total for row in bars) == total - 1000 == result.total_usage


def test_late_real_history_replaces_estimates_without_adding_usage():
    first, last, middle = events_for(("2026-09-18T17:00", 1000), ("2026-09-21T08:00", 1301), ("2026-09-19T12:00", 1100))
    before = project([first, last])
    after = project([last, middle, first, middle, last])
    assert before.total_usage == after.total_usage == 301
    assert before.revision != after.revision
    assert after.revision == project([middle, first, last]).revision
    assert [(row.day.day, row.total, row.estimated) for row in after.daily_graph()] == [(19, 100, False), (20, 201, True)]


def test_fraction_is_not_rounded_until_presentation():
    result = project(events_for(("2026-09-18T17:00", 1000), ("2026-09-22T08:00", 1301)))
    assert [row.total for row in result.daily_graph()] == [Fraction(301, 3)] * 3
    assert sum(row.total for row in result.daily_graph()) == 301


def test_manual_read_keeps_all_four_real_points_and_no_estimates():
    result = project(events_for(*[(f"2026-09-18T{clock}", value) for clock, value in
                                  [("10:00", 1000), ("10:10", 1010), ("10:15", 1015), ("10:30", 1030)]]))
    assert len(result.points) == 4
    assert result.total_usage == 30
    assert all(not interval.empty_days for interval in result.intervals)
    assert not result.daily_graph()[0].estimated


def test_maximum_not_last_received_and_reset_cannot_add_absolute_value():
    events = events_for(("2026-09-18T10:00", 1000), ("2026-09-18T10:15", 1030), ("2026-09-18T10:30", 5), ("2026-09-18T10:45", 10))
    result = project(list(reversed(events)))
    assert result.maximum == 1030 and result.total_usage == 30
    assert result.intervals[-1].amount == 0
    assert "counter_baseline_review_required" in result.intervals[-1].holds


def test_price_and_billing_boundaries_require_review():
    events = events_for(("2026-09-29T17:00", 1000), ("2026-10-02T08:00", 1300))
    result = project(events, price_change_dates=[date(2026, 10, 1)])
    assert set(result.intervals[0].holds) == {"interval_crosses_price_change", "interval_crosses_billing_period"}


@pytest.mark.parametrize('crossing_usage', [0, 50])
def test_zero_boundary_interval_does_not_hold_later_usage(crossing_usage):
    events = events_for(('2026-09-30T17:00', 1000),
                        ('2026-10-01T08:00', 1000 + crossing_usage),
                        ('2026-10-01T09:00', 1200 + crossing_usage))
    result = project(events, price_change_dates=[date(2026, 10, 1)])
    assert result.total_usage == 200 + crossing_usage
    expected = {'interval_crosses_price_change', 'interval_crosses_billing_period'} if crossing_usage else set()
    assert set(result.intervals[0].holds) == expected
    assert result.intervals[1].holds == ()


def test_other_printer_cannot_fill_this_printers_missing_day():
    events = events_for(("2026-09-18T17:00", 1000), ("2026-09-21T08:00", 1300))
    wrong = deepcopy(events[0])
    wrong["payload"]["serial"] = "SER-B"
    wrong["id"] = hashlib.sha256(_json(wrong["payload"]).encode()).hexdigest()
    with pytest.raises(ValueError, match="different slots"):
        project(events + [wrong])


def test_web_day_without_selected_counter_is_not_a_wholly_missing_day():
    events = events_for(("2026-09-18T17:00", 1000), ("2026-09-21T08:00", 1300), ("2026-09-19T12:00", 1100))
    partial = events[-1]
    partial["payload"]["reading"]["counters"] = partial["payload"]["reading"]["counters"][1:]
    partial["id"] = hashlib.sha256(_json(partial["payload"]).encode()).hexdigest()
    result = project(events)
    assert result.intervals[0].empty_days == (date(2026, 9, 20),)
    assert "selected_counter_missing_on_observed_days" in result.intervals[0].holds


def test_non_cumulative_telemetry_rejected():
    with pytest.raises(ValueError, match="cumulative counter"):
        project_counter([], slot=0, serial="SER-A", epoch_id="epoch", counter=CounterIdentity("toner.black"), calendar_timezone=BANGKOK)
