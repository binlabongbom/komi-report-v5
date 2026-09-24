from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from database import _open


class CostCategory(StrEnum):
    A3_COLOR = "a3_color"
    A3_BW = "a3_bw"
    A4_COLOR = "a4_color"
    A4_BW = "a4_bw"
    NO_CHARGE = "no_charge"


A3_EQUIVALENT_PAPER_SIZES = frozenset(
    {
        "a0",
        "a1",
        "a2",
        "a3",
        "b0",
        "b1",
        "b2",
        "b3",
        "b4",
        "legal",
        "folio",
    }
)
A4_EQUIVALENT_PAPER_SIZES = frozenset(
    {"a4", "a5", "a6", "a7", "a8", "b5", "b6", "b7", "b8"}
)
_PAPER_SIZE_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:a[0-8]|b[0-8]|legal|folio)(?![a-z0-9])",
    re.IGNORECASE,
)


def recognized_paper_size(text: str) -> str | None:
    """Return only paper-size aliases approved for automatic billing.

    Unknown/custom aliases deliberately return ``None`` so they remain visible
    as raw counters without accidentally acquiring a billable price.
    """

    match = _PAPER_SIZE_PATTERN.search(text)
    return match.group(0).lower() if match else None


@dataclass(frozen=True)
class PriceList:
    a3_color: float = 0.0
    a3_bw: float = 0.0
    a4_color: float = 0.0
    a4_bw: float = 0.0

    def price(self, category: CostCategory) -> float:
        return 0.0 if category is CostCategory.NO_CHARGE else float(getattr(self, category.value))


def default_cost_category(raw_key: str, label: str = "", category: str = "") -> CostCategory:
    text = " ".join((raw_key, label, category)).lower()
    if any(token in text for token in ("scan", "fax", "toner", "supply")):
        return CostCategory.NO_CHARGE
    is_bw = any(token in text for token in ("black", "b&w", "bw", "gray", "grey", "grayscale"))
    is_color = any(token in text for token in ("color", "colour", "single", "double", "two_color"))
    paper_size = recognized_paper_size(text)
    if paper_size is None or not (is_bw or is_color):
        return CostCategory.NO_CHARGE
    prefix = "a3" if paper_size in A3_EQUIVALENT_PAPER_SIZES else "a4"
    suffix = "bw" if is_bw else "color"
    return CostCategory(f"{prefix}_{suffix}")


