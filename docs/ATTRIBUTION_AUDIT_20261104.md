# User attribution audit — 2026-11-04

Base: 5.2.15, commit 495e6d537ac0e1912e3f70a20e1847497c0d6c6b. Candidate: 5.2.16.

The supplied screenshots establish missing named-user usage for a bizhub 950i in KOMI, despite named cumulative counters in a printer spreadsheet. They do not establish the failed request, installed app version, or report period. These changes correct independently reproduced defects; they do not establish that the customer's missing history has been recovered.

## Confirmed defects corrected

1. The modern connector emits Account Track subjects as `account`, but the Live Meter report converter accepted only `user` and `track`. Preserve all three supported types without merging identities.
2. Administrator failures followed by successful public reads discarded the classified failure details. Preserve the diagnostic code and safe context in the fallback warning, with no additional login attempt.
3. Background polling did not surface `reading.warnings` in Sync Log. Display sanitized warnings and the auth state while retaining valid machine counters. The explicit auth-disabled evidence marker is not a failure.
4. Setup Test displayed unqualified success even when user counters were unavailable. Carry sanitized warnings into its status, tooltip and details dialog; machine-counter success remains distinct from complete user attribution.

Regression tests for the first three defects failed on the original code, then passed after the changes. Additional worker and UI tests cover warning propagation and redaction.

## End-to-end review

- Protocol: 950i has no dedicated verified profile and follows generic modern JSON over HTTPS. This is not a real-device compatibility certification. Existing explicit XML and 287 hotfixes are preserved.
- Login: modern Admin collection checks returned `MFP.LoginMode == Admin`, with one configured credential attempt, logout and cookie clearing. Public fallback can still read machine totals when Admin fails. Total-read success alone does not prove named-user access.
- PKI: current client uses password-based Administrator forms and server certificate validation/pinning. No client-certificate PKI login flow is implemented. No screenshot proves that this printer requires such a flow; do not enable/disable PKI or relax TLS on this evidence.
- Subject API: AuthType and TrackType gate user/account requests. Rejected or malformed replies preserve machine totals and generate partial-read warnings. The current maximum range is bounded at 1,000; larger directories/firmware variants require actual metadata and responses before changing request shapes.
- History: subject history requires exact subject total evidence, preserves device identity and computes deltas from recorded baselines. First cumulative counters are not historical usage allocations. Missing total fields or missing baselines require diagnosis, not invented values.
- Identity: user/account/track types and IDs are preserved; existing name enrichment replaces placeholders and ambiguous numeric aliases are not merged.
- Public User: this is currently the intentional virtual group for daily machine usage without overlapping subject history, not proof that printer authentication is disabled. No historical reallocation or change to that reporting contract is included.

## Validation and limits

Linux isolated checks: 107 collection/history/report tests, 72 setup tests, one additional warning UI test, 42 cloud smoke tests and 19 Web tests passed; focused lint, version alignment and Web production build passed. Original regression run: 45 passed, 3 failed as expected. Test evidence remains in `/workspace/komi-audit-*-20261104`.

Windows full regression and artifact build must complete before accepting a Windows installer. Hosted tests and synthetic fixtures do not replace real-printer acceptance or clean-machine installation/upgrade testing. Confirm customer version, report dates and fresh Slot 2 Test/Sync diagnostics to determine the customer's remaining cause.

## Full Windows gate follow-up

Run 41813365325 completed with 2,206 passed and 10 failed; no installer job ran. All ten failures also reproduced in an isolated checkout of unchanged 5.2.15 (55 passed / 10 failed across the six affected suites), establishing inherited release-gate gaps.

- Correct shared billing preview to use the same quantity-first pricing helper as the immutable ledger. The existing test covers atomic confirmation, idempotence, conservation and rollback; 301 pages at 2.5% waste now previews and posts 293 billable pages, not a monetary-discount result of 293.48.
- Preserve the maintained manual asset version (5.2.12) instead of demanding or relabeling nonexistent PDFs for every application patch release.
- Refresh version, migration and pricing fixtures for the shipped quantity-first contract while retaining their invariants and checks. No tests are skipped or removed.

All 99 focused gate/pricing tests pass on Linux after these corrections, as do lint and the 5.2.16 version gate. The full Windows gate is required again on the updated source SHA.
