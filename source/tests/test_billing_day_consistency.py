from datetime import date
from threading import Event

import pytest

import database
from services.secondary_setup import setup_snapshot_from_connection
from services.web_evidence_report import load_evidence, inspect_counter
from services.web_usage_projection import CounterIdentity
from test_web_usage_projection import events_for, BANGKOK


@pytest.mark.parametrize("configured", [None, "", "not-a-day", "31"])
def test_settings_export_and_web_gap_flags_match_the_actual_billing_cycle(configured):
    events_for(("2026-09-24T17:00", 1000), ("2026-09-26T08:00", 1100))
    database.set_cfg("company_name", "Synthetic company")
    if configured is not None:
        database.set_cfg("billing_day", configured)
    expected = 31 if configured == "31" else 25
    with database._open(commit=False) as conn:
        assert setup_snapshot_from_connection(conn)["settings"]["billing_day"] == expected
    request = dict(slot=0, serial="SER-A", start=date(2026, 9, 24), end=date(2026, 9, 26), calendar_timezone=BANGKOK)
    evidence = load_evidence(database.get_db_path(), **request, cancelled=Event())
    assert evidence["billing_day"] == database.get_billing_day() == expected
    projection = inspect_counter(evidence, CounterIdentity("counter.user.total.total", "user", "u-1"), **request)
    assert ("interval_crosses_billing_period" in projection.intervals[0].holds) == (expected == 25)
