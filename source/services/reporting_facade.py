"""Read-only application boundary shared by Desktop and HTTP presentation layers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from services.monthly_history import HistoryGranularity, load_usage_history
from services.report_scope import report_slots
from services.subject_history import load_subject_history


@dataclass(frozen=True)
class ReportReadService:
    """Expose report data without coupling callers to SQLite module functions."""

    usage_loader: Callable[..., Sequence[Any]] = load_usage_history
    subject_loader: Callable[..., Sequence[Any]] = load_subject_history
    slots_loader: Callable[[], list[int]] = report_slots

    def slots(self) -> list[int]:
        return self.slots_loader()

    def usage(self, *, granularity: HistoryGranularity = "monthly") -> Sequence[Any]:
        return self.usage_loader(self.slots(), granularity=granularity)

    def subjects(
        self,
        *,
        period_start: date | None = None,
        period_end: date | None = None,
    ) -> Sequence[Any]:
        if period_start is None or period_end is None:
            return self.subject_loader(self.slots())
        return self.subject_loader(
            self.slots(),
            period_start=period_start,
            period_end=period_end,
        )
