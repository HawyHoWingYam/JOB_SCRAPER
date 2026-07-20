# Source Catalog governance UI design

## Feature boundary

Create a feature-local `sourceCatalogs` module. It owns route parsing, API decoding, page state, diff/validation/impact projections, confirmations, and visual components. It does not own catalog rules, scope resolution, publication eligibility, or Automation impact; those remain backend projections.

Suggested shape:

```text
frontend/src/features/sourceCatalogs/
  SourceCatalogsPage.jsx
  sourceCatalogsApi.js
  sourceCatalogsReducer.js
  sourceCatalogsRoute.js
  sourceCatalogsProjection.js
  components/
    SourceRevisionSummary.jsx
    CandidateDiff.jsx
    ValidationEvidence.jsx
    AutomationImpactTable.jsx
    PublicationHistory.jsx
    CatalogActionDialog.jsx
  SourceCatalogsPage.test.jsx
```

No project-wide router/table/dialog/toast abstraction is created. The page may reuse existing CSS tokens and API client.

## Route

```text
#source-catalogs
#source-catalogs?source=jobsdb
```

`App.jsx` recognizes the first hash segment and passes the hash/query to a feature-local parser. Source tab changes update the hash so browser back/forward works. Invalid source falls back to the first supported Source without triggering discovery.

Links from Task Control Board include the Source query and optional candidate/revision anchor, but publication state is always refetched.

## API adapter

`sourceCatalogsApi.js` calls `apiPath` and `apiFetchJson` and exports domain-shaped operations. Before feature work, the shared client is extended compatibly to retain backend `code`, `message`, `details`, and request ID on an `ApiClientError`; existing message behavior remains for older callers. Governance decoders consume the structured fields once and never parse error strings.

```javascript
getCatalogSummaries({ signal })
getPublishedCatalog(source, { signal })
discoverCandidate(source)
getCandidate(source, candidateId, { signal })
startValidation(source, candidateId)
getValidationRuns(source, candidateId, { signal })
createPublicationReview(source, candidateId)
publishCandidate(source, candidateId, reviewToken)
getRevisionHistory(source, { signal })
createRollbackReview(source, revisionId)
rollbackRevision(source, revisionId, reviewToken)
```

Each response is decoded once. Unknown/missing fields become an adapter error, not undefined component behavior. Structured backend error codes map to stable view states; raw messages remain secondary diagnostics.

## State model

```javascript
{
  source,
  summaries: {status, value, error},
  published: {status, value, requestVersion, error},
  candidate: {status, value, requestVersion, error},
  validation: {status, runs, polling, error},
  impactReview: {status, value, error},
  mutation: {kind, status, error},
  history: {status, value, error},
  dialog: null | {kind, payload}
}
```

Reducer actions are explicit for request start/success/failure and source changes. Every source change increments a request version/aborts old calls; late responses are discarded. A successful mutation invalidates summaries, published, candidate, impact, and history and then refetches authoritative state.

Validation polling runs only while durable rows are pending/running/manual-action-transitioning. It uses cleanup and a bounded interval; there is no global polling manager.

## Page hierarchy

### Header and Source summary

- Page title and one-sentence governance purpose.
- Source tabs with active revision/health/candidate badges.
- Summary cards show fingerprint prefix, publication time, provenance, nodes/query targets, validation status, and impacted Automation count.
- `Check for updates` is the primary low-risk command. It says explicitly that discovery cannot change execution.

Loading the page never calls discovery.

### Candidate diff

Candidate header shows base revision, candidate fingerprint, discovered time, and state. Diff controls filter:

- Added
- Renamed
- Moved
- Removed
- Alias changed
- Selectability/capability changed
- Query semantics changed

Rows/tree lead with source-native path and show before/after. Execution-affecting changes receive a risk badge; canonical `clean_match` text is secondary and never used as a diff identity.

An unchanged candidate has an explicit `No source changes` state and cannot be published as a pointless new revision unless backend policy says provenance changed materially.

### Validation

Separate panels:

- Offline full-catalog checks and counts.
- Live smoke table only for added/query-changed targets.

Each smoke row shows Source Classification/path, supported mode, attempt/status, bounded evidence, elapsed time, and retry/manual action. CTgoodjobs always says Headed. Manual action offers the backend-provided action/resume path and never exposes a headless toggle.

Validation start/retry is idempotent and does not optimistically mark passed.

### Automation impact

Impact review is requested only after validation is publishable. Table shows:

- Automation name/revision/lifecycle;
- Exact/Subtree/all rule;
- before/after selected/Query Target counts;
- Page Cap effect;
- `compatible` or `scope review required` reason.

The review response contains a review token/fingerprint and active revision. Any catalog/Automation mutation invalidates it.

### Publish

`Publish revision` remains disabled until backend says publishable and impact review is current. A feature-local dialog:

- moves initial focus to heading/least destructive action;
- traps/handles Tab within the dialog;
- Escape cancels;
- restores focus to trigger;
- lists execution-affecting counts and Automations requiring review;
- requires explicit confirmation text/action.

On submit, UI shows pending and prevents duplicate actions. It does not switch local active revision until authoritative success/refetch. Stale impact/candidate conflict returns to review.

### History and rollback

History is append-only and shows revision/fingerprint/provenance/publication event/actor/time/status. Selecting rollback first fetches a current impact review. Confirmation clearly says it reactivates an old immutable revision but does not restore deleted Crawl Control Data.

## Error and empty states

Explicit states:

- no published revision: governance setup required; execution remains blocked;
- no candidate;
- unchanged candidate;
- stale/superseded candidate;
- offline validation failure;
- live smoke failure;
- manual action required;
- headed worker unavailable;
- stale impact;
- publication/rollback conflict;
- network error with retry;
- successful publication/rollback.

A prior good summary remains visible with a stale/error banner when refresh fails.

## Accessibility and desktop layout

- Source tabs use tab semantics and keyboard navigation.
- Diff hierarchy uses tree/treeitem only if full keyboard behavior is implemented; otherwise use semantic nested lists/buttons rather than partial ARIA.
- Impact/history use real tables with captions/headers.
- Status has text/icons in addition to color.
- Dialog behavior is implemented/tested locally.
- Desktop layout uses a source summary rail plus main review content; narrow desktop may stack/scroll. Dedicated mobile treatment is out of scope.

## Testing

Component/API tests cover:

- initial summary without discovery;
- hash source navigation and back/forward;
- stale response suppression/AbortController cleanup;
- candidate diff filters and source-native paths;
- unchanged/stale/failed/manual-action states;
- validation polling start/stop/retry;
- CTgoodjobs headed-only copy;
- impact/cap projection;
- publish disabled/enabled, dialog focus/Escape, duplicate suppression;
- stale publish requiring review refresh;
- success authoritative refetch;
- rollback impact and confirmation;
- malformed API payload and prior-good-data retention.
