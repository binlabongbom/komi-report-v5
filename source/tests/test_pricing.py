from __future__ import annotations

from datetime import date

from database import init_db, set_db_path
from services.device_config import DeviceConfig, DeviceConfigRepository
from services.pricing import (
    CostCategory,
    PriceList,
    PricingRepository,
    apply_waste_discount,
    calculate_cost,
    default_cost_category,
)


def _database(tmp_path):
    set_db_path(tmp_path / "pricing.db")
    init_db()
    DeviceConfigRepository().replace_all([DeviceConfig(0, "Office", "192.0.2.10")])


def test_default_cost_categories_follow_size_and_color_rules():
    assert default_cost_category("counter.paper.full_color.a4") is CostCategory.A4_COLOR
    assert default_cost_category("counter.paper.black.a3") is CostCategory.A3_BW
    assert default_cost_category("counter.paper.single_two_color.b4") is CostCategory.A3_COLOR
    assert default_cost_category("counter.scan_fax.scan_total") is CostCategory.NO_CHARGE


def test_effective_dated_price_history(tmp_path):
    _database(tmp_path)
    repository = PricingRepository()
    repository.set_prices(0, date(2026, 1, 1), PriceList(a4_color=2.0))
    repository.set_prices(0, date(2026, 7, 1), PriceList(a4_color=1.0))

    assert repository.get_prices(0, date(2026, 6, 30)).a4_color == 2.0
    assert repository.get_prices(0, date(2026, 7, 1)).a4_color == 1.0


def test_batch_categories_match_effective_overrides_and_defaults(tmp_path):
    _database(tmp_path)
    repository = PricingRepository()
    repository.set_category(
        0,
        "counter.paper.full_color.a4",
        date(2026, 1, 1),
        CostCategory.A3_COLOR,
    )
    repository.set_category(
        0,
        "counter.paper.full_color.a4",
        date(2026, 7, 1),
        CostCategory.A4_COLOR,
    )

    categories = repository.get_categories(
        0,
        date(2026, 6, 30),
        {
            "counter.paper.full_color.a4": ("", ""),
            "custom-counter": ("Black A3", "paper"),
        },
    )

    assert categories == {
        "counter.paper.full_color.a4": CostCategory.A3_COLOR,
        "custom-counter": CostCategory.A3_BW,
    }


def test_cost_and_waste_discount():
    amount = calculate_cost(
        {"a": 100, "b": 50},
        {"a": CostCategory.A4_COLOR, "b": CostCategory.NO_CHARGE},
        PriceList(a4_color=2.0),
    )

    assert amount == 200.0
    assert apply_waste_discount(amount, 2) == 196.0