class PricingRepository:
    def set_prices(self, slot: int, effective_date: date, prices: PriceList) -> None:
        with _open() as conn:
            self.write_prices(conn, slot, effective_date, prices)

    @staticmethod
    def write_prices(conn, slot: int, effective_date: date, prices: PriceList) -> None:
        from services.shared_settings_document import PRICE_KEYS, validate_price_history
        validate_price_history([{"slot": slot, "effective_date": effective_date.isoformat(),
                                 **{key: getattr(prices, key) for key in PRICE_KEYS}}])
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        conn.execute(
            """INSERT INTO price_history(
                   device_slot,effective_date,a3_color,a3_bw,a4_color,a4_bw,created_at
               ) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(device_slot,effective_date) DO UPDATE SET
                 a3_color=excluded.a3_color,a3_bw=excluded.a3_bw,
                 a4_color=excluded.a4_color,a4_bw=excluded.a4_bw,created_at=excluded.created_at""",
            (slot, effective_date.isoformat(), prices.a3_color, prices.a3_bw, prices.a4_color, prices.a4_bw, now),
        )

    def get_prices(self, slot: int, on_date: date) -> PriceList:
        with _open(commit=False) as conn:
            row = conn.execute(
                """SELECT a3_color,a3_bw,a4_color,a4_bw FROM price_history
                   WHERE device_slot=? AND effective_date<=?
                   ORDER BY effective_date DESC LIMIT 1""",
                (slot, on_date.isoformat()),
            ).fetchone()
        return PriceList(*row) if row else PriceList()

    def get_prices_for_days(self, requests) -> dict[tuple[int, date], PriceList]:
        """Resolve historical prices for a report with one read, not one per day."""
        requests = set(requests)
        if not requests:
            return {}
        slots = sorted({slot for slot, _day in requests})
        latest = max(day for _slot, day in requests).isoformat()
        placeholders = ','.join('?' for _slot in slots)
        with _open(commit=False) as conn:
            rows = conn.execute(f'''SELECT device_slot,effective_date,a3_color,a3_bw,a4_color,a4_bw
                FROM price_history WHERE device_slot IN ({placeholders}) AND effective_date<=?
                ORDER BY device_slot,effective_date''', (*slots, latest)).fetchall()
        dates, prices = defaultdict(list), defaultdict(list)
        for slot, effective, *amounts in rows:
            dates[slot].append(effective)
            prices[slot].append(PriceList(*amounts))
        resolved = {}
        for slot, day in requests:
            index = bisect_right(dates[slot], day.isoformat()) - 1
            resolved[(slot, day)] = prices[slot][index] if index >= 0 else PriceList()
        return resolved

    def set_category(self, slot: int, raw_key: str, effective_date: date, category: CostCategory) -> None:
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with _open() as conn:
            conn.execute(
                """INSERT INTO cost_category_history(device_slot,raw_key,effective_date,category,created_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(device_slot,raw_key,effective_date) DO UPDATE SET
                     category=excluded.category,created_at=excluded.created_at""",
                (slot, raw_key, effective_date.isoformat(), category.value, now),
            )

    def get_category(
        self,
        slot: int,
        raw_key: str,
        on_date: date,
        *,
        label: str = "",
        source_category: str = "",
    ) -> CostCategory:
        with _open(commit=False) as conn:
            row = conn.execute(
                """SELECT category FROM cost_category_history
                   WHERE device_slot=? AND raw_key=? AND effective_date<=?
                   ORDER BY effective_date DESC LIMIT 1""",
                (slot, raw_key, on_date.isoformat()),
            ).fetchone()
        return CostCategory(row[0]) if row else default_cost_category(raw_key, label, source_category)

    def get_categories(
        self,
        slot: int,
        on_date: date,
        counters: dict[str, tuple[str, str]],
    ) -> dict[str, CostCategory]:
        """Resolve many counter categories with a single database connection.

        ``counters`` maps each raw counter key to ``(label, source_category)``.
        The result is equivalent to calling :meth:`get_category` for every key,
        but avoids opening and closing SQLite once per counter.  This matters on
        synced/cloud-backed folders where connection teardown is relatively
        expensive.
        """
        if not counters:
            return {}

        keys = tuple(counters)
        placeholders = ",".join("?" for _ in keys)
        with _open(commit=False) as conn:
            rows = conn.execute(
                f"""SELECT raw_key,category FROM cost_category_history
                    WHERE device_slot=? AND raw_key IN ({placeholders})
                      AND effective_date<=?
                    ORDER BY raw_key,effective_date""",
                (slot, *keys, on_date.isoformat()),
            ).fetchall()

        overrides: dict[str, CostCategory] = {}
        for raw_key, category in rows:
            # Rows are oldest -> newest, so the final value is the effective
            # category on the requested date.
            overrides[str(raw_key)] = CostCategory(category)

        return {
            raw_key: overrides.get(
                raw_key,
                default_cost_category(raw_key, label, source_category),
            )
            for raw_key, (label, source_category) in counters.items()
        }


def calculate_cost(deltas: dict[str, int | float], categories: dict[str, CostCategory], prices: PriceList) -> float:
    return sum(max(0.0, float(value)) * prices.price(categories.get(key, CostCategory.NO_CHARGE)) for key, value in deltas.items())


def apply_waste_discount(amount: float, waste_pct: float) -> float:
    pct = min(100.0, max(0.0, float(waste_pct)))
    return round(max(0.0, amount) * (100.0 - pct) / 100.0, 2)
