# Desktop component and page ownership

Updated: 2026-09-24

The desktop application imports each page from its owning feature module. `pages.py` and `v5_pages.py` retain explicit class/function aliases for existing callers; they contain no duplicate implementation and do not forward arbitrary module mutations.

## Shared components

| Component | Responsibility | Variants retained by callers |
|---|---|---|
| `ui/components/toner_bar.py` | Percentage validation, unknown state, painting and Qt properties | Overview height/width and device-card height/width; old private class names remain thin subclasses |
| `ui/components/metric_card.py` | Title/value/detail labels and safe A3/A4 detail formatting | Overview horizontal layout and integer formatting; Reports grid, translation and responsive number fitting |
| `ui/components/task_header.py` | Settings title, wrapping description and action placement | Immediate action versus expandable editor; page owns signals, drafts and saving |
| `ui/components/notices.py` | Compact modal notice layout | Calling page supplies title/message |

`ui/styles/text.py` owns escaped paper-size rich text. Other visual rules remain in `ui/styles/`. Business calculations stay in services/page data preparation. The components do not query the database.

`TaskHeader` is a layout, so existing card widget parentage and Qt stylesheet scope stay intact. Metric and toner wrappers retain object names and attributes required by the existing UI and tests. Differences between Overview and Reports are explicit options or subclass layout code, not copied paint/detail-format implementations.

## Feature modules

| Location | Contents |
|---|---|
| `ui/setup/wizard.py` | Setup navigation, worker lifetime, persistence and enrollment coordination |
| `ui/setup/steps/` | Company, device selection, pricing and review components; step-local input validation and presentation |
| `ui/setup/appearance.py` | Shared combo/calendar appearance using central style definitions |
| `ui/setup/workers.py` | Cancellable device tests, discovery, connectivity, snapshot and enrollment workers |
| `ui/setup/controls.py`, `legacy_import.py` | Wizard controls and legacy-history import dialog |
| `ui/pages/overview.py` | Main overview and its metric/toner variants |
| `ui/pages/devices.py`, `device_overview.py` | Device cards/import wrapper and identity/connection overview |
| `ui/pages/imports.py`, `activity.py`, `manual.py` | Import/preview, pipeline log and retained document viewer |
| `ui/reports/page.py` | Report page lifecycle, background snapshot jobs, filtering, cache and export coordination |
| `ui/reports/export_dialog.py` | Export period/content selection |
| `ui/reports/charts.py` | Shared Qt chart series, axes, hover behavior, semantic colors and legends; GUI thread only |
| `ui/reports/legacy.py` | Existing report base and optional plotting backend state |
| `ui/settings/page.py` | Settings tab composition and routing |
| `ui/settings/fleet.py`, `controls.py` | Settings coordinator, save transactions, dirty navigation, schedule controls and web access-code dialog |
| `ui/settings/sections/` | Billing, schedule, autostart, registration, network and support section components |
| `ui/settings/billing_audit.py` | Audit loading, table and detail dialog |
| `ui/settings/legacy.py` | Existing settings tools still composed into the current Settings page |
| `ui/parser_editor.py` | Shared parser-editor window retention/opening |
| `ui/policy.py` | Shared visibility policy for edition-specific customer entry points |

`ui/cloud_reports.py` owns report composition, tables, selections and responsive layout. It delegates chart rendering to `ui/reports/charts.py`. `PageHistoryV5` still derives from the legacy report base because existing export/reconciliation paths use it; the normal application keeps its staged initialization.

## Report chart preparation

`services/report_chart_models.py` contains immutable, Qt-free chart values. `services/report_snapshot.py` prepares Overview and Printers chart models in the existing background job and caches them within the same period and generation as their snapshot. Cancellation is checked while aggregating and again before applying a snapshot. The GUI creates Qt objects from those values; direct/non-staged callers and identity-filtered timelines use the same pure builders as a fallback. Interactive Users selections still prepare their selected values in the UI and use the shared renderer.

Rendering preserves the approved categories and meanings:

- The five categories are always `Print Color`, `Print B&W`, `Copy Color`, `Copy B&W`, `Scan`, in either UI language. The first four stack dark A4 and light A3; Print is blue, Copy orange, Scan green.
- Overview timeline keeps separate Print/Copy bars and one centered date label per day, with A4/A3 stacked.
- Printers timeline keeps one bar per day, stacking slots in slot order with dark Color/light B&W per printer. Slot names come from configuration.
- Legends wrap whole entries and retain `A4 | A3 Print` / `C | BW Slot …` order. Existing chart replacement/disposal owns Qt lifetime.

