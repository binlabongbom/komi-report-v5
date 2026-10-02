"""Small pytest evidence plugin; collection and outcomes are JSON, not scraped text."""

import json
import os
from pathlib import Path

from _pytest.subtests import SubtestReport

_subtest_reports = []


def pytest_runtest_logreport(report) -> None:
    # Terminal stats may hide successful subtests at quiet verbosity or combine
    # failing/skipped subtests with top-level cases. Capture them independently.
    if isinstance(report, SubtestReport):
        _subtest_reports.append(report)


def _write(variable: str, payload: dict) -> None:
    path = os.environ.get(variable)
    if path:
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf8")


def pytest_collection_finish(session) -> None:
    _write("KOMI_CI_COLLECTION", {"nodeids": [item.nodeid for item in session.items]})


def pytest_sessionfinish(session, exitstatus) -> None:
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    statuses = ("passed", "failed", "skipped", "error", "xfailed", "xpassed")
    stats = reporter.stats if reporter is not None else {}
    counts = {
        name: sum(not isinstance(report, SubtestReport) for report in stats.get(name, []))
        for name in statuses
    }
    subtest_counts = dict.fromkeys(statuses, 0)
    for report in _subtest_reports:
        outcome = report.outcome
        if hasattr(report, "wasxfail"):
            outcome = "xfailed" if outcome == "skipped" else "xpassed"
        subtest_counts[outcome] += 1
    executed = sorted({
        report.nodeid
        for name in statuses
        for report in stats.get(name, [])
        if hasattr(report, "nodeid") and not isinstance(report, SubtestReport)
    })
    _write("KOMI_CI_OUTCOMES", {
        "exit_code": int(exitstatus),
        "counts": counts,
        "subtest_counts": subtest_counts,
        "executed_nodeids": executed,
    })
