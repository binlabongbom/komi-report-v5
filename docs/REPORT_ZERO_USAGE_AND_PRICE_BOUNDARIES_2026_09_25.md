# Reports: zero user usage and unchanged price boundaries — 25 September 2026

Screenshots at 11:06 showed empty Users charts and printer rows marked for review with unavailable cost.

## Verified causes

- Slot 3 has a valid initial meter of 2,475. Its device Print/Copy/Scan deltas remain zero, so the usage report intentionally has no usage row for it. This is distinct from a failed device read.
- Slot 3 user1/user2 have verified counters with zero opening, closing and usage. A chart with labels and empty axes made that state unclear.
- Real subject counters use `counter.user.print.full_color` / `bw` and corresponding large counters. Report operation mapping expected the device `*_total` form, so future nonzero user Print/Copy usage could also be missed.
- Saving Wizard on 25 September added dated price records for Slot 1/2, but all four prices stayed exactly the same as 22 September. Report projection treated every effective date as a change, causing a false `interval_crosses_price_change` review hold and suppressing otherwise valid costs.
- The stored warning for Slot 1/2 subject reads claimed unreadable firmware schema, but its catch block also covered transport and rejected attribution requests. The persisted warning does not establish which underlying failure occurred.

## Changes

- Actual price transitions are resolved by one read-only helper shared by normal reports, evidence inspection and billing amendment preview. Audit price rows remain untouched. First price coverage and real rate changes remain boundaries.
- A zero-usage interval crossing a price/billing boundary does not hold later usage; nonzero ambiguous intervals remain held.
- User charts show an explicit zero-usage message, distinguish incomplete details, and retain table rows. Real nonzero readings replace the message with charts. Five-category names stay in English in either UI language.
- Subject operation mapping accepts real Auth/Track counter shapes within one subject/printer scope, with alias conflict and missing-size checks. Device and subject overlapping totals cannot be summed together.

## Data preservation check

On an isolated SQLite backup of the real data, the original screenshot totals remain:

| Printer | Pages | Gross THB | Net THB (2% discount) |
|---|---:|---:|---:|
| Slot 2 | 869 | 1,360.60 | 1,333.39 |
| Slot 1 | 766 | 1,197.40 | 1,173.45 |

Both costs become available and the false review flag clears. Hashes of ten existing tables (settings, prices, categories, ledger, daily meter/raw, epoch/head, shared day and Web observations) are unchanged. No stored prices, counters, baseline values or ledger records are rewritten by these report fixes.

## Fresh physical-printer reads and remaining attribution boundary

Source restarted at 11:18. All three printers returned new device meters. Slot 1/2 explicitly rejected `POST api/AppReqGetAuthCounter` with `ResultInfo=Nack` after successful Admin/device-meter reads. Read-only common metadata confirmed AuthType `MiddleServer` for both, versus `Device` for Slot 3; TrackType is `None` for all, and both optional max fields are absent for all. No printer settings changed; diagnostic sessions logged out. The observation identifies a subject-counter endpoint rejection; it does not prove unsupported firmware or a password/TLS problem.

Added `KOMI-DATA-004` (`attribution_rejected`) with endpoint, Admin mode, authentication mode, request/response stage and sanitized ResultInfo. HTTP/session/response parsing failures retain their own diagnostics. Reading users through the MiddleServer path remains unresolved; no user usage is invented from device totals.

UI verification used an isolated copy with the production Qt report widgets because the Windows automation helper repeatedly failed to activate the real Reports window. Native startup/device reads and the Overview cost card were observed directly. Generated Users/Printers screenshots are in `outputs/report-fixes-20260925/`; they are test renders from real evidence copied to a separate database, not screenshots of the interactive app.

The full Users snapshot also exposed an older warning-classification error: the informational shared-Web provenance note alone set `needs_review=True`, despite zero resets/missing baselines/incomplete days. Only that exact informational note is excluded; unknown and actual warning notes remain reviewable.

## Final validation

- Pricing/shared projection/evidence/amendment: 75 tests passed.
- Subject mapping/name/report/Excel regressions: 92 tests passed; complete cloud report UI suite 17 passed after correcting two fixtures whose raw serial differed from the subject serial.
- Zero/incomplete Users chart states and refresh to real bars: 8 tests passed in Thai/English.
- Shared-provenance warning regression plus subject/shared history: 55 tests passed.
- Attribution diagnostics, connector, meter, error registry and support diagnostics: 91 tests passed.
- Suites overlap; these are per-run counts, not a unique combined total. Changed files passed scoped Ruff F/E9 except the verified pre-existing F402 at billing_web_amendment.py:108; git diff --check passed.
- Final production-widget render from a new isolated DB copy confirms both Users charts explicitly show 0 usage without axes, both user cost cells are 0.00, and both Printers rows are Online with numeric costs. Continued physical printing raised Slot1 to 802 pages/net1,224.61; Slot2 remained869/net1,333.39. Screenshot-period earlier totals are preserved in the table above.
- Source application was restarted with all final fixes. No installer, commit or remote publication was produced in this task.
