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

Validation is in progress on the isolated Mac checkout using Python 3.14.7 and
the repository's locked dependencies, plus Node 24.21.0/npm 12.1.0 for Web.
Exact results and CI links will be recorded before merge.

Existing release evidence retains its documented signing, Host staging E2E,
live-printer and tray/autostart limitations. This source merge does not change
those results or claim a new production acceptance.
