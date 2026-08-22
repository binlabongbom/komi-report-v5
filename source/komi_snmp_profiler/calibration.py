from __future__ import annotations

from .models import CounterDelta, DeviceSnapshot


def compare_snapshots(
    before: DeviceSnapshot,
    after: DeviceSnapshot,
    expected_delta: int | None = None,
) -> list[CounterDelta]:
    if before.host != after.host:
        raise ValueError("Snapshot ก่อนและหลังต้องมาจากเครื่องเดียวกัน")

    previous = {item.oid: item for item in before.values if item.numeric_value is not None}
    deltas: list[CounterDelta] = []
    for current in after.values:
        old = previous.get(current.oid)
        if old is None or current.numeric_value is None or old.numeric_value is None:
            continue
        delta = current.numeric_value - old.numeric_value
        if delta <= 0:
            continue
        deltas.append(
            CounterDelta(
                oid=current.oid,
                canonical_field=current.canonical_field,
                label=current.label,
                before=old.numeric_value,
                after=current.numeric_value,
                delta=delta,
                confidence=current.confidence,
                matches_expected=expected_delta is not None and delta == expected_delta,
            )
        )
    previous_web = {item.canonical_field: item for item in before.web_counters}
    for current in after.web_counters:
        old = previous_web.get(current.canonical_field)
        if old is None:
            continue
        delta = current.count - old.count
        if delta <= 0:
            continue
        deltas.append(
            CounterDelta(
                oid=f"WEB:{current.source_path}",
                canonical_field=current.canonical_field,
                label=current.label,
                before=old.count,
                after=current.count,
                delta=delta,
                confidence=current.confidence,
                matches_expected=expected_delta is not None and delta == expected_delta,
            )
        )
    return sorted(deltas, key=lambda item: (-item.delta, item.oid))
