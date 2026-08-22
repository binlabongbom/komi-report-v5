#!/usr/bin/env python3
"""Small benchmark for summary-service refresh cost.

This script uses the configured app database. For synthetic benchmarking,
point the app to a copied database first.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import init_db
from services.summary_service import build_overview_summary


def run(iterations: int, filter_key: str) -> list[float]:
    timings: list[float] = []
    init_db()
    for _ in range(iterations):
        started = time.perf_counter()
        build_overview_summary(filter_key)
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark overview summary refresh.")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--filter", default="all", choices=["current", "3m", "1y", "all"])
    args = parser.parse_args()

    timings = run(args.iterations, args.filter)
    print(f"iterations: {len(timings)}")
    print(f"filter: {args.filter}")
    print(f"min_ms: {min(timings):.3f}")
    print(f"median_ms: {statistics.median(timings):.3f}")
    print(f"max_ms: {max(timings):.3f}")
    print(f"mean_ms: {statistics.mean(timings):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
