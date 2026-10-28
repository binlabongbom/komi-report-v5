# Desktop regression CI

`.github/workflows/desktop-regression.yml` validates normal pull requests into
`main`, pushes to `main`, and manually requested runs. Checkout has no fixed
branch or commit override: GitHub tests the pull request merge commit or the
commit that triggered the main push. The regression job uses a hosted Windows
runner, read-only repository permissions, and no secrets or deployment step.
Normal PR/push runs and default manual runs only test. A manual dispatch may
explicitly set `build_installer=true` to run the artifact-only candidate workflow
after regression passes; see `CLOUD_DEVELOPMENT.md`. This optional job never
publishes a release, signs, installs the generated application or deploys.
Manual `diagnostic_files` accepts space-separated test filenames for failure
investigation; combining it with `build_installer=true` fails before testing.
Failed batch tracebacks are also printed in the ordinary job log, so an artifact
download is not required to identify a failing test.

Python comes from `.python-version` (currently 3.14.7). Runtime and development
packages use the existing Windows and development lockfiles with hash checking
and binary wheels. The job fails on the focused runtime import/unused-code lint
rules already used for this repository; it does not suppress test failures.

## Tests and isolation

`tools/ci/run_desktop_tests.py` discovers all `source/tests/test_*.py` files,
including nested test directories and newly added tests. Five release/package
assembly suites are explicitly excluded in `EXCLUDED_FILES`; the JSON report
records their names and reasons. This workflow focuses on desktop behavior,
including architecture boundaries, shared components, setup/settings, reporting,
Excel calculations, database services, and UI/performance regressions.

Pytest first writes an authoritative JSON collection. The runner then starts a
fresh pytest process for each batch of at most 8 cases. This avoids accumulated
Windows Qt widget/thread lifetime state from a monolithic test process. A failed,
timed-out, crashed or incomplete batch makes the entire run fail, even when other
batches pass. Later batches still run so their evidence remains available.

Every collection and batch process receives its own temporary application home,
user profile, roaming/local application data, bootstrap database, runtime
configuration, peer state and logs. Legacy database discovery receives an
explicit absent test path. Inherited `KOMI_*` overrides and pytest filters/plugins
are discarded before applying the runner's own settings. The normal pytest
database fixture adds per-test database isolation. LAN discovery is disabled.
An opt-in Python audit hook permits only loopback sockets and DNS, allowing local
HTTP/HTTPS fixtures without contacting printers or Internet services. Wildcard
socket binds are narrowed to loopback before binding, so local discovery fixtures
do not expose listeners to the LAN. Python children that inherit the runner
environment receive the same hook through
`sitecustomize`; this is a test safeguard, not a sandbox for native subprocesses.
The workflow uses GitHub/PyPI to fetch actions and dependencies and upload evidence.

## Run locally

From the repository root with the project's virtual environment activated:

```powershell
python tools/ci/run_desktop_tests.py
python tools/ci/run_desktop_tests.py --files test_shared_ui_components test_report_models
```

Optional `--batch-size`, `--timeout` and `--output-dir` flags support focused
investigation. Use a new output directory for each run; existing result manifests
are never overwritten. The default is a timestamped directory under `outputs/`.

## Evidence

The workflow uploads only lint output, collection, batch logs, JUnit XML and
result JSON. Temporary databases and runtime state are outside the artifact
directory. `results.json` records the tested commit, exact planned/executed cases,
real top-level outcome counts, separate subtest counts, missing/unexpected cases,
exits and timeouts. Failed subtests also fail the batch. A run left
with `complete: false` was interrupted or could not collect its tests; it is
never treated as successful.
