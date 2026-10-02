# Performance audit evidence — 19 September 2026

Product source: `59544e6` (documentation-only change on top of `64a512a`).
No product code changes, release/installer build, Host changes, real printers or
customer data. See [the audit report](../../../docs/V5_2_12_PERFORMANCE_AUDIT.md)
for conclusions, priorities and limits. Results are individual local observations,
not statistical latency guarantees.

| Evidence | Workload / scope | Completion |
|---|---|---|
| `idle-current.json` | Fresh empty DB, Desktop and Agent, one sample each, 5-second measured idle | Both child processes exit 0 |
| `active-current.json` | Each mode: 3 printers × 100 users × 2 counters × 3 accelerated rounds | Both exit 0; 9/9 persisted events and outbox items |
| `ui-five-year.json` | Real MainWindow + staged Reports; unarchived five-year DB; 41 measured operations | All operations complete, no report error; harness cleanup exit 1 (see below) |
| `queries-five-year.json` | Same verified fixture copied afresh; ranged queries, Archive stats, Overview summary | Exit 0; temporary copy cleaned |
| `evidence-30days-xlsx.json` | One counter, 960 points; actual evidence renderer and Excel writer | Exit 0; row counts verified |
| `evidence-128days-xlsx.json` | One counter, 4,096 points; actual evidence renderer and Excel writer | Exit 0; row counts verified |
| `evidence-128days-pdf.json` | One counter, 4,096 points; actual PDF writer on GUI thread | Exit 0; valid PDF header/non-empty output, not visual pagination QA |
| `chart-ownership.json` | 90 users/3 printers/2 days; ten Overview replacements with current implementation | Exit 0; destroyed signals 2/22 after closing |
| `chart-ownership-control.json` | Same experiment, harness temporarily keeps previous Python wrapper through `setChart` | Exit 0; destroyed signals 22/22 |

UI uses the documented synthetic DB from the earlier five-year benchmark. It
contains 547,800 subject rows and 547,800 raw rows, one user total counter per day.
The full annual range has 109,500 raw rows; it is different from the earlier
Excel benchmark's 797,160 rows/eight Print-Copy counters/90 users.

The audit copies the database using a read-only source connection after checking
all three device serials/addresses against fixture identities. It migrates only
the private temporary copy. Source/DB preparation and Python imports are outside
the UI step timer; `copy_migration_init_seconds` is recorded separately in newer
runs. Query mode verified schema 30 using `PRAGMA user_version`. The earlier UI
run's `copy_schema: null` came from looking for a settings key, not evidence of a
missing database schema. No claim of a packaged cold-start timing is made.

The UI run recorded 159 blocked `socket.connect` attempts. Settings contains a
periodic Web status probe even when full background services have not started.
Every attempt was denied before connecting; original UI logs recorded event
names, not call stacks, so do not attribute all 159 to a specific destination.
Other query/evidence/chart runs recorded no blocked attempts. These timings do
not include real network timeout costs.

Each timer uses a 10 ms Qt heartbeat, includes a post-operation event-loop turn,
and stores working/private/peak process memory. `seconds_until_ready` excludes
the final 25 ms heartbeat observation, so very small operations can have a larger
gap than their action duration. Staged Reports readiness includes snapshot jobs,
debounce and deferred table/chart rendering. Query mode deliberately invokes
services synchronously to measure their duration; its heartbeat gaps do not mean
the Reports page reads its data on the GUI thread.

The UI run completed every measurement and saved `complete: true`, then failed
removing its disposable DB because the harness's `with sqlite3.connect(...)`
context did not close that connection. This was a harness cleanup error, not a
MainWindow crash. The tool now uses `contextlib.closing`; subsequent query,
evidence and chart modes completed with `temporary_copy_cleaned: true`. The
leftover UI fixture was removed after that process exited. The 41-operation UI
matrix was not rerun merely for this cleanup change. Initial harness development
errors (fixture table name and missing render argument) were corrected; their
partial outputs are not used as product findings.

Chart observation stores only weak refs and integer identity tokens in destroyed
callbacks. `live_wrappers_not_deleted: 0` does not prove native charts were freed:
the old wrapper can disappear while its C++ chart is no longer owned by the view.
The control experiment intentionally changes wrapper lifetime; this lets SIP
return the old chart to Python ownership before the local reference is dropped.
It is diagnostic evidence, not a shipped product fix. Qt documents disposal of
the replaced chart at [QChartView::setChart](https://doc.qt.io/qt-6/qchartview-qtcharts.html#setChart).

## Reproduce

Use the project's Python environment from the repository root. Create a new
fixture if the documented old one is unavailable; never pass a customer DB.

```text
python source/tools/benchmark_five_years.py <new-synthetic-directory>
python tools/audit_performance_v5.py --mode ui --synthetic-db <synthetic-history.sqlite3> --output outputs/performance-audit/ui-five-year.json
python tools/audit_performance_v5.py --mode queries --synthetic-db <synthetic-history.sqlite3> --output outputs/performance-audit/queries-five-year.json
python tools/audit_performance_v5.py --mode evidence --days 30 --format xlsx --output outputs/performance-audit/evidence-30days-xlsx.json
python tools/audit_performance_v5.py --mode evidence --days 128 --format xlsx --output outputs/performance-audit/evidence-128days-xlsx.json
python tools/audit_performance_v5.py --mode evidence --days 128 --format pdf --output outputs/performance-audit/evidence-128days-pdf.json
python tools/audit_performance_v5.py --mode charts --output outputs/performance-audit/chart-ownership.json
python tools/audit_performance_v5.py --mode charts --hold-previous-chart --output outputs/performance-audit/chart-ownership-control.json
python tools/measure_idle_runtime.py --repeats 1 --output outputs/performance-audit/idle-current.json
python tools/measure_idle_runtime.py --active-rounds 3 --repeats 1 --output outputs/performance-audit/active-current.json
```

The five-year UI and query modes can take several minutes. The tool prints
diagnostic stacks every 60 seconds during long runs; these messages alone are
not failures. Measure modes sequentially, not concurrently. Services remain
disabled, and audit modes deny network connections/broadcast/bind and subprocess
launches. Footprint children enforce their existing no-external-process guard.
Full audits still need packaged startup, real Windows rendering, long-duration
runtime, archived/corrupt-file cases and the user-approved A + VM105 checks after build.
