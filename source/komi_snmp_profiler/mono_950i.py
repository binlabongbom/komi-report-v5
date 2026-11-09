"""Evidence-gated aliases for the 950i monochrome Web Connection user Total.

The approved UCR001 template renders TotalCounterList.Counter Type=Bw as the
user Total when MFP.isColor is False. Paper, document, and print-page counters
are separate observations, not components to sum. Missing values stay unknown.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .models import Confidence, WebCounterValue

TEMPLATE_PATH = "spa_003_001_UCR001.tmpl.html"
APPROVED_TEMPLATE_SHA256 = "3e1c1e1b442bb8ce77b3cf74d97d6fdcda97fb20b6da985958a80084a0cbf30e"
SCHEMA_VERSION = "komi.meter.reading.950i-monochrome.v1"


@dataclass(frozen=True)
class Mono950iMappingResult:
    counters: tuple[WebCounterValue, ...]
    changed: bool
    warnings: tuple[str, ...] = ()


def is_950i_model(model: str) -> bool:
    """Match only the monochrome model, with optional known vendor prefixes."""
    return isinstance(model, str) and re.fullmatch(
        r"(?:(?:KM|KONICA\s+MINOLTA)\s+)?(?:bizhub\s*)?950i",
        model.strip(), re.IGNORECASE,
    ) is not None


def _valid_count(value: object) -> bool:
    if type(value) not in (int, float) or value < 0:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        # Downstream UI/history use finite numeric values. Preserve an extreme
        # raw observation but do not promote it into a usable Total alias.
        return False


def map_950i_user_totals(
    counters: Iterable[WebCounterValue], *, model: str,
    is_color: object, template_sha256: str,
) -> Mono950iMappingResult:
    """Return immutable counters/changed/warnings; preserve original rows verbatim.

    Append at most one mapped Total per explicit user ID. Model, monochrome
    flag and the exact reviewed template hash must all match. Existing totals
    (including invalid totals) are never overwritten. Ambiguous or missing BW
    observations produce no alias. Calling this twice never creates duplicates.
    """
    original = tuple(counters)
    failures = []
    if not is_950i_model(model):
        failures.append("950i Total mapping skipped: unrecognized monochrome model")
    if not (is_color is False or (type(is_color) is str and is_color == "False")):
        failures.append("950i Total mapping skipped: monochrome flag is not explicit False")
    if template_sha256 != APPROVED_TEMPLATE_SHA256:
        failures.append("950i Total mapping skipped: template evidence does not match")
    if failures:
        return Mono950iMappingResult(original, False, tuple(failures))

    users: dict[str, list[WebCounterValue]] = {}
    warnings: list[str] = []
    for counter in original:
        if counter.subject_type != "user":
            continue
        if not isinstance(counter.subject_id, str) or not counter.subject_id.strip():
            if counter.canonical_field == "counter.user.total.bw":
                warnings.append("950i user Total unknown: BW observation has no explicit user ID")
            continue
        users.setdefault(counter.subject_id, []).append(counter)

    aliases = []
    for subject_id, rows in users.items():
        if any(row.canonical_field == "counter.user.total.total" for row in rows):
            continue
        bw = [row for row in rows if row.canonical_field == "counter.user.total.bw"]
        expected_source = (
            f"MFP.AuthCounterList.AuthCounter[{subject_id}]"
            ".TotalCounterList.Counter[Type=Bw]"
        )
        if not bw:
            warnings.append("950i user Total unknown: explicit BW observation is missing")
            continue
        if any(row.source_path != expected_source for row in bw):
            warnings.append("950i user Total unknown: BW source does not match explicit user ID")
            continue
        if any(not _valid_count(row.count) for row in bw):
            warnings.append("950i user Total unknown: invalid BW count")
            continue
        first = bw[0]
        if any(row.count != first.count or row.subject_name != first.subject_name for row in bw[1:]):
            warnings.append("950i user Total unknown: conflicting BW observations")
            continue
        aliases.append(replace(
            first, canonical_field="counter.user.total.total",
            label="Total: Total (950i monochrome, mapped from explicit BW)",
            confidence=Confidence.MAPPED,
        ))
    return Mono950iMappingResult(original + tuple(aliases), bool(aliases), tuple(warnings))
