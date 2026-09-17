# KOMI 5.2.12 — approved work and handoff

User authorized sequential autonomous implementation on 2026-09-17. Continue
completed items into the next unblocked item. Park only decisions that genuinely
need user input. Communicate in Thai. No installers, release builds, deployments,
publishing, or production Host/customer mutations until explicitly authorized.
Source tests and local previews are allowed. Update this file with evidence.

## Baseline / preserve

Work only in this worktree, branch codex/v5.2.12-registration-recovery, based on
bf453738b934dcf5bea59dd8c70e191b52ba6b89 (committed 5.2.11).
Do not modify the original Documents/KOMI Report V5 checkout. Do not import its
uncommitted registration-pending unlock policy. Current recovery work is a
disabled foundation, not a working customer Hotfix. UI preview is a prototype.

## Approved requirements

1. Equal peers, no permanent Primary/Secondary. Every member collects printer
   readings, exchanges missing observations without double counting, and shares
   backups/settings. Sync at startup and every five minutes. Offline peers catch
   up. Automatic LAN joining/rejoining. Unlimited computers, one company with
   three shared printer slots. Member list with connectivity and last sync.
2. Settings changes shared across members; confirmation popup lists old/new
   values and warns all members are affected, offline members later. No new admin
   account module. Conflicts require selection. Audit machine/time/old/new;
   selective undo creates another audited change and requires confirmation.
3. Prices have an effective date. Retroactive recalculation previews dates,
   affected billing periods and differences before confirmation. Issued/closed
   reports remain immutable; create amended versions and differences.
4. Slot replacement preserves history and accumulated usage. Require a real new
   serial/meter read, show old/new confirmation, use the new meter as baseline,
   sync identical baseline to peers. Same serial with falling meter raises an
   alert shared by all peers; no silent reset or negative usage. Missing days:
   recover actual history where available, otherwise show interval usage without
   invented daily allocation. Do not automatically hold all catch-up usage.
5. Network settings redesign: name การตั้งค่าเครือข่าย, consistent controls,
   fewer nested frames, Web URL/open/copy, collapsible port, shared member
   controls instead of permanent roles. Clear save/service feedback. Audit in
   Status/history. Test actual save/cancel/restart and port conflicts.
6. Web refresh every 60 seconds plus manual refresh. Keep last successful data
   and timestamp with stale warning when offline. No false zero on initial
   failure. Passwordless reports by default, optional password, preserve prior
   locked settings. Shortcut created on installation plus recreate control;
   every computer opens its own local Web service (supersedes redirection).
7. Headless agent owns collection/sync/Host/Web; closing UI releases UI resources
   but keeps agent running. Reopen without duplicate services. Tray action to
   stop everything requires confirmation. Measure whole-process-tree CPU/RAM,
   idle/collection/sync/Web and lifecycle transitions.
8. Twelve recent months detailed. Older data summarized monthly per printer and
   user; archive originals by year, load only on explicit detail request or
   confirmed retroactive recalculation. Validate before removal, preserve audit
   and availability across peers. No uncontrolled deletion of original data.
9. Registration certificate Hotfix is installer opt-in after normal verification
   fails, initial contract registration only, bound durable idempotent retry,
   permanent closure after valid acknowledgement. Status/Meter keep normal TLS
   and queue retry. No global TLS change, no temporary/free activation policy.
10. Refactor touched monolith sections behind regression tests. Identify dead
    code before deleting. Inventory old evidence and verify commit/push/tag or
    Release plus references before removing any. Preserve Git history and useful
    regression tests. Refresh manuals/screenshots after behavior settles BEFORE
    any user-authorized build.

## Unresolved — park dependent release behavior

- Hotfix Host authentication: native Windows trust vs verified pin. No approved
  pin exists. Do not trust an unvalidated observed certificate.
- Authoritative company identity and Host company-wide three-slot enforcement;
  LAN name/discovery alone is not proof of company membership. User deferred
  investigating Host showing only one name after settings sync; inspect separate
  installation IDs rather than assuming shared identity is correct.
