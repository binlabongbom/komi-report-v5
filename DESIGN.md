---
name: KOMI Report V5.1
description: A calm corporate operations console for printer reporting and billing.
colors:
  operations-navy: "#102A43"
  operations-navy-hover: "#183B5B"
  table-navy: "#00284D"
  action-blue: "#0065A3"
  action-blue-hover: "#017DD0"
  active-blue-wash: "#E9F3FA"
  workspace-gray: "#F0F0F0"
  card-white: "#FFFFFF"
  soft-surface: "#F8FAFC"
  structural-border: "#919191"
  soft-border: "#D6E0EA"
  primary-text: "#191919"
  secondary-text: "#505050"
  success-green: "#16A34A"
  warning-amber: "#CA8A04"
  danger-red: "#DC2626"
typography:
  headline:
    fontFamily: "-apple-system, 'Helvetica Neue', 'Thonburi', 'Noto Sans Thai', 'Segoe UI', sans-serif"
    fontSize: "28pt"
    fontWeight: 700
  title:
    fontFamily: "-apple-system, 'Helvetica Neue', 'Thonburi', 'Noto Sans Thai', 'Segoe UI', sans-serif"
    fontSize: "16pt"
    fontWeight: 700
  body:
    fontFamily: "-apple-system, 'Helvetica Neue', 'Thonburi', 'Noto Sans Thai', 'Segoe UI', sans-serif"
    fontSize: "12pt"
    fontWeight: 400
  label:
    fontFamily: "-apple-system, 'Helvetica Neue', 'Thonburi', 'Noto Sans Thai', 'Segoe UI', sans-serif"
    fontSize: "11pt"
    fontWeight: 600
rounded:
  xs: "4px"
  sm: "7px"
  md: "8px"
  lg: "10px"
  xl: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.action-blue}"
    textColor: "{colors.card-white}"
    rounded: "{rounded.md}"
    padding: "7px 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.action-blue-hover}"
    textColor: "{colors.card-white}"
  button-outline:
    backgroundColor: "{colors.card-white}"
    textColor: "#24506E"
    rounded: "{rounded.md}"
    padding: "7px 16px"
    height: "40px"
  card:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.primary-text}"
    rounded: "{rounded.xl}"
    padding: "12px"
---

# Design System: KOMI Report V5.1

## Overview

**Creative North Star: “The Corporate Operations Desk”**

KOMI Report is an Operate-mode desktop application for office staff who may have little technical confidence. The interface should feel calm, dependable, and immediately scannable: show the operational result first, expose the next safe action, and defer diagnostics until a support case requires them.

The visual system is a light workspace with a stable navy sidebar, white task surfaces, restrained blue actions, and semantic status color. Information density may be high in reports, but hierarchy must remain obvious and technical detail must never compete with the user’s primary task.

**Key Characteristics:**

- Five top-level destinations only: Overview, Devices, Reports, Settings, and Manual.
- Plain-language task grouping; Sync is an implementation detail, not a main navigation concept.
- Settings defaults to common operational choices, with staff-only detail routes for reading activity, billing audit, and advanced tools.
- No Settings password. Potentially destructive actions retain an explicit warning and confirmation.
- Thai and English are equal product surfaces, not a partial translation layer.

Implementation anchors: `source/config.py` owns shared visual tokens and QSS; `source/app.py` owns the five-item shell; `source/v5_pages.py` owns responsive cards, Reports, and the simplified Settings information architecture. The rendered references are `.impeccable/review/th/v5-matrix-3dev-1024x768.png`, `.impeccable/review/th/v5-1024-3dev-settings.png`, and `.impeccable/review/en/v5-1024-3dev-settings.png`.

## Colors

The palette uses sober corporate navy and a single action blue, with bright semantic colors reserved for states that require attention.

### Primary

- **Operations Navy** (`#102A43`): persistent sidebar and the application’s visual anchor.
- **Action Blue** (`#0065A3`): primary actions, links, active controls, and focus indication.
- **Table Navy** (`#00284D`): high-contrast table headers where dense data needs a firm reading edge.

### Neutral

- **Workspace Gray** (`#F0F0F0`): main application canvas.
- **Card White** (`#FFFFFF`): content sections, controls, and data surfaces.
- **Soft Surface** (`#F8FAFC`): summaries, read-only values, and quiet grouping.
- **Primary Text** (`#191919`): headings and essential operational values.
- **Secondary Text** (`#505050`): descriptions and supporting copy.
- **Structural Border** (`#919191`): shared control/table boundary where a stronger edge is required.
- **Soft Border** (`#D6E0EA`): Settings sections and low-emphasis containers.

### Semantic

- **Success Green** (`#16A34A`): ready, online, saved, or completed states.
- **Warning Amber** (`#CA8A04`): caution and conditions that need review.
- **Danger Red** (`#DC2626`): offline, failure, or irreversible risk only.

**The One Action Color Rule.** Blue communicates interaction. Do not add decorative blue fills that give passive cards the same weight as buttons.

**The Status Is Not Color Alone Rule.** Every semantic color must be paired with text, an icon, or both.

## Typography

**Display and Body Font:** the native UI stack: `.AppleSystemUIFont` (SF) on macOS, Segoe UI on Windows, Ubuntu on Linux, with Thonburi and Noto Sans Thai coverage.

**Character:** familiar system typography keeps the application readable across platforms and avoids asking non-technical users to decode a stylized interface. Weight and spacing establish hierarchy; decorative type is out of scope.

### Hierarchy

