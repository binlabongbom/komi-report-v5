# Desktop UI/style architecture

Updated: 2026-09-24

The desktop presentation rules live in `source/ui/styles/`. Pages construct widgets, select their visual state and arrange layouts. They call named stylesheet builders/constants instead of defining QSS in each constructor.

## Ownership

| Location | Owns |
|---|---|
| `ui/styles/tokens.py` | Application colors, platform fonts, typography sizes, geometry and chart defaults; no Qt or storage imports |
| `ui/styles/typography.py` | `fnt()` and Qt font construction |
| `ui/styles/application.py` | Application stylesheet, including focus, hover and disabled states |
| `ui/styles/navigation.py`, `overview.py` | Page tabs and overview stylesheet scopes |
| `ui/styles/text.py` | Reusable label declarations; callers supply text state/appearance values |
| `ui/styles/buttons.py`, `inputs.py` | Shared button variants, parser actions and legend checkboxes |
| `ui/styles/surfaces.py`, `tables.py` | Cards, banners, badges, dividers and table/header scopes |
| `ui/styles/reports.py` | Report palette, chart/table controls, responsive density, export progress and billing review |
| `ui/styles/setup.py` | Setup wizard, company fields, device selection and price inputs |
| `ui/styles/settings.py` | Settings, network controls, schedule and sync status |
| `ui/styles/devices.py`, `shell.py` | Device/import views and application shell |
| `ui/styles/legacy.py` | Existing preview/manual component styles kept for their current callers |
| `ui/button_system.py` | Application-wide button size, radius normalization and motion behavior |
| `ui/components/` | Shared widget construction/painting: toner, metric labels, task headers and compact notices |
| `widgets.py`, `ui/pages/`, `ui/setup/`, `ui/settings/`, `ui/reports/`, other `ui/*.py` | Widget composition, layout, state and interaction; no direct nonempty QSS literals in `setStyleSheet` |
| `pages.py`, `v5_pages.py` | Compatibility class/function re-exports; runtime composition imports the owning modules |
| `config.py` | Business defaults and compatibility exports, not a second style implementation |
| `ui_consistency.py` | Compatibility re-export of the button system |

Dependency direction: `tokens → stylesheet builders → widgets/pages`. The typography helper additionally depends on Qt. Styles do not import pages, services, the database or application configuration.

Page and component ownership is documented in [UI_COMPONENT_ARCHITECTURE.md](UI_COMPONENT_ARCHITECTURE.md). Shared components do not access storage or depend on feature pages.

## How to change appearance

1. Change app-wide colors, fonts and dimensions in `ui/styles/tokens.py`.
2. Change a shared component in its component module. Use options for genuine variants (for example `dialog_action(compact=True)`), rather than copying rules.
3. Change a feature-specific selector in its scoped module, such as `reports.py`. Keep selectors scoped to the owning component.
4. Keep widget/data access in the page. Pass the computed color, slot or object name into a pure builder; do not pass the widget itself.
5. Preserve stylesheet application order. A local Qt stylesheet can mask application-level disabled/hover rules, so moving all rules onto the application is not equivalent.
6. Keep the responsive-density change guard in the report widget, to avoid repeated re-polishing of every descendant.

The existing palettes are intentionally preserved. This refactor does not impose a new visual design or make unrelated feature colors identical. Data access, billing calculations and report limits are outside this change.

`source/tools/preview_colors.py` now reads and writes the authoritative `ui/styles/tokens.py` and rebuilds the application stylesheet from those tokens. Existing imports from `config`, `widgets.fnt` and `ui_consistency` remain available as references to the central implementation, not copies.

## Regression protection

`source/tests/test_style_architecture.py` checks dependency direction, compatibility references, theme-preview authority, component variants, matching rendered label pixels, resolution of every runtime style reference, and rejection of direct nonempty inline styles in runtime setters. Clearing an override with `setStyleSheet("")` is allowed.

Run these tests with the project Python environment and `QT_QPA_PLATFORM=offscreen`. The regular UI/report/setup tests cover layout, states, navigation, grouped tables and export behavior. Qt-heavy Windows tests may need separate processes to avoid accumulated native widget state.
