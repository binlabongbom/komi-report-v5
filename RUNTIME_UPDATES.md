# Runtime and development toolchain — 24 September 2026

This update targets stable releases compatible with KOMI Report V5.2.12. Node
uses the supported 24 LTS line. Python prereleases and incompatible transitive
major versions are deliberately excluded.

| Component | Validated version |
| --- | --- |
| CPython (development and embedded Windows runtime) | 3.14.7 |
| Qt / Qt Charts native libraries | 6.11.2 |
| PyQt6 / PyQt6-Charts bindings | 6.11.0 |
| pyqtgraph | 0.14.0 |
| cryptography | 50.0.1 |
| FastAPI / Uvicorn | 0.141.1 / 0.53.0 |
| keyring / truststore | 25.7.0 / 0.10.4 |
| openpyxl / pysnmp | 3.1.5 / 7.1.29 |
| Node.js / npm | 24.21.0 / 12.1.0 |
| Next.js / React | 16.3.6 / 19.3.0 |
| TypeScript / tsx | 7.0.2 / 4.23.15 |
| pytest / Ruff | 9.1.1 / 0.16.8 |
| PyInstaller / uv / pip-audit | 6.22.3 / 0.12.18 / 2.10.1 |
| Git for Windows CLI (project-local MinGit) | 2.55.0.windows.5 |

All resolved dependencies and hashes are recorded in `source/uv.lock`, the
production requirements lockfiles, the new `source/requirements-dev.lock.txt`,
and `web/package-lock.json`. Production and development dependencies remain
separate. npm 12 permits the pinned esbuild installation script explicitly;
unrelated dependency scripts are not granted blanket permission.

## Local development

From this repository in PowerShell:

```powershell
. .\tools\activate-dev.ps1
python --version
node --version
npm.cmd --version
git --version
uv pip sync --python .venv/Scripts/python.exe --require-hashes source/requirements-dev.lock.txt
npm.cmd ci --prefix web
.\tools\start-dev.ps1
```

The activation script selects `.venv` and the verified runtimes under `.tools`.
It changes only the current terminal environment. The Node and Git installations
used by unrelated applications are not replaced. `.tools` and `.venv` are local
build prerequisites, not files to commit or ship to customers. Python must match
`.python-version`; Node must match `.node-version`. The Node archive is verified
against its official SHA-256 checksum. MinGit is verified against the GitHub
release asset digest.

## Build and CI

The Windows builder now packages Node 24.21.0 and prepares its web build with npm
12.1.0. The security workflow uses Python 3.14.7 and the same Node/npm versions.
Workflow actions are updated to checkout 7.0.1, setup-python 7.0.0,
upload-artifact 7.0.1, and download-artifact 8.0.1. Self-hosted runners must support
Node 24 actions (runner 2.327.1 or later). No remote runner upgrade or GitHub
workflow run is implied by this local change.

## Validation and limits

- Web TypeScript checking, 9 security tests, 2 numeric tests, and the production
  build passed using the new toolchain.
- `pip check`, Python compilation, release version consistency, and `uv lock
  --check` passed.
- npm audit and pip-audit reported no known package vulnerabilities at audit time.
- Desktop regression validation is recorded in
  `tmp/runtime-update-20260923/isolated-tests/summary.json`: **1,701 tests passed
  across 199 test files, with zero failures, errors, or skips**. Files run in
  separate processes to isolate native Qt state; corrected failing files were
  rerun and merged into this final result. The initial combined run exposed
  resource callbacks being cleared during cyclic Python/Qt destruction. Cleanup
  now uses retained, once-only finalizers, with dedicated Python/Qt/parent
  destruction tests. The original affected group subsequently passed all 309
  tests in one process; the 14 navigation/export regression tests also passed.
- Older test fixtures were aligned with the existing asynchronous report/export
  flow, Slot display names, daily chart evidence, and external delivery manuals.
  Date-range, ledger, error-reporting, and workbook-content assertions remain.
- Shared-epoch tests now record observations before checking the canonical
  journal, verify a 10-page next-day delta and 40-page combined delta, and check
  that member-local caches do not create duplicate ledger postings. Startup
  doubles include the manual-read feedback label used by the real shell.
- The built standalone web server served `/` and `/login` successfully under
  Node 24.21.0. Installed local Python packages, Node, source, and web runtime
  were updated without creating an installer. Existing data and credentials
  were preserved; old code/build directories are backed up under
  `tmp/runtime-update-20260923/`. VM 105 and remote CI were not exercised here.
- After the final regression run, `tools/start-dev.ps1` reopened the source app.
  Its KOMI main window responded, both configured device polls completed, and
  the active Next.js `/login` endpoint returned HTTP 200. The running Node
  process uses the verified project-local 24.21.0 executable.

Package audits do not prove the absence of native-library vulnerabilities.
Official CPython 3.14.7 currently embeds OpenSSL 3.5.7; Node 24.21.0 embeds 3.5.8,
and cryptography 50.0.1 embeds 4.0.2. CPython's DLLs are kept as its official
distribution rather than replaced with an unvalidated ABI combination.

Sources: [Python releases](https://www.python.org/downloads/),
[Node 24.21.0](https://nodejs.org/en/blog/release/v24.21.0),
[Qt 6.11.2](https://www.qt.io/blog/qt-6.11.2-released),
[Git for Windows](https://github.com/git-for-windows/git/releases/tag/v2.55.0.windows.5),
[GitHub checkout runner requirements](https://github.com/actions/checkout).
