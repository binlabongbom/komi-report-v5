# #37 — LAN membership and runtime integration

Updated 20 September 2026. Working source based on local `main` at `35442d1`.
Issue remains **open; not ready to build**. This work does not defer Sync to a
later release and does not change the Host.

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
3. Complete ordinary report/history integration. Imported Web events currently
   populate evidence/maxima and live views. They **do not populate the legacy
   daily/subject/raw report tables or billed history by themselves**. Implement
   a deterministic projection/reconciliation path with event provenance,
   duplicate and out-of-order handling, missing-day allocation/graph remarks,
   dated prices, Slot boundaries and explicit revisions for closed reports.
   Do not simply replay old serials into the active printer's mutable cache.
   `devices.last_total`/Host meter telemetry is also not updated by the new live
   view projection. No test here claims those downstream paths are complete.
4. Finish enrollment/recovery UX and policies. Address recovery currently needs
   the local report Web service to answer discovery/contact requests. Revocation
   is local; recovery/key rotation and sharing historical identities of removed
   members need completion. There is no global revocation authority implied by
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
