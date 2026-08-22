from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from komi_snmp_profiler.models import MeterReading, WebCounterValue


@dataclass(frozen=True)
class RuntimeCounterRow:
    canonical_field: str
    label: str
    count: int | float
    source_path: str
    subject_type: str | None = None
    subject_id: str | None = None
    subject_name: str | None = None

    @classmethod
    def from_counter(cls, counter: WebCounterValue) -> RuntimeCounterRow:
        return cls(
            canonical_field=counter.canonical_field,
            label=counter.label,
            count=counter.count,
            source_path=counter.source_path,
            subject_type=counter.subject_type,
            subject_id=counter.subject_id,
            subject_name=counter.subject_name,
        )


@dataclass(frozen=True)
class RuntimeDeviceSnapshot:
    device_slot: int
    collected_at: str
    source: str
    web_rows: tuple[RuntimeCounterRow, ...]
    subject_rows: tuple[RuntimeCounterRow, ...]


class RuntimeSnapshotStore:
    """Latest Web reading per device; intentionally process-memory only."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[int, RuntimeDeviceSnapshot] = {}

    def update(self, slot: int, reading: MeterReading) -> RuntimeDeviceSnapshot:
        rows = tuple(RuntimeCounterRow.from_counter(counter) for counter in reading.counters)
        snapshot = RuntimeDeviceSnapshot(
            device_slot=slot,
            collected_at=reading.collected_at,
            source=reading.source,
            web_rows=tuple(row for row in rows if row.subject_type is None),
            subject_rows=tuple(row for row in rows if row.subject_type is not None),
        )
        with self._lock:
            self._snapshots[slot] = snapshot
        return snapshot

    def get(self, slot: int) -> RuntimeDeviceSnapshot | None:
        with self._lock:
            return self._snapshots.get(slot)

    def clear(self, slot: int | None = None) -> None:
        with self._lock:
            if slot is None:
                self._snapshots.clear()
            else:
                self._snapshots.pop(slot, None)


runtime_snapshots = RuntimeSnapshotStore()
