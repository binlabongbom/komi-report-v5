# KOMI Report V5 — Support Matrix

| Platform | Status | Supported scope | Release evidence required |
|---|---|---|---|
| Windows 10/11 x64 | Pilot | Desktop, polling, SQLite, portable runtime | Native clean-machine launch, printer read, tray/autostart and restore UAT |
| macOS Apple Silicon | Pilot | Desktop local bundle, polling, SQLite | Native bundle launch, tray behavior, printer read and restore UAT |
| Linux x64 | Planned | Core Desktop/reporting only; print/calibration is not yet supported | Choose AppImage or Flatpak, then native launch/polling/SQLite UAT |

## Release gates

1. Run Python tests, focused Ruff checks for changed modules, TypeScript check, and dependency lock validation.
2. Build on the target OS; do not cross-claim a package checked on another OS as UAT.
3. Check package contains no database, logs, runtime cache, `.env*`, bytecode or development credentials.
4. Verify clean-machine launch, upgrade/backup/restore and controlled device read separately from live billing acceptance.
5. Code signing/notarization and TLS/security rollout remain separate decisions; current security behavior is an approved exception, not a production security pass.
