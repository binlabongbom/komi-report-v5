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
