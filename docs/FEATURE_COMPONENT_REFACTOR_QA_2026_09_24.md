# Feature component refactor verification — 2026-09-24

Baseline: `73c56f5`. Scope: Overview/Printers chart preparation and shared Qt rendering, Setup step components, Settings section components, and normal PR/main desktop CI. Existing report meanings, filters, billing rules, save confirmations and UI geometry are preserved. No installer or remote deployment is part of this validation.

## Ownership and behavior

- Overview/Printers chart values are prepared by the existing cancellable snapshot worker and cached by period/generation. Qt widgets remain on the GUI thread. Interactive Users selections continue to prepare selected values locally and share the renderer.
- Setup coordinator: 3,675 → 2,748 lines. Four step components own their forms and local validation; the coordinator retains I/O, registration, saving and worker lifetime.
- Settings coordinator: 1,954 → 1,452 lines. Six section components own their controls and local values; the coordinator retains dirty navigation and shared-setting/OS/Web transactions. The old network builder that mutated an arbitrary host is removed.
- Report composition: 2,734 → 2,582 lines, with chart data and rendering now in separate modules. These are coordinator reductions, not a claim that all moved code disappeared.

## Visual and native checks

- Twelve chart renders in Thai/English have identical pixels, values, series labels and colors compared with the baseline renderer.
- Thirty-six synthetic desktop page captures at 1440×900 completed without errors or network attempts. Thirty-one are pixel-identical to the prior baseline. The remaining differences are the animated device status dots, current times and generated temporary database paths.
- Twenty-six Setup captures cover both languages at 1024×640. All thirteen Thai baseline comparisons preserve window/control sizes, size hints, fonts and scroll ranges. Six images are pixel-identical; the remaining differences are runtime data and localized button paint/focus. The existing Thai Review check-mark glyph issue is unchanged.
- Native Windows source startup smoke exited successfully in 4.03 seconds, using a separate database, runtime, logs and APPDATA. It shut down cleanly.
- Ten chart replacements destroyed all 22 observed chart objects after close; no chart wrapper remained live.

## Performance comparison

The synthetic database contains 200 users, three printers and five years of history. Both runs preview one year, with the same data and offscreen Windows fonts. These are single before/after runs; OS cache and system scheduling were not controlled, so small differences do not establish a speed improvement.

| Measurement | Before | After |
|---|---:|---:|
| Median warm Overview switch, five cycles | 162 ms | 159 ms |
| Median warm Printers switch, five cycles | 168 ms | 166 ms |
| First report navigation | 6.00 s | 6.06 s |
| First one-year Overview | 2.54 s | 2.54 s |
| First one-year Users | 31.27 s | 26.79 s |

Warm chart switching remains comparable. This refactor establishes worker preparation and clear ownership; it does not resolve the separate cold Users loading cost. Both UI measurements blocked three attempted synthetic socket connections; no real printer was contacted.

Local evidence is under `outputs/`: `report-ui-{before,after}.json`, `report-charts-{before,after}.json`, `report-chart-render-parity.json`, `feature-page-parity.json`, `feature-ui-review/`, and `setup-component-visual-20260924/`. These generated files are not runtime dependencies.

## Regression checks

Final local validation passed **1,830 top-level cases and 8 subtests**, with no failures, errors, skips or expected failures:

| Scope | Cases | Subtests |
|---|---:|---:|
| Final desktop runner: 206 files, 222 fresh processes | 1,772 | 8 |
| Five release/package contract suites, separate fresh processes | 58 | 0 |

The final runner reports `complete: true`, `successful: true`, no missing cases and no unexpected cases. Runtime and runner Ruff checks and staged whitespace checks passed. The runner was corrected during validation to keep discovery fixtures on loopback, discard inherited test filters, count subtests separately, and isolate the bootstrap database through runtime configuration without masking the Setup database-choice behavior. Earlier incomplete/failed diagnostic runs are retained and are not counted as the final result.

Evidence: `outputs/feature-full-regression-final/{results,collection,source-snapshot}.json`, its batch logs/JUnit files, and `outputs/feature-excluded-suite-results.json`. SHA-256 verification matches all 524 captured source/test/harness/lock files. One whitespace-only Fleet cleanup during the run is recorded in the snapshot with identical AST before/after.

The normal desktop workflow and local runner are documented in [DESKTOP_CI.md](DESKTOP_CI.md). Local validation also runs the five release/package contract suites omitted from that workflow; they use synthetic packaging fixtures and do not build a real installer. GitHub execution requires the committed workflow to be pushed and has not been triggered by this local validation.
