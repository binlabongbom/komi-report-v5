from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass
class DevicePollState:
    last_snmp_total: int | None = None
    last_web_at: datetime | None = None
    pending_detail: bool = False
    web_failures: int = 0
    next_web_retry_at: datetime | None = None
    offline: bool = False
    last_scheduled_web_at: datetime | None = None
    scheduled_clock_initialized: bool = False


@dataclass(frozen=True)
class PollDecision:
    request_web: bool
    status: str
    reason: str


@dataclass(frozen=True)
class ScheduleWindow:
    """A user-configured collection policy for a time range and weekday set.

    ``snmp_interval`` is optional only for schedules persisted by older V5
    builds.  New rows always define both SNMP and Web/RAM cadence.
    """

    start: time
    end: time
    web_interval: timedelta
    label: str = "ช่วงกำหนดเอง"
    snmp_interval: timedelta | None = None
    weekdays: frozenset[int] = frozenset(range(7))

    def contains(self, clock: time) -> bool:
        # Rows meet at their boundary: 08:00–08:30 owns 08:00, while the
        # preceding 00:00–08:00 row ends immediately before it.  23:59 is a
        # practical inclusive end-of-day value for the final row.
        if self.end == time(23, 59):
            return self.start <= clock <= self.end
        return self.start <= clock < self.end

    def applies(self, now: datetime) -> bool:
        local = now.timetz().replace(tzinfo=None)
        return now.weekday() in self.weekdays and self.contains(local)


@dataclass(frozen=True)
class PollingPolicy:
    web_interval: timedelta = timedelta(minutes=15)
    peak_web_interval: timedelta = timedelta(minutes=5)
    retry_interval: timedelta = timedelta(minutes=5)
    max_web_failures: int = 5
    offline_web_probe: timedelta = timedelta(hours=1)
    work_start: time = time(8, 0)
    work_end: time = time(17, 0)
    peak_margin: timedelta = timedelta(minutes=30)
    # ``None`` retains the V5 legacy Peak windows.  An empty tuple is an
    # intentional user schedule with no special intervals (Normal all day).
    schedule_windows: tuple[ScheduleWindow, ...] | None = None

    def window_at(self, now: datetime) -> ScheduleWindow | None:
        """Return the user-defined interval that owns local time and weekday."""
        for window in self.schedule_windows or ():
            if window.applies(now):
                return window
        return None

    def snmp_interval_at(self, now: datetime, fallback: timedelta) -> timedelta | None:
        window = self.window_at(now)
        if window is not None:
            return window.snmp_interval or fallback
        # A configured table is authoritative: gaps and unselected weekdays
        # deliberately do not generate network work.
        return fallback if self.schedule_windows is None else None

    def web_interval_at(self, now: datetime) -> timedelta:
        window = self.window_at(now)
        if window is not None:
            return window.web_interval
        return self.peak_web_interval if self.is_peak(now) else self.web_interval

    def is_peak(self, now: datetime) -> bool:
        if self.schedule_windows is not None:
            return self.window_at(now) is not None
        local = now.timetz().replace(tzinfo=None)
        start = datetime.combine(now.date(), self.work_start)
        end = datetime.combine(now.date(), self.work_end)
        current = datetime.combine(now.date(), local)
        return (start - self.peak_margin <= current <= start + self.peak_margin) or (
            end - self.peak_margin <= current <= end + self.peak_margin
        )


class PollingStateMachine:
    def __init__(self, policy: PollingPolicy | None = None) -> None:
        self.policy = policy or PollingPolicy()

    def scheduled_web_due(self, state: DevicePollState, now: datetime) -> bool:
        anchor = state.last_scheduled_web_at if state.scheduled_clock_initialized else state.last_web_at
        return anchor is None or now - anchor >= self.policy.web_interval_at(now)

    def snmp_success(self, state: DevicePollState, total: int, now: datetime) -> PollDecision:
        previous = state.last_snmp_total
        state.last_snmp_total = max(0, int(total))
        state.web_failures = 0
        state.next_web_retry_at = None
        state.offline = False
        changed = previous is None or total != previous
        if changed:
            state.pending_detail = True
        window = self.policy.window_at(now)
        periodic_web_due = (
            window is not None
            and window.snmp_interval is not None
            and self.scheduled_web_due(state, now)
        )
        if not state.pending_detail and not periodic_web_due:
            return PollDecision(False, "online", "Total Meter ไม่เปลี่ยน")
        if self.scheduled_web_due(state, now):
            reason = (
                "ถึงรอบ Web/RAM ตาม Schedule"
                if periodic_web_due and not state.pending_detail
                else "Total Meter เปลี่ยนและพ้น Web throttle"
            )
            return PollDecision(True, "online", reason)
        return PollDecision(False, "online", "รอ Web throttle")

    def snmp_failure(self, state: DevicePollState, now: datetime) -> PollDecision:
        if state.offline:
            due = state.next_web_retry_at is None or now >= state.next_web_retry_at
            return PollDecision(due, "offline", "Offline hourly Web probe" if due else "Offline; รอ probe")
        due = state.next_web_retry_at is None or now >= state.next_web_retry_at
        return PollDecision(due, "checking", "SNMP ไม่ตอบ; ใช้ Web fallback" if due else "รอ Web retry")

    def web_success(self, state: DevicePollState, now: datetime, *, scheduled: bool = True,
                    scheduled_at: datetime | None = None) -> None:
        if not state.scheduled_clock_initialized:
            state.last_scheduled_web_at = state.last_web_at
            state.scheduled_clock_initialized = True
        if scheduled:
            state.last_scheduled_web_at = scheduled_at or now
        state.last_web_at = now
        state.pending_detail = False
        state.web_failures = 0
        state.next_web_retry_at = None
        state.offline = False

    def web_failure(self, state: DevicePollState, now: datetime) -> PollDecision:
        state.web_failures += 1
        if state.web_failures >= self.policy.max_web_failures:
            state.offline = True
            state.next_web_retry_at = now + self.policy.offline_web_probe
            return PollDecision(False, "offline", "Web fallback ไม่สำเร็จครบ 5 ครั้ง")
        state.next_web_retry_at = now + self.policy.retry_interval
        return PollDecision(False, "checking", f"Web fallback {state.web_failures}/5; ลองใหม่ใน 5 นาที")
