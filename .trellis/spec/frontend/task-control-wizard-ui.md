# Task Control Wizard UI Contract

## Scope

Use this contract for Task Control Automation, One-off, and Run-now authoring
under `#scheduler/*`. The current `#scheduler` board remains reachable.

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
  `review_fingerprint`. Edit replaces the current Automation row without an
  expected revision; refetch the saved Automation before showing success.
- One-off and Run-now dispatch the exact prepared plan ID, one-time confirmation
  token, and expected plan fingerprint. Pending/result state prevents duplicate
  consumption.
- Run saved configuration never edits the Automation. Run with changes creates
  a distinct One-off draft with the Automation ID cleared.
- CTGoodJobs supports `headless` and `headed`; new drafts default to headless.
  Headed is explicitly labelled for debugging/operator recovery, and React does
  not rewrite a selected mode. OfferToday `offertoday:118000` is a visible
  recommendation, never an implicit default. React never compiles Query Targets.

### Source classification request lifecycle

- Start the ordinary Source classification request only after the wizard route has a
  stable draft ID. The first render creates that ID in the URL; fetching before
  the transition can leave the result attached to a request version that a
  later draft hydrate has already invalidated.
- Hydrating a draft or changing only the history-visible step must preserve
  classifications already loaded for the same Source. Hydrating or selecting a
  different Source must clear the old value and advance the request version so
  its late response cannot render the wrong taxonomy.
- The scope step renders explicit loading and retryable failure states when no
  classification value is available; a successful value renders the normal
  source-scope controls.

## Detail conflict and accessibility

- A detail conflict links to the normalized Task route, confirms cancellation
  through the shared crawl action, renders `cancelling`, polls once per second,
  cleans up, and requests fresh authority only after `cancelled` acknowledgement.
- Dialogs use the least-destructive initial focus, trap Tab, support Escape,
  and restore trigger focus. Step changes move focus to the step heading.
- Errors/statuses are semantic and textual; do not branch on error message
  strings or read raw request/event payloads.
- Do not start classification loading before draft URL stabilization and then
  let `hydrate` recreate an `idle` classification state: a successful 200 response can be
  ignored, leaving the scope panel blank.

## Verification

Run focused `src/features/taskControl` tests, scoped ESLint, and a production
frontend build. Leave complete-suite integration to the parent UI gate.

## Scenario: Historical OfferToday fixed-sweep authoring

### 1. Scope / Trigger

This scenario documents legacy UI expectations only. New authoring follows the
adaptive scenario below; JobsDB and CTgoodjobs retain existing controls.

### 2. Signatures

```javascript
OFFERTODAY_QUERY_TARGET_COUNT = 36
OFFERTODAY_DEFAULT_PAGE_DEPTH = 100
OFFERTODAY_DEFAULT_RUN_PAGE_CAP = 3600

offerTodayEstimatedMaxPages(pageDepthValue) -> number | null
buildAuthoredScope(draft, sourceClassifications) -> AuthoredCrawlScopeV1
```

### 3. Contracts

- OfferToday displays no All-scope option. Its active top-level classifications
  are one radio group; selecting a second root replaces the first.
- A listing intent starts at `Page Depth=100` and `Run Page Cap=3600`. Both
  fields stay editable, and OfferToday Page Depth has no HTML product `max`.
- The execution step immediately displays `36 keywords × depth = estimate`.
  React owns only the fixed cardinality preview; it never creates keyword
  strings or Query Targets. Server review remains authoritative.
- Continue/command building requires positive safe integers, exactly one
  OfferToday root, a representable estimate, and cap greater than or equal to
  the estimate. The backend repeats every rule.
- Hydrating an old `mode=all` or under-budget OfferToday Automation never
  rewrites it. Scope is incomplete or review is blocked until the operator
  selects one category and saves valid limits.

### 4. Validation & Error Matrix

