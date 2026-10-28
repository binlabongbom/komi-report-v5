# Develop KOMI from Cloud

Code editing, synthetic-data Python/API checks and Web builds can run in Linux
Cloud without the personal Mac. This does not turn the desktop product into a
public SaaS service. Printer/LAN, OS vault, native UI and customer installation
acceptance are separate checks.

## Source and preservation

Use a task branch from the current GitHub main after inspecting `git status`.
Preserve existing edits; do not reset, clean or stash to prepare a task.
On 2026-10-28, GitHub main and the saved checkout both resolved to
`41896f20961b54a236cd1da6ad0a5c598a10c98f`. The earlier Windows source
`2e4d1a51c23ec9656664b28e9352105aa3cdd2bd` is an ancestor, ten commits behind.
This comparison does not establish the latest Mac working-tree state.

## Fresh setup

Run from the repository root on Linux x64. Choose a new writable path for each
setup; existing environments and runtime data are never overwritten.

```bash
bash tools/ci/setup_cloud.sh /workspace/komi-development
source /workspace/komi-development/activate.sh
/workspace/komi-development/venv/bin/python tools/ci/check_cloud.py \
  --web-modules /workspace/komi-development/web/node_modules \
  --output /workspace/komi-check-001
```

Prerequisites: Git, Bash, Python 3.12+ for safe archive extraction, uv, tar,
Linux Qt runtime libraries, writable storage and access to official Python/uv,
Node and package registries. No application credentials are needed. The script
uses `.python-version`, `.node-version`, the existing uv lock and npm lock;
it installs npm 12.1.0 in a scoped Node directory when necessary. It never
starts the app or changes system binaries. `activate.sh` selects these tools
without loading the old application environment.

The Web dependency setup uses committed HEAD. The check copies tracked Web
paths from the current working tree, so edits to existing files are tested.
New Web files must be staged with `git add` before the check includes them;
staging is not a commit. Deleted tracked files fail the check visibly.

The default check runs focused lint, version gate, 42 synthetic Python/API/UI
cases, 19 Web cases, TypeScript and the Web production build. `--full` runs all
tests selected by the existing desktop runner instead of the 42-case smoke set.
The runner excludes five release-assembly suites and isolates temporary data,
home directories and Python network access. See `DESKTOP_CI.md`. Linux results
are not Windows or macOS acceptance. Inspect `cloud-results.json` and the
desktop `results.json`; an incomplete run is not a pass.

The initial pinned Linux run exposed two product portability defects. A denied
peer request now drains its bounded body without decoding or dispatching before
returning 403, preventing a Linux TCP reset from losing the response. Pricing
page margins/spacing now preserve visible billing controls at 980x620 with Linux
font metrics. Original assertions remain; two extra unauthorized-body cases
verify malformed and larger bodies are never decoded or dispatched. The style
architecture scan also excludes virtualenv dependencies identified by
`pyvenv.cfg`, while retaining application-file coverage.

## Windows installer from a Cloud-authored change

The existing `desktop-regression.yml` runs tests on GitHub-hosted
`windows-latest`, but produces no installer. Legacy `native-windows-x64.yml`
uses `[self-hosted, Windows, X64]` and hard-coded 5.2.6 artifact metadata.
Do not dispatch it as the generic current installer pipeline. Other historical
workflows can publish releases, push branches, sign or install software.

`windows-installer-candidate.yml` is a manual, artifact-only replacement path:

1. Commit and push the reviewed task branch only when authorized.
2. With authorization for the stated build scope, dispatch the existing
   `desktop-regression.yml` workflow on that branch with `build_installer=true`
   and `installer_edition=normal` (Online) or `offline`.
3. The Windows regression job must pass before its optional reusable candidate
   job runs. Ordinary PR/push runs and default manual runs only execute tests.
4. It uses GitHub-hosted Windows x64, the repository's locked Python packages,
   pinned Node/npm through the existing builder, and Inno Setup 7.0.2.
5. Download the Actions artifact and match `WINDOWS_MANIFEST.json` source SHA
   and checksums to the reviewed commit. Retention is 14 days.

The candidate workflow uses `contents: read` and the automatically provided
GitHub Actions token. It references no custom repository secret. The optional
builder variable `KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_BUILD_FILE` points to public
verification keys; this workflow does not set it or create keys. Package
downloads and Actions artifact storage require network access and available
GitHub Actions capacity.

The builder runs with `--virtualized`, keeps `release_decision=HOLD` and
`production_go=false`, and does not sign, install the generated app, create
credentials, publish a release, deploy or contact customer printers. Hosted
runner results cannot claim native physical-device UAT. A completed artifact
build is still required to validate this newly added workflow; local YAML
validation alone is insufficient. Dispatch through the existing workflow name
allows the branch version to call its local candidate workflow without merging
main first. The workflow accepts inputs from the selected branch version.
Example after the branch has been authorized, committed and pushed:

```bash
gh workflow run desktop-regression.yml --repo binlabongbom/komi-report-v5 \
  --ref codex/cloud-development-readiness-20261028 \
  -f build_installer=true -f installer_edition=normal
```

Inspect the returned run's head SHA before accepting evidence. If GitHub rejects
the branch workflow or inputs, stop and report that error; do not merge main or
alter repository permissions to bypass it.

Customer distribution remains a separate approval with signing, clean-machine
install/upgrade/restore and applicable sanitized staging evidence. No billing
backlog data from Windows is needed for this infrastructure work or authorized
for transfer by these instructions.

## Preview

The saved `komi-cloud/start.sh` opens saved runtime paths and TLS/auth state; do
not use it for a data-isolated demo. The Web app proxies the local Python API
on port 8766, with Web on 3000. Phone preview needs fresh synthetic state and
an approved authenticated preview route. Never expose the LAN Web service
directly to the public Internet. No phone-browser acceptance is claimed here.