- Missing data across price/billing boundaries: inspect available source history;
  do not invent a daily allocation or pricing rule.
- Installer architecture/build workflow awaits explicit user decision.

## Work order / status

- [x] Persist requirements and blockers.
- [x] Capture regression baseline and inventory current edits.
- [x] Web: periodic refresh + correct stale/initial-failure behavior, local UI checks.
- [ ] Extract network settings and implement approved view with real behavior.
- [ ] Agent/UI lifecycle and tray; measure resource usage.
- [ ] Peer identity/data/settings replication, conflicts, audit and undo.
- [ ] Slot replacement and meter reset safeguards.
- [ ] Effective pricing, previews and amended reports.
- [ ] Archive and performance on large database.
- [ ] Complete registration recovery once trust/config decision is available.
- [ ] Evidence/dead-code audit, documentation/manual updates.
- [ ] Multi-instance source tests; two-machine installer/upgrade tests WAIT BUILD.

## Existing evidence (not release approval)

### 2026-09-18 continuation — falling meter safeguard

- Moved to slot/meter work while native Tray verification remains outstanding.
  Found daily cache treated a falling counter as a zero reset and added its new
  absolute value to usage (100→7 added 7). Removed that automatic interpretation.
- Counter drops now retain the known accumulated delta and observed raw values,
  record a per-counter review marker and warning in the pipeline log, and stop
  accumulating that counter until an explicit resolution exists. Catching back
  up above the former value does not silently clear review. Other counters are
  not rewritten. Existing billing reset hold is retained.
- Review evidence persists in daily source JSON and carries forward for the
  same device identity across restart/day rollover, direct Web fallback without
  SNMP heartbeat, and intervening offline-only days. This does not change the
  separate missing-interval pricing policy or invent daily usage.
- Cache/billing/polling/report regression: **46 passed**. After adding offline-day
  carry-forward coverage, daily cache suite: **19 passed**. Temporary DB only.
- NOT complete: explicit reviewed baseline resolution + audit, confirmation UI,
  shared peer resolution, new-serial slot replacement and retained slot totals.
  This safeguard must not be presented as a completed replacement workflow.
  Historical finalized rows are unchanged; no automatic historical correction.

### 2026-09-18 continuation — idle footprint and cancellation state

- Handoff now explicitly records ready/cancelled state. An unready or cancelled
  request cannot commit, and late timer events cannot revive a cancelled request.
  Handoff/tray/lifecycle regressions: **23 passed**.
- Added reproducible Windows experiment `tools/measure_idle_runtime.py`; raw
  results: `docs/V5_2_12_IDLE_FOOTPRINT.json`. Six fresh subprocesses (3 per
  mode), each with its own temporary database. Real MainWindow construction,
  offscreen show/refresh/close versus constructed BackgroundAgent + AgentTray.
  Workers not started, Web disabled, no printers configured. Python network and
  child-process launch attempts blocked by audit hook inside each sample.
- Median interpreter working set after 5 seconds idle: desktop **95.85 MiB**,
  Agent + Tray **67.63 MiB**, approximately **29.4% lower**. Observed idle CPU
  sample: desktop 0%, agent 0–0.31% of one core. Short samples/Windows counters;
  do not interpret zero as no CPU use. This excludes Web/Node, interpreter
  launcher overhead, active collection/sync and loaded customer history. It is
  NOT a whole-process-tree or production workload benchmark.
- First harness attempts failed during close because its network audit hook
  raised RuntimeError where network callers handle OSError. Corrected the
  fixture to raise OSError (still denies connection); all six final samples
  then closed cleanly. No confirmed product crash from that harness failure.
- Remaining: complete GUI→Agent→GUI lifecycle with active synthetic reads and
  local Web fixture, OS tray verification and whole-tree resource sampling.
  Source feature still pending full validation; no build or Host/customer edits.

### 2026-09-18 continuation — source desktop-to-agent handoff

- Source desktop close now prepares an independent `--tray --handoff` agent
  while keeping the current window and collectors alive. A private temporary
  rendezvous carries ready/commit/cancel. Only a live, ready child is committed;
  the child cannot start collection until the desktop lock is released after
  old workers drain. Closing UI then exits the large desktop process.
