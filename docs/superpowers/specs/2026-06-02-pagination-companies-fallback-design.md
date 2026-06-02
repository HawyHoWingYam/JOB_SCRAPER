# Pagination, Companies Run Orchestration, and Fallback Reduction Design

Date: 2026-06-02

## Overview

This design covers three approved workstreams:

1. Add direct page-number jump controls to both the Job Browser and Companies paginations.
2. Fix the Companies page run queue / polling flow so it no longer gets stuck in stale progress states.
3. Reduce the Dashboard fallback bucket by improving taxonomy normalization, not by changing dashboard presentation.

`Experience From` is explicitly out of scope for this implementation cycle because the user found the existing control and does not want additional changes there.

## Goals

- Provide a consistent page-jump interaction across Job Browser and Companies.
- Make Companies run state converge reliably from `pending` to `running` to terminal states in both backend data and frontend rendering.
- Reduce avoidable `General / General` taxonomy assignments for high-signal jobs while preserving conservative classification boundaries.
- Improve maintainability by extracting clearer shared or orchestration boundaries instead of layering more page-local patches.

## Non-Goals

- No changes to dashboard API shape or chart rendering contract.
- No new state-management library for the frontend.
- No broad telemetry subsystem for fallback analysis in this cycle.
- No redesign of the existing search / retrieval behavior outside pagination.

## Current Problems

### Pagination

- Job Browser and Companies both implement pagination UI separately.
- Neither page supports direct numeric page jumps.
- Any pagination behavior change currently risks duplication and drift.

### Companies run lifecycle

- `CompaniesPage` currently mixes company list concerns with run orchestration concerns.
- Polling, visibility-resume refresh, optimistic run adoption, and terminal reconciliation are split across several effects and helper paths.
- The UI derives company card status from a combination of `currentRun`, `current_company_name`, and run items, which can temporarily diverge.
- Backend run and item status updates are persisted incrementally, so frontend reads can observe partially updated state during polling windows.

### Fallback bucket inflation

- Dashboard fallback counts are downstream symptoms of canonical taxonomy assignments landing in `General / General`.
- The right fix point is taxonomy normalization during enrichment, not dashboard aggregation.
- Existing deterministic heuristics already refine some software-role cases, which makes the normalizer the correct extension point for additional fallback reduction.

## Design Summary

The implementation is divided into three modules:

1. A shared pagination control component used by both Job Browser and Companies.
2. A dedicated Companies run orchestration hook that centralizes polling and terminal-state reconciliation.
3. A fallback-reduction path in taxonomy normalization that promotes specific governed subcategories over generic fallback when strong signals exist.

## Module 1: Shared Pagination Control

### New component

Add `frontend/src/components/PaginationControl.jsx`.

Props:

- `page`
- `totalPages`
- `totalItems`
- `isLoading`
- `onPageChange`
- `summaryText`
- `hideWhenSinglePage`

### Behavior

- Render current page summary, `Previous`, `Next`, numeric input, and `Go`.
- Maintain a local draft input value that syncs from the external `page`.
- Support `Enter` to submit the draft page.
- Ignore empty or non-numeric submissions.
- Clamp submitted values into `1..totalPages`.
- Skip `onPageChange` if the clamped page equals the current page.
- Disable the input and `Go` while loading.

### Page integrations

#### Job Browser

- Replace the current pagination footer UI with `PaginationControl`.
- Preserve existing `handlePageChange` behavior and current search scope handling.
- Keep the current one-page behavior by hiding the component when `totalPages <= 1`.

#### Companies

- Replace the current pagination footer UI with `PaginationControl`.
- Preserve existing list query behavior driven by `page`, `appliedQuery`, and `statusFilter`.
- Use `hideWhenSinglePage={true}` so both pages follow the same one-page pagination rule.

## Module 2: Companies Run Orchestration

### New hook

Add `frontend/src/components/companies/useCompanyEnrichmentRun.js`.

Responsibilities:

- Store and refresh `currentRun`.
- Store and refresh `runItemsByCompanyId`.
- Manage polling lifecycle.
- Manage visibility-resume refresh.
- Manage run creation adoption and optimistic startup state.
- Reconcile terminal runs into a stable view model for the page.

### Hook output

Raw state:

- `currentRun`
- `runItemsByCompanyId`
- `refreshError`
- `isCreatingRun`

Derived view model:

- `hasActiveRun`
- `hasQueuedRun`
- `progress`
- `progressValue`
- `remainingCount`
- `batchButtonLabel`
- `currentCompanyId`
- `currentCompanyName`
- `companyStatusById`
- `terminalMessage`

