# Export Excel — 90-user source regression

Measured on 19 September 2026 in the task worktree, based on `8b3e31b` plus
the Excel fixes in this change. No customer database, printer, Host, installer
or release build was used.

## Problem and changes

Reports had a header Export button and equivalent buttons in four date toolbars.
The toolbars now contain only the period controls; the header button serves every tab.

The old handler read history and generated the workbook on the Qt GUI thread.
The writer also scanned the entire Raw history repeatedly for each user/day/operation
and repeatedly filtered it for Legacy cells. These paths explain prolonged UI blocking
on this synthetic workload; they do not prove the exact cause in the customer's old installation.

The handler now captures the selected database and inputs, then reads history and writes
Excel in one background worker. Database connections in that worker are read-only and
settings reads bypass the app-wide cache. The GUI collects progress/results using a timer.
The writer indexes evidence once and reuses per-day calculations, preserving missing-value
semantics and per-operation currency rounding. It publishes a completed temporary file
atomically; cancellation or failure does not replace an existing destination.

## Workload and measurements

Fixture: 90 users, three printers, 30 days; eight exact Print/Copy paper counters
for each user/device/day, 65,520 Raw rows. No network calls. The export timer starts
after preparing the in-memory data and ends after the controller collects completion.
It includes Qt setup and writing the workbook, not database loading or subsequent validation.

| Measurement | Result |
| --- | --- |
| Old synchronous writer | Still unfinished at 195.9 seconds; synthetic process stopped |
| Indexed writer via background controller | 8.887 seconds |
| Workbook size | 53,883 bytes |
| User rows verified | 90 |
| Pages per user, all three printers | 720 |
| Cost per user on the first printer | 480 |
| GUI timer / simulated button clicks during export | 567 / 567 |
| Largest gap between GUI timer callbacks | 26.0 ms |

These are single local measurements, not a service-level guarantee. Real database size,
archives, storage and period length can affect total export time. No real customer
database or packaged installer was tested. The baseline did not finish, so its completed
workbook and total runtime are unavailable.

- [Stopped baseline](excel-export-before.json)
- [Completed background run](excel-export-after.json)
- Reproduce the completed run: `python tools/benchmark_excel_export.py --ui --name current`
  using the project's Python environment. Temporary workbooks remain under ignored `outputs/`.

## Correctness and interaction checks

### One-year follow-up

At the user's request, repeated the same background-controller benchmark on commit
`dbe711e` with **365 days**, 90 users and three printers: **797,160 Raw rows**.
The writer completed in **60.101 seconds** and produced a 154,236-byte workbook.
All 90 user rows passed validation: 8,760 pages per user across three printers,
and 5,840 cost per user on the first printer. During export the Qt event loop
processed **3,758 timer callbacks and simulated button clicks**, with a largest
callback gap of **135 ms**. No sustained GUI freeze occurred in this fixture.

This timing has the same limits as the monthly run: it excludes fixture preparation,
database/Archive loading and workbook validation. It does not guarantee the duration
or responsiveness of a real customer installation on different hardware.

- [One-year measurement](excel-export-one-year.json)
- Reproduce: `python tools/benchmark_excel_export.py --ui --days 365 --name one-year-ui`

### Regression suite

The focused run covers 17 source test files. It passed 150 tests, followed by 28 tests
in four files after an additional varying-price/missing-evidence assertion and final
fixture/manual adjustments. Latest results per file: **151 passed in 17 files**, with
no failures or skips. This is not a new run of all 1,380 tests from the previous checkpoint.

- Date selection and cancellation do not load history on the GUI thread.
- A real isolated SQLite service test excludes data outside the requested dates.
- A real Reports page event loop remains responsive while a deliberately slow database
  loader runs on the worker; duplicate requests are ignored and failures restore the button.
- The 90-user workbook verifies user rows, usage, cost, Legacy rows and daily rows.
- A separate workbook checks unequal daily rates and missing daily cost: Print 12,
  Copy 8, total 20; missing evidence remains unavailable instead of a fabricated zero.
- Cancel, synthetic write failure and a locked destination preserve the original file
  and remove temporary workbooks. The controller supports retry and shutdown cancellation.
- Switching the application's database while exporting does not switch the worker's database
  or leak its settings into the application cache.

An initial integration run encountered a native QtCharts abort after a sequence of old
widget tests began processing deferred events. The old integration test now waits for
its worker and collects its result directly on the main thread; all 19 tests in that file
pass. Separate fresh-page and controller tests still process a real Qt event loop.

- [Initial run, including failure](excel-export-initial-regression.json)
- [Successful 17-file run](excel-export-regression.json)
- [Final four-file run](source-followup-regression.json)

The actual Reports screenshot and the Thai/English in-app guide were updated. The source
PDF was regenerated and all ten pages visually reviewed. Packaged-manual copying tests
and the 5.2.12 version gate pass; no package was built.

## Progress popup follow-up

Replaced the basic progress dialog with a dedicated popup showing a progress bar,
stage percentage, completed user count and elapsed time. Percentage advances on real
stage and per-user completion, not on a simulated timer; elapsed time updates once
per second. It does not claim a remaining-time estimate. Cancel, window close and
Escape request cancellation and keep the popup visible until the worker stops.

The updated 90-user test verifies intermediate and final user progress, workbook values
and GUI responsiveness. The controller test checks elapsed time and that cancellation
waits for worker acknowledgement. [Five affected test files passed, 47 tests](excel-popup-regression.json).
An actual synthetic export completed while capturing `reports-excel-progress.png` for
the guide. The Thai/English in-app guide and source PDF were updated. The PDF keeps
compact popup images at native size instead of enlarging them to full-page width.
