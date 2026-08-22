from __future__ import annotations

from datetime import date

from services.billing_ledger import ledger_totals
from services.usage import billing_period, current_device_identity


def period_gross_cost(slot: int, *, today: date | None = None) -> float:
    current = today or date.today()
    start, end = billing_period(current)
    identity = current_device_identity(slot)
    if not identity:
        return 0.0
    gross_cents, _net_cents = ledger_totals(
        slot,
        start,
        end,
        device_identity=identity,
    )
    return gross_cents / 100


def period_net_cost(slots: list[int], *, today: date | None = None) -> tuple[float, float, float]:
    current = today or date.today()
    start, end = billing_period(current)
    gross_cents = net_cents = 0
    for slot in slots:
        gross, net = ledger_totals(slot, start, end)
        gross_cents += gross
        net_cents += net
    # There is no single mutable discount for a frozen multi-day period.
    implied_waste = 0.0 if gross_cents == 0 else round((1 - net_cents / gross_cents) * 100, 2)
    return gross_cents / 100, implied_waste, net_cents / 100