### Page boundary after extraction

`CompaniesPage` should remain responsible for:

- Company list fetching and pagination.
- Search and status filter state.
- Modal selection state.
- Rendering cards and progress sections.

`CompaniesPage` should stop owning the internal orchestration details of run polling and reconciliation.

### Frontend state flow

1. Page loads companies list and current run.
2. The hook determines whether a run is active, queued, or terminal.
3. If active and page is visible, polling continues on a single controlled path.
4. If the page becomes visible again, the hook performs one resume refresh without racing a second concurrent refresh.
5. When a run becomes terminal:
   - the hook finalizes the run view model,
   - refreshes the visible companies list in a deterministic order,
   - clears stale generating states,
   - emits a stable terminal message.

### Backend consistency changes

Primary backend touchpoint: `backend/app/services/company_enrichment_run_service.py`.

Changes:

- Tighten the order in which `current_company_name`, item status, counters, and final run status are updated.
- Prefer stable `current_company_id` resolution when the frontend needs to identify the actively running company card.
- Preserve the current API contract while making intermediate polled states less ambiguous.

## Module 3: Fallback Reduction Pipeline

### Primary adjustment point

Primary implementation point: `backend/app/services/job_category_normalizer.py`.

`backend/app/services/ai_enrichment_service.py` remains the upstream source of title, description, and extracted-skill context that the normalizer already consumes.

### Strategy

#### Specific-over-General promotion

When the resolved path would otherwise remain `General / General`, the normalizer should promote to a more specific governed subcategory only when all of the following hold:

- The source slice already allows a concrete governed destination.
- Title, description, or extracted skills provide strong role evidence.
- The rule is deterministic and bounded to the source slice.
- Governance override semantics remain intact.

#### High-frequency heuristics

Add at least one and at most two heuristics targeted at currently high-value fallback sources rather than broad global guessing.

The first candidates should extend the same design language already used for software-role heuristics:

- explicit signal sets,
- minimum evidence thresholds,
- source-slice availability checks,
- conservative fallback when evidence is weak.

#### Contract preservation

- No dashboard schema change.
- No dashboard query logic change beyond naturally observing improved stored taxonomy decisions.
- No weakening of conservative cross-domain logic for ambiguous cases.

## Testing Strategy

### Frontend

Add focused tests for:

- shared pagination direct jump behavior,
- enter-to-submit behavior,
- page clamping,
- disabled behavior while loading,
- Companies regression where a terminal run must not remain stuck in generating or progress UI.

Files:

- `frontend/src/components/PaginationControl.test.jsx`
- `frontend/src/components/JobBrowser.test.jsx`
- `frontend/src/components/companies/CompaniesPage.test.jsx`

### Backend

Add tests for:

- run state ordering and terminal reconciliation coverage for `current_company_id`, `current_company_name`, counters, and final status,
- normalizer cases that previously fell back to `General / General` but should now resolve to a specific governed subcategory,
- negative controls proving weak-signal jobs still remain conservative.

Files:

- `backend/tests/test_job_category_normalizer.py`
- `backend/tests/test_company_enrichment_run_service.py`

## Implementation Sequence

1. Build the shared pagination control and cover it with tests.
2. Integrate the control into Job Browser and Companies.
3. Extract Companies run orchestration into a hook and add regression coverage for stuck states.
4. Tighten backend run-state consistency where needed to support the new frontend assumptions.
5. Add fallback-reduction heuristics and matching tests in the normalizer.
6. Run targeted frontend and backend verification commands for the touched areas.

## Risks and Mitigations

### Risk: over-general shared component design

Mitigation:

- keep `PaginationControl` narrowly scoped to the two current consumers,
- avoid premature render-prop or slot abstraction.

### Risk: frontend and backend run-state assumptions drift

Mitigation:

- define the hook around stable API fields,
- prefer id-based current-company derivation,
- add regression tests that exercise terminal convergence.

### Risk: fallback reduction becomes over-aggressive

Mitigation:

- require strong multi-signal evidence,
- stay inside governed source slices,
- add negative tests alongside every promotion heuristic.

## Success Criteria

- Both Job Browser and Companies support direct numeric page jumps.
- Companies run UI reliably clears stuck progress / generating states after terminal completion.
- At least one previously fallback-prone high-signal taxonomy case is promoted to a governed specific subcategory via tests.
- Dashboard fallback counts can decrease naturally as improved enriched results accumulate, without any dashboard API change.
