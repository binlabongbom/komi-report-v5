# KOMI Report V5 — Support Matrix

| Platform | Status | Supported scope | Release evidence required |
|---|---|---|---|
| Windows 10/11 x64 | Release target — RC blocked until native/signing/UAT evidence closes | Desktop, polling, SQLite, OS vault, LAN Web HTTPS, per-user installer | Native x64 clean install/upgrade/restore/uninstall, signed artifact and controlled printer/billing proof |
| Windows 11 ARM64 VM | Preflight only | x64-emulated package/install/launch checks and Windows behavior triage | Must remain labelled VM/ARM; never substitutes for Windows x64 native acceptance |
| macOS Apple Silicon | Internal UAT | Desktop local bundle, polling, SQLite, LAN Web HTTPS | Native bundle/tray/printer/restore UAT; customer Production blocked until signing/notarization |
| Linux x64 | Deferred | No Production claim in V5.2.2 | A later approved phase must choose package format and run native UAT |

## Release gates

1. Run Python tests, focused Ruff checks for changed modules, TypeScript check, and dependency lock validation.
2. Build on the target OS; do not cross-claim a package checked on another OS as UAT.
3. Check package contains no database, logs, runtime cache, `.env*`, bytecode or development credentials.
4. Verify clean-machine launch, upgrade/backup/restore and controlled device read separately from live billing acceptance.
5. Verify `RC_MANIFEST.json`, `CHECKSUMS.sha256`, `FILE_INVENTORY.json` and `SBOM.cdx.json`; signing must be `verified` before Production GO.
6. Registration remains fail-closed without an approved policy artefact. Phase 3 Update is deferred and no Update runtime path may be packaged.
7. Follow `RELEASE_SUPPORT_AND_RECOVERY.md`; VM/offscreen/automated results must not be promoted to native or real-device evidence.
