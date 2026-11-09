"""Display observed identities without manufacturing missing user totals.

This presentation-only projection never writes history or changes counters.
BW, paper, document and physical-print meters may overlap and are not aliases
for an explicit cumulative Total.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from komi_snmp_profiler.subject_identity import prefer_subject_name
from services.runtime_snapshots import RuntimeCounterRow


@dataclass(frozen=True)
class SubjectPreviewRow:
    subject_type: str
    subject_id: str
    subject_name: str
    total: int | float | None
    total_state: str
    counters: tuple[RuntimeCounterRow, ...]


def build_subject_preview_rows(rows: tuple[RuntimeCounterRow, ...]) -> tuple[SubjectPreviewRow, ...]:
    grouped: dict[tuple[str, str], list[RuntimeCounterRow]] = {}
    for index, row in enumerate(rows):
        kind = str(row.subject_type or "").strip().lower()
        if kind not in {"user", "account", "track"}:
            continue
        sid = str(row.subject_id or "").strip()
        name = str(row.subject_name or "").strip()
        # Equal names never merge different IDs. With no identity at all,
        # keep the observation separate rather than merging unknown accounts.
        identity = f"id:{sid}" if sid else (f"name:{name}" if name else f"unknown:{index}")
        grouped.setdefault((kind, identity), []).append(row)

    result = []
    for (kind, _identity), observations in grouped.items():
        sid = str(observations[0].subject_id or "").strip()
        name = ""
        unique: dict[RuntimeCounterRow, None] = {}
        for row in observations:
            name = prefer_subject_name(sid, name, row.subject_name)
            unique.setdefault(row, None)
        counters = tuple(unique)
        total_rows = [row for row in counters if row.canonical_field == f"counter.{kind}.total.total"]
        valid = [row.count for row in total_rows if isinstance(row.count, (int, float))
                 and not isinstance(row.count, bool) and isfinite(row.count) and row.count >= 0]
        values = set(valid)
        if not total_rows:
            state, total = "missing", None
        elif len(valid) != len(total_rows):
            state, total = "invalid", None
        elif len(values) != 1:
            state, total = "conflicting", None
        else:
            state, total = "available", valid[0]
        result.append(SubjectPreviewRow(kind, sid, name or sid or "Unknown", total, state, counters))
    return tuple(result)