- **Page headline** (700, 28pt; 24pt on Windows): one clear title per surface.
- **Navigation/title** (500–700, 16pt; 13pt on Windows): destinations and high-priority actions.
- **Section/body** (400–700, 12–13pt): short descriptions, form values, and table content.
- **Label/status** (600, 11pt): field labels, timestamps, and concise supporting information.
- **Primary metrics** (700, 40pt; 34pt on Windows): use only for values that deserve first-glance emphasis.

**The Plain Language Rule.** Prefer task labels such as “Read now” and “Reading status and history.” Keep SNMP, parser, ledger internals, and schedule-window details inside staff contexts or explanatory copy.

## Layout

The shell uses a fixed 230px navy sidebar and a flexible content stack. The supported minimum window is 1024×768; all five top-level pages must remain operable at this size without horizontal page scrolling. Larger windows add breathing room and chart area rather than inflating every control.

Page rhythm uses 8px internal gaps, 12px card/grid spacing, 16–24px page margins, and compact 10–17px card padding. Long task pages scroll vertically. Controls shrink within flexible columns; two-column forms may stack or compress before content is clipped. Dense tables may own their horizontal scrolling, but the application canvas must not.

Settings follows a strict scan order: page title and health, operational snapshot, printers and pricing, billing, automatic readings, web/database, staff information, then save action. Advanced schedule editing is collapsed by default. Staff-only destinations use an obvious “Back to Settings” route.

Reports show all configured printers together by default. Choosing a row may refine detail but must not be required to make the primary graph useful. Date ranges use separate From and To controls.

## Elevation & Depth

The system is flat by default. Hierarchy comes from tonal layering, borders, and spacing rather than stacked shadows. White cards sit on the gray workspace; active navigation uses a pale-blue inset surface. Native dialogs may use platform elevation, but ordinary sections should not look like floating modals.

**The One Container Rule.** Use one meaningful boundary per section. Avoid thick frames, nested cards, and repeated outlines around content that already has a clear parent.

## Shapes

Controls use an 8px radius, compact notices use 7px, task sections use 10px, and primary cards use 12px. Corners are restrained rather than pill-like. Borders are generally 1px; a 2px border is reserved for focus, selected modes, warnings, or destructive emphasis.

Touch/click targets use 40px standard height, 48px for wizard and high-priority choice actions, and 32px only for low-priority text/link actions. Shape must remain consistent across Thai and English even when labels change length.

## Components

### Buttons

- **Primary:** action blue, white text, 8px radius, 40px minimum standard height, and bold label. Use once per decision area for the safest next step.
- **Outline:** white surface, blue-gray text, and a soft blue-gray border. Use for secondary navigation and reversible actions.
- **Hover / Pressed:** move from action blue to `#017DD0`, then `#074A76`; do not animate layout.
- **Focus:** a visible 2px action-blue border. Every actionable button must accept keyboard focus and have an accessible name.
- **Recovery:** empty, stale, or failed states provide a contextual action such as Read now, Retry, Open Reports, or Open reading status—not a dead-end message.

### Cards / Containers

- **Task card:** white, 10–12px radius, 1px soft border, 12–17px internal padding.
- **Summary strip:** low-emphasis neutral background with compact labels and bold operational values.
- **Warning:** warm pale background, amber/brown text, concise consequence, and an explicit confirmation at the action boundary.
- **Empty state:** soft neutral surface, a plain reason, and one useful recovery action when recovery is possible.

### Inputs / Fields

- White background, 1–1.5px border, 8px radius, and at least 38–40px height.
- Focus uses the same 2px blue treatment as buttons.
- Labels are associated with controls through label buddies or accessible names; placeholders do not replace labels.
- Read-only paths and generated values use Soft Surface and remain selectable.

### Tables and Charts

- Tables use high-contrast headers, visible selected rows, and restrained alternating rows.
- Keyboard selection must drive the same detail behavior as pointer selection.
- Charts must provide textual totals and an understandable empty state; color never carries the only meaning.
- At 1024px, prioritize essential columns and permit table-owned scrolling before clipping labels or actions.

### Navigation

- The sidebar contains exactly five user destinations: Overview, Devices, Reports, Settings, Manual.
- Default items are transparent with soft blue-gray text; hover deepens the navy surface; active state is pale blue with dark-blue bold text.
- Do not restore Sync, Billing Audit, or Advanced Tools as top-level navigation. These live behind Settings → Staff information.

### Settings

- Present common choices on one vertically scrollable page using plain-language sections.
- Hide advanced timing details until requested; recommended defaults remain usable without technical knowledge.
- Staff-only detail routes must include context, a back action, and a warning where data can change.
- Never require a password merely to open Settings. Destructive operations must still explain the impact and ask for confirmation.

## Do's and Don'ts

### Do:

- **Do** keep each screen focused on the user outcome: monitor, add devices, review reports, adjust common settings, or learn.
- **Do** verify Thai and English at 1024×768, 1280×800, and 1440×900 with one to three printers.
- **Do** preserve visible keyboard focus, accessible names, label relationships, and keyboard-driven table selection.
- **Do** place recovery actions next to the failure or empty state they resolve.
- **Do** show plain-language summaries first and reveal technical evidence progressively.
- **Do** use `.impeccable/review/th/` and `.impeccable/review/en/` screenshots as visual regression references after UI changes.

### Don't:

- **Don't** add another top-level tab for a backend concept such as Sync.
- **Don't** expose wide diagnostic tables, parser controls, raw paths, or scheduling internals as the default Settings experience.
- **Don't** use a password gate for routine configuration; use warnings and explicit confirmation for risky operations.
- **Don't** rely on horizontal scrolling for the entire page at the 1024px minimum window.
- **Don't** make users click each printer before the primary report graph becomes meaningful.
- **Don't** leave mixed Thai/English interface copy after the user switches language.
- **Don't** present color-only status, invisible focus, or empty states with no next step.
