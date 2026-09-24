"""Shared daily user cost allocation for screen reports and Excel."""
from collections import defaultdict

from services.report_operation_breakdown import breakdown_from_raw_records

OPERATION_COST_FIELDS = tuple(
    (f'{operation}_{suffix}', suffix if suffix != 'other' else '')
    for operation in ('print', 'copy')
    for suffix in ('a4_color', 'a4_bw', 'a3_color', 'a3_bw', 'other')
)


def device_daily_evidence(raw_records, costs):
    grouped = defaultdict(list)
    for record in raw_records:
        if record.is_subject:
            continue
        identities = {f'slot:{record.device_slot}'}
        if record.device_serial_snapshot:
            identities.add('serial:' + record.device_serial_snapshot)
        for identity in identities:
            grouped[(record.record_date, (record.device_slot, identity))].append(record)
    breakdowns = {key: breakdown_from_raw_records(rows) for key, rows in grouped.items()}
    prices = {}
    for cost in costs:
        prices.setdefault((cost.record_date, (cost.device_slot, cost.device_identity)), cost)
    return breakdowns, prices


def subject_costs(subject_records, device_key, evidence, *, checkpoint=None):
    """Allocate each day's category cost using that day's device denominator."""
    by_day = defaultdict(list)
    for record in subject_records:
        by_day[record.record_date].append(record)
    device_days, costs = evidence
    amounts, seen, missing = defaultdict(float), set(), set()
    for day, rows in by_day.items():
        if checkpoint is not None:
            checkpoint()
        subject = breakdown_from_raw_records(rows)
        device = device_days.get((day, device_key))
        daily_cost = costs.get((day, device_key))
        for field, category in OPERATION_COST_FIELDS:
            pages = float(getattr(subject, field) or 0.0)
            if not category or pages <= 0:
                continue
            seen.add(field)
            suffix = field.split('_', 1)[1]
            denominator = (getattr(device, 'print_' + suffix, 0.0) +
                           getattr(device, 'copy_' + suffix, 0.0)) if device else 0.0
            if (daily_cost is None or not daily_cost.available or denominator <= 0
                    or abs(getattr(daily_cost, 'unallocated', 0.0)) > 0.001):
                missing.add(field)
            else:
                amounts[field] += float(getattr(daily_cost, category) or 0.0) * pages / denominator
    return {field: round(amounts[field], 2) if field in seen and field not in missing else None
            for field, _category in OPERATION_COST_FIELDS}


def subject_total_cost(breakdown, amounts):
    values = []
    for field, category in OPERATION_COST_FIELDS:
        if not category or float(getattr(breakdown, field) or 0.0) <= 0:
            continue
        if amounts[field] is None:
            return None
        values.append(amounts[field])
    return round(sum(values), 2) if values else None