| Draft state | UI/command result |
|---|---|
| OfferToday mode is `all` | Scope incomplete; command rejects exactly-one rule |
| Zero or two selected roots | Continue disabled; command rejects |
| Depth `100`, cap `3600` | Estimate `3600`; execution complete |
| Depth changes to `101`, cap remains `3600` | Estimate `3636`; invalid copy and Continue disabled |
| Estimate exceeds technical safe bound | Display unavailable estimate; command rejects |
| JobsDB/CTgoodjobs selected scope | Existing checkbox/multi-select behavior |

### 5. Good / Base / Bad Cases

- **Good:** The operator selects IT, changes depth to 200, sees 7200
  immediately, changes cap to 7200, then receives matching server authority.
- **Base:** An old Automation opens with insufficient limits. Its values remain
  visible and Save stays unavailable until reviewed changes are valid.
- **Bad:** JSX contains the `A-Z/0-9` keyword list and constructs targets. This
  duplicates backend authority and can drift from fingerprints.
- **Bad:** `mode=all` returns early from command building before the
  OfferToday-specific cardinality check.

### 6. Tests Required

- `wizardReducer.test.js`: OfferToday defaults, all-scope rejection, full-budget
  completion, and under-budget invalidation.
- `wizardCommands.test.js`: exactly one active category, legacy all rejection,
  safe integer/technical bound, and `36 * depth` cap validation.
- `TaskControlWizard.test.jsx`: no All button, radio replacement behavior,
  editable/no-max Page Depth, live estimate, invalid copy, and disabled
  Continue.
- Keep existing JobsDB/CTgoodjobs wizard tests green; run scoped ESLint, all
  Vitest, and production build.

### 7. Wrong vs Correct

#### Wrong

```javascript
if (draft.scope.mode === 'all') return allScope;
if (draft.source_site === 'offertoday') validateOneSelection();
```

#### Correct

```javascript
if (draft.source_site === 'offertoday') validateOneSelection();
else if (draft.scope.mode === 'all') return allScope;
```

Source-specific validation must run before a generic early return.

## Scenario: Adaptive OfferToday listing authoring

### 1. Scope / Trigger

Use this for current OfferToday One-off and Automation listing drafts and the
global keyword-management page.

### 2. Signatures

```text
#offertoday-keywords
GET/POST /api/offertoday-keyword-packs/**
```

### 3. Contracts

- Scope remains one top-level radio selection. Copy explains that current
  children and the enabled root keyword pack are resolved by the server.
- React validates positive safe Page Depth/Run Page Cap only; it never assumes
  36 targets and never compiles Query Targets.
- Server review/Dispatch Plan is authoritative and displays native target/page,
  keyword target/page, total page, freshness, warning, and cap evidence.
- Keyword management is a dedicated read-only/filterable page. All mutations
  use CSV download, upload preview, and explicit confirmation; no inline row
  mutation exists.

### 4. Validation & Error Matrix

| State | UI result |
|---|---|
| No/excess top-level selections | Scope incomplete |
| Positive limits before review | Continue to server review |
| Server reports cap exceeded | Review blocked; preserve draft values |
| Invalid CSV | Show row errors; no confirm |
| Stale/replayed preview | Show error and require new preview |

### 5. Good / Base / Bad Cases

- **Good:** current server review reports 12 native and 127 keyword targets with
  separate page totals and blocks an insufficient cap.
- **Base:** a root with no keywords reports native work and zero keyword work.
- **Bad:** JSX embeds A-Z/0-9, multiplies a local constant, or edits keyword rows.

### 6. Tests Required

- Wizard reducer/command/UI tests cover one-root selection, positive bounds,
  server-owned workload copy, and blocked review.
- Keyword page tests cover routing, filtering, download, preview errors,
  confirmation, stale preview, loading/empty/error, and absence of row controls.

### 7. Wrong vs Correct

```javascript
// Wrong
const pages = 36 * pageDepth;

// Correct
const pages = serverReview.listing_workload.estimated_max_pages;
```
