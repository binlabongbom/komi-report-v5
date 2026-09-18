from datetime import datetime, timezone

from config import SLOT_NAMES
from database import (
    calc_billing_month,
    calc_cost,
    get_cfg,
    get_month_top_users,
    get_monthly_summary,
    get_price,
)
from services.device_config import DeviceConfigRepository
from services.daily_cache import DailyCacheStore
from services.monthly_history import load_usage_history
from services.report_scope import report_slots
from services.subject_history import load_subject_history
from services.usage import current_device_identity
from komi_snmp_profiler.subject_identity import subject_name_is_placeholder as _subject_name_is_placeholder


def months_ago(billing_month: str, n_months: int) -> str:
    try:
        dt = datetime.strptime(billing_month, "%Y-%m")
        total = dt.month - 1 - n_months
        year = dt.year + total // 12
        month = total % 12 + 1
        return f"{year}-{month:02d}"
    except Exception:
        return billing_month


def _frozen_device_label(record, *, fallback: str) -> str:
    name = record.device_name_snapshot.strip() or fallback
    serial = record.device_serial_snapshot.strip()
    if serial:
        return f"{name} ({serial})"
    identity = record.device_identity.removeprefix("host:")
    return f"{name} ({identity})" if identity and not identity.startswith("unattributed:") else name


