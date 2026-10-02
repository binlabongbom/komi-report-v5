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

## Validation

Validation uses an isolated Mac checkout with Python 3.14.7 and the repository's
locked dependencies, plus Node 24.21.0/npm 12.1.0 for Web. Runtime/CI Ruff,
the 5.2.12 version gate, Web typecheck, all 19 Web tests and the production Web
build passed. The actual source startup smoke exited successfully with a
temporary database and no Host transport calls.

Cross-platform test setup needed three corrections: retain a QApplication on
every offscreen platform; close widgets before the isolated database fixture
restores its bootstrap path; and compare path components instead of assuming
Windows separators in the macOS autostart assertion. The affected five suites
passed all 37 tests. Application/runtime and Web contents remain byte-identical
to the shipped macOS source; no assertion is skipped or weakened.

The initial full Mac run was interrupted by a host disconnection after 250
completed batches and preserved its failure evidence. A fresh full run is
required after the fixture corrections. Final Mac results and Windows CI links
are recorded in [PR 41](https://github.com/binlabongbom/komi-report-v5/pull/41)
before merge. The desktop runner deliberately excludes the five release-assembly
suites documented in `DESKTOP_CI.md`; installers are not rebuilt in this task.

### Current validation blocker

The full Mac run on `6732990` completed all 2,134 planned cases with no missing
cases: 2,133 passed, one failed and three teardown errors (the latter accompany
otherwise passing cases). The teardown errors came from lifecycle tests mocking
`QApplication.instance()`; cleanup now retains the real session application.
The affected tray/UI suites passed 19/19 after that correction.

The remaining failure is intermittent:
`test_web_export_worker_keeps_ui_responsive[4096-pdf]` raises
`RuntimeError: wrapped C/C++ object of type QAbstractTextDocumentLayout has been deleted`
at `services/web_evidence_export.py:67`, while setting the PDF layout paint device.
Three fresh repetitions of the exact eight-case batch passed twice and failed
once; a diagnostic run independently captured the same source traceback. This
is not resolved by the validated fixture changes, and the suite is not green.

Keep the PR draft pending diagnosis and a validated resolution consistent with
the source-alignment scope. No runtime workaround, skip, weakened assertion or
merge bypass has been applied. These results concern source tests on Python
3.14.7/Qt 6.11.2; they are not an installed-package reproduction. The published
Mac verification records Python 3.14.3.

Existing release evidence retains its documented signing, Host staging E2E,
live-printer and tray/autostart limitations. This source merge does not change
those results or claim a new production acceptance.
