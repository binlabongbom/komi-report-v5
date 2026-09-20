# #37 — LAN membership and runtime integration

Updated 20 September 2026. Runtime checkpoint: local `main` at `6d74476`;
ordinary reports/Archive/manual checkpoint: `624a617` (not pushed).
Issue remains **open; not ready to build**. This work does not defer Sync to a
later release and does not change the Host.

## Follow-up: ordinary shared report projections

Implemented after the runtime checkpoint:

- Schema 32 adds rebuildable daily/monthly evidence summaries. A reviewed Web
  assignment and its summaries commit together, before a transport receipt.
  Original Web events still retain every scheduled/manual read. The summaries
  retain actual first/maximum/last points and their event IDs, without copying
  every user's counter for every reading into a second full journal.
- Repeated deliveries do not increment sample counts or usage. Reordered reads
  produce the same maximum/deltas. Neighbor checks preserve decreases hidden
  between daily extrema. Reviewed replacement epochs do not import a used
  printer's physical opening meter as new usage.
- Ordinary Users, Raw/Legacy, usage history, report snapshots and Excel now read
  received Web history even when the receiving PC has no local daily cache.
  Missing originals are derived report rows; the original daily tables are not
  populated with fabricated reads. Printer usage not posted to the ledger is
  explicitly provisional, with no estimated money when counter checks or
  price/billing boundaries are unresolved.
- Gap totals appear on the day before reading resumes, with a remark and no
  fabricated successful-read timestamp. Charts have a separate data series
  averaged over wholly missing Web days, retain decimals and an estimate label.
  Tables/Excel retain the actual allocation rather than chart averages.
- Existing daily/archived detail and issued ledger entries take priority. A
  resumed-day record outside the selected window still blocks a second gap
  allocation inside that window. A conflicting closed financial allocation is
  marked for review; the existing explicit amendment path preserves originals.
- Bounded requests use monthly context outside the selected calendar months,
  plus actual prior/next points and the prior maximum. They do not decode all
  old daily summaries or open archived Web payloads. Calculation uses the root
  epoch's recorded fixed UTC offset on every PC, not each computer's timezone.
- Python projection loops honor worker cancellation and yield periodically to
  Qt. Request-local reuse avoids repeating device projections across views.
  Historical receipts invalidate reports even if the live maximum is unchanged.
- Upgrade indexing runs in bounded idle batches before ordinary archival and
  on peer runtime startup. Completed indexing is not rescanned on every receipt.
  No old archive file is opened automatically. Newly archived journal payloads
  leave the compact reporting summaries available.
- Archive settings now offers **Fill reports from archived history** explicitly.
  The background job verifies archived payloads and indexes bounded atomic
  batches; cancellation/retry resumes without duplicate usage. Opening the
  panel only reads metadata. Known unindexed Web dates are flagged and are not
  falsely treated as dates without any reading.

**Limits still open:** This is usage/report integration, not automatic creation
of new original financial ledger postings or remote repair of legacy originals.
Existing issued revisions remain explicit. Pre-existing archived events can now
be indexed with the explicit Archive action; automatic startup deliberately does
not open those files. `devices.last_total`/Host meter
telemetry is unchanged. First-install enrollment, recovery and final manuals
remain separate unfinished work; do not describe #37 as ready to build.

New source tests cover duplicate/permuted arrivals, an added historical read,
weekend allocation versus fractional graph values, hidden counter decreases,
cross-offset clocks, used-printer replacement, transaction rollback, rebuild,
archive-free report reads, monthly context versus a complete projection, worker
cancellation, actual Qt chart/table separation, ordinary Excel contents and two
independent databases. These are synthetic source tests, not installation tests.

Repeatable benchmark: `tools/benchmark_shared_report_history.py`, temporary
synthetic DB only, 100 users / one printer / 365 days / one reading per day.
Latest measurement: indexing 42.786 s for the complete dataset; two selected
subject periods spanning the year 8.692 s / 200 rows; full-year Raw read 7.701 s /
36,865 rows; December Overview snapshot 2.407 s / 100 users; DB 34,930,688 bytes.
The earlier Overview measurement before compact monthly context was 7.854 s.
These are worker preparation timings, not Excel writing or GUI responsiveness
measurements. One reading/day exercises daily index size, not the database size
of a deployed 15-minute collector. Timing varies by machine and concurrent work.

Report/runtime/accounting regression: **260 passed, 1 warning in 178.11 s**,
`qa/v5.2.12/issue37-shared-reports-regression.xml`. Follow-up after the explicit
Archive workflow: **49 passed in 22.79 s**,
`qa/v5.2.12/issue37-shared-archive-regression.xml`. These runs overlap.
The warning is the existing Starlette/AnyIO deprecation.
Guide/translation/Archive UI checks: **15 passed in 11.30 s**,
`qa/v5.2.12/issue37-guide-regression.xml`. Updated the TH/EN source guide,
in-app report instructions, Archive screenshot and 25-page PDF, and visually
checked the changed pages. Removed the incorrect claim that shared work was
deferred to the next release. The final guide still depends on finished flows.