def _runtime_status(device, *, now: datetime) -> str:
    """Normalize the operational status and expose stale online devices."""
    status = str(device.connection_status or "pending").lower()
    if status != "online" or not device.last_checked_at:
        return status
    try:
        checked = datetime.fromisoformat(device.last_checked_at.replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        reference = now if now.tzinfo is not None else now.astimezone()
        if (reference.astimezone() - checked.astimezone()).total_seconds() > 15 * 60:
            return "stale"
    except (TypeError, ValueError):
        return "stale"
    return "online"


def _build_legacy_overview_summary(filter_key: str, *, now: datetime | None = None) -> dict:
    """Prepare the retained V4.6 import summary for databases without V5 devices."""
    now = now or datetime.now()
    current_bm = calc_billing_month(now.strftime("%Y/%m/%d"))

    all_monthly: dict = {}
    for slot in range(3):
        slot_monthly = get_monthly_summary(slot)
        for bm, md in slot_monthly.items():
            if bm not in all_monthly:
                all_monthly[bm] = {
                    "total": 0,
                    "total_color": 0,
                    "total_bw": 0,
                    "a4c": 0,
                    "a4bw": 0,
                    "a3c": 0,
                    "a3bw": 0,
                    "meter_c": 0,
                    "meter_bw": 0,
                    "cost": 0.0,
                    "machines": [0, 0, 0],
                }
            entry = all_monthly[bm]
            a4c = md.get("a4_color", 0)
            a4bw = md.get("a4_bw", 0)
            a3c = md.get("a3_color", 0)
            a3bw = md.get("a3_bw", 0)
            mc = md.get("meter_color", 0)
            mbw = md.get("meter_bw", 0)

            if a4c == 0 and a4bw == 0 and a3c == 0 and a3bw == 0 and mc == 0 and mbw == 0:
                a4c = md.get("total_color", 0)
                a4bw = md.get("total_bw", 0)

            total = md.get("total", 0)
            if mc > 0 or mbw > 0:
                cost = mc * get_price("a4_color", slot) + mbw * get_price("a4_bw", slot)
            else:
                cost = calc_cost(a4c, a4bw, a3c, a3bw, slot)

            entry["total"] += total
            entry["total_color"] += md.get("total_color", 0)
            entry["total_bw"] += md.get("total_bw", 0)
            entry["a4c"] += a4c
            entry["a4bw"] += a4bw
            entry["a3c"] += a3c
            entry["a3bw"] += a3bw
            entry["meter_c"] += mc
            entry["meter_bw"] += mbw
            entry["cost"] += cost
            entry["machines"][slot] += total

    sorted_months = sorted(all_monthly.keys())
    normalized_filter = "current" if filter_key == "month" else filter_key
    if normalized_filter == "day":
        filtered_months = [current_bm] if current_bm in all_monthly else []
    elif normalized_filter == "year":
        filtered_months = [key for key in sorted_months if key.startswith(f"{now.year}-")]
    elif normalized_filter == "current":
        display_bm = current_bm
        if display_bm not in all_monthly and sorted_months:
            display_bm = sorted_months[-1]
        filtered_months = [display_bm] if display_bm in all_monthly else []
    elif normalized_filter == "3m":
        base_month = sorted_months[-1] if sorted_months else current_bm
        cutoff = months_ago(base_month, 3)
        filtered_months = [m for m in sorted_months if m >= cutoff]
    elif normalized_filter == "1y":
        cutoff = months_ago(current_bm, 12)
        filtered_months = [m for m in sorted_months if m >= cutoff]
    else:
        filtered_months = sorted_months

    current_metrics: dict = {}
    for month in filtered_months:
        data = all_monthly[month]
        for key in ("total", "total_color", "total_bw", "a4c", "a4bw", "a3c", "a3bw", "meter_c", "meter_bw", "cost"):
            current_metrics[key] = current_metrics.get(key, 0) + data.get(key, 0)
        previous = current_metrics.get("machines", [0, 0, 0])
        current_metrics["machines"] = [previous[i] + data["machines"][i] for i in range(3)]

    machine_names = [get_cfg(f"machine_name_{i}", SLOT_NAMES[i]) for i in range(3)]
    top_bm = filtered_months[-1] if filtered_months else current_bm

    return {
        "all_monthly": all_monthly,
        "filtered_months": filtered_months,
        "current_billing_month": current_bm,
        "metrics": current_metrics,
        "machine_names": machine_names,
        "machine_values": current_metrics.get("machines", [0, 0, 0]),
        "type_values": [
            current_metrics.get("a4c", 0),
            current_metrics.get("a4bw", 0),
            current_metrics.get("a3c", 0),
            current_metrics.get("a3bw", 0),
            current_metrics.get("meter_c", 0),
            current_metrics.get("meter_bw", 0),
        ],
        "top_users": get_month_top_users(top_bm),
        "source": "legacy_import",
        "quality": {"held_days": 0, "incomplete_days": 0},
    }


def _build_v5_overview_summary(filter_key: str, *, now: datetime) -> dict:
    """Build the visible V4.6-style Overview from frozen V5 ledger rows.

    Device Web Connection data is the billing source.  Prices, waste discount,
    billing period and categories come from each append-only ledger entry, so a
    later Settings change cannot rewrite an earlier Overview.
    """
    configured_by_slot = {
        device.slot: device for device in DeviceConfigRepository().list(enabled_only=False)
    }
    slots = report_slots()
    slot_indexes = {slot: index for index, slot in enumerate(slots)}
    records = load_usage_history(slots, granularity="monthly", today=now.date())
    all_monthly: dict[str, dict] = {}
    active_months: set[str] = set()

    for record in records:
        key = record.period_end.strftime("%Y-%m")
        if record.period_start <= now.date() <= record.period_end:
            active_months.add(key)
        entry = all_monthly.setdefault(
            key,
            {
                "total": 0.0,
                "total_color": 0.0,
                "total_bw": 0.0,
                "a4c": 0.0,
                "a4bw": 0.0,
                "a3c": 0.0,
                "a3bw": 0.0,
                "meter_c": 0.0,
                "meter_bw": 0.0,
                "cost": 0.0,
                "gross_cost": 0.0,
                "provisional_total": 0.0,
                "provisional_color": 0.0,
                "provisional_bw": 0.0,
                "provisional_cost": 0.0,
                "provisional_gross_cost": 0.0,
                "provisional_cost_available": True,
                "print_color": 0.0,
                "print_bw": 0.0,
                "copy_color": 0.0,
                "copy_bw": 0.0,
                "machines": [0.0 for _slot in slots],
                "provisional_machines": [0.0 for _slot in slots],
                "held_days": 0,
                "incomplete_days": 0,
            },
        )
        entry["total"] += record.total
        entry["total_color"] += record.a3_color + record.a4_color
        entry["total_bw"] += record.a3_bw + record.a4_bw
        entry["a4c"] += record.a4_color
        entry["a4bw"] += record.a4_bw
        entry["a3c"] += record.a3_color
        entry["a3bw"] += record.a3_bw
        entry["cost"] += record.net_cost
        entry["gross_cost"] += record.gross_cost
        entry["provisional_total"] += record.provisional_total
        entry["provisional_color"] += record.provisional_a3_color + record.provisional_a4_color
        entry["provisional_bw"] += record.provisional_a3_bw + record.provisional_a4_bw
        entry["provisional_cost"] += record.provisional_net_cost
        entry["provisional_gross_cost"] += record.provisional_gross_cost
        entry["provisional_cost_available"] = (
            entry["provisional_cost_available"] and record.provisional_cost_available
        )
        for key in (
            "print_color", "print_bw", "copy_color", "copy_bw",
            "print_a3_color", "print_a4_color", "print_a3_bw", "print_a4_bw",
            "copy_a3_color", "copy_a4_color", "copy_a3_bw", "copy_a4_bw",
        ):
            entry[key] = entry.get(key, 0.0) + float(getattr(record, key, 0.0) or 0.0)
        entry["print_available"] = entry.get("print_available", False) or bool(record.print_available)
        entry["copy_available"] = entry.get("copy_available", False) or bool(record.copy_available)
        entry["held_days"] += record.held_days
        entry["incomplete_days"] += record.incomplete_days
        index = slot_indexes.get(record.device_slot)
        if index is not None:
            entry["machines"][index] += record.total
            entry["provisional_machines"][index] += record.provisional_total
        entry["display_total"] = entry["total"] + entry["provisional_total"]
        entry["display_cost"] = entry["cost"] + entry["provisional_cost"]

    sorted_months = sorted(all_monthly)
    current_key = max(active_months, default=now.strftime("%Y-%m"))
    normalized_filter = "current" if filter_key == "month" else filter_key
    if normalized_filter == "day":
        filtered_months = [current_key] if current_key in all_monthly else []
    elif normalized_filter == "year":
        filtered_months = [key for key in sorted_months if key.startswith(f"{now.year}-")]
    elif normalized_filter == "current":
        # A billing-day change can leave two immutable frozen cycles active at
        # once.  Both are valid posted evidence and must remain visible.
        filtered_months = sorted(active_months)
        if not filtered_months and sorted_months:
            filtered_months = [sorted_months[-1]]
    elif normalized_filter == "3m":
        base = sorted_months[-1] if sorted_months else current_key
        cutoff = months_ago(base, 2)
        filtered_months = [key for key in sorted_months if key >= cutoff]
    elif normalized_filter == "1y":
        base = sorted_months[-1] if sorted_months else current_key
        cutoff = months_ago(base, 11)
        filtered_months = [key for key in sorted_months if key >= cutoff]
    else:
        filtered_months = sorted_months

    if normalized_filter == "day":
        selected_records = [
            record for record in load_usage_history(slots, granularity="daily", today=now.date())
            if record.period_start == now.date()
        ]
    elif normalized_filter == "year":
        selected_records = [
            record for record in load_usage_history(slots, granularity="yearly", today=now.date())
            if record.period_start <= now.date() <= record.period_end
        ]
    elif normalized_filter == "current" and active_months:
        selected_records = [
            record for record in records
            if record.period_start <= now.date() <= record.period_end
        ]
    else:
        selected_records = [
            record for record in records
            if record.period_end.strftime("%Y-%m") in filtered_months
        ]

    metrics = {
        "total": 0.0,
        "total_color": 0.0,
        "total_bw": 0.0,
        "a4c": 0.0,
        "a4bw": 0.0,
        "a3c": 0.0,
        "a3bw": 0.0,
        "meter_c": 0.0,
        "meter_bw": 0.0,
        "cost": 0.0,
        "gross_cost": 0.0,
        "provisional_total": 0.0,
        "provisional_color": 0.0,
        "provisional_bw": 0.0,
        "provisional_cost": 0.0,
        "provisional_gross_cost": 0.0,
        "provisional_scan": 0.0,
        "provisional_days": 0,
        "provisional_cost_available": True,
        "print_color": 0.0,
        "print_bw": 0.0,
        "copy_color": 0.0,
        "copy_bw": 0.0,
        "print_a3_color": 0.0,
        "print_a4_color": 0.0,
        "print_a3_bw": 0.0,
        "print_a4_bw": 0.0,
        "copy_a3_color": 0.0,
        "copy_a4_color": 0.0,
        "copy_a3_bw": 0.0,
        "copy_a4_bw": 0.0,
        "provisional_print_color": 0.0,
        "provisional_print_bw": 0.0,
        "provisional_copy_color": 0.0,
        "provisional_copy_bw": 0.0,
        "provisional_print_a3_color": 0.0,
        "provisional_print_a4_color": 0.0,
        "provisional_print_a3_bw": 0.0,
        "provisional_print_a4_bw": 0.0,
        "provisional_copy_a3_color": 0.0,
        "provisional_copy_a4_color": 0.0,
        "provisional_copy_a3_bw": 0.0,
        "provisional_copy_a4_bw": 0.0,
        "print_available": False,
        "copy_available": False,
        "machines": [0.0 for _slot in slots],
        "provisional_machines": [0.0 for _slot in slots],
        "held_days": 0,
        "incomplete_days": 0,
    }
    for record in selected_records:
        metrics["total"] += record.total
        metrics["total_color"] += record.a3_color + record.a4_color
        metrics["total_bw"] += record.a3_bw + record.a4_bw
        metrics["a4c"] += record.a4_color
        metrics["a4bw"] += record.a4_bw
        metrics["a3c"] += record.a3_color
        metrics["a3bw"] += record.a3_bw
        metrics["cost"] += record.net_cost
        metrics["gross_cost"] += record.gross_cost
        metrics["provisional_total"] += record.provisional_total
        metrics["provisional_color"] += record.provisional_a3_color + record.provisional_a4_color
        metrics["provisional_bw"] += record.provisional_a3_bw + record.provisional_a4_bw
        metrics["provisional_cost"] += record.provisional_net_cost
        metrics["provisional_gross_cost"] += record.provisional_gross_cost
        metrics["provisional_scan"] += record.provisional_scan
        metrics["provisional_days"] += record.provisional_days
        metrics["provisional_cost_available"] = (
            metrics["provisional_cost_available"] and record.provisional_cost_available
        )
        for key in (
            "print_color", "print_bw", "copy_color", "copy_bw",
            "print_a3_color", "print_a4_color", "print_a3_bw", "print_a4_bw",
            "copy_a3_color", "copy_a4_color", "copy_a3_bw", "copy_a4_bw",
            "provisional_print_color", "provisional_print_bw",
            "provisional_copy_color", "provisional_copy_bw",
            "provisional_print_a3_color", "provisional_print_a4_color",
            "provisional_print_a3_bw", "provisional_print_a4_bw",
            "provisional_copy_a3_color", "provisional_copy_a4_color",
            "provisional_copy_a3_bw", "provisional_copy_a4_bw",
        ):
            metrics[key] += float(getattr(record, key, 0.0) or 0.0)
        metrics["print_available"] = metrics["print_available"] or bool(record.print_available)
        metrics["copy_available"] = metrics["copy_available"] or bool(record.copy_available)
        metrics["held_days"] += record.held_days
        metrics["incomplete_days"] += record.incomplete_days
        index = slot_indexes.get(record.device_slot)
        if index is not None:
            metrics["machines"][index] += record.total
            metrics["provisional_machines"][index] += record.provisional_total
    metrics["display_total"] = metrics["total"] + metrics["provisional_total"]
    metrics["display_color"] = metrics["total_color"] + metrics["provisional_color"]
    metrics["display_bw"] = metrics["total_bw"] + metrics["provisional_bw"]
    metrics["display_cost"] = metrics["cost"] + metrics["provisional_cost"]
    for key in ("print_color", "print_bw", "copy_color", "copy_bw"):
        metrics[f"display_{key}"] = metrics[key] + metrics[f"provisional_{key}"]
    for key in (
        "print_a3_color", "print_a4_color", "print_a3_bw", "print_a4_bw",
        "copy_a3_color", "copy_a4_color", "copy_a3_bw", "copy_a4_bw",
    ):
        metrics[f"display_{key}"] = metrics[key] + metrics[f"provisional_{key}"]

    records_by_slot = {
        slot: [record for record in selected_records if record.device_slot == slot]
        for slot in slots
    }
    mixed_identity_slots = [
        slot
        for slot, slot_records in records_by_slot.items()
        if len({record.device_identity for record in slot_records}) > 1
    ]
    historical_identity_slots = [
        slot
        for slot, slot_records in records_by_slot.items()
        if any(record.device_identity != current_device_identity(slot) for record in slot_records)
    ]
    machine_names: list[str] = []
    for slot in slots:
        device = configured_by_slot.get(slot)
        slot_records = records_by_slot[slot]
        labels = sorted(
            {
                _frozen_device_label(record, fallback=f"เครื่อง {slot + 1}")
                for record in slot_records
            }
        )
        if len({record.device_identity for record in slot_records}) > 1:
            machine_names.append(
                f"เครื่อง {slot + 1} · หลายเครื่อง ({' / '.join(labels)})"
            )
        elif labels:
            machine_names.append(labels[0])
        else:
            machine_names.append(device.name if device is not None else f"เครื่อง {slot + 1}")

    selected_ranges = {
        (record.period_start, record.period_end) for record in selected_records
    }
    subject_totals: dict[tuple[str, str, str], list] = {}
    for subject in load_subject_history(slots, today=now.date()):
        if (subject.period_start, subject.period_end) not in selected_ranges:
            continue
        subject_name = subject.subject_name
        if (
            subject.device_slot in mixed_identity_slots
            or subject.device_slot in historical_identity_slots
        ):
            subject_name = (
                f"{subject.subject_name} · "
                f"{_frozen_device_label(subject, fallback=f'เครื่อง {subject.device_slot + 1}')}"
            )
        item = subject_totals.setdefault(
            (subject.device_identity, subject.subject_type, subject.subject_id),
            [subject_name, 0.0],
        )
        if (
            _subject_name_is_placeholder(subject.subject_id, item[0])
            and not _subject_name_is_placeholder(subject.subject_id, subject_name)
        ):
            item[0] = subject_name
        item[1] += subject.period_usage
    top_users = [
        (name, 0.0, 0.0, total)
        for name, total in sorted(subject_totals.values(), key=lambda item: item[1], reverse=True)[:5]
    ]

    device_summaries = []
    cache_store = DailyCacheStore()
    for device in configured_by_slot.values():
        if not device.enabled:
            continue
        slot_records = records_by_slot.get(device.slot, [])
        confirmed_total = sum(record.total for record in slot_records)
        provisional_total = sum(record.provisional_total for record in slot_records)
        confirmed_cost = sum(record.net_cost for record in slot_records)
        provisional_cost = sum(record.provisional_net_cost for record in slot_records)
        cost_available = all(
            record.provisional_cost_available
            for record in slot_records
            if record.provisional_days
        )
        held = sum(record.held_days for record in slot_records)
        incomplete = sum(record.incomplete_days for record in slot_records)
        cache_state = cache_store.load(device.slot, now.date()) or {}
        toner = cache_state.get("snmp_toner") if isinstance(cache_state, dict) else {}
        toner = toner if isinstance(toner, dict) else {}
        device_summaries.append(
            {
                "slot": device.slot,
                "name": device.name,
                "model": device.model,
                "host": device.host,
                "serial": device.serial,
                "toner": {key: toner.get(key) for key in ("C", "Y", "M", "K")},
                "status": _runtime_status(device, now=now),
                "last_checked_at": device.last_checked_at,
                "last_success_at": device.last_success_at,
                "last_error": device.last_error,
                "confirmed_total": confirmed_total,
                "provisional_total": provisional_total,
                "display_total": confirmed_total + provisional_total,
                "confirmed_cost": confirmed_cost,
                "provisional_cost": provisional_cost,
                "display_cost": confirmed_cost + provisional_cost,
                "provisional_cost_available": cost_available,
                "held_days": held,
                "incomplete_days": incomplete,
            }
        )
    device_summaries.sort(key=lambda item: item["slot"])
    status_counts = {
        key: sum(device["status"] == key for device in device_summaries)
        for key in ("online", "offline", "stale", "pending", "syncing")
    }
    last_sync_at = max(
        (
            str(device["last_success_at"])
            for device in device_summaries
            if device["last_success_at"]
        ),
        default="",
    )
    display_machine_values = [
        metrics["machines"][index] + metrics["provisional_machines"][index]
        for index in range(len(slots))
    ]

    return {
        "all_monthly": all_monthly,
        "filtered_months": filtered_months,
        "current_billing_month": current_key,
        "metrics": metrics,
        "machine_names": machine_names,
        "machine_values": display_machine_values,
        "confirmed_machine_values": metrics["machines"],
        "provisional_machine_values": metrics["provisional_machines"],
        "type_values": [
            metrics["a4c"],
            metrics["a4bw"],
            metrics["a3c"],
            metrics["a3bw"],
            metrics["meter_c"],
            metrics["meter_bw"],
        ],
        "top_users": top_users,
        "devices": device_summaries,
        "source": "billing_ledger",
        "quality": {
            "held_days": int(metrics["held_days"]),
            "incomplete_days": int(metrics["incomplete_days"]),
            "mixed_identity_slots": mixed_identity_slots,
            "historical_identity_slots": historical_identity_slots,
            "provisional_days": int(metrics["provisional_days"]),
            "provisional_cost_available": bool(metrics["provisional_cost_available"]),
            "last_sync_at": last_sync_at,
            "status_counts": status_counts,
        },
    }


def build_overview_summary(filter_key: str, *, now: datetime | None = None) -> dict:
    """Prepare Overview metrics without touching PyQt widgets."""
    current = now or datetime.now()
    if report_slots():
        return _build_v5_overview_summary(filter_key, now=current)
    legacy_filter = {
        "day": "current",
        "month": "current",
        "year": "1y",
    }.get(filter_key, filter_key)
    return _build_legacy_overview_summary(legacy_filter, now=current)
