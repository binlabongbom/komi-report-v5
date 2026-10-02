"""Deterministic usage intervals from immutable Web evidence in one meter epoch.

An epoch must be supplied by the caller after slot/baseline review. This module
does not infer resets, membership, price approval or monetary ledger postings.
Calendar dates describe an allocation rule; they are not invented read events.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from decimal import Decimal
from fractions import Fraction
import hashlib
import json

from services.billing_periods import billing_month_range
from services.web_observations import validate_event


@dataclass(frozen=True)
class CounterIdentity:
    field: str
    subject_type: str | None = None
    subject_id: str | None = None


@dataclass(frozen=True)
class CounterPoint:
    at: datetime
    value: Fraction
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class UsageInterval:
    start: CounterPoint
    end: CounterPoint
    amount: Fraction
    allocation_day: date
    empty_days: tuple[date, ...]
    holds: tuple[str, ...]

    @property
    def estimated_per_day(self):
        return self.amount / len(self.empty_days) if self.empty_days else None

    @property
    def remark(self):
        if not self.empty_days:
            return ""
        return (
            f"ยอดสะสมช่วงขาดการอ่าน: {self.start.at:%d/%m/%Y %H:%M}–{self.end.at:%d/%m/%Y %H:%M} "
            f"ลงวันที่ {self.allocation_day:%d/%m/%Y} ก่อนกลับมาอ่านได้ "
            "ไม่ใช่ยอดที่ยืนยันว่าเกิดเฉพาะวันนั้น; กราฟเป็นค่าเฉลี่ยประมาณการของวันที่ไม่มีข้อมูล Web"
        )


@dataclass(frozen=True)
class DailyUsagePoint:
    day: date
    observed_interval_usage: Fraction
    estimated_usage: Fraction
    estimated: bool
    remarks: tuple[str, ...]

    @property
    def total(self):
        return self.observed_interval_usage + self.estimated_usage


@dataclass(frozen=True)
class CounterProjection:
    epoch_id: str
    revision: str
    points: tuple[CounterPoint, ...]
    intervals: tuple[UsageInterval, ...]
    issues: tuple[str, ...]

    @property
    def maximum(self):
        return max((point.value for point in self.points), default=None)

    @property
    def total_usage(self):
        return sum((interval.amount for interval in self.intervals), Fraction())

    def daily_graph(self):
        """Replace gap allocation bars with estimates; never append both."""
        buckets = {}
        for interval in self.intervals:
            days = interval.empty_days or (interval.allocation_day,)
            amount = interval.amount / len(days)
            for day in days:
                row = buckets.setdefault(day, [Fraction(), Fraction(), False, set()])
                row[1 if interval.empty_days else 0] += amount
                row[2] |= bool(interval.empty_days)
                if interval.remark:
                    row[3].add(interval.remark)
        return tuple(DailyUsagePoint(day, row[0], row[1], row[2], tuple(sorted(row[3])))
                     for day, row in sorted(buckets.items()))


def project_counter(events, *, slot: int, serial: str, epoch_id: str,
                    counter: CounterIdentity, calendar_timezone: tzinfo,
                    billing_day: int = 31, price_change_dates=(), reviewed_epoch=None):
    """Project one reviewed serial/counter epoch, independent of arrival order.

    Current value is the maximum, never a sum or last-arrival value. Decreases
    remain evidence and block automatic billing; they cannot establish a new
    baseline. The requested counter must be cumulative (counter.* namespace).
    Names/source paths may change without changing a subject's stable identity.
    """
    if (type(slot) is not int or slot not in range(3) or not serial or not epoch_id
            or not isinstance(calendar_timezone, tzinfo)
            or not counter.field.startswith("counter.")
            or type(billing_day) is not int or not 1 <= billing_day <= 31):
        raise ValueError("A cumulative counter, calendar and reviewed meter epoch are required")
    changes = tuple(sorted(set(price_change_dates)))
    reset_boundary = None
    if reviewed_epoch is not None:
        from services.slot_meter_continuity import validate_epoch
        definition = validate_epoch(reviewed_epoch)
        anchor = definition["baseline_event"]
        if (reviewed_epoch["id"], anchor["payload"]["slot"], anchor["payload"]["serial"]) != (epoch_id, slot, serial):
            raise ValueError("Reviewed epoch does not match this projection")
        if definition["operation"] == "reset":
            reset_boundary = (anchor["id"], definition["parent"])
    if any(type(day) is not date for day in changes):
        raise ValueError("Invalid price effective date")
    unique, jobs, web_days, by_time, schemas = {}, {}, set(), {}, set()
    issues = set()
    for event in events:
        validate_event(event)
        p = event["payload"]
        if (p["slot"], p["serial"]) != (slot, serial):
            raise ValueError("Cannot combine different slots or physical printers")
        declared = p.get("meter_epoch_id")
        if declared is not None and declared != epoch_id and (event["id"], declared) != reset_boundary:
            raise ValueError("Cannot combine different reviewed meter epochs")
        if event["id"] in unique:
            continue
        job = p["origin"], p["read_id"]
        if job in jobs and jobs[job] != event["id"]:
            raise ValueError("Conflicting evidence for a read job")
        jobs[job] = event["id"]
        unique[event["id"]] = event
        stamp = datetime.fromisoformat(p["observed_at"]).astimezone(calendar_timezone)
        web_days.add(stamp.date())
        values = {Fraction(Decimal(str(c["count"]))) for c in p["reading"]["counters"]
                  if (c["canonical_field"], c["subject_type"], c["subject_id"])
                  == (counter.field, counter.subject_type, counter.subject_id)}
        if len(values) > 1:
            raise ValueError("One Web result contains conflicting values for the selected counter")
        if not values:
            continue
        schemas.add(p["reading"]["schema_version"])
        value = values.pop()
        group = by_time.setdefault(stamp, [])
        group.append((value, event["id"]))
    if len(schemas) > 1:
        issues.add("normalization_schema_changed")
    points = tuple(CounterPoint(at, max(value for value, _ in group), tuple(sorted(eid for _, eid in group)))
                   for at, group in sorted(by_time.items()))
    if any(len({value for value, _ in group}) > 1 for group in by_time.values()):
        issues.add("same_time_counter_conflict")
    revision_data = {"epoch": epoch_id, "slot": slot, "serial": serial,
                     "counter": (counter.field, counter.subject_type, counter.subject_id),
                     "events": sorted(unique), "calendar_points": [p.at.isoformat() for p in points],
                     "billing_day": billing_day, "price_dates": [d.isoformat() for d in changes]}
    return project_points(points, epoch_id=epoch_id, web_days=web_days, issues=issues,
        billing_day=billing_day, price_change_dates=changes, revision_data=revision_data)


def project_points(points, *, epoch_id, web_days, issues, billing_day, price_change_dates, revision_data, opening_high=None):
    """Internal reducer for validated journal points and their compact daily index.

    Points must be sorted, unique by timestamp and carry original evidence IDs.
    Only the journal/index adapters may call this; network input uses validate_event.
    """
    issues = set(issues)
    changes = price_change_dates
    intervals = []
    high = points[0].value if points else Fraction()
    if opening_high is not None:
        high = max(high, opening_high)
    counter_review = False
    for left, right in zip(points, points[1:]):
        if right.value < high:
            counter_review = True
            issues.add("lower_counter_or_clock_conflict")
        amount = max(Fraction(), right.value - high)
        high = max(high, right.value)
        empty_days = tuple(left.at.date() + timedelta(days=offset)
                           for offset in range(1, (right.at.date() - left.at.date()).days)
                           if left.at.date() + timedelta(days=offset) not in web_days)
        holds = set()
        if counter_review:
            holds.add("counter_baseline_review_required")
        if "normalization_schema_changed" in issues:
            holds.add("normalization_schema_changed")
        if "same_time_counter_conflict" in issues:
            holds.add("same_time_counter_conflict")
        # Positive usage spanning a boundary cannot be assigned to either side.
        # An unchanged counter has nothing to allocate and must not hold later
        # usage that is fully observed under the new price or billing period.
        if amount > 0 and billing_month_range(left.at.date(), billing_day) != billing_month_range(right.at.date(), billing_day):
            holds.add("interval_crosses_billing_period")
        if amount > 0 and any(left.at.date() < day <= right.at.date() for day in changes):
            holds.add("interval_crosses_price_change")
        middle_days = (right.at.date() - left.at.date()).days - 1
        if middle_days > len(empty_days):
            holds.add("selected_counter_missing_on_observed_days")
        allocation = right.at.date() - timedelta(days=1) if empty_days else right.at.date()
        intervals.append(UsageInterval(left, right, amount, allocation, empty_days, tuple(sorted(holds))))
    revision = hashlib.sha256(json.dumps(revision_data, sort_keys=True).encode()).hexdigest()
    return CounterProjection(epoch_id, revision, points, tuple(intervals), tuple(sorted(issues)))