### Full-year Excel and unavailable money follow-up

`tools/benchmark_shared_report_history.py --ui-export` now runs the actual Qt
export controller and worker, probes clicks/timer delivery, then opens the file
and verifies 100 users and 36,865 evidence rows. All data is synthetic. The
export took **53.402 s**, producing 1,081,731 bytes. Progress advanced through
99 before completion; 2,513 probe clicks were processed. The maximum measured
event-loop gap was **362.1 ms**, down from **630.3 ms** in the instrumented
before run. The earlier uninstrumented run reached 1,010.2 ms.

Materialized report rows no longer retain duplicate request-cache projections
while the workbook is being created. Cancellation/yield checkpoints also cover
detail notes. This reduces observed cyclic-GC pauses without changing global GC
policy. It does not make the export instantaneous or guarantee a latency limit
on customer hardware. One sample/day is not a 15-minute collection-size test.
Raw before/after measurements: `qa/v5.2.12/issue37-shared-year-export-before.json`
and `qa/v5.2.12/issue37-shared-year-export.json`.

Unpriced shared usage now shows unavailable money in the printer table and
blank money cells with review status in Excel, rather than a misleading zero or
"ready" status. Known zero prices remain numeric zero. Focused report/Excel/Qt
regression: **101 passed in 80.22 s**, `qa/v5.2.12/issue37-export-followup-regression.xml`.

## Implemented and exercised with synthetic installations

- Schema 31 stores one local group and signed member contacts. Group capability
  and installation private keys stay in the OS vault; a copied database alone
  cannot authenticate. Installation identity, observation origin, certificate
  fingerprint and contact generation are checked independently. Replayed older
  contacts cannot undo address changes or local removals.
- `PeerMembership` is a concrete LAN approval policy, not an always-true test
  authorizer or a Host license adapter. It **does not establish global company
  uniqueness**, company entitlement or a server-issued company identity.
- `PeerTransportFactory` creates separate per-installation dual-use TLS leaf
  certificates. Both ends verify pinned approved leaves and current membership.
  No shared CA private key or OS trust-store change is used.
- `PeerNetworkNode` connects the existing settings, Web evidence, Slot epoch,
  billing amendment, election and shared-reader services. Tests cross actual
  HTTPS sockets with independent SQLite databases and installation keys.
- `PeerNetworkRuntime` loads approved local records for both Desktop and Agent,
  watches membership changes, prepares TLS outside the Qt thread and attaches
  while collection is idle. The listener defaults to TCP 37853. There is no
  network listener or vault access for unenrolled installations.
- Startup/reconnect wakes use deduplicated IDs. Receipt audits resume after a
  failed startup. Contact exchange is paged and verifies each installation proof
  before an atomic page commit; a roster change wakes existing peers to learn a
  third computer. This does not impose a license limit on computer count.
- Known-member address recovery uses the existing UDP hints, then a public
  signed contact served by the **local desktop Web API**. Only a previously
  approved identity with valid group proof and a newer contact may renew trust.
  This is not a Host endpoint or an enrollment endpoint. Discovery failures
  leave stored direct addresses usable; discovery cannot enroll a new computer.
- Manual reads share the first active job, saved Web results cross HTTPS, and
  registration-ineligible readers yield to eligible members. Local availability
  is checked before probing offline peers. Partitioned networks may read
  independently; this is availability-based election, not distributed consensus.
- Received current Web evidence refreshes live Web/User snapshots using the
  saved reading time and maximum within the same serial/epoch. It does not
  fabricate Web freshness from SNMP or read archived JSON during normal refresh.
- HTTPS receipt notifications apply settings on the existing Qt owner. A real
  TLS integration test verifies both automatic descendant application and live
  snapshot refresh without manually calling either application method.
- Shutdown fences authorization, stops accepts and drains inbound handlers
  before ownership transfer. HTTP input has a total deadline, including slow
  headers, so a trickling client cannot retain the Agent lock indefinitely.
- A reviewed Slot reset/replacement invalidates temporary total/success state,
  including resets with the same Serial. Credentials, recorded evidence and
  closed reports remain intact. Retrying a confirmation is idempotent.
- Usage reset preserves LAN identity/capability; Factory Reset removes them
  transactionally with database changes and restores them if vault deletion
  fails. Schema migration does not alter existing accounting or origin IDs.
- The UI and English translations no longer claim these features were moved
  to the next version. Network status shows actual attached members and errors.

### Historical member provenance, schema 33

The enrolled TLS session now pulls paged historical origin proofs before Web
catch-up. Each proof retains its installation signature and group proof, with
consistent origin/member/public-key binding. An old certificate can identify
historical evidence after expiry, but it cannot authorize TLS sessions, reading
or settings access. The separate provenance table is not an active roster.

