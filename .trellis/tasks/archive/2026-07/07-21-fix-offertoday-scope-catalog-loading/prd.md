# Fix OfferToday source scope catalog loading

## Goal

Make the Task Control wizard reliably render the OfferToday source catalog on
the `Choose Source scope` step so operators can select classifications or use
the OfferToday IT recommendation.

## Requirements

- R1: A published OfferToday catalog must render its source-scope controls and
  classification tree after the catalog request succeeds.
- R2: Creating the draft URL and hydrating the draft must not abort or reset a
  valid catalog result back to `idle`.
- R3: While the catalog is loading, the scope step must show an explicit
  loading status; if loading fails, the existing error alert must remain
  visible.
- R4: Preserve source changes, draft persistence, scope selection, and
  existing JobsDB/CTgoodjobs wizard behavior.
- R5: Add component regression coverage and verify the flow through the real
  browser UI after the change.

## Confirmed Facts

- The screenshot reproduces `Catalog: idle` with an empty scope panel for
  OfferToday, even after waiting for the page to load.
- `backend/app/api/source_catalogs.py:187-205` serves a published catalog, and
  the current OfferToday endpoint returns HTTP 200 with 493 nodes and 462
  query targets.
- `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:207-219`
  starts the catalog request for every wizard route and aborts it on cleanup.
- `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:185-195`
  hydrates the draft and changes the URL when a draft ID is first generated.
- `frontend/src/features/taskControl/wizard/wizardReducer.js:31-32` makes
  `hydrate` recreate the whole wizard state, including an `idle` catalog.
- `frontend/src/features/taskControl/wizard/TaskControlWizard.jsx:376` only
  renders `SourceScopeTree` when `state.catalog.value` exists, so an idle
  catalog produces a blank scope panel.
- `frontend/src/features/taskControl/wizard/SourceScopeTree.jsx:64-68`
  contains the expected `All source classifications` and OfferToday
  recommendation controls.
- Browser reproduction against
  `http://localhost:3000/#scheduler/one-off/new?source=offertoday&step=scope`
  showed one aborted catalog request followed by a successful 200 request,
  while the UI remained `Catalog: idle`.

## Acceptance Criteria

- [x] Directly opening an OfferToday one-off scope route shows `All source
      classifications`, the search field, and the classification tree after
      the published catalog request completes.
- [x] The OfferToday `Recommend: All IT categories (offertoday:118000 subtree)`
      control is visible and can select the recommended subtree.
- [x] The UI no longer remains at `Catalog: idle` after a successful 200
      catalog response or after the draft ID is added to the URL.
- [x] A loading status is visible during the catalog request, and a failed
      request renders an actionable error state without a blank panel.
- [x] Component regression tests pass, and a real browser UI run confirms the
      scope controls remain visible after waiting for the request.
- [x] Existing wizard tests and unrelated source behavior remain unchanged.

## Out of Scope

- Changing the OfferToday catalog data, publication state, or backend endpoint.
- Redesigning source classification selection or taxonomy semantics.
- Changing the dashboard SkillChart fix.

## Implementation Plan

1. Stabilize the catalog request and draft hydration lifecycle so the first
   draft-ID URL transition cannot abort or reset the successful catalog state.
2. Add explicit loading rendering for the scope step and preserve the existing
   error path.
3. Add a focused OfferToday component regression test for catalog rendering and
   recommendation selection.
4. Rebuild the current `frontend-ui` container and verify the flow through
   Playwright, including waiting for the catalog and checking browser errors.
5. Run frontend tests, lint, and production build.

## Open Questions

- None blocking; the backend contract and desired OfferToday controls are
  already confirmed by the live API and existing component code.
