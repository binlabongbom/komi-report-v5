from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime
from threading import RLock
from services.computer_names import local_computer_name


@dataclass(frozen=True)
class PipelineEvent:
    sequence: int
    at: str
    device_slot: int | None
    device_name: str
    host: str
    stage: str
    action: str
    target: str
    value: str
    detail: str
    status: str
    computer_name: str = ''
    reader_name: str = ''
    diagnostic: str = ''

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PipelineLogStore:
    """Thread-safe, bounded runtime trace for the meter pipeline.

    This is intentionally kept out of SQLite.  Durable state remains in the
    daily cache and daily rollup tables; this trace is for live observability.
    """

    def __init__(self, max_events: int = 5_000) -> None:
        self.max_events = max(100, int(max_events))
        self._events: deque[PipelineEvent] = deque(maxlen=self.max_events)
        self._sequence = 0
        self._lock = RLock()

    def append(
        self,
        *,
        stage: str,
        action: str,
        device_slot: int | None = None,
        device_name: str = "",
        host: str = "",
        target: str = "",
        value: object = "",
        detail: str = "",
        status: str = "info",
        at: datetime | None = None,
        reader_name: str | None = None,
    ) -> PipelineEvent:
        with self._lock:
            self._sequence += 1
            from services.support_diagnostics import diagnostic_report, safe_text
            computer = local_computer_name()
            timestamp = (at or datetime.now().astimezone()).isoformat(timespec="seconds")
            diagnostic = ''
            if isinstance(value, BaseException):
                diagnostic = diagnostic_report(value, stage=stage + ' / ' + action, target=target or host,
                                               device=device_name, computer=computer, at=timestamp)
            elif 'KOMI Diagnostic v1\n' in str(value):
                diagnostic = safe_text(value)
            event = PipelineEvent(
                sequence=self._sequence,
                at=timestamp,
                device_slot=device_slot,
                device_name=device_name,
                host=host,
                stage=stage.upper(),
                action=action,
                target=target,
                value=safe_text(value),
                detail=safe_text(detail),
                status=status,
                computer_name=computer,
                reader_name=(local_computer_name() if stage.upper() in {'SNMP', 'WEB'} else '')
                    if reader_name is None else reader_name,
                diagnostic=diagnostic,
            )
            self._events.append(event)
            return event

    def snapshot(self, *, newest_first: bool = True, limit: int | None = None) -> list[PipelineEvent]:
        with self._lock:
            events = list(self._events)
        if newest_first:
            events.reverse()
        return events[:limit] if limit is not None else events

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


pipeline_log = PipelineLogStore()
