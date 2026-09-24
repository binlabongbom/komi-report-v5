# Dead-code cleanup — 24 September 2026

## Scope and recovery

Work is isolated on `codex/dead-code-cleanup`. Commit `6abd87f` preserves the
previously reviewed UI, diagnostics, runtime and preview changes before cleanup.
Cleanup is a separate commit. Local `main` is updated only after verification.

The live database is outside the repository. Tests and startup smoke checks use
separate synthetic databases. No installer is built and no remote push is part
of this cleanup.

## Removed

- The six hidden Users KPI cards, their responsive-layout registration and their
  per-render aggregate calculations. Visible Users tables and charts remain.
- Printer-row selection callbacks that rebuilt identical charts. Native table
  selection remains; regression tests verify the chart objects are reused.
- Unreachable `PageLiveMeter`/worker, `PageConnectionInspector`/worker and
  `PageIndividual` screens, plus the inspector-only `_flatten_ram` helper/test.
- The obsolete `SetupWizard` and its private parser drop zone. First-run setup
  still uses `SetupWizardV5`; its six application-entry regressions passed again
  after the old wizard was removed.
- The closed chain of old Usage/Management/Meter renderers in `PageHistoryV5`.
  Their old table controls had no construction sites or external callers.
- The unused line-chart renderer, obsolete no-op callbacks, service helpers,
  constants, old Excel headers and imports confirmed to have no callers.
- References to the deleted live-meter module in source/package manifests.
- Unused imports and local values in development tools. The capture safety
  guard import is retained and explicitly documented as a side-effect import.

The earlier investigation is recorded in `DEAD_CODE_REVIEW_2026-09-24.md`;
its source line numbers and before-cleanup measurements are historical.

## Retained intentionally

- Legacy paths used by export, reconciliation and billing audit.
- Qt overrides, signals, HTTP/FastAPI handlers and other framework entry points.
- Parser compatibility re-exports and pytest fixture imports.
- Customer-guide assets/tools still used to generate external documentation.
- Existing untracked `tmp/` scripts, which are not part of the application.

Static unused-name results alone do not establish that a callback or import is
safe to delete. This cleanup does not claim a proof that every possible unused
path has been eliminated.

## Verification

- Final result: **1,751 Python tests passed across 20 isolated process groups**,
  plus 8 subtests and 11 web tests. All four initially failing groups were rerun
  in full after correcting the five stale/contaminated test cases. Initial and
  final results are retained separately under `outputs/`.
- Cleanup diff before this report: 38 tracked files, 52 lines added and 2,348
  removed (2,296 net lines removed). These are source/tool/test changes, not
  database records or customer files.
- Report/UI/parser/Excel regression: 73 passed.
- TypeScript unused locals/parameters and type checking: passed.
- Web security: 9 passed; numeric formatting: 2 passed.
- Python compile check and launch-doctor desktop manifest: passed.
- Runtime/development-tool Ruff checks: `F401,F811,F821,F822,F823,F841` passed,
  excluding tests because fixture imports and QApplication keepalive references
  require different handling.
- Actual `source/app.py --smoke-test` startup: exit 0, isolated database,
  offscreen Qt platform. This verifies startup, not physical-printer connectivity.
- Repeated startup after the old setup wizard was removed with the native
  Windows Qt platform: exit 0. The synthetic startup shell closes automatically
  in smoke-test mode, before first-run dialogs or network services.
- Runtime probe: opening Users adds 0 hidden cards (previously 6); selecting a
  printer reuses both chart objects (previously rebuilt identical charts).
- Full Python suite: results are recorded in
  `outputs/dead-code-suite-results.json` and individual group logs. The initial
  monolithic run stopped progressing in a Qt history test; it was stopped and
  replaced by bounded groups in fresh processes, with faulthandler diagnostics.
- Two network-status tests initially opened the obsolete Advanced location.
  They now select the visible Network tab by its label, including lazy mounting.
  All eight tests in `test_performance_issue19.py` pass after this correction;
  no production network-status behavior was changed to satisfy the tests.
- One snapshot-cache test still patched the removed billing-day import from
  before calendar-based preview periods. The obsolete patch was removed;
  immutable sharing and database invalidation assertions remain and all three
  report-model tests pass.
- The sidebar's no-data test now supplies a fresh RAM snapshot store instead
  of inheriting readings left by preceding peer-history tests. Running those
  history tests followed by sidebar tests passes all 30 cases; production
  snapshot behavior is unchanged.
- The Printers empty-state regression now checks the actual full-width no-data
  table message, replacing an assertion about the previously removed KPI card.
  All 15 UX regressions pass.

Windows denied input to the already running desktop window during the restart
attempt (`GetCursorPos: Access is denied`). The existing app was not force-killed.
The isolated source startup and Qt regression checks are the verified run
evidence; they are not a claim that the old visible process was restarted.

No measured speedup percentage is claimed. The verified performance improvement
is removal of hidden-card work and redundant printer-chart rebuilds.
