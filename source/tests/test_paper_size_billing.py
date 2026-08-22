from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from database import _open, set_cfg
from komi_snmp_profiler.models import (
    Confidence,
    MeterReading,
    WebAuthState,
    WebCounterValue,
)
from services.daily_cache import DailyCacheStore
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import (
    CostCategory,
    PriceList,
    PricingRepository,
    default_cost_category,
)
from services.reconciliation import ReconciliationReport
from services.usage import default_usage_groups


@pytest.mark.parametrize(
    ("raw_key", "label", "expected"),
    (
        ("counter.paper.full_color.legal", "", CostCategory.A3_COLOR),
        ("counter.paper.black.legal_r", "", CostCategory.A3_BW),
        ("counter.paper.full_color.folio", "", CostCategory.A3_COLOR),
        ("counter.paper.black.folio-r", "", CostCategory.A3_BW),
        ("counter.paper.full_color.unknown", "Paper size: Legal", CostCategory.A3_COLOR),
        ("counter.paper.black.unknown", "Paper size: Folio", CostCategory.A3_BW),
    ),
)
def test_legal_and_folio_are_approved_as_a3(
    raw_key: str,
    label: str,
    expected: CostCategory,
) -> None:
    assert default_cost_category(raw_key, label) is expected


@pytest.mark.parametrize(
    "raw_key",
    (
        "counter.paper.full_color.letter",
        "counter.paper.full_color.ledger",
        "counter.paper.full_color.statement",
        "counter.paper.full_color.envelope",
        "counter.paper.full_color.custom",
        "counter.paper.full_color.other",
        "counter.paper.full_color.a9",
        "counter.paper.full_color.b9",
        "counter.paper.full_color.illegal",
        "counter.paper.full_color.portfolio",
        "counter.paper.full_color.legalish",
    ),
)
def test_unapproved_or_ambiguous_paper_size_remains_no_charge(raw_key: str) -> None:
    assert default_cost_category(raw_key) is CostCategory.NO_CHARGE


def test_scan_remains_no_charge_even_when_label_contains_approved_size() -> None:
    assert (
        default_cost_category(
            "counter.scan_fax.scan_total",
            label="Scanned Legal paper",
            category="Full Color",
        )
        is CostCategory.NO_CHARGE
    )


def test_default_usage_groups_show_legal_and_folio_as_other_without_mutating_raw_keys() -> None:
    counters = {
        "counter.print.full_color.legal": 2.0,
        "counter.print.full_color.folio": 3.0,
        "counter.copy.black.folio": 4.0,
    }

    groups = default_usage_groups(counters)

    assert groups["Other size (Print)"] == 5.0
    assert groups["Other size (Copy)"] == 4.0
    assert set(counters) == {
        "counter.print.full_color.legal",
        "counter.print.full_color.folio",
        "counter.copy.black.folio",
    }


_COUNTER_SPECS = (
    ("counter.paper.full_color.legal", "Legal Full Color", "Paper size full color"),
    ("counter.paper.black.legal", "Legal Black", "Paper size black"),
    ("counter.paper.full_color.folio", "Folio Full Color", "Paper size full color"),
    ("counter.paper.black.folio", "Folio Black", "Paper size black"),
    ("counter.paper.full_color.letter", "Letter Full Color", "Paper size full color"),
    ("counter.scan_fax.scan_total", "Scanned pages", "Scan/Fax"),
)


def _reading(values: tuple[int, ...], at: datetime) -> MeterReading:
    return MeterReading(
        host="192.0.2.10",
        collected_at=at.isoformat(),
        counters=tuple(
            WebCounterValue(
                canonical_field=raw_key,
                label=label,
                count=value,
                category=source_category,
                source_path=f"fixture.{raw_key}",
                confidence=Confidence.VERIFIED,
            )
            for (raw_key, label, source_category), value in zip(
                _COUNTER_SPECS,
                values,
                strict=True,
            )
        ),
        source="fixture",
        auth_state=WebAuthState.ADMIN,
    )


def test_daily_cache_to_ledger_bills_legal_and_folio_as_a3_only(tmp_path) -> None:
    DeviceConfigRepository().replace_all(
        [DeviceConfig(0, "Office", "192.0.2.10", serial="SER-PAPER")]
    )
    PricingRepository().set_prices(
        0,
        date(2026, 7, 1),
        PriceList(a3_color=2.0, a3_bw=0.5, a4_color=99.0, a4_bw=98.0),
    )
    set_cfg("waste_paper_pct", "0")
    cache = DailyCacheStore(tmp_path / "cache")
    first = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    safe = ReconciliationReport(checked_count=1, issues=())
    cache.update_reading(
        0,
        _reading((100, 100, 100, 100, 100, 100), first),
        at=first,
        reconciliation=safe,
    )
    cache.update_reading(
        0,
        _reading((102, 103, 104, 105, 106, 107), first + timedelta(hours=1)),
        at=first + timedelta(hours=1),
        reconciliation=safe,
    )

    record = cache.finalize(0, first.date())

    assert record is not None
    with _open(commit=False) as conn:
        daily = conn.execute(
            "SELECT delta_json,category_json FROM daily_meter_records"
        ).fetchone()
        ledger = conn.execute(
            """SELECT entry_kind,delta_json,category_json,gross_cents,net_cents
               FROM billing_ledger"""
        ).fetchone()

    expected_delta = {
        "counter.paper.full_color.legal": 2,
        "counter.paper.black.legal": 3,
        "counter.paper.full_color.folio": 4,
        "counter.paper.black.folio": 5,
        "counter.paper.full_color.letter": 6,
        "counter.scan_fax.scan_total": 7,
    }
    expected_categories = {
        "counter.paper.full_color.legal": "a3_color",
        "counter.paper.black.legal": "a3_bw",
        "counter.paper.full_color.folio": "a3_color",
        "counter.paper.black.folio": "a3_bw",
        "counter.paper.full_color.letter": "no_charge",
        "counter.scan_fax.scan_total": "no_charge",
    }
    assert json.loads(daily[0]) == expected_delta
    assert json.loads(daily[1]) == expected_categories
    assert ledger[0] == "posting"
    assert json.loads(ledger[1]) == expected_delta
    assert json.loads(ledger[2]) == expected_categories
    # (2 + 4) color pages x 200 satang + (3 + 5) B&W pages x 50 satang.
    assert ledger[3:] == (1_600, 1_600)
