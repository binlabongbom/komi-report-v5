from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    serial: str = ''
    epoch_id: str = ''
    event_id: str = ''


class RuntimeSnapshotStore:
    """Latest Web reading per device; intentionally process-memory only."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._snapshots: dict[int, RuntimeDeviceSnapshot] = {}

    def update(self, slot: int, reading: MeterReading, *, serial='', epoch_id='', event_id='',
               preserve_newer=False) -> RuntimeDeviceSnapshot:
        rows = tuple(RuntimeCounterRow.from_counter(counter) for counter in reading.counters)
        snapshot = RuntimeDeviceSnapshot(
            device_slot=slot,
            collected_at=reading.collected_at,
            source=reading.source,
            web_rows=tuple(row for row in rows if row.subject_type is None),
            subject_rows=tuple(row for row in rows if row.subject_type is not None),
            serial=serial, epoch_id=epoch_id or '', event_id=event_id,
        )
        with self._lock:
            previous = self._snapshots.get(slot)
            if preserve_newer and previous and (previous.serial, previous.epoch_id) == (serial, epoch_id or ''):
                old = {(row.canonical_field, row.subject_type, row.subject_id): row.count
                       for row in previous.web_rows or previous.subject_rows}
                new = {(row.canonical_field, row.subject_type, row.subject_id): row.count
                       for row in snapshot.web_rows or snapshot.subject_rows}
                if (any(new[k] < old[k] for k in old.keys() & new.keys()) or
                        (old == new and datetime.fromisoformat(snapshot.collected_at) < datetime.fromisoformat(previous.collected_at))):
                    return previous
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
