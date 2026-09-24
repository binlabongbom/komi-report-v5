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
| `ui/setup/wizard.py` | Setup steps, navigation, validation and enrollment coordination |
| `ui/setup/workers.py` | Cancellable device tests, discovery, connectivity, snapshot and enrollment workers |
| `ui/setup/controls.py`, `legacy_import.py` | Wizard controls and legacy-history import dialog |
| `ui/pages/overview.py` | Main overview and its metric/toner variants |
| `ui/pages/devices.py`, `device_overview.py` | Device cards/import wrapper and identity/connection overview |
| `ui/pages/imports.py`, `activity.py`, `manual.py` | Import/preview, pipeline log and retained document viewer |
| `ui/reports/page.py` | Report page lifecycle, background snapshot jobs, filtering, cache and export coordination |
| `ui/reports/export_dialog.py` | Export period/content selection |
| `ui/reports/legacy.py` | Existing report base and optional plotting backend state |
| `ui/settings/page.py` | Settings tab composition and routing |
| `ui/settings/fleet.py`, `controls.py` | Fleet settings/editors, schedule controls and web access-code dialog |
| `ui/settings/billing_audit.py` | Audit loading, table and detail dialog |
| `ui/settings/legacy.py` | Existing settings tools still composed into the current Settings page |
| `ui/parser_editor.py` | Shared parser-editor window retention/opening |
| `ui/policy.py` | Shared visibility policy for edition-specific customer entry points |

`ui/cloud_reports.py` continues to own report charts/tables and its responsive layout. This extraction separates feature ownership without rewriting that renderer or splitting a single page across inheritance mixins. `PageHistoryV5` still derives from the legacy report base because existing export/reconciliation paths use it; the normal application keeps its staged initialization.

## Dependency and lifecycle rules

- Import classes/services from the owning module. Feature modules must never import `pages` or `v5_pages` compatibility facades.
- Settings composition may import Setup, Activity and Billing Audit; these modules do not import the Settings composition root.
- `ui.reports.legacy` alone owns the mutable `pg`, `_PQG_OK` and `_pg_load_attempted` state. The current report page reads that live module, not copied values.
- Keep optional Excel/plotting dependencies lazy. Importing the desktop pages must not import OpenPyXL or pyqtgraph.
- Keep the shared parser-editor window list in `ui/parser_editor.py`; independent lists would let windows be destroyed early.
- The moved document viewer resolves diagram assets relative to the source/repository roots, not its new directory.
- Background-worker cancellation, signals, timers, report generations and executor shutdown remain with the owning page.
- Tests and synthetic UI tools patch the owner of a dependency. Patching a compatibility facade does not change a class's module globals.

## Verification

`test_shared_ui_components.py` covers toner values/geometry, metric labels/detail safety and Settings header behavior. `test_ui_module_boundaries.py` checks import order in fresh processes, class identity, lazy optional dependencies and one-way imports. `test_style_architecture.py` protects central styles.

The existing Setup, Settings, Overview, Devices, Reports, export and billing suites exercise behavior after extraction. Use separate processes for large Qt test groups on Windows. Synthetic UI capture tools disable network and use temporary databases; the native startup smoke also requires an isolated data directory.