- Failure before readiness keeps the current UI/services. Unsaved draft approval
  is deferred until readiness, and the draft is not discarded before commit.
  Reopening the window or choosing explicit full-stop cancels an uncommitted
  handoff. Duplicate close attempts reuse the pending request.
- Packaged/frozen close behavior and autostart are unchanged pending packaging
  verification; default agent launch is still headless unless `--tray` is passed.
  This is a source implementation, not installer/release validation.
- Real subprocess tests run the actual child main with offscreen tray availability
  substituted and collection start replaced by a marker. They prove no start
  before commit or while the desktop lock remains held, cancellation without
  collection, and child cleanup. No real printer or Host calls are made.
- Handoff/agent/tray/setup/startup suite: **43 passed**. After adding draft and
  reopen regressions, tray lifecycle alone: **13 passed**. Native OS tray display,
  complete real GUI close/reopen, process-tree RAM/CPU and Web continuity still
  need verification. Do not mark the entire Agent feature complete yet.
- Next: measure and verify this source lifecycle in an isolated environment;
  retain the no-build restriction and avoid customer DB/Host traffic. Then move
  into remaining peer/slot/archive work, parking authoritative Host decisions.

### 2026-09-18 continuation — worker cancellation prerequisite

- While tracing UI-to-agent handoff, found two existing shutdown hazards:
  cancelling queued futures invokes completion callbacks immediately, removing
  entries from the dictionary being iterated; queued timer/network/status events
  could submit to a shut-down executor or try to resume a stopped collector.
- Polling pause/stop now iterate a snapshot. Stop serializes with submissions
  using the existing rollover lock, then releases locks before draining workers.
  Scheduled/manual reads and direct submissions no-op after shutdown.
- Registration runtime ignores late timer/retry/network/config/completion events
  after stop; desktop and agent ignore late collection-gate changes on shutdown.
- Lifecycle/polling/registration/tray suite: **49 passed**. Added the matching
  pause cancellation regression and reran lifecycle: **9 passed**. The tests use
  real queued futures with a blocked synthetic worker, no printer/Host calls.
- Desktop-close handoff is still NOT wired. Safe integration needs child tray
  readiness before parent stops, failure recovery that retains the existing UI,
  and ownership transfer only after worker drain. Continue this next; do not
  mark lightweight-agent feature complete from these prerequisite fixes.

### 2026-09-18 continuation — isolated Agent tray

- Added `ui/agent_tray.py` and opt-in source `background_agent.py --tray`.
  This mode uses QApplication for a tray only; default remains QCoreApplication.
  No desktop, report pages or chart imports. Tray offers open and confirmed stop;
  opening leaves agent running until the desktop acquires its lock and requests
  takeover. Failed launches keep collection running and allow retry. Repeated
  clicks are throttled. Child gets the same database path and no Windows console.
- macOS 27 keeps the existing native status-menu workaround via a small
  asynchronously opened dialog. macOS behavior is source-only, not device-tested.
- Tray/lifecycle regression: 21 passed; added fresh-process import boundary test
  and reran tray file: 6 passed. No real OS tray clicks, collection or Host calls.
- Not wired into desktop close or autostart yet. `--tray` fails explicitly when
  the OS tray is unavailable, instead of leaving an agent without visible stop
  controls. Next wire and verify desktop-close handoff with launch-failure
  recovery and in-flight worker drain; keep explicit full-stop separate. Then
  resource measurements. No claimed RAM savings yet; no build or deployment.

### 2026-09-18 continuation — shutdown safety

- System Tray stop now requires explicit confirmation (Cancel is the default),
  preserves the separate unsaved-settings check, and ignores duplicate exit
  actions once shutdown starts. Cancel leaves all workers and Web running.
- Desktop now drains polling/registration workers before releasing its instance
  lock, closing the reverse takeover race as well as the agent-to-desktop race.
