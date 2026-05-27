# Direct Override Form UX Design

> Date: 2026-05-28
> Scope: Iteration C / remaining direct-override workflow slice
> Priority order: A complete -> C.2 complete -> C direct-override form UX -> B runtime crawl success

## Goal

Make the `Direct Override Sequence` form faster to operate and harder to misuse when launching listing or detail crawl jobs.

The design target is not visual novelty. The target is:

1. reduce operator hesitation before launch
2. prevent invalid or ambiguous request combinations
3. make the resulting crawl payload obvious before submit
4. keep listing-mode and detail-mode mental models separate

## Current Evidence

The current repo state shows:

- `frontend/src/components/scraper/ScheduleManager.jsx` already validates the direct-override payload before POST.
- The form supports two operational modes through `crawl_phase`:
  - `listing`
  - `detail`
- The same surface currently multiplexes:
  - crawl phase
  - crawl mode
  - sector selection
  - pages/detail limit
  - optional legacy listing batch narrowing
- Validation errors are mostly surfaced after clicking submit via a single banner or top-level error string.
- The existing summary panel explains the run, but the operator still has to translate the live field state into the eventual payload mentally.

This means the form is functional, but it still places too much interpretation burden on the operator.

## Problem Statement

The current direct-override form has three core UX problems:

1. **Mode switching ambiguity**
   Listing and detail runs reuse much of the same layout, even though they are different tasks with different risks and requirements.

2. **Late validation**
   The operator often learns about invalid combinations only after attempting to launch.

3. **Payload opacity**
   The form state, helper copy, and eventual backend request are related, but not visible as one coherent launch summary.

For an operational tool, this means slower launches and a higher chance of malformed or unintended runs.

## UX Principles

This iteration follows these principles:

- **Mode clarity first:** listing and detail workflows should feel distinct even when they share one screen.
- **Validate before launch, not only after launch:** surface blockers inline when possible.
- **Show consequences of choices:** the operator should understand the run shape from the UI without reverse-engineering request logic.
- **Preserve fast operation:** no wizard or modal flow; this is still an operations console, not a guided consumer form.
- **Prefer constrained inputs over prose:** show enabled/disabled states, summaries, and chips rather than long explanation text.

## Chosen Approach

Keep the single direct-override panel, but reorganize it around three layers:

1. **Mode header**
2. **Request builder**
3. **Launch readiness summary**

This avoids a full page redesign while making the form more explicit and self-checking.

## Information Architecture

### 1. Mode Header

The top of the form should immediately answer:

- what kind of run am I configuring
- what this run is for
- what will be targeted

This layer should react strongly to `crawl_phase`.

#### Listing mode

Emphasize:

- sector discovery
- page depth
- job ID collection

#### Detail mode

Emphasize:

- backlog recovery
- eligible detail scope
- optional listing-batch narrowing

The operator should not have to infer the mode from a single dropdown alone.

### 2. Request Builder

The main form body should be organized by decision order, not by raw field list:

1. crawl phase
2. crawl mode
3. scope selection
4. batch/size controls

This should preserve the current data model but make dependencies clearer.

#### Scope selection behavior

- sector selection remains visible in both modes
- when detail mode is active, the UI should make it explicit that sectors and listing-batch ID are alternative or complementary narrowing tools
- the legacy listing batch filter should appear as an advanced narrowing control, not as a peer to the primary mode fields

#### Numeric control behavior

The numeric field should no longer rely on a label switch alone.

The UI should make it obvious whether the operator is setting:

- `max_pages`
- or `detail_limit`

The active control should carry mode-specific helper copy and expected range.

### 3. Launch Readiness Summary

Before the submit button, the form should show a compact readiness block that answers:

- is this request launchable right now
- what source/phase/mode will be sent
- what scope is selected
- what numeric limit will be applied
- whether a listing batch filter will be included

This is not a raw JSON preview. It is an operator-readable request contract.

## Validation Strategy

Validation should be split into two layers:

### Inline readiness validation

Show unmet requirements before submit whenever possible.

Examples:

- no sectors selected for listing mode
- invalid max pages
- detail mode without sectors and without listing batch narrowing
- invalid detail limit

This should be visible near the readiness block and/or the relevant control.

### Submission-time validation

Keep the existing submit-time safeguards, but submission errors should become the fallback, not the primary feedback mechanism.

## Interaction Rules

- Switching `crawl_phase` should visibly change helper copy and readiness semantics.
- A detail-mode operator should immediately understand whether they are recovering from the full backlog pool or a narrowed legacy batch.
- Disabled/unavailable launch states should be legible without trial-and-error clicking.
- The launch button label should remain action-specific, but the readiness summary should do most of the explanatory work.
- The form should continue to behave as a fast inline operations tool, not a multi-step wizard.

## Scope

This iteration is expected to focus primarily on:

- `frontend/src/components/scraper/ScheduleManager.jsx`
- `frontend/src/components/scraper/ScheduleManager.test.jsx`
- `frontend/src/components/scraper/Scheduler.css`

Small helper extraction is acceptable if it reduces local JSX complexity.

## Out of Scope

This iteration does not include:

- backend payload contract changes
- scheduler history modal redesign
- progress panel redesign beyond already-completed C.2 work
- crawl runtime logic changes

## Verification Plan

Implementation for this design is only considered complete when evidence shows:

1. listing vs detail mode differences are clearer in the UI
2. invalid direct-override combinations are surfaced before submit where practical
3. the launch readiness summary reflects the effective request state
4. existing direct-override request payload tests still pass
5. no regression is introduced to scheduler progress recovery behavior

Expected verification layers:

- `ScheduleManager.test.jsx` behavior tests
- focused direct-override test additions for readiness and inline validation
- full frontend test suite
- frontend production build

## Deliverables

This design is expected to produce:

- a clearer direct-override form hierarchy
- stronger inline validation for launch readiness
- a readable launch summary block tied to the effective request state
- updated tests that prove request-shaping behavior still matches backend expectations

## Risks and Tradeoffs

- More explicit readiness signaling may add a little UI density, but that is preferable to hidden validation rules in an operational console.
- If the summary block becomes too verbose, it will repeat the existing guidance rather than clarify it. The implementation should keep it compact and payload-oriented.
- The design must not bury the form in excessive explanation; operators need clarity, not ceremony.

## Success Criteria

This iteration is successful when an operator can configure a direct override and answer these questions before launch without guessing:

1. am I launching a listing run or a detail run
2. what exact scope is being targeted
3. what limit/depth will apply
4. is this request currently valid
5. what request shape will be sent when I press launch
