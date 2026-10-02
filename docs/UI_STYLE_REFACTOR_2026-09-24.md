# Desktop style refactor — 2026-09-24

Scope: centralize and deduplicate desktop presentation rules without changing the approved UI or business behavior.

## Changes

- Introduced `source/ui/styles/` with 17 modules, organized by tokens, typography, reusable components and feature scopes. See [UI_STYLE_ARCHITECTURE.md](UI_STYLE_ARCHITECTURE.md).
- Moved button behavior to `ui/button_system.py` and font construction to `ui/styles/typography.py`.
- Split business defaults from visual definitions; replaced runtime wildcard imports from `config` with explicit imports.
- Replaced **401 nonempty inline stylesheet expressions** in runtime setters with central builders/constants. The only direct string reset is `setStyleSheet("")`.
- Consolidated **54 groups of identical inline rules**, representing **125 repeated copies** beyond the first definition. Shared text rules and button/checkbox variants use builders instead of copied bodies.
- Extracted assigned table/setup/status rules and preserved local application order, responsive-density guards, inherited disabled/focus/hover behavior and all approved chart labels/colors.
- Retained small compatibility re-exports for existing `config`, `widgets.fnt` and `ui_consistency` callers; these do not contain duplicate implementations.
- Updated the color/font preview tool to edit `ui/styles/tokens.py` and added architecture regression checks.

This is a structural refactor, not a promise that the entire repository has fewer lines. Named modules, explicit imports, documentation and regression checks add lines while removing copied style definitions from pages.

## Verification

- **719 tests passed** across the 65 existing affected test files, plus **11 architecture/render tests**: **730 unique test cases**. The existing suite also reported 8 passing subtests.
- Application, overview and tab QSS exactly matched pre-refactor strings; the extracted report base, wizard light/modal and frozen-table scopes also matched exactly.
- All 130 final scoped-expression extractions matched their original AST expressions after builder parameters were substituted back. Shared-label rendering checks matched image pixels.
- Architecture checks verify all runtime style references resolve, styles cannot import business/storage/pages, preview edits the central tokens, compatibility exports share implementations, and runtime setters cannot reintroduce inline definitions.
- Source compilation, targeted Ruff checks and the version gate passed.
- Native Windows startup smoke test passed from `source/app.py --smoke-test`, using a new isolated database, runtime configuration and log directory. The live database was not used.

### Test execution notes

An early test process loaded style modules while they were being relocated and reported missing report attributes. Its full 44-case group passed again from a fresh process after the moves were complete. A separate Windows Qt process exited natively while accumulating settings widgets; all 30 settings cases passed in fresh batches of at most eight. The final verified results include those reruns, not the failed attempts.

One existing virtual-printer test emitted its expected warning for explicitly disabling TLS verification in the test compatibility setup. No runtime TLS behavior was changed.

The complete 1,751-case repository suite was not repeated for this presentation-only refactor. No installer was built, and no GitHub push was performed.

Local logs: `outputs/styles-verified-results.json`, `outputs/styles-architecture.log`, `outputs/styles-native-smoke.log`. Intermediate attempts remain in `outputs/styles-suite-results.json` and `outputs/styles-final-results.json` for traceability.
