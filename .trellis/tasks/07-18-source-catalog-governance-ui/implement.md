# Source Catalog governance UI implementation plan

## Ordered implementation

### 1. Add route and API/domain adapter

- [x] Add `#source-catalogs` App/Sidebar destination and feature-local source query parser.
- [x] Implement API operations through `apiPath`/`apiFetchJson`.
- [x] Extend/test the shared API error object to retain `code/message/details/requestId` without breaking existing message-based callers.
- [x] Add strict response decoders, structured-error mapping, reducer, and stale-request guards.
- [x] Add route/API/reducer unit tests.

Checkpoint commit: route renders a safe empty shell; no mutation UI.

### 2. Build overview

- [x] Implement source tabs and revision-health summary.
- [x] Ensure initial render performs read-only requests only.
- [x] Add loading/no-published/error/prior-good-data states.
- [x] Add `Check for updates` with pending/duplicate prevention and authoritative refetch.

### 3. Build candidate diff

- [x] Render source-native before/after hierarchy and all diff categories.
- [x] Add filters/counts and execution-affecting badges.
- [x] Render aliases without independent selectable identity.
- [x] Add no-candidate, unchanged, stale, and superseded states/tests.

### 4. Build validation workflow

- [x] Render offline validation separately from changed-target smoke.
- [x] Start/retry validation and poll durable status with cleanup.
- [x] Add failed/manual-action/worker-offline actions.
- [x] Assert CTgoodjobs is headed-only.
- [x] Verify stale responses never replace the selected Source.

### 5. Build impact and publication

- [x] Render Automation before/after Query Target/cap impact.
- [x] Invalidate review token on any relevant refresh/mutation.
- [x] Implement publish eligibility and accessible local confirmation dialog.
- [x] Handle stale candidate/active revision/impact as refresh-required.
- [x] Refetch authoritative summary/catalog/history after success.

Rollback point: page can be hidden without changing server publication policy.

### 6. Build history and rollback

- [x] Render immutable revision/publication history.
- [x] Fetch current rollback impact before enabling confirmation.
- [x] Implement rollback confirmation and conflict/error/success states.
- [x] State clearly that rollback does not restore deleted Crawl Control Data.

### 7. Visual/accessibility pass

- [x] Apply calmer dark operations styling and source-native hierarchy.
- [x] Verify real table headings/captions, tab semantics, visible focus, status text, dialog focus trap/Escape/restore.
- [x] Ensure narrow desktop overflow/stacking is safe.
- [x] Do not extract speculative global primitives.

### 8. Verify and hand off the shared seam

Focused:

```bash
cd frontend
npx vitest run src/features/sourceCatalogs/SourceCatalogsPage.test.jsx
npx vitest run src/api/client.test.js
```

Child checkpoint:

```bash
cd frontend
npx vitest run src/features/sourceCatalogs
npx vitest run src/api/client.test.js
npm run build
```

Run the complete frontend suite/lint once at the parent integration gate after
all three UI children converge; do not repeat it here without a feature failure
that requires broader evidence.

Integration checklist:

- [x] Read-only page load creates no candidate.
- [x] Discovery never changes active revision.
- [x] Offline/live/manual-action states match backend.
- [x] Real Automation impact gates publish/rollback.
- [x] Stale token cannot publish.
- [x] Successful publish switches category/validator/runtime consumers atomically.
- [x] CTgoodjobs never exposes headless.
- [x] Browser back/forward and keyboard/focus behavior pass.
- [x] `git diff --check` passes.
- [x] Structured API-error behavior is documented for Wizard/Board consumers;
      neither child must reimplement or re-review it.

## Rollback

- Remove Sidebar/App route and feature files while leaving backend catalog state untouched.
- Never compensate a frontend publication error by mutating local active state; refetch or use server rollback review.
- If the page is unavailable, explicit CLI/API publication remains operator-gated and auditable.
