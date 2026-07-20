# Automation and One-off wizard implementation plan

## Ordered implementation

### 1. Add Automation review contract

- [ ] Define request/review/detail-preview/schedule-summary contracts.
- [ ] Implement a read-only service reusing Crawl Scope, workload, detail
  eligibility/count, readiness, and timezone seams.
- [ ] Add `POST /api/v1/automations/reviews` and structured
  `AUTOMATION_REVIEW_STALE` mapping.
- [ ] Require review fingerprint on create/update and recompute it under current
  Catalog/Automation state before write.
- [ ] Prove review creates no Automation, revision, plan, claim, job, event,
  outbox row, or source request.
- [ ] Add focused API/service tests for listing/detail, edit comparison,
  non-frozen detail preview, stale Catalog/revision, and timezone summary.

Checkpoint: the UI has one truthful review seam; no frontend route yet.

### 2. Establish shared frontend seams

- [ ] Reuse the Governance-delivered structured API client.
- [ ] Add `taskControl/shared` API operations, runtime decoders, route
  parser/builders, explicit timezone formatter, and local confirmation dialog.
- [ ] Preserve `#scheduler`; add lazy Wizard subroute composition without
  replacing the legacy Board.
- [ ] Test invalid/encoded routes, App hash preservation, decoded errors, and
  dialog focus/Escape/restore.

### 3. Add versioned draft and reducer

- [ ] Implement safe `taskControl.draft.v1.<id>` read/write/clear.
- [ ] Validate version, enums, Source/route consistency, fields, and timestamps;
  catch unavailable/quota/private-mode storage.
- [ ] Implement reducer invariants for Source/intent/edit invalidation,
  step completeness, review/plan freshness, and duplicate mutation prevention.
- [ ] Add command builders that cannot emit implicit empty or cross-source
  scope.
- [ ] Test malformed/old drafts, navigation retention/discard/completion, and
  reducer/request-builder edge cases.

### 4. Build shared shell and intent step

- [ ] Implement four-step progress, Back/Continue, focus movement, summary rail,
  and desktop layout.
- [ ] Add four phase-correct intent choices and edit-mode reset behavior.
- [ ] Load Source from route/board; block draft/route mismatch.
- [ ] Test all four local state paths before network mutations.

### 5. Build Source Scope step

- [ ] Decode/render active published hierarchy and capabilities.
- [ ] Implement explicit all, Exact, Subtree, expand, partial, alias,
  native-path search, rule chips, and optional canonical alias text.
- [ ] Show OfferToday IT subtree as a visible recommendation, never a default.
- [ ] Use server canonicalization/resolution; do not compile targets in React.
- [ ] Test JobsDB, CTgoodjobs, OfferToday, same-code aliases, unsupported
  actions, and Source reset.

### 6. Build Execution step

- [ ] Listing: Page Depth, target count, estimate, Run Page Cap/system ceiling,
  Advanced crawl mode/readiness.
- [ ] Detail: Source/Crawl Scope/Listing Batch, eligible-now preview, future
  snapshot semantics, entire/Stop-after cap, absolute safety cap.
- [ ] Automation: schedule builder, natural-language summary, visible HKT,
  Advanced cron/IANA timezone.
- [ ] Keep Recovery Segment hidden and CTgoodjobs headed-only.
- [ ] Add cap/catalog/worker/conflict and non-HKT/DST tests.

### 7. Build Automation review/create/edit

- [ ] Request a current review only for the current draft fingerprint.
- [ ] Render before/after, Authored/Resolved Scope, Catalog Revision,
  workload/detail preview, schedule, readiness, and warnings.
- [ ] Send review fingerprint on create/update and expected revision on edit.
- [ ] Preserve draft on stale review/revision conflict; refresh and re-review,
  never overwrite.
- [ ] Refetch created/updated Automation and navigate back through route builder.
- [ ] Test duplicate submit, late response suppression, stale review, and
  authoritative success.

### 8. Build One-off and Run-now plan review

- [ ] Prepare exact listing/detail Dispatch Plans and render expiry,
  Catalog/Resolved Scope, workload/snapshot, readiness, and risks.
- [ ] Dispatch with one-time token and expected plan fingerprint.
- [ ] Invalidate on editable change; refresh on expired/stale/consumed plan.
- [ ] Add `Run saved configuration` and `Run with changes` without Automation
  mutation.
- [ ] Test screen/plan/dispatch parity and double-consume prevention.

Rollback point: legacy forms remain available; do not remove them in this child.

### 9. Build detail-conflict cancellation

- [ ] Render decoded active run/progress and Task Details link.
- [ ] Confirm and reuse `crawlTaskActions.cancelCrawlJob`.
- [ ] Render `cancelling`, disable invalid actions, poll at one second, and clean
  up on terminal/unmount/route/source change.
- [ ] Discard blocked plan and generate a fresh review/plan only after
  `cancelled` acknowledgement.
- [ ] Cover cancel rejection/API failure, terminal no-cancel behavior, and
  committed metric retention.

### 10. Add paired detail draft and accessibility/style pass

- [ ] Prefill a separate detail Automation draft after listing creation using
  only safe Source/Authored Scope context.
- [ ] Confirm no plan/runtime/snapshot/dependency fields are copied.
- [ ] Apply calmer dark desktop styling, visible focus, semantic status, and
  complete nested-list/tree/dialog keyboard behavior.
- [ ] Confirm no Wizard component reads `request_payload`, raw event payloads,
  or error message strings.

### 11. Verify and hand off to Board child

Focused backend examples:

```bash
python3 -m pytest -q backend/tests/test_automation_review_service.py
python3 -m pytest -q backend/tests/test_crawl_control_api.py -k automation_review
python3 -m ruff check backend/app/crawl_control/automation_review_contracts.py backend/app/crawl_control/automation_review_service.py backend/app/api/crawl_control.py backend/app/schemas/crawl_control.py
python3 -m compileall -q backend/app/crawl_control backend/app/api/crawl_control.py
```

Focused frontend examples:

```bash
cd frontend
npx vitest run src/features/taskControl/shared
npx vitest run src/features/taskControl/wizard
npm run build
```

- [ ] Existing `#scheduler` Board remains reachable.
- [ ] Shared routes/decoders/action helpers are documented for the Board child.
- [ ] Four flows, stale paths, cancellation, keyboard/focus, and
  `git diff --check` pass.
- [ ] Do not run the full backend suite. The complete frontend suite/lint runs
  once at parent integration after the Board child.

## Rollback

- Remove Wizard subroutes and the read-only Automation review seam; keep legacy
  forms/Board.
- A stale/expired plan is discarded and prepared again, never reconstructed.
- A UI rollback must not mutate existing Catalog, Automation, or run history.
