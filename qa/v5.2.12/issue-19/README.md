# Issue #19 source evidence

Implementation and measured limits: [report](../../../docs/V5_2_12_ISSUE_19_IMPLEMENTATION.md).
Baseline source: `0fca8e4`; after source is the local commit containing this directory.
Synthetic data only; no production Host, printers, customer database, installer or release.

| Files | Purpose |
|---|---|
| before-ui.json / after-ui.json | Same 100-user / 3-printer / 5-year fixture; sequential source UI runs, all steps complete, temporary copy cleaned |
| after-ui-interim.json | Retained diagnostic intermediate; includes slow Archive join since corrected; never use as final |
| after-queries.json | Synchronous service timing only, not production UI responsiveness |
| navigation-profile-*.json / navigation-phases.json | cProfile diagnosis and import/copy/migration/construct/paint phases; overhead included; OS caches uncontrolled |
| export-database-year.json | Controller + actual DB read + workbook write; validates all 100 users / 6 sheets / 109,500 Raw records |
| evidence-*.json / evidence-*.pdf | Background Web evidence 960/4,096 points, XLSX/PDF, timer/click heartbeat |
| pdf-text-validation.json / evidence-{first,middle,last}.png | All PDF pages nonempty; representative visual pagination review |
| charts.json | Normal source lifecycle, no wrapper-retention diagnostic control |
| idle.json / active.json | Short source Desktop/Agent footprint and synthetic collector regression |
| tests.json | Latest result of each unique regression test, 281 passed; failed intermediate XML retained honestly |
| screens/ | TH/EN Archive loading/ready/error, Overview retry and Manual, real source QSS/fonts |
| guide-validation.json / guide-page-*.png | Updated 24-page guide text and changed-page visual checks |
| manifest.json | SHA-256 of source changes and retained evidence |

## Reproduction

Use the project's Python environment from this worktree. No build is required.
Create a NEW synthetic directory using `source/tools/benchmark_five_years.py`.
The audit validates FIXTURE serials/IPs, opens the original DB read-only,
and copies/migrates it into a temporary directory. Do not pass customer data.

```powershell
python tools/audit_performance_v5.py --mode ui --synthetic-db <synthetic-history.sqlite3> --output <after-ui.json>
python tools/audit_performance_v5.py --mode queries --synthetic-db <synthetic-history.sqlite3> --output <after-queries.json>
python tools/audit_performance_v5.py --mode export --synthetic-db <synthetic-history.sqlite3> --output <export-database-year.json>
python tools/audit_performance_v5.py --mode charts --output <charts.json>
python tools/audit_performance_v5.py --mode evidence --days 128 --format pdf --output <evidence-128-pdf.json>
python tools/profile_navigation_v5.py --synthetic-db <synthetic-history.sqlite3> --output <navigation-phases.json>
python tools/capture_performance_states.py
```

Run benchmark modes sequentially. The profiler includes its own overhead and is
diagnostic; use the UI runs for before/after latency. Empty-database profiles
and the old baseline Devices profile without a dirty refresh are not equivalent
to the five-year first-navigation measurements.

`faulthandler` prints a stack every 60 seconds during long audits for diagnosis;
that alone is not failure. Check `complete`, `temporary_copy_cleaned`, and process exit.
The audit blocks external network/process operations before they occur.
The large export fixture is hot; small end-to-end tests separately cover Archive.
The capture tool also refreshes the guide's Archive screenshot.

Old writer-only 90-user/8-counter results are a different fixture; do not combine
their duration with service timings or call them DB-to-file end-to-end results.