A can relay C's saved observations to B after A locally removes C. B learns
their provenance without enrolling C. Relay does not propagate local removal
as a global revocation either; an independently active membership on B remains
under B's current policy. Historical generations cannot silently replace a
newer endpoint or resurrect a locally removed member. Invalid pages roll back.

Runtime watches provenance changes as well as the active roster so existing
peers learn a newly relayed origin before its evidence. Usage reset keeps this
provenance with membership; Factory Reset removes it atomically. Existing
databases receive an additive migration; old membership records are exported
directly without needing a fabricated historical approval.

Source regression: **51 passed, 1 warning in 126.45 s**,
`qa/v5.2.12/issue37-origin-regression.xml`, including real mutual-TLS historical
relay, expired certificates, no session revival, tampering/identity collisions,
atomic rollback, bounded resume, runtime changes, migrations and reset. A stale
test that simulated losing the journal now also deletes the rebuildable report
index first, consistent with its foreign keys; the production reset path was
already covered. Warning: the existing Starlette/AnyIO deprecation.

This completes historical-origin transport, not reinstallation/key recovery,
global revocation or the end-user enrollment Wizard.

## What the user can actually do at this checkpoint

The existing installation Wizard still performs its approved initial setup
copy. **It does not create the new continuous membership records yet.** The
runtime above can load such records, but the automated tests explicitly create
synthetic approved groups. That is not an end-to-end installation result and is
not a supported customer enrollment procedure. Do not manually seed customer
databases or treat the old persistent initial-copy approval as consent to share
usage and settings continuously.

## Remaining work in 5.2.12

1. Resolve the company enforcement boundary. A company on two disconnected LANs
   cannot be proven to have only one group by local broadcasts. Existing Host
   frontend evidence is not a verified company-membership contract (see
   `V5_2_12_HOST_SOURCE_INTAKE.md`). An asynchronous question asks whether the
   accepted guarantee is conflicts found within the LAN, or must also cover
   isolated LANs. No answer has been received at this checkpoint. No Host write
   or weaker company guarantee has been silently authorized.
2. Wire explicit continuous approval and the pinned initial membership handoff
   into the Wizard. Adopt the reviewed source settings ancestry and Slot bases
   before starting peer sessions; do not create an unrelated local settings root
   or infer a used printer's starting meter. Include review, cancellation,
   retry, conflicting groups and manual IP in the actual user flow.
3. Complete the remaining accounting/legacy reconciliation. Ordinary derived
   reports and explicit old-archive indexing are now integrated as described
   above. They do not create new original financial ledger postings, silently
   replace legacy closed rows or update `devices.last_total`/Host telemetry.
   Preserve the reviewed correction workflow and price/Slot boundaries.
4. Finish enrollment/recovery UX and policies. Address recovery currently needs
   the local report Web service to answer discovery/contact requests. Revocation
   is local; recovery/key rotation need completion. Historical identities of
   removed members now relay without session access. No global revocation authority is implied by
   the LAN group secret.
5. Finish source integration tests for the complete first-install flow, restore
   and address/certificate changes across three processes, including dropped
   receipts and report/export reconciliation. Complete TCP/UDP installer rule
   preparation and status messages without building an installer.
6. Update the final TH/EN manual, screenshots and PDF after the user flow is
   complete. Current text corrections are not a completed manual refresh.
7. Keep installation/upgrade/Firewall/sleep/failover tests on this PC + Proxmox
   VM105 at **WAIT BUILD** until separately authorized. Loopback is not that test.

## Verification

Intermediate checks passed: membership/transport/runtime subset 203 tests before
schema 31; migration/reset 13; contacts/network/delivery 21; Slot/setting/polling
regressions 46; latest HTTPS/UI/API integration subset 24; translations/manual
reader coordination 9. These counts overlap and must not be added together.

Final affected source run: **297 passed, 1 warning in 226.26 seconds**;
`qa/v5.2.12/issue37-source-regression.xml`. Follow-up reader/ledger/Web amendment/
Archive/Excel/report regression: **81 passed, 1 warning in 49.07 seconds**;
`qa/v5.2.12/issue37-report-regression.xml`. The latter also verifies the final
partial-coordination status when some peers time out without exhausting the
whole election budget. These runs overlap; do not add their test counts.
Translation/manual-reader checks separately passed 9 tests in 4.93 seconds.
The warning is Starlette's deprecation of `anyio.abc.BlockingPortal`; it is not
a failing application assertion or a runtime-thread leak. `git diff --check`
passed with the repository's configured line-ending normalization.

Web source checks: `npm run test:security` **8 passed**, including the exact
read-only contact route and rejection of write/nested/enrollment paths;
`npm run lint` (`tsc --noEmit`) passed. Dependencies were installed from the lock
file in this worktree with lifecycle scripts disabled. No Web build was run.

All data and keys in tests are synthetic and all test listeners use loopback.
No installer/release build, push, deployment, Host mutation, Documents source
edit, actual A/VM105 test or customer data operation was performed.
