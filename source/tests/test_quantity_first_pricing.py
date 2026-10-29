from decimal import Decimal

import pytest
from database import get_waste_paper_pct, set_cfg, _open
from services.pricing import quantity_first_amounts, provisional_quantity_cost, PriceList


@pytest.mark.parametrize('pages,bp,expected', [(101,500,96),(1,5000,1),(3,5000,2),(1,5100,0),(101,0,101),(101,10000,0)])
def test_pages_half_up_before_price(pages,bp,expected):
    gross, net, proof = quantity_first_amounts({'bw': pages}, {'bw': 'a4_bw'}, {'a4_bw': 123}, bp)
    assert gross == pages * 123
    assert net == expected * 123
    assert proof['billable_category_pages']['a4_bw'] == expected
    assert Decimal(proof['raw_category_pages']['a4_bw']) == pages


def test_round_once_per_category_not_per_raw_counter():
    gross, net, proof = quantity_first_amounts({'copy': 1, 'print': 1},
        {'copy': 'a4_bw', 'print': 'a4_bw'}, {'a4_bw': 100}, 5000)
    assert gross == 200 and net == 100
    assert proof['billable_category_pages']['a4_bw'] == 1


def test_categories_round_separately_and_use_their_own_price():
    gross, net, proof = quantity_first_amounts({'bw': 1, 'color': 1},
        {'bw': 'a4_bw', 'color': 'a4_color'}, {'a4_bw': 100, 'a4_color': 300}, 5000)
    assert (gross, net) == (400, 400)
    assert proof['category_net_cents']['a4_bw'] == 100
    assert proof['category_net_cents']['a4_color'] == 300


def test_provisional_uses_same_unit_cent_rounding_as_posted_ledger():
    assert provisional_quantity_cost({'color': 3}, {'color': 'a4_color'}, PriceList(a4_color=1.005), 2.5) == (3.03, 3.03)


def test_default_two_percent_preserves_explicit_zero():
    with _open() as conn:
        conn.execute("DELETE FROM settings WHERE key='waste_paper_pct'")
    assert get_waste_paper_pct() == 2
    set_cfg('waste_paper_pct', '0')
    assert get_waste_paper_pct() == 0
    set_cfg('waste_paper_pct', '5')
    assert get_waste_paper_pct() == 5
