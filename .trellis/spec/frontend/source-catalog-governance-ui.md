# Source Catalog Governance UI Contracts

## Scenario: govern immutable Source Catalog revisions from the operations UI

### 1. Scope / Trigger

Use this contract when changing `#source-catalogs`, the shared JSON API client,
Source Catalog response fields, candidate validation controls, Automation impact
review, or publication/rollback UI. Catalog eligibility, scope resolution, and
impact remain backend authority; React only decodes and presents them.

### 2. Signatures

The feature-local adapter in
`frontend/src/features/sourceCatalogs/sourceCatalogsApi.js` owns these calls:

```javascript
getCatalogSummaries({ signal })
getPublishedCatalog(source, { signal })
discoverCandidate(source)
getCandidate(source, candidateId, { signal })
startValidation(source, candidateId)
getValidationRuns(source, candidateId, { signal })
createPublicationReview(source, candidateId, actor)
publishCandidate(source, candidateId, reviewToken, actor)
getRevisionHistory(source, { signal })
createRollbackReview(source, revisionId, actor)
rollbackRevision(source, revisionId, reviewToken, actor)
```

The shared failure boundary is:

```javascript
new ApiRequestError(message, {
  status,
  code,
  details,
  detail,    // compatibility alias for existing consumers
  requestId,
})
```

### 3. Contracts

- Route: `#source-catalogs?source=jobsdb|ctgoodjobs|offertoday`; invalid sources
  fall back to JobsDB without discovery.
- Initial load calls only summary, published, candidate-read, validation-read,
  and history-read endpoints. Candidate discovery requires the explicit
  `Check for updates` action.
- Every JSON response is decoded from `unknown` once in the adapter. Missing
  required fields raise `SourceCatalogPayloadError`; components never cast raw
  payload fields.
- Source changes abort old fetches and increment `requestVersion`. Reducer
  success/failure actions with an older version are ignored.
- `details` retains `details`, `context`, or legacy `detail` payloads;
  `detail` remains available. Prefer the response `X-Request-ID`, then body
  request ID, then the caller request ID.
- CTGoodJobs validation displays the server-selected browser mode. Routine
  validation defaults to headless; the Governance UI does not invent a headed
  requirement or compile transport policy locally.
- Publish and rollback first obtain a current backend impact review token.
  Success invalidates local resources and refetches authoritative state; React
  never moves the active revision optimistically.
- Revision history renders immutable revision rows plus append-only
  publish/rollback events.

### 4. Validation & Error Matrix

| Condition | UI behavior |
|---|---|
| Malformed success payload | `SourceCatalogPayloadError`; keep prior good data and show retryable error |
| `CATALOG_NOT_PUBLISHED` | Show setup-required state; execution remains blocked |
| `CATALOG_CANDIDATE_STALE` | Show stale-candidate state and require authoritative refresh |
| `CATALOG_VALIDATION_REQUIRED` / `FAILED` | Keep publish disabled and show durable validation state |
| `CATALOG_MANUAL_ACTION_REQUIRED` | Show backend action/evidence and the explicit operator recovery path; do not silently change browser mode |
| `CATALOG_IMPACT_STALE` | Discard review token and require a new impact review |
| Late response for old `requestVersion` | Reducer ignores it |
| Network refresh failure with prior value | Keep value visible with stale/error banner |

### 5. Good / Base / Bad Cases

- **Good:** opening OfferToday renders its active revision and history without
  calling discovery.
- **Good:** a validated candidate obtains current Automation impact, confirms
  fingerprint/base/impact, publishes once, then refetches the active pointer.
- **Base:** no candidate shows an explicit empty state and leaves the active
  revision visible.
- **Bad:** selecting a Source calls `POST /candidates`, or a successful publish
  replaces local active state before a server refetch.
- **Bad:** a component parses `error.message` to infer stale impact or reads raw
  snake_case response fields outside the adapter.

### 6. Tests Required

- `SourceCatalogsPage.test.jsx`: read-only initial load, source/hash keyboard
  navigation, server-selected CTGoodJobs mode/manual action, impact-before-confirmation, dialog
  focus/Escape/restore, and stale reducer suppression.
- `sourceCatalogsApi.test.js`: route fallback and malformed-response rejection.
- `api/client.test.js`: legacy `detail`, structured `code/details`, and server
  request-ID precedence.
- `appRoute.test.js`: `#source-catalogs?source=...` resolves to the feature.
- `backend/tests/test_source_catalog_api.py`: enriched revision metadata stays
  aligned with the immutable catalog row.
- Child gate: focused Vitest, scoped ESLint, backend API file, production Vite
  build, and `git diff --check`. Run the complete frontend suite once only at
  the parent UI integration gate.

### 7. Wrong vs Correct

#### Wrong

```javascript
useEffect(() => discoverCandidate(source), [source]);
if (String(error.message).includes('stale')) refresh();
setPublishedRevision(candidate);
```

This makes page load mutate governance state, discards stable error codes, and
optimistically promotes a non-authoritative candidate.

#### Correct

```javascript
useEffect(() => getCatalogSummaries({ signal }), [requestVersion]);
if (error.code === 'CATALOG_IMPACT_STALE') requestNewReview();
await publishCandidate(source, candidate.id, review.reviewToken);
dispatch({ type: 'refreshRequested' });
```

Discovery remains explicit, errors stay structured, and the server active
pointer is the only publication authority.
