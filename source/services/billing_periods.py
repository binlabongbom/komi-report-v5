from __future__ import annotations

import calendar
from datetime import date, timedelta


def effective_billing_day(raw) -> int:
    """Match the established report fallback for legacy/missing configuration.

    New setup persists its explicit default (31). An older database without a
    value has historically used 25; exporting/summarizing it must not turn 25
    into 31 and move usage into another billing period.
    """
    try:
        value = int(raw or "25")
    except (ValueError, TypeError):
        value = 25
    return max(1, min(31, value))


def billing_month_range(day: date, billing_end_day: int) -> tuple[date, date]:
    """Return the billing cycle containing ``day`` for an end-of-cycle day.

    A configured 31st stays valid in every month: shorter months close on
    their final calendar day.
    """
    billing_end_day = min(31, max(1, billing_end_day))

    def cutoff(year: int, month: int) -> date:
        return date(year, month, min(billing_end_day, calendar.monthrange(year, month)[1]))

    this_month_end = cutoff(day.year, day.month)
    if day <= this_month_end:
        end = this_month_end
    else:
        next_month = 1 if day.month == 12 else day.month + 1
        next_year = day.year + 1 if day.month == 12 else day.year
        end = cutoff(next_year, next_month)
    previous_month = 12 if end.month == 1 else end.month - 1
    previous_year = end.year - 1 if end.month == 1 else end.year
    start = cutoff(previous_year, previous_month) + timedelta(days=1)
    return start, end
