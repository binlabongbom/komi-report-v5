from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from database import _open, get_billing_day, get_waste_paper_pct
from services.billing_periods import billing_month_range
from services.daily_cache import DailyCacheStore
from services.pricing import (
    PricingRepository,
    apply_waste_discount,
    calculate_cost,
)
from services.usage import default_usage_groups


@dataclass(frozen=True)
class MonthlyUsage:
    device_slot: int
    period_start: date
    period_end: date
    total: float
    a3_color: float
    a3_bw: float
    a4_color: float
    a4_bw: float
    scan: float
    gross_cost: float
    net_cost: float
    day_count: int
    incomplete_days: int
    held_days: int = 0
    device_identity: str = ""
    device_name_snapshot: str = ""
    device_serial_snapshot: str = ""
    print_color: float = 0.0
    print_bw: float = 0.0
    copy_color: float = 0.0
    copy_bw: float = 0.0
    provisional_total: float = 0.0
    provisional_a3_color: float = 0.0
    provisional_a3_bw: float = 0.0
    provisional_a4_color: float = 0.0
    provisional_a4_bw: float = 0.0
    provisional_print_color: float = 0.0
    provisional_print_bw: float = 0.0
    provisional_copy_color: float = 0.0
    provisional_copy_bw: float = 0.0
    provisional_scan: float = 0.0
    provisional_gross_cost: float = 0.0
    provisional_net_cost: float = 0.0
    provisional_days: int = 0
    provisional_cost_available: bool = True
    print_a3_color: float = 0.0
    print_a4_color: float = 0.0
    print_a3_bw: float = 0.0
    print_a4_bw: float = 0.0
    copy_a3_color: float = 0.0
    copy_a4_color: float = 0.0
    copy_a3_bw: float = 0.0
    copy_a4_bw: float = 0.0
    print_other: float = 0.0
    copy_other: float = 0.0
    provisional_print_a3_color: float = 0.0
    provisional_print_a4_color: float = 0.0
    provisional_print_a3_bw: float = 0.0
    provisional_print_a4_bw: float = 0.0
    provisional_copy_a3_color: float = 0.0
    provisional_copy_a4_color: float = 0.0
    provisional_copy_a3_bw: float = 0.0
    provisional_copy_a4_bw: float = 0.0
    provisional_print_other: float = 0.0
    provisional_copy_other: float = 0.0
    print_available: bool = False
    copy_available: bool = False
    remarks: tuple[str, ...] = ()


HistoryGranularity = Literal["daily", "weekly", "monthly", "quarterly", "yearly"]


@dataclass(frozen=True)
class _LedgerDay:
    source_daily_record_id: int
    device_slot: int
    record_date: date
    latest_kind: str
    period_start: date
    period_end: date
    billing_day: int
    delta_json: str
    gross_cents: int
    net_cents: int
    device_identity: str
    device_name_snapshot: str
    device_serial_snapshot: str
    hold_reason: str | None
    remarks: tuple[str, ...] = ()


def _ledger_remarks(raw):
    try:
        proof = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    while isinstance(proof, dict):
        amendment = proof.get("web_allocation")
        if isinstance(amendment, dict):
            remarks = ["ฉบับแก้ไขการแบ่งยอดตามหลักฐาน Web · เก็บรายการเดิมไว้ในประวัติบัญชี"]
            remarks.extend(item["remark"] for item in amendment.get("intervals", [])
                           if isinstance(item, dict) and isinstance(item.get("remark"), str) and item["remark"])
            return tuple(dict.fromkeys(remarks))
        proof = proof.get("original_attestation")
    return ()


def _billing_period_ending_in(year: int, month: int, billing_day: int) -> tuple[date, date]:
    end = date(year, month, min(billing_day, calendar.monthrange(year, month)[1]))
    return billing_month_range(end, billing_day)


