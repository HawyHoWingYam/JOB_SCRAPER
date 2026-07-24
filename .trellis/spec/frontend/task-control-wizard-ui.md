# Task Control Wizard UI Contract

## Scope

Use this contract for Task Control Automation, One-off, and Run-now authoring
under `#scheduler/*`. The legacy `#scheduler` board remains reachable.

## Routes and drafts

- Use `controlRoute.js` for board, Automation create/edit, One-off, Run-now,
  Source, draft ID, and step hashes. Wizard steps are history-visible so browser
  back/forward can restore them without discarding work.
- Store recoverable, non-authoritative input only under
  `taskControl.draft.v1.<draft-id>`. Validate route/Source/flow binding and catch
  malformed or unavailable storage. Never persist review fingerprints,
  confirmation tokens, Dispatch Plan IDs, readiness, or runtime snapshots as
  reusable authority.
- Source, intent, scope, execution, or schedule changes invalidate current
  review/plan authority. Late responses are ignored by draft fingerprint.

## Server authority

- Automation create/update sends the exact current server
  `review_fingerprint`; edit also sends expected revision. Refetch the saved
  Automation before showing success.
- One-off and Run-now dispatch the exact prepared plan ID, one-time confirmation
  token, and expected plan fingerprint. Pending/result state prevents duplicate
  consumption.
- Run saved configuration never edits the Automation. Run with changes creates
  a distinct One-off draft with Automation ID/revision cleared.
- CTGoodJobs supports `headless` and `headed`; new drafts default to headless.
  Headed is explicitly labelled for debugging/operator recovery, and React does
  not rewrite a selected mode. OfferToday `offertoday:118000` is a visible
  recommendation, never an implicit default. React never compiles Query Targets.

### Published catalog request lifecycle

- Start the published Source Catalog request only after the wizard route has a
  stable draft ID. The first render creates that ID in the URL; fetching before
  the transition can leave the result attached to a request version that a
  later draft hydrate has already invalidated.
- Hydrating a draft or changing only the history-visible step must preserve a
  catalog already loaded for the same Source. Hydrating or selecting a
  different Source must clear the old value and advance the request version so
  its late response cannot render the wrong taxonomy.
- The scope step renders explicit loading and retryable failure states when no
  published catalog value is available; a successful value renders the normal
  source-scope controls.

## Detail conflict and accessibility

- A detail conflict links to the normalized Task route, confirms cancellation
  through the shared crawl action, renders `cancelling`, polls once per second,
  cleans up, and requests fresh authority only after `cancelled` acknowledgement.
- Dialogs use the least-destructive initial focus, trap Tab, support Escape,
  and restore trigger focus. Step changes move focus to the step heading.
- Errors/statuses are semantic and textual; do not branch on error message
  strings or read raw request/event payloads.
- Do not start catalog loading before draft URL stabilization and then let
  `hydrate` recreate an `idle` catalog: a successful 200 response can be
  ignored, leaving the scope panel blank.

## Verification

Run focused `src/features/taskControl` tests, scoped ESLint, and a production
frontend build. Leave complete-suite integration to the parent UI gate.
