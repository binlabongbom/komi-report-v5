# KOMI Report V5 — Release Runbook

## Before packaging

1. Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` from `source/`.
2. Run focused Ruff checks for every changed module; the repository-wide legacy baseline is tracked separately and must not grow.
3. Run `npm run lint` in the configured Web runtime.
4. Confirm the package source contains no local DB, log, cache, `.env.local`, `__pycache__` or `.DS_Store`.

## Per operating system

- **Windows:** Build the portable kit on the release workflow, then perform the clean Windows 10/11 x64 UAT with `START_KOMI_REPORT.cmd`.
- **macOS:** Build the local arm64 bundle on macOS, verify checksum, then run the clean-machine UAT. Signing/notarization is a separate release gate.
- **Linux:** Do not claim support until an AppImage or Flatpak is produced and tested natively. Print/calibration is currently out of scope.

## Evidence to record

- package name, SHA-256, OS/build architecture and source revision;
- automated test/lint results;
- clean-machine launch, DB migration/backup/restore and tray/background result;
- live printer and billing acceptance as separate evidence.