def history_period_range(
    day: date,
    billing_day: int,
    granularity: HistoryGranularity,
) -> tuple[date, date]:
    """Return a reporting bucket aligned to the configured billing cycle."""
    cycle_start, cycle_end = billing_month_range(day, billing_day)
    if granularity == "daily":
        return day, day
    if granularity == "weekly":
        week_start = cycle_start + timedelta(days=((day - cycle_start).days // 7) * 7)
        return week_start, min(week_start + timedelta(days=6), cycle_end)
    if granularity == "monthly":
        return cycle_start, cycle_end
    if granularity == "quarterly":
        first_month = ((cycle_end.month - 1) // 3) * 3 + 1
        start, _ = _billing_period_ending_in(cycle_end.year, first_month, billing_day)
        _, end = _billing_period_ending_in(cycle_end.year, first_month + 2, billing_day)
        return start, end
    if granularity == "yearly":
        start, _ = _billing_period_ending_in(cycle_end.year, 1, billing_day)
        _, end = _billing_period_ending_in(cycle_end.year, 12, billing_day)
        return start, end
    raise ValueError(f"unsupported history granularity: {granularity}")
def _group_value(groups: dict[str, float | None], label: str) -> float:
    return float(groups.get(label) or 0.0)


def _identity_snapshot(value: object, slot: int) -> tuple[str, str, str]:
    """Return a stable report identity without falling back to current slot metadata."""
    source = value if isinstance(value, dict) else {}
    captured = source.get("device_identity") if isinstance(source, dict) else None
    if not isinstance(captured, dict):
        captured = {}
    name = str(captured.get("name") or "")
    serial = str(captured.get("serial") or "").strip()
    host = str(captured.get("host") or "").strip()
    identity = f"serial:{serial}" if serial else (f"host:{host}" if host else f"unattributed:slot:{slot}")
    return identity, name, serial


def _source_identity(source_json: str, slot: int) -> tuple[str, str, str]:
    try:
        source = json.loads(source_json)
    except (TypeError, json.JSONDecodeError):
        source = {}
    return _identity_snapshot(source, slot)


def _cache_meter_is_safe(state: dict) -> bool:
    """Allow current-day presentation only from explicitly safe Web evidence."""
    source = state.get("source")
    reconciliation = source.get("reconciliation") if isinstance(source, dict) else None
    return bool(
        state.get("first_success")
        and isinstance(state.get("delta"), dict)
        and isinstance(reconciliation, dict)
        and reconciliation.get("billing_safe") is True
        and not state.get("identity_conflict")
        and not state.get("identity_baseline_mismatch")
        and not state.get("resets")
        and not state.get("out_of_order")
        and not state.get("unsafe_reconciliation_seen")
        and not state.get("cache_corruption")
    )


def _provisional_cost(
    slot: int,
    day: date,
    deltas: dict[str, float],
    state: dict,
) -> tuple[float, float, bool]:
    """Estimate today's cost without creating or mutating a Ledger entry."""
    with _open(commit=False) as conn:
        price_exists = conn.execute(
            """SELECT 1 FROM price_history
               WHERE device_slot=? AND effective_date<=?
               ORDER BY effective_date DESC LIMIT 1""",
            (slot, day.isoformat()),
        ).fetchone()
    if price_exists is None:
        return 0.0, 0.0, False

    source = state.get("source") if isinstance(state.get("source"), dict) else {}
    counter_sources = (
        source.get("counter_sources")
        if isinstance(source.get("counter_sources"), dict)
        else {}
    )
    pricing = PricingRepository()
    counter_metadata = {}
    for key in deltas:
        evidence = counter_sources.get(key)
        evidence = evidence if isinstance(evidence, dict) else {}
        counter_metadata[key] = (
            str(evidence.get("label") or ""),
            str(evidence.get("source_path") or ""),
        )
    categories = pricing.get_categories(slot, day, counter_metadata)
    gross = calculate_cost(deltas, categories, pricing.get_prices(slot, day))
    return gross, apply_waste_discount(gross, get_waste_paper_pct()), True


def _ledger_period_range(day: date, ledger: _LedgerDay, granularity: HistoryGranularity) -> tuple[date, date]:
    if granularity == "daily":
        return day, day
    if granularity == "weekly":
        week_start = ledger.period_start + timedelta(days=((day - ledger.period_start).days // 7) * 7)
        return week_start, min(week_start + timedelta(days=6), ledger.period_end)
    if granularity == "monthly":
        return ledger.period_start, ledger.period_end
    return history_period_range(day, ledger.billing_day, granularity)


def _load_ledger_days(slots: list[int]) -> dict[int, _LedgerDay]:
    if not slots:
        return {}
    placeholders = ",".join("?" for _ in slots)
    with _open(commit=False) as conn:
        rows = conn.execute(
            f"""SELECT id,entry_kind,source_daily_record_id,device_slot,record_date,
                       period_start,period_end,billing_day,
                       delta_json,gross_cents,net_cents,device_identity,device_name_snapshot,
                       device_serial_snapshot,hold_reason,attestation_json
                FROM billing_ledger
                WHERE device_slot IN ({placeholders}) AND source_daily_record_id IS NOT NULL
                ORDER BY id""",
            slots,
        ).fetchall()
    accumulated: dict[int, dict] = {}
    for (
        _entry_id,
        kind,
        source_id,
        slot,
        record_date,
        period_start,
        period_end,
        billing_day,
        delta_json,
        gross,
        net,
        device_identity,
        device_name,
        device_serial,
        hold_reason,
        attestation_json,
    ) in rows:
        item = accumulated.setdefault(source_id, {"gross": 0, "net": 0})
        if kind in {"posting", "replacement", "reversal"}:
            item["gross"] += int(gross)
            item["net"] += int(net)
        item.update(
            {
                "latest_kind": kind,
                "source_daily_record_id": int(source_id),
                "device_slot": int(slot),
                "record_date": date.fromisoformat(record_date),
                "period_start": date.fromisoformat(period_start),
                "period_end": date.fromisoformat(period_end),
                "billing_day": int(billing_day),
                "delta_json": delta_json,
                "device_identity": str(device_identity),
                "device_name_snapshot": str(device_name or ""),
                "device_serial_snapshot": str(device_serial or ""),
                "hold_reason": hold_reason,
                "remarks": _ledger_remarks(attestation_json),
            }
        )
    return {
        int(source_id): _LedgerDay(
            source_daily_record_id=item["source_daily_record_id"],
            device_slot=item["device_slot"],
            record_date=item["record_date"],
            latest_kind=item["latest_kind"],
            period_start=item["period_start"],
            period_end=item["period_end"],
            billing_day=item["billing_day"],
            delta_json=item["delta_json"],
            gross_cents=item["gross"],
            net_cents=item["net"],
            device_identity=item["device_identity"],
            device_name_snapshot=item["device_name_snapshot"],
            device_serial_snapshot=item["device_serial_snapshot"],
            hold_reason=item["hold_reason"],
            remarks=item["remarks"],
        )
        for source_id, item in accumulated.items()
    }


def load_usage_history(
    slots: list[int],
    *,
    granularity: HistoryGranularity = "monthly",
    today: date | None = None,
    cache: DailyCacheStore | None = None,
) -> tuple[MonthlyUsage, ...]:
    current = today or date.today()
    cache_store = cache or DailyCacheStore()
    billing_day = get_billing_day()
    buckets: dict[tuple[int, str, date, date], dict] = {}
    finalized: set[tuple[int, date]] = set()
    ledger_days = _load_ledger_days(slots)

    if slots:
        placeholders = ",".join("?" for _ in slots)
        with _open(commit=False) as conn:
            rows = conn.execute(
                f"""SELECT id,device_slot,record_date,incomplete,source_json
                    FROM daily_meter_records WHERE device_slot IN ({placeholders})
                    ORDER BY record_date""",
                slots,
            ).fetchall()
    else:
        rows = []

    def bucket_for(
        slot: int,
        identity: tuple[str, str, str],
        start: date,
        end: date,
    ) -> dict:
        device_identity, device_name, device_serial = identity
        return buckets.setdefault(
            (slot, device_identity, start, end),
            {
                "counters": {},
                "provisional_counters": {},
                "gross_cents": 0,
                "net_cents": 0,
                "provisional_gross_cost": 0.0,
                "provisional_net_cost": 0.0,
                "provisional_days": 0,
                "provisional_cost_available": True,
                "days": 0,
                "incomplete": 0,
                "held": 0,
                "remarks": set(),
                "device_name_snapshot": device_name,
                "device_serial_snapshot": device_serial,
            },
        )

    def add_day(slot: int, day: date, deltas: dict, incomplete: bool, ledger: _LedgerDay) -> None:
        start, end = _ledger_period_range(day, ledger, granularity)
        bucket = bucket_for(
            slot,
            (
                ledger.device_identity,
                ledger.device_name_snapshot,
                ledger.device_serial_snapshot,
            ),
            start,
            end,
        )
        for key, value in deltas.items():
            bucket["counters"][key] = bucket["counters"].get(key, 0.0) + max(0.0, float(value))
        bucket["gross_cents"] += ledger.gross_cents
        bucket["net_cents"] += ledger.net_cents
        bucket["days"] += 1
        bucket["incomplete"] += int(incomplete)
        bucket["remarks"].update(ledger.remarks)

    def add_provisional(
        slot: int,
        day: date,
        deltas: dict[str, float],
        state: dict,
    ) -> None:
        start, end = history_period_range(day, billing_day, granularity)
        bucket = bucket_for(slot, _identity_snapshot(state, slot), start, end)
        for key, value in deltas.items():
            bucket["provisional_counters"][key] = (
                bucket["provisional_counters"].get(key, 0.0)
                + max(0.0, float(value))
            )
        gross, net, cost_available = _provisional_cost(slot, day, deltas, state)
        bucket["provisional_gross_cost"] += gross
        bucket["provisional_net_cost"] += net
        bucket["provisional_days"] += 1
        bucket["provisional_cost_available"] = (
            bucket["provisional_cost_available"] and cost_available
        )

    def hold_day(
        slot: int,
        day: date,
        incomplete: bool,
        ledger: _LedgerDay | None = None,
        *,
        source_json: str = "{}",
        identity: tuple[str, str, str] | None = None,
    ) -> None:
        start, end = (
            _ledger_period_range(day, ledger, granularity)
            if ledger is not None
            else history_period_range(day, billing_day, granularity)
        )
        snapshot = (
            (
                ledger.device_identity,
                ledger.device_name_snapshot,
                ledger.device_serial_snapshot,
            )
            if ledger is not None
            else identity or _source_identity(source_json, slot)
        )
        bucket = bucket_for(slot, snapshot, start, end)
        bucket["held"] += 1
        bucket["incomplete"] += int(incomplete)

    # Ledger is the canonical reporting source.  A posted/replaced day remains
    # reportable even if its mutable operational daily row is later changed or
    # removed.  Daily rows are consulted below only for never-ledgered evidence.
    for ledger in ledger_days.values():
        slot = ledger.device_slot
        day = ledger.record_date
        incomplete = ledger.hold_reason == "incomplete_day"
        if ledger.latest_kind in {"posting", "replacement"}:
            try:
                raw_deltas = json.loads(ledger.delta_json)
                if not isinstance(raw_deltas, dict):
                    raise TypeError("ledger delta is not an object")
                deltas = {key: float(value) for key, value in raw_deltas.items()}
            except (TypeError, ValueError, json.JSONDecodeError):
                hold_day(slot, day, incomplete, ledger)
            else:
                add_day(slot, day, deltas, incomplete, ledger)
        else:
            hold_day(slot, day, incomplete, ledger)
        finalized.add((slot, day))

    for record_id, slot, record_date, incomplete, source_json in rows:
        if int(record_id) in ledger_days:
            continue
        day = date.fromisoformat(record_date)
        hold_day(slot, day, bool(incomplete), source_json=source_json)
        finalized.add((slot, day))

    for slot in slots:
        if (slot, current) in finalized:
            continue
        state = cache_store.load(slot, current)
        if state and state.get("delta"):
            # Safe current-day evidence is visible as provisional usage/cost,
            # but remains outside the append-only Billing Ledger until rollover.
            if _cache_meter_is_safe(state):
                add_provisional(
                    slot,
                    current,
                    {key: float(value) for key, value in state["delta"].items()},
                    state,
                )
            else:
                hold_day(
                    slot,
                    current,
                    False,
                    identity=_identity_snapshot(state, slot),
                )

    result: list[MonthlyUsage] = []
    for (slot, device_identity, start, end), bucket in buckets.items():
        groups = default_usage_groups(bucket["counters"])
        provisional_groups = default_usage_groups(bucket["provisional_counters"])
        print_labels = (
            "A3 Color (Print)", "A4 Color (Print)",
            "A3 B&W (Print)", "A4 B&W (Print)", "Other size (Print)",
        )
        copy_labels = (
            "A3 Color (Copy)", "A4 Color (Copy)",
            "A3 B&W (Copy)", "A4 B&W (Copy)", "Other size (Copy)",
        )
        print_available = any(groups.get(label) is not None for label in print_labels) or any(
            provisional_groups.get(label) is not None for label in print_labels
        )
        copy_available = any(groups.get(label) is not None for label in copy_labels) or any(
            provisional_groups.get(label) is not None for label in copy_labels
        )
        a3_color = _group_value(groups, "A3 Color (Print)") + _group_value(groups, "A3 Color (Copy)")
        a3_bw = _group_value(groups, "A3 B&W (Print)") + _group_value(groups, "A3 B&W (Copy)")
        a4_color = _group_value(groups, "A4 Color (Print)") + _group_value(groups, "A4 Color (Copy)")
        a4_bw = _group_value(groups, "A4 B&W (Print)") + _group_value(groups, "A4 B&W (Copy)")
        print_color = _group_value(groups, "A3 Color (Print)") + _group_value(groups, "A4 Color (Print)")
        print_bw = _group_value(groups, "A3 B&W (Print)") + _group_value(groups, "A4 B&W (Print)")
        copy_color = _group_value(groups, "A3 Color (Copy)") + _group_value(groups, "A4 Color (Copy)")
        copy_bw = _group_value(groups, "A3 B&W (Copy)") + _group_value(groups, "A4 B&W (Copy)")
        total = bucket["counters"].get("counter.total.total")
        if total is None:
            total = (
                a3_color
                + a3_bw
                + a4_color
                + a4_bw
                + _group_value(groups, "Other size (Print)")
                + _group_value(groups, "Other size (Copy)")
            )
        provisional_a3_color = _group_value(provisional_groups, "A3 Color (Print)") + _group_value(
            provisional_groups, "A3 Color (Copy)"
        )
        provisional_a3_bw = _group_value(provisional_groups, "A3 B&W (Print)") + _group_value(
            provisional_groups, "A3 B&W (Copy)"
        )
        provisional_a4_color = _group_value(provisional_groups, "A4 Color (Print)") + _group_value(
            provisional_groups, "A4 Color (Copy)"
        )
        provisional_a4_bw = _group_value(provisional_groups, "A4 B&W (Print)") + _group_value(
            provisional_groups, "A4 B&W (Copy)"
        )
        provisional_print_color = _group_value(
            provisional_groups, "A3 Color (Print)"
        ) + _group_value(provisional_groups, "A4 Color (Print)")
        provisional_print_bw = _group_value(
            provisional_groups, "A3 B&W (Print)"
        ) + _group_value(provisional_groups, "A4 B&W (Print)")
        provisional_copy_color = _group_value(
            provisional_groups, "A3 Color (Copy)"
        ) + _group_value(provisional_groups, "A4 Color (Copy)")
        provisional_copy_bw = _group_value(
            provisional_groups, "A3 B&W (Copy)"
        ) + _group_value(provisional_groups, "A4 B&W (Copy)")
        provisional_total = bucket["provisional_counters"].get("counter.total.total")
        if provisional_total is None:
            provisional_total = (
                provisional_a3_color
                + provisional_a3_bw
                + provisional_a4_color
                + provisional_a4_bw
                + _group_value(provisional_groups, "Other size (Print)")
                + _group_value(provisional_groups, "Other size (Copy)")
            )
        result.append(
            MonthlyUsage(
                device_slot=slot,
                period_start=start,
                period_end=end,
                total=float(total),
                a3_color=a3_color,
                a3_bw=a3_bw,
                a4_color=a4_color,
                a4_bw=a4_bw,
                scan=_group_value(groups, "SCAN"),
                gross_cost=bucket["gross_cents"] / 100,
                net_cost=bucket["net_cents"] / 100,
                day_count=bucket["days"],
                incomplete_days=bucket["incomplete"],
                held_days=bucket["held"],
                remarks=tuple(sorted(bucket["remarks"])),
                device_identity=device_identity,
                device_name_snapshot=bucket["device_name_snapshot"],
                device_serial_snapshot=bucket["device_serial_snapshot"],
                print_color=print_color,
                print_bw=print_bw,
                copy_color=copy_color,
                copy_bw=copy_bw,
                provisional_total=float(provisional_total),
                provisional_a3_color=provisional_a3_color,
                provisional_a3_bw=provisional_a3_bw,
                provisional_a4_color=provisional_a4_color,
                provisional_a4_bw=provisional_a4_bw,
                provisional_print_color=provisional_print_color,
                provisional_print_bw=provisional_print_bw,
                provisional_copy_color=provisional_copy_color,
                provisional_copy_bw=provisional_copy_bw,
                provisional_scan=_group_value(provisional_groups, "SCAN"),
                provisional_gross_cost=bucket["provisional_gross_cost"],
                provisional_net_cost=bucket["provisional_net_cost"],
                provisional_days=bucket["provisional_days"],
                provisional_cost_available=bucket["provisional_cost_available"],
                print_a3_color=_group_value(groups, "A3 Color (Print)"),
                print_a4_color=_group_value(groups, "A4 Color (Print)"),
                print_a3_bw=_group_value(groups, "A3 B&W (Print)"),
                print_a4_bw=_group_value(groups, "A4 B&W (Print)"),
                copy_a3_color=_group_value(groups, "A3 Color (Copy)"),
                copy_a4_color=_group_value(groups, "A4 Color (Copy)"),
                copy_a3_bw=_group_value(groups, "A3 B&W (Copy)"),
                copy_a4_bw=_group_value(groups, "A4 B&W (Copy)"),
                print_other=_group_value(groups, "Other size (Print)"),
                copy_other=_group_value(groups, "Other size (Copy)"),
                provisional_print_a3_color=_group_value(provisional_groups, "A3 Color (Print)"),
                provisional_print_a4_color=_group_value(provisional_groups, "A4 Color (Print)"),
                provisional_print_a3_bw=_group_value(provisional_groups, "A3 B&W (Print)"),
                provisional_print_a4_bw=_group_value(provisional_groups, "A4 B&W (Print)"),
                provisional_copy_a3_color=_group_value(provisional_groups, "A3 Color (Copy)"),
                provisional_copy_a4_color=_group_value(provisional_groups, "A4 Color (Copy)"),
                provisional_copy_a3_bw=_group_value(provisional_groups, "A3 B&W (Copy)"),
                provisional_copy_a4_bw=_group_value(provisional_groups, "A4 B&W (Copy)"),
                provisional_print_other=_group_value(
                    provisional_groups, "Other size (Print)"
                ),
                provisional_copy_other=_group_value(
                    provisional_groups, "Other size (Copy)"
                ),
                print_available=print_available,
                copy_available=copy_available,
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda item: (item.period_start, item.device_slot, item.device_identity),
            reverse=True,
        )
    )


def load_monthly_usage(
    slots: list[int],
    *,
    today: date | None = None,
    cache: DailyCacheStore | None = None,
) -> tuple[MonthlyUsage, ...]:
    """Backward-compatible monthly billing-cycle view."""
    return load_usage_history(slots, granularity="monthly", today=today, cache=cache)
