# UI / UX source audit — 2026-09-19

Source baseline: `64a512a`. This folder contains synthetic UI evidence, not customer data.
No product UI fixes, installer build, release, Host calls or printer calls were made.

- `manifest.json`: 12 selected successful runs, 262 captures including repeats,
  actual logical window dimensions, captured tab names and KPI elision examples.
- `control-measurements.json`: rendered state comparisons, empty Counter save,
  substring translation and table-data translation reproductions.
- `findings.json`: 22 open findings matching the Thai audit report.
- PNG files: 24 selected native Qt captures. They are not design mockups.

All selected runs had empty `errors` and `network_attempts`. Earlier harness-only
errors were corrected and rerun; stale output folders ending `-extra` are not
included. Images outside this folder remain under ignored `outputs/ui-ux-audit`.

The audit uses `tools/audit_ui_v5.py` with the existing Qt source-test runtime.
Example from the repository root in PowerShell:

```powershell
$auditPython = 'C:\Users\User\Documents\KOMI Report V5\.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
& $auditPython tools/audit_ui_v5.py --mode pages --width 1024 --height 640
& $auditPython tools/audit_ui_v5.py --mode pages --width 1440 --height 900
& $auditPython tools/audit_ui_v5.py --mode dialogs --width 900 --height 600
& $auditPython tools/audit_ui_v5.py --mode wizard --width 900 --height 600
& $auditPython tools/audit_ui_v5.py --mode controls
& $auditPython tools/audit_ui_v5.py --mode evidence --width 900 --height 600
& $auditPython tools/audit_ui_v5.py --mode pages --width 1024 --height 640 --only settings
& $auditPython tools/audit_ui_v5.py --mode pages --width 1024 --height 640 --only reports
$env:QT_SCALE_FACTOR = '1.5'
& $auditPython tools/audit_ui_v5.py --mode pages --width 900 --height 600 --language en
& $auditPython tools/audit_ui_v5.py --mode pages --width 900 --height 600 --language en --only settings
Remove-Item Env:QT_SCALE_FACTOR
& $auditPython tools/audit_ui_v5.py --mode dialogs --width 900 --height 600 --language en
& $auditPython tools/audit_ui_v5.py --mode wizard --width 900 --height 600 --language en
```

The final tool adds expanded states to a normal pages/wizard run, so a fresh run
may capture more images than the historical matrix in this manifest. The first
English main-page run preceded the `scale_factor` manifest field; its known 1.5
factor was recorded when consolidating evidence.

Qt uses the offscreen platform and registered Windows fonts. The MainWindow
screen-fit function is replaced only to avoid the artificial 800×800 offscreen
display clamp; layout minimum sizes remain active. Sizes in the manifest are
logical client sizes, not physical screen pixels. OS chrome, actual DPI changes,
System Tray, screen readers, native file pickers and production registration
require separate real-device verification. Emoji fallback in these captures is
not treated as proof of a packaged-application icon defect.

The network hook rejects socket connect/sendto/bind; background services are not
started. Wizard uses edit mode, and all writes are to a temporary fixture database.
The empty pinned-Counter save intentionally exercises that synthetic preference.

This audit does not rerun the full application regression suite or the one-year
Excel performance benchmark. Web-evidence export responsiveness is a source-path
finding, not a measured freeze duration.
