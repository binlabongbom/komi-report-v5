# Users report load performance — 2026-09-24

This records the first optimization pass. The subsequent bounded/incremental
Users and Archive work is recorded in
[USERS_INCREMENTAL_PERFORMANCE_2026_09_24.md](USERS_INCREMENTAL_PERFORMANCE_2026_09_24.md).

The Users worker now loads a compact Counter projection and releases it after
building the complete table/graph model. Exact Raw rows are loaded when opening
Legacy or exporting Excel. The subject-history loader also uses compact private
daily rows, reuses immutable source metadata, and initializes aggregation buckets
only when first encountered. Public history records and database schema are unchanged.

## Measurements

The verified synthetic database contains 200 users, three printers and five years
of history. The selected preview is 2025-09-18 through 2026-09-17: 219,000 subject
daily rows and 219,000 Raw rows. The benchmark opens the fixture read-only, checks
its synthetic identities, and backs it up to an isolated temporary runtime.

| Measurement | Baseline `0faaf0d` | First optimization pass |
| --- | ---: | ---: |
| Three Users preparation runs, seconds | 28.64 / 24.81 / 26.67 | 20.10 / 22.52 / 21.49 |
| Median preparation time | 26.67 s | 21.49 s |
| Harness working set after preparation | 312–320 MiB | 115–124 MiB |
| Harness private committed memory after preparation | 524–533 MiB | 327–336 MiB |
| Exact Raw rows retained by Users snapshot | 219,000 | 0 |

Median preparation time fell 19.4%. These are worker load measurements, excluding
Qt rendering and fingerprint generation. Request caches are fresh each run;
module and OS caches may warm. This is not a physical cold-disk benchmark, and
memory values refer to the load harness, not the entire desktop application.

The separate Qt offscreen run reached the annual Users screen in 20.42 seconds.
Five warm returns took 0.16–0.23 seconds. All report tabs completed without a
visible report error. The longest annual Users event-loop gap was 614 ms, so this
does not claim elimination of every UI pause.

### Tradeoff

Legacy loads its full Raw evidence on first use (15.00 seconds for this annual
Qt run). Previously, visiting Users first had already paid for and retained that
read. Opening both pages can therefore do more total reading, while Users alone
retains much less data. Excel continues to load exact Raw independently. A full
year still takes about 21 seconds to prepare; further acceleration would require
additional aggregation/query work.

## Correctness and evidence

All fields and ordering in all 200 Users models and 600 subject summaries have
identical deterministic hashes across all six measured runs. The sum of user
usage matches the fixture SQL total of 2,628,000. The fixture's Raw category is
the subject total counter; detailed category/cost correctness is additionally
covered by focused fixtures, not inferred from this performance dataset.

Tests cover changing daily costs, missing evidence, pending/baseline/reset review,
replacement serials, fallback counter labels, negative deltas, archived revisions,
shared/local overlap outside the selected date range, cancellation, and Users
table expansion/selection/cost display with prepared models and no retained Raw.
The final isolated regression run passed all 197 cases in 19 suites (25 fresh
processes), with no failures, errors, skips or missing cases. Focused Ruff and
Git whitespace checks also passed.

Generated evidence is under `outputs/users-load-performance/`:

- `baseline.json`, `final.json`: three measurements per version and full fingerprints.
- `comparison.json`: matching presentation hash and exact product source SHA-256 values.
- `ui-final.json`: source Qt navigation, all report tabs, warm switches and totals checks.
- `regression-final/results.json`: authoritative focused regression results.

The UI audit blocked three pre-existing network status probes during shutdown,
as the earlier audit did; no network connection succeeded. The load-only harness
attempted no network/process operation. Customer databases and installers were
not used. Early development test failures remain in their separate output folders;
only the final regression manifest represents the completed verification.

## Reproduce

From the source repository with its virtual environment:

```powershell
python tools/profile_report_users.py --synthetic-db <verified-fixture.sqlite3> --output <new-result.json> --runs 3
```

The command rejects an unrelated database and existing output files. Optional
`--profile` adds a separately timed cProfile iteration. It does not launch Qt,
services, printers or other processes.
