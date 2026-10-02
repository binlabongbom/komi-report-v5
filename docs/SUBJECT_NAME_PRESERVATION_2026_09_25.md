# Preserve real user names in report history

The collector already replaces numeric ID placeholders with exported printer
names. That rule did not cover all later stages: a newer daily Subject row could
replace a real name with an ID, and reporting could group leading-zero numeric
placeholders from different printers as though they were the same real name.

The existing `subject_name_is_placeholder` rule remains authoritative. The new
`prefer_subject_name` helper keeps known names through ID/blank observations and
accepts actual renamed users. Whitespace-only collector names fall back to the
subject ID. Real-name dates are tracked separately from meter dates, preserving
the newest meter and totals even when its name is unavailable. A period's
optional `name_observed_on` comes from the derived bucket's ISO `_name_date`;
existing archive summary JSON is accepted without this metadata. No additional
schema version or rewrite of old daily/billing evidence is required.

Modern Users table/chart models and the main Users Excel sheet resolve names
from already-selected Subject and Raw evidence using `report_subject_names.py`.
The lookup key includes slot, physical printer identity, subject type and exact
ID. Numeric aliases of display names do not establish cross-printer identity.
Known conflicting serials stay separate; a legacy slot-only record can use a
single identity only when no competing identity exists in the selected data.
Actual real-name presentation grouping remains compatible. Missing real names
remain IDs; no name is invented. Legacy Raw sheets retain original audit labels.

The Users Excel sheet also applies unambiguous legacy identity aliases to its
printer columns. A slot-only record and a later serial-identified record for
the same printer therefore share one column group, preventing repeated Raw
operation totals when both forms occur in the selected history.
Legacy slot-based device-day price evidence fills missing physical identity
keys only. Exact serial evidence, including zero, wins; competing serials
disable this fallback. Both the screen and Users Excel use this rule.

## Verification

All checks use isolated runtimes and synthetic databases. No customer database,
installer, or visible customer application was modified or launched.

| Evidence directory under `outputs/` | Passing cases |
| --- | ---: |
| `subject-name-history-regression-2026-09-25` | 50 |
| `subject-name-preservation-tests-verified` | 15 |
| `subject-name-archive-tests-2026-09-25` | 3 |
| `desktop-ci-subject-report-names-20260925-03` | 41 |
| `desktop-ci-subject-report-names-20260925-04` | 3 |
| `subject-name-integrated-regression-2026-09-25` | 78 |
| Total distinct cases | 190 |

Coverage includes real names followed by IDs/blank names, leading zeros, true
renames, all permutations of daily row ordering, same-ID users on different
slots/serials/types, Raw-only name recovery, full/compact reader equality,
unchanged pages/prices, archive summaries, amendments, cache invalidation,
snapshot/UI consumers and generated Excel cell values. Ruff F/E9 and the Git
whitespace check also pass. Mixed legacy/serial records have one Users Excel
printer group, unchanged page totals and retained prices; conflicting serials
remain separate. `subject-name-final-verification-2026-09-25/verification.json`
records the distinct case union and final source hashes.

`upgrade-v5.2.4-name-fix-2026-09-25/` recreates a database with release commit
`aa8bda3`, migrates schema 19 to 34, compares every original column/row in 21
tables, verifies the pre-upgrade backup, SQLite integrity and repeat startup,
and reads the resulting histories. A separate copy uses IDs 123/124 with Thai
names. Both names survive migration and warm reads; changing the latest Subject
name to `123` still yields the known real name in both Subject history and the
Users presentation model. `result.json`, `name-result.json` and
`source-hashes.json` record the evidence. This is a source migration rehearsal,
not an executed installer upgrade. Its hashes retain the rehearsal snapshot;
the final verification manifest also covers the subsequent Excel identity and
legacy price lookup corrections.

The performance measurements from September 24 precede this name fix. No new
first-load performance claim is made and no repeated cold-load tuning was done.

## Follow-up: one person across printer-local IDs

Desktop Reports groups the same real name and subject type into one row, with
separate Slot 1/2/3 usage and costs, even if each printer uses a different local
ID. The Users Excel sheet now uses the identical presentation group key rather
than additionally splitting on the local ID. Its ID cell retains the original
IDs with slot labels when they differ. Raw counters are still selected by the
exact printer, subject type and local ID, once per source identity. A shared
numeric placeholder alone cannot merge users; different real names remain
separate. Existing trim/case-insensitive name matching remains unchanged.

`outputs/subject-cross-printer-grouping-2026-09-25-03/results.json` records 39 passing
cases on this follow-up, including seven new cases for two/three printers with
different IDs, per-slot prices, multiple IDs in one slot and distinct names
sharing the same local ID. Counter derivation and cost rounding occur separately
per exact source identity before summing the display row. Positive usage with
missing counter/price evidence keeps the combined cost unavailable. Regression
cases cover mixed counter formats, separately rounded allocations, and missing
Raw evidence. These 39 overlap the earlier verification suite and
are not added wholesale to its count.

## Web report parity

Web Users and Overview now use the same presentation grouping as Desktop and
Excel. The Users API resolves names and physical identities for the full selected
range before pagination, returning additive `report_user_key` and
`report_device_identity` fields. Original IDs, usage and audit fields remain
unchanged. A fresh nonempty snapshot reads compact user counters once, bounded
by selected dates and slots, so real names present only in counter evidence are
also recovered. Cached pages reuse the resolved payload. No full Raw-history read
is added; first-snapshot timing has not been measured for this change.

The Web row builder sums usage and per-printer subtotals using these shared keys.
Numeric placeholders remain scoped to their source, User and Account Track stay
separate, and older API payloads without grouping keys retain source identity.
Search, selection, user counts and both charts consume the resulting rows.

`outputs/web-user-name-api-20260925-02/results.json` records 33 passing API cases
(18 new and 15 existing). Frontend checks pass on Node 24.21.0: eight report-user
cases, nine security cases, two numeric-format cases, and TypeScript validation.
Microsoft Edge UI verification used paginated synthetic responses in an isolated
Web copy: one Thai name across three printers gives one row with 170 pages and
100/50/20 printer subtotals, while two identical numeric placeholders stay
separate. Search, clearing, keyboard selection, Thai/English and desktop/mobile
layouts passed with no browser console errors. Browser evidence is outside the
repository in the temporary QA workspace; no live customer database was used.
