"""Changing the preview range reuses overlapping days without losing gaps."""
from datetime import date

import pytest

from services import report_day_projection, report_user_counters, subject_history
from test_report_day_projection import load, seed


@pytest.mark.parametrize('kind', ['subject', 'raw'])
@pytest.mark.parametrize('cached_day', [1, 2])
def test_extending_period_only_decodes_missing_days_and_preserves_totals(kind, cached_day, monkeypatch):
    report_day_projection.DAY_PROJECTIONS.clear()
    owner = subject_history if kind == 'subject' else report_user_counters
    name = '_subject_day_from_row' if kind == 'subject' else '_user_counter_from_row'
    decode = getattr(owner, name)
    decoded = []

    def track(row):
        decoded.append((row[0], row[1]))
        return decode(row)

    monkeypatch.setattr(owner, name, track)
    seed(kind)
    day = date(2026, 7, cached_day)
    load(kind, period_start=day, period_end=day)
    decoded.clear()
    extended = load(kind)
    assert set(decoded) == {(slot, f'2026-07-{number:02}')
                            for slot in range(2) for number in (1, 2, 3)
                            if number != cached_day}
    assert extended == load(kind, False)
    report_day_projection.DAY_PROJECTIONS.clear()
