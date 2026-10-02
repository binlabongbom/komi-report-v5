# Align main with shipped 5.2.12

The owner authorized merging the shipped Windows and macOS 5.2.12 source into
`main` on 2026-10-02. This is source alignment; it does not publish, rebuild,
retag, replace, or approve new release artifacts.

## Source selection

The published [v5.2.12 release](https://github.com/binlabongbom/komi-report-v5/releases/tag/v5.2.12)
and its `RELEASE_CONTENTS.json` identify:

| Shipped artifact | Source commit |
| --- | --- |
| Windows Online | `9f678ec4c0dcb090644ece2edc3f3ea3565e384e` |
| Windows Offline and release tag | `2e4d1a51c23ec9656664b28e9352105aa3cdd2bd` |
| macOS arm64 Online and Offline | `0e8b07d0477d7890fffbc346da536ad44b4c4c3c` |

The two macOS build receipts independently identify `0e8b07d`. The downloaded
release manifest and both verification ZIPs matched the SHA-256 digests returned
by GitHub. All three source commits are ancestors of the selected macOS commit.
The pre-alignment `main`, `facc677a130132bd7d7b0d5c42dcb6c3b768ba9a`, is 123
commits behind it and has no unique commits.

The three commits after the release tag contain isolated macOS edition builds,
full bundle/source/edition receipt validation, clean Web rebuilds, packaged
edition smoke checks, and Offline Wizard guidance. They are shipped fixes and
must be retained. No later feature branch or dependency update is included.

## Workflow safety

Three historical installer/release workflows are now manual-only:

- `native-windows-x64.yml`: assembles an installer under legacy V5.2.6 paths.
- `publish-v526-release.yml`: edits/publishes V5.2.6 and overwrites its assets.
- `rebuild-v527-free-signed.yml`: rebuilds/signs the historical V5.2.7 release.

Their old main-push triggers would otherwise run during this alignment. Their
manual jobs are preserved. Desktop regression remains enabled for PRs into main
and main pushes. Free Security Audit remains enabled for relevant main changes.
No release workflow is dispatched by this task.

## Approved PDF lifetime repair

After the source-alignment checks exposed an intermittent macOS PDF export
failure, the owner approved the minimal runtime repair before merge. A Web
evidence export now retains one worker-owned QTextDocument, replaces its HTML
for each existing 48-row chunk, and releases it before QPdfWriter in the final
cleanup. Pagination, cancellation points, progress reporting, error propagation
and atomic destination replacement remain in place.

This is the only application/runtime change beyond shipped `0e8b07d`; Web
contents are unchanged. It addresses the observed deleted
QAbstractTextDocumentLayout failure without rebuilding or replacing installers.
The underlying Qt/PyQt defect is not claimed to be proven.

## Validation

Validation uses an isolated Mac checkout with Python 3.14.7 and locked Qt 6.11.2
packages, plus Node 24.21.0/npm 12.1.0. Runtime/CI Ruff, the 5.2.12 version gate,
Web typecheck, all 19 Web tests and the production Web build passed.
Comparing exports of 128 and 4,096 synthetic points before and after the PDF
repair produced respectively 9 and 264 pages, with identical extracted text on
every page.

Cross-platform test fixtures retain a QApplication on every offscreen platform,
close widgets before restoring the isolated database, avoid lifecycle test
doubles during cleanup, compare autostart path components portably, and use an
explicit +07:00 reference timestamp with +07:00 device records. The summary
suite was reproduced under UTC and Asia/Bangkok; after the timestamp correction
both zones passed 9/9. The export responsiveness test waits in its worker until
six GUI heartbeat samples exist, so very fast XLSX exports can be measured;
the original heartbeat-count and two-second limit remain, and the measured
interval now also covers startup and completion.

The earlier full Mac run on `6732990` executed all 2,134 cases: 2,133 passed,
one PDF failure and three teardown errors. Those results are preserved as
failure evidence. Windows CI on `2ca2473` passed all 2,134 cases before the
approved PDF repair. Fresh repeated export checks, full Mac results and Windows
CI for the final candidate are recorded in
[PR 41](https://github.com/binlabongbom/komi-report-v5/pull/41); merge is gated on
the final checks, not the earlier passing Windows run.

Mac dependency files acquired native hidden flags, which caused Qt to skip its
platform plugins before tests could start. Local validation uses byte-identical
plugin copies in an isolated temporary directory via QT_PLUGIN_PATH and
QT_QPA_PLATFORM_PLUGIN_PATH. Installed wheel-record hashes were checked; no
package versions or application plugin-loading code were changed for this
local environment repair.

The desktop runner excludes the five release-assembly suites documented in
`DESKTOP_CI.md`. Native installers, live Host/printer UAT, signing and
notarization are not repeated. The published Mac receipt used Python 3.14.3;
these source checks do not claim installed-package acceptance. Existing release
limitations remain unchanged.
