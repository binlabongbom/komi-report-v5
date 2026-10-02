# Incremental Users and Archive performance — 2026-09-24

Three changes build on the previous compact Users read model:

The recorded performance timings and source hashes below precede the September
25 subject-name preservation fix. That follow-up has separate correctness and
upgrade verification; these figures are not new timing claims for that revision.

1. Users bounds daily usage payload reads to its selected preview dates. A small
   all-history closure lookup remains necessary to reject overlapping shared
   allocations; monthly summaries still populate the period selector. Ledger
   corrections retain their complete source-day posting/reversal chain.
2. Users reuses compressed immutable daily read models per device. Schema 34
   adds transactional mutation tokens for hot Subject/Raw inserts, updates and
   deletes, including both sides of moved rows. A refresh loads only dirty days.
   Exact canonical category breakdowns are memoized separately; period totals,
   current-day cache, archive/revision/shared precedence and prices remain fresh.
3. Archive statistics count eligible old rows sequentially and subtract retained
   identity anchors through indexes. Existing UI metadata caching remains; no
   additional stale count cache or change to pruning eligibility is introduced.

The day cache is process-local and capped at 32 MiB of compressed payload,
2,400 entries and 4 million rows. Entry/key overhead is additional but bounded.
The internal serialized bytes are generated solely from our immutable objects
and never loaded from disk/network/database. Restarting discards the cache.
Database generation/path, day mutation token and amendment exclusions isolate
entries. Failed/cancelled block preparation never publishes partial results.

The additive schema upgrade uses the existing backup and transaction mechanism.
It adds `idx_report_raw_day(device_slot,record_date)` for selective reads. Source
Raw ordering is explicit so a changed query plan cannot rearrange equal-key
values before floating-point addition. Exact Raw and original billing records
are retained. Excel continues to read original history independently.

## Verification scope

All work uses the verified synthetic 200-user, three-printer, five-year fixture
copied into an isolated temporary runtime. Preview dates span one year with
219,000 Subject rows and 219,000 Raw rows. No customer database or installer is
used. The fixture has a single aggregate Raw counter per user/day; richer
A3/A4/Color/B&W cost and availability cases are covered by regression fixtures.

Worker timings exclude fingerprint generation, schema upgrade and Qt rendering.
Each request receives fresh UI snapshot/day-state stores. The incremental module
cache intentionally persists across refreshes, and OS caches may warm. These
measurements are not physical cold-HDD timings or a promise for every dataset.
The initial database upgrade on the large fixture also performs a one-time
backup/index/backfill; its time is recorded separately by the profiling tool.

The main isolated regression run passed 347 cases in 31 suites across 44 fresh
processes, without skips/failures. The cache API cleanup is followed by a separate
36-case rerun, also passing without skips/failures. Coverage includes inserts/deletes/moves, unchanged timestamps,
transaction rollback, reset/backfill, exact binary64 values, archive/amendment
precedence, current prices, cancellation, bounded cache eviction, UI models,
Excel, background reads and preview limits. After coalescing adjacent dirty dates,
47 projection/snapshot cases passed again, plus four new range-extension cases: a
total of 351 distinct verified tests. Date extension reads adjacent missing days
as ranges rather than a long per-day list, preserving cached gaps.

Evidence is under `outputs/users-incremental-performance/`. Early JSON-based
experiments are retained as development evidence: they consumed more resources
and were replaced by mutation-token tracking. Only final measurements describe
the current implementation.

## Worker measurements

The previous compact-reader pass took 20.10 / 22.52 / 21.49 seconds with fresh
request caches (median 21.49 seconds). The final run here distinguishes the
initial preparation from subsequent reloads rather than mixing them into a
single improvement percentage:

| Scenario | Seconds |
| --- | ---: |
| First preparation, empty day cache | 24.22 |
| Three fresh-snapshot reloads, validated day cache | 9.80 / 9.17 / 8.23 |
| Reload after changing one device/day | 10.26 |
| Daily device-history component | 0.41–0.52 |

Reload median is 9.17 seconds, about 57% lower than the previous 21.49-second
fresh-request median. **First preparation is not faster in this measurement**;
building the reusable cache adds work. The old daily-history component alone
took 1.45–2.36 seconds. The one-time migration/backup/index/backfill of the copied
963 MB fixture took 16.69 seconds outside the preparation timings.

All four Users/subject presentation hashes equal the previous pass's
`9c515fc79fc33ba652721256cc05d55978817989a5c81a0bb7f01a0f7e53a2a0`.
The changed-day run reused 2,188 blocks and rebuilt exactly two (Subject and Raw
for that device/day). Its complete fingerprint matched an uncached oracle read.

The cache contained 2,190 blocks / 438,000 rows in 3.93 MiB compressed. Harness
working set after loads was 97.21 / 123.68 / 150.50 / 191.59 MiB; private committed
memory was 309.24 / 336.17 / 362.82 / 402.91 MiB. Warm process memory is higher
than the previous pass's 115–124 MiB working set, despite the small retained
cache; do not describe the cache's 32 MiB payload cap as a whole-process RAM cap.

Archive SQL-only comparison on the same copied fixture returned exactly
1,759,800 eligible rows with both implementations: old queries 9.83 seconds,
new queries 6.14 seconds (one paired run). A separate fresh production
`HistoryArchive.stats()` call took 7.83 seconds. These are not median cold-disk
measurements.

## Source Qt verification

The final offscreen source run completed all five report tabs and five warm
navigation cycles. The one-year Users preview contained 200 users, and its
totals matched the selected 219,000 Raw source rows. No report error occurred.

| UI action | Seconds |
| --- | ---: |
| First preparation of one-year Users preview | 27.99 |
| Return to already prepared Users tab, final warm cycle | 0.21 |
| First Archive statistics request | 6.86 |
| Cached Archive statistics request | 0.007 |

The earlier compact-reader UI run took 20.42 seconds for initial annual Users
preparation, so this round **does not improve first-open latency**. The maximum
event-loop gap during the final annual Users preparation was 409 ms. The 0.21 s
tab return reuses a complete snapshot and must not be confused with the 9.17 s
worker reload that validates/rebuilds a fresh snapshot. Archive's earlier UI
measurement was 11.13 s; the final run was 6.86 s. These are single UI runs.

All runs use copied synthetic data and offscreen Qt, not the visible customer
app. The test guard blocked three existing shutdown status probes before any
connection: two local port checks and one UDP-connect LAN-address lookup. The
isolated runtime copy was cleaned after completion.

Final evidence files:

- `final-ranges.json`: first/reload/changed-day measurements, exact fingerprints and
  hashes of all nine relevant product source files.
- `regression-final/results.json`: 347-case regression manifest.
- `cache-api-final/results.json`: 36-case verification after API cleanup.
- `range-cache-final/results.json`: 47 projection/snapshot cases after coalescing dirty dates.
- `range-extension-final/results.json`: four additional range-extension parity cases.
- `comparison.json`: previous/final comparison and verified product source hashes.
- `ui-final-ranges.json`: completed source Qt navigation, exact preview totals,
  responsiveness, Archive timings and blocked-operation evidence.
- `archive-sql-profile.json`, `archive-final.json`: count/query timings.
