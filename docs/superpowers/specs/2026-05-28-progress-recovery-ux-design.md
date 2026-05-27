# Live Progress and Manual Recovery UX Design

> Date: 2026-05-28
> Scope: Iteration C / slice 2 of the project audit and optimization cycle
> Priority order: A complete -> C (live progress + manual recovery UX) -> remaining C scheduler form work -> B runtime crawl success

## Goal

Restructure the scheduler progress experience so operators can decide the next action quickly when a crawl is running, degraded, failed, or blocked on manual action.

The design target is not "show more telemetry." The target is:

1. understand current state in seconds
2. know whether intervention is required
3. see the most relevant recovery action first
4. access diagnostics without overwhelming the default view

## Current Evidence

The current repo state shows:

- `frontend/src/components/scraper/ScrapeProgressPanel.jsx` already exposes rich state:
  - crawl phase and mode
  - manual action payloads
  - proxy metrics
  - resume / close / cancel / jump actions
  - timing and workload counters
- `frontend/src/components/scraper/ScheduleManager.jsx` uses the progress panel as the main operator runtime surface.
- The current scheduler snapshot shows a dense operational surface where runtime metadata, recovery actions, and detailed diagnostics compete for the same visual priority.
- The progress item currently treats many statuses as equivalent blocks of text, which makes active decision-making slower than it should be.

This means the UX problem is not missing data. It is missing hierarchy.

## Problem Statement

The current progress item asks the operator to parse too much at one level:

- current status
- progress counters
- warnings
- manual-action context
- proxy diagnostics
- raw errors
- action buttons

This creates three operator costs:

1. slow triage
2. delayed recovery action selection
3. reduced scanability when multiple runs are visible

The interface needs to separate "what is happening," "what should I do next," and "what technical evidence explains it."

## UX Principles

This iteration follows these operating principles:

- **Visibility of system status:** current state must be obvious without reading the entire card.
- **Error recovery over narration:** when intervention is needed, the UI should prioritize the next recovery action before showing verbose diagnostics.
- **Status and severity should be visually encoded:** status chips and severity indicators should not rely on paragraph text alone.
- **Primary actions should be singular and prominent:** when a card needs intervention, the interface should emphasize one best next action instead of giving equal weight to all actions.
- **Diagnostics should remain available but secondary:** detailed telemetry belongs behind an explicit affordance or expanded state, not as the first-read surface for every run.

## Chosen Approach

Use a three-layer progress-card model:

1. **Primary status strip**
2. **Decision panel**
3. **Diagnostics drawer**

This preserves current backend payloads and most existing action capabilities, while changing the frontend information architecture to favor triage speed and action clarity.

## Information Architecture

### 1. Primary Status Strip

The top layer is always visible and answers:

- what run is this
- what state is it in
- does it need intervention
- is there a warning condition worth noticing
- when was it last updated

This layer should include compact, scan-friendly fields:

- source site
- crawl phase
- crawl mode
- primary status label
- intervention-required chip when applicable
- warning chip when applicable
- last-updated timestamp

This strip should use pills / chips / compact badges rather than sentences. It is designed for list scanning.

### 2. Decision Panel

This layer appears only when action selection matters:

- `manual_action_required`
- `failed`
- `running_with_warning`
- or another state with a meaningful operator action

The panel should surface:

- one primary recommended action
- up to three secondary actions
- explicit runtime/helper blocking guidance if an action is unavailable

Examples of actions that can appear here:

- resume with existing browser
- launch fresh profile
- close profile windows
- jump to linked run
- inspect diagnostics
- cancel job

The decision panel is not a generic button tray. It is a guided recovery surface.

### 3. Diagnostics Drawer

This layer contains the rich technical detail already supported by the panel, but it becomes secondary.

It is:

- collapsed by default for routine states
- expanded by default for `manual_action_required`
- expanded by default for `failed`

It should group information into smaller sections rather than one unstructured block:

- run timing
- workload and counts
- technical diagnostics

`Technical diagnostics` is where the deep details live:

- proxy counters
- blocked URL
- current title
- listing batch
- raw error text
- manual-action analysis payload details

## State Model

Each progress item should resolve to one primary display state. Recommended priority order:

1. `manual_action_required`
2. `failed`
3. `running_with_warning`
4. `running`
5. `queued`
6. `completed`
7. `cancelled`

This prevents the UI from presenting multiple top-level statuses with equal weight.

### State Semantics

#### `manual_action_required`

Highest priority. The card must:

- visually stand out
- show intervention-required status immediately
- expand diagnostics by default
- surface one recommended recovery action first

#### `failed`

Also high priority, but below manual action. The card must:

- foreground failure state and brief cause
- surface retry/jump/inspect patterns before secondary details
- expand diagnostics by default

#### `running_with_warning`

Used when the run is still active but telemetry indicates degradation, such as proxy instability or another non-terminal warning condition.

The card must:

- show the run as active, not failed
- expose a warning chip
- avoid promoting destructive or recovery actions unnecessarily
- bias toward inspect-diagnostics as the primary action when no direct recovery is warranted

#### `running` / `queued`

Routine states should stay visually quiet and compact. They should not auto-expand diagnostics or show the full recovery surface.

#### `completed` / `cancelled`

Terminal routine states should remain scannable and low-noise. Keep the summary, but suppress the decision panel unless there is an explicit reason to revisit the run.

## Proxy Signal Strategy

Proxy telemetry remains important, but most proxy counters should not live in the always-visible summary.

Recommended model:

- primary strip gets only a condensed warning chip when proxy state deserves operator attention
- diagnostics drawer keeps the full numeric counters

Possible warning summaries:

- `Proxy unstable`
- `Challenge spike`
- `Lease quarantined`

This keeps observability without forcing operators to parse low-level metrics during first-pass triage.

## Interaction Rules

- Only one action should feel primary in a recovery panel.
- Secondary actions may exist, but they should not visually compete with the main recovery step.
- Buttons that depend on helper/runtime availability must explain why they are unavailable.
- Diagnostics should be intentionally opened, except for failure/manual-action states where the system should expand them automatically.
- Completed and cancelled runs should not look like unresolved incidents.

## Scope

This iteration is expected to focus primarily on:

- `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`
- `frontend/src/components/scraper/Scheduler.css` when layout or styling support is needed

Minimal incidental changes to `ScheduleManager` are acceptable only if required to preserve integration.

## Out of Scope

This iteration does not include:

- backend API contract changes
- scheduler direct-override form redesign
- broad scheduler page layout redesign
- crawl runtime behavior changes
- proxy runtime algorithm changes

## Verification Plan

Implementation for this design is only considered complete when evidence shows:

1. progress items render distinct primary display states with predictable priority
2. manual-action and failed states surface clear recovery actions before deep diagnostics
3. routine states remain more compact and less noisy
4. diagnostics expansion defaults behave correctly for routine vs. intervention-required runs
5. the scheduler still integrates with the progress panel correctly

Expected verification layers:

- component tests in `ScrapeProgressPanel.test.jsx`
- regression checks in existing scheduler tests when integration behavior changes
- at least one rendered UI/snapshot or browser verification pass to confirm improved hierarchy

## Deliverables

This design is expected to produce:

- a redesigned progress item information hierarchy
- clearer intervention-first action grouping
- preserved diagnostic depth behind a secondary layer
- updated frontend tests that prove the new status and interaction rules

## Risks and Tradeoffs

- More explicit hierarchy means some currently always-visible details will move behind a drawer. That is intentional and should improve triage speed.
- Compressing warnings into summary chips risks hiding nuance if the diagnostics section is weak. The drawer content must remain rich and easy to open.
- If too many actions remain visually prominent, the design will fail its main objective. The implementation must genuinely privilege one primary action when recovery is needed.

## Success Criteria

This iteration is successful when an operator can open the progress panel and, for any visible run, answer these questions quickly:

1. what state is this run in
2. do I need to intervene
3. what is the best next action
4. where do I open deeper diagnostics if I need justification
