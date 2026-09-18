"""Read-only report scope independent from the live polling fleet."""

from __future__ import annotations

from database import _open


def report_slots() -> list[int]:
    """Return enabled slots plus every slot that still owns historical evidence.

    Disabling a printer stops live polling, but it must never hide frozen ledger,
    daily meter, or RAM/User history from reports.
    """

    with _open(commit=False) as conn:
        rows = conn.execute(
            """SELECT slot FROM devices WHERE enabled=1
               UNION SELECT device_slot FROM billing_ledger
               UNION SELECT device_slot FROM daily_meter_records
               UNION SELECT device_slot FROM daily_subject_records
               UNION SELECT device_slot FROM archived_subject_periods
               ORDER BY 1"""
        ).fetchall()
    return [int(row[0]) for row in rows]