Users report snapshots prepare their complete table model in the worker using
`services/report_user_counters.py`. This temporary projection keeps daily
canonical counters, subject/physical-device identities and review flags for the
existing breakdown and daily cost calculations. It uses the same effective Raw
selector as Legacy, including archive, amendment and shared-history precedence.
Only the completed Users model is sent to Qt; a Users snapshot has no
full `raw_counter_records`. Legacy and Excel load full Raw independently.

User display names use the shared placeholder predicate and name preference in
`komi_snmp_profiler/subject_identity.py`. Subject daily cache and period aggregation
keep a real name when a later observation contains only an ID or blank name.
The real-name observation day is separate from the latest meter date; existing
archive summary JSON optionally carries `_name_date` without a schema change.
`services/report_subject_names.py` resolves selected Subject/Raw evidence once,
scoped by slot, physical printer, subject type and exact subject ID. Modern Users
table/chart models and the Users Excel sheet use this same index. Real names may
retain the existing cross-printer presentation grouping; numeric placeholders
cannot establish that grouping. Legacy Raw views retain original audit labels.

Users requests bound daily usage reads to the selected preview period. Their
process-local incremental read models live in `services/report_day_projection.py`:
schema 34 tracks every hot Subject/Raw insertion, update and deletion by device
and day. An unchanged day reuses its compressed immutable rows; dirty days alone
fetch source payloads again. Daily category breakdowns also memoize exact
canonical values. Period aggregation and daily price allocation remain fresh.

The day cache retains at most 32 MiB of compressed payload, 2,400 entries and
4 million source rows. It is separate from the UI snapshot generation, so a
refresh can reuse validated days. Database generation/path, mutation tokens and
amendment exclusions form its identity. Archive verification and shared-history
reads retain their existing precedence. It uses no persisted serialized objects;
restarting the application discards it. Schema migration uses the existing
transactional upgrade and pre-upgrade backup path.

## Setup and Settings composition

Setup steps communicate through explicit signals and values. `PricingSelection` and `SetupReviewData` capture values for validation/review without having the review component read arbitrary wizard controls. The wizard retains device I/O, registration, saving and async cancellation.

Settings sections receive explicit actions and dependencies. Billing owns its draft and verifies that the requested values were persisted; Schedule owns row values and validation; Network owns controls and local presentation. Fleet still coordinates shared-setting confirmation, OS autostart and Web service transactions. Existing widget aliases remain explicit for the Settings shell's layout composition. The former `ui/network_settings.py` host-mutation builder is replaced by `ui/settings/sections/network.py`.

## Dependency and lifecycle rules

- Import classes/services from the owning module. Feature modules must never import `pages` or `v5_pages` compatibility facades.
- Settings composition may import Setup, Activity and Billing Audit; these modules do not import the Settings composition root.
- Setup steps and Settings sections must not import their wizard/fleet/page composition roots. Components must receive actions or data explicitly.
- Chart model preparation must not import Qt. Qt chart creation must run on the application GUI thread.
- `ui.reports.legacy` alone owns the mutable `pg`, `_PQG_OK` and `_pg_load_attempted` state. The current report page reads that live module, not copied values.
- Keep optional Excel/plotting dependencies lazy. Importing the desktop pages must not import OpenPyXL or pyqtgraph.
- Keep the shared parser-editor window list in `ui/parser_editor.py`; independent lists would let windows be destroyed early.
- The moved document viewer resolves diagram assets relative to the source/repository roots, not its new directory.
- Background-worker cancellation, signals, timers, report generations and executor shutdown remain with the owning page.
- Tests and synthetic UI tools patch the owner of a dependency. Patching a compatibility facade does not change a class's module globals.

## Verification

`test_shared_ui_components.py` covers toner values/geometry, metric labels/detail safety and Settings header behavior. `test_ui_module_boundaries.py` checks import order in fresh processes, class identity, lazy optional dependencies and one-way imports. `test_style_architecture.py` protects central styles.

`test_report_chart_models.py` checks arithmetic, filtering, immutable worker values, cancellation and GUI-thread rendering. `test_setup_step_components.py` and `test_settings_sections.py` exercise local validation, draft retention and explicit callbacks without constructing the whole coordinator. [DESKTOP_CI.md](DESKTOP_CI.md) documents normal PR/main regression coverage and isolated test batches.

The existing Setup, Settings, Overview, Devices, Reports, export and billing suites exercise behavior after extraction. Use separate processes for large Qt test groups on Windows. Synthetic UI capture tools disable network and use temporary databases; the native startup smoke also requires an isolated data directory.
