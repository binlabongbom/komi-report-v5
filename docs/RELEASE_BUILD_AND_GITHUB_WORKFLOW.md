# KOMI Report V5 — Build, Version and GitHub workflow

Updated: 2026-09-01

## Decision

Use a **versioned release hub with a protected promotion step**. Source code, temporary build output, customer deliverables and historical evidence must never share the same folder level.

The existing builders remain the product authority. This workflow standardizes their input/output locations and the Git/GitHub steps around them; it does not weaken `production_go=false`, signing, native UAT, Registration, or external approval gates.

## Release-hub structure

```text
KOMI-Report-V5.2-Installers/
├── KOMI Report Vx.y.z/                 # exactly one current customer bundle
│   ├── ตัวติดตั้ง/                      # Windows EXE, macOS DMG
│   ├── คู่มือ/                          # customer guide PDF/DOCX
│   ├── ไฟล์สำหรับตรวจสอบ/              # checksums, manifests, SBOM, source archive
│   └── README-ก่อนติดตั้ง.txt
├── _Build-Staging/
│   └── Vx.y.z/<short-git-commit>/       # OS build attempts; never distribute
└── _Archive/
    ├── Previous-Releases/               # superseded release bundles and candidates
    └── MOVE_LOG_YYYY-MM-DD.md           # old path -> new path and verification result
```

Only the root-level `KOMI Report Vx.y.z/` folder is available to an installer. A successful build is still a candidate until its manifest, checksums and release gates are approved.

## Version rule

`source/komi_version.py:APP_VERSION` is the human-edited version authority.

For every new release, update the patch/minor version there and update the user-facing release documents. The existing `source/tools/version_gate.py` must then prove alignment with:

- `source/pyproject.toml`
- `web/package.json` and `web/package-lock.json`
- macOS bundle metadata and Windows installer metadata
- customer guide, install guide, release notes, support/recovery guide and runbook
- shared-contract checksum

Use semantic versioning:

- `5.2.5` — compatible defect fix or documentation/package correction
- `5.3.0` — compatible feature or user-visible behavior change
- `6.0.0` — migration or compatibility break that requires an explicit upgrade/rollback plan

Never reuse a published version number. A re-build of the same code gets a new staging folder keyed by the Git commit; it does not replace a published artifact.

## Build sequence

Run commands from `source/` with the project development environment:

1. Start from a clean committed Git revision and record `git rev-parse HEAD`.
2. Run `uv run --extra dev python -m tools.version_gate`.
3. Run the scoped/full regression, Web validation and `release_safety` checks required by the release runbook.
4. Build macOS to `_Build-Staging/Vx.y.z/<commit>/macos/` using `tools.build_macos_customer`.
5. Build Windows to `_Build-Staging/Vx.y.z/<commit>/windows/` using `tools.build_windows_rc --customer-release` on the target build environment.
6. Use `tools.build_local_release` to produce the source archive, then verify its manifest and SHA-256.
7. Use `tools.build_customer_delivery` only to assemble a cross-platform candidate. Its `HOLD` output is expected until all independent release gates have real evidence.
8. Verify every checksum and retain the OS manifests/SBOMs. Do not copy loose binaries, `payload/`, `runtime/`, `node_modules/`, DB/CSV/logs, licenses or secrets into the final bundle.
9. After an explicit release decision, promote the assembled customer folder to root-level `KOMI Report Vx.y.z/`, move the former root bundle to `_Archive/Previous-Releases/`, and append the move log.

## Git and GitHub flow

```text
codex/feature-* or codex/fix-*  -> review and tests
codex/release-vX.Y.Z            -> clean candidate build and evidence
vX.Y.Z-rc.N tag                 -> reproducible candidate snapshot
main                            -> approved source integration
vX.Y.Z tag                      -> approved release source only
```

- Commit source, release documents and sanitized manifests; never commit installer binaries, user data, `.env`, tokens, DB, CSV, logs, local runtime or build cache.
- Push the release branch and annotated candidate tag after the release-safety gate passes.
- Push `main` and final `vX.Y.Z` tag only after the required business/release approval. A Git tag proves source provenance; it does not claim OS signing, native UAT or Production GO.
- GitHub binary Releases are a later, separate decision. Upload only the checksummed final bundle after retention, signing and distribution policy are approved.

## Required promotion record

Every promotion records: source commit, version, build environment, manifest paths, SHA-256, old -> new folder paths, test result, decision owner and unresolved blockers.

The expected technical delivery state is one of `HOLD`, `RC`, or `APPROVED FOR DISTRIBUTION`; it must never infer Production GO automatically.