- Agent IPC reads split stop commands asynchronously instead of blocking Qt;
  unknown commands return an error and cannot stop the agent. Named-pipe server
  access is restricted to the current OS user.
- Lifecycle/tray/setup/startup source tests: **30 passed**, including split pipe
  delivery, unknown command rejection, stop cancellation, unsaved draft refusal,
  and duplicate stop actions. Tests use isolated databases and local IPC.
- Remaining Agent work is substantial: closing UI still hides the large desktop
  process; no memory reduction is claimed. Next implement an independently owned
  tray/runtime and a verified desktop-close handoff (or disposable UI client),
  preserve setup/settings operations, then measure total process tree CPU/RAM.
  The existing agent has QCoreApplication only and no tray; simply exiting the
  GUI and spawning it would remove the user's tray stop control. Do not ship
  that incomplete shortcut. Do not enable production services for measurements.

### 2026-09-17 overnight implementation

- Web source: 60-second refresh, 20-second request timeout, complete-snapshot
  updates, preserved old data/time on partial or full API failure. Initial
  failure shows an unavailable message instead of zero usage. Date selector
  recovers after initial outage. TypeScript `tsc --noEmit --incremental false`
  passed on a temporary copy with existing dependencies (no release build).
- Isolated local API/browser fixture: auto-refresh changed 175 to 225 pages,
  350 to 450 THB without clicking, exactly one minute apart. Stopping the fixture
  retained 225/450 and the old successful timestamp with a stale warning.
  Reload during outage showed unavailable, no zero summary cards. Restart
  recovered data, date range and removed warnings. Fixture uses synthetic
  readers; not a real printer or two-machine end-to-end test.
- Web API/report snapshot/registration recovery: 36 tests passed.
- Extracted network controls into `source/ui/network_settings.py`; simplified
  three sections, collapsed port, visible disabled open/copy actions. Existing
  save/password/port/cancel bindings preserved. Settings/navigation: 36 tests
  passed after the changes. Rendered actual widget at 1080x1000 in offscreen Qt;
  `Temp/komi-lan-settings-qa/lan-settings.png`. Full application theme/mobile
  review and final peer member UI remain; current share control is setup-only.
- Agent handoff safety: desktop acquires its lock before requesting stop; agent
  publishes ownership while holding desktop exclusion; takeover waits for agent
  lock release, fails closed on timeout. Agent drains running polling/Host
  workers before releasing lock. Lifecycle/polling/runtime/instance suite:
  36 passed; the lifecycle file then passed all 4 tests including two added
  real-worker drain checks.
  This fixes takeover overlap; it does NOT yet implement persistent agent
  ownership with an independent tray and disposable UI.
- Continuation automation `komi-5-2-12` resumes this thread every 30 minutes.
  Preserve it while work remains; pause it when all unblocked work is complete.
- Additional startup/tray/setup regression: 21 passed. Certificate/registration
  foundation: 19 passed, still disabled pending trusted transport choice.
- Saved local commits: `3f48800` web refresh, `4262bd2` network controls,
  `4573d40` agent takeover safety. No push, installer or production changes.

Next: finish Agent ownership/lifecycle design and source tests; keep the real
desktop/customer DB untouched. Then peer/settings/slot work, archive and manuals.
Do not erase this distinction between foundational fixes and completed features.

- Earlier recovery/runtime/setup/TLS run: 108 passing, then added recovery tests
  passed 11 (see conversation); must recheck after changes.
- Web/report source tests: 32 passing. Browser on isolated API fixture confirmed
  manual refresh 120→175 pages, 240→350 THB; initial implementation rendered zero
  after API failure and had no auto-refresh. Actual customer printers not tested.
- Capacity fixture: outputs/capacity-5-years/result.json and simulate.py.
  Synthetic DB in Temp/komi-capacity-04538ad9: 1,826 days, 3 printers, 100 users
  on each daily, 2 raw counters per user, 30 device counters, 1,818,696 rows,
  1,127,170,048 bytes after checkpoint, quick_check ok. Size experiment only;
  repeated daily templates do not prove financial correctness or real workload
  performance. Do not commit the large synthetic database.
