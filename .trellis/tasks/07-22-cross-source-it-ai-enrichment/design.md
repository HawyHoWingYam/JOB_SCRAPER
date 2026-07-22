# Design: IT Enrichment scoped governance and provenance recovery

## 1. Design intent

The current failure is a routing and comprehension problem, not a taxonomy
decision problem. AI Enrichment knows the selected pending slice and the
preflight exclusion reasons, but its link drops the operator into an
unfiltered governance queue. The governance page then presents a generic
canonical-taxonomy decision surface for an exclusion that actually belongs to
Source Job Attribute provenance.

The design keeps canonical taxonomy safety fail-closed and adds a deep module
for the two pieces that callers currently have to reconstruct:

1. resolving the current oldest-first pending slice from the AI filter scope;
2. inspecting and applying a bounded, report-first Source Catalog provenance
   repair for that slice.

The frontend consumes those interfaces and owns only presentation, route state,
and confirmation. It does not infer catalog coverage, choose a revision, or
turn a legacy source scalar into canonical authority.

## 2. Boundaries and non-goals

### In scope

- Source-specific AI Enrichment filtering with an explicit IT parent/descendant
  summary.
- Context-preserving navigation from an exclusion group to Job Taxonomy Review.
- A 10-item governance queue with previous/next controls and arbitrary page
  number input.
- A stable two-column desktop layout and a narrow stacked layout.
- A reason-specific right-side diagnosis and provenance repair flow.
- Partial repair results that allow the repaired, preflight-supported subset to
  return to AI Enrichment.
- Backend/frontend contract and browser-level interaction verification.

### Out of scope

- LLM provider, prompt, worker, retry, or concurrency changes.
- Automatic re-collection for `source_classification_paths_missing`.
- Bulk human assignment of Canonical Job Subcategories.
- Repairing the entire source when the operator selected a bounded batch.
- Unauthenticated governance exposure beyond the existing trusted-local model.

## 3. Deep module and seam

### Module: Pending Enrichment Selection

The existing `EnrichmentRunService` already owns pending filtering, oldest-first
ordering, limit-before-exclusion semantics, and canonical preflight. Deepen
that module with one public read interface rather than duplicating selection
logic in the governance route:

```python
EnrichmentRunService.inspect_pending_selection(
    *, filters: PendingJobFilters, limit: int
) -> PendingSelectionReport
```

The report contains the selected Job IDs, supported Job IDs, grouped exclusion
details, and the matching/selected/effective/excluded counts. Existing preview
code delegates to this interface. The provenance governance endpoint uses the
same interface to resolve the current batch, so the AI preview and repair
scope cannot silently disagree about source filters, dates, limit, or order.

The interface guarantees:

- one source scope at a time as selected by the UI;
- oldest-first selection;
- limit applied before preflight exclusions;
- no writes and no reservation;
- stable exclusion reason strings;
- selected IDs are a short-lived scope result, not a new authority.

### Module: Source Catalog Provenance Repair

Reuse the existing `SourceCatalogProvenanceRepair` module and its report/apply
interface. Add a thin HTTP adapter only. The adapter resolves the current
published revision for inspection, returns the report's revision ID and
fingerprint to the frontend, and requires those exact values again on apply.

The existing implementation remains responsible for catalog fingerprint
validation, identity coverage, active-pointer drift fencing, NULL-only path
updates, bounded commits, and outbox idempotency. No frontend or route code
duplicates those rules.

### Module: Governance Queue Pagination

The shared `GovernanceQueue` interface receives `page`, `pageCount`, and page
navigation callbacks. It defaults to `limit=10`. Existing opaque cursor
requests remain compatible; a new page mode is added for direct human page
jumps. In page mode, the domain read modules use a bounded offset derived from
`(page - 1) * limit` and return the same item/detail contracts. The frontend
derives `pageCount` from `total` and `limit`.

This is a deliberate usability seam: cursor mode remains available to existing
consumers, while the operator-facing governance queue can jump directly to any
page without issuing hundreds of sequential cursor requests. The queue warns
through its live count when the underlying backlog changes after a decision;
the selected item detail remains independently loadable.

## 4. End-to-end data flow

```text
AI Enrichment filters
  -> PendingSelectionReport (preview)
  -> grouped exclusions + scope context
  -> scoped Job Taxonomy Review route
  -> PendingSelectionReport (inspect, same filters/limit)
  -> SourceCatalogProvenanceRepair.inspect(active revision, selected excluded IDs)
  -> operator confirmation with revision fingerprint
  -> SourceCatalogProvenanceRepair.apply(revalidated report)
  -> Source Job Attribute outbox events
  -> canonical preflight re-evaluation
  -> AI Enrichment preview refresh
```

The deep link carries serializable filter scope: source site, qualified
classification/subclassification IDs, posted date bounds, pending limit, and
the exclusion reason. The repair inspect call resolves the current bounded
slice again and reports the actual counts it inspected. It does not trust a
displayed count or a legacy label.

## 5. HTTP contracts

### Scoped governance route

Extend the governance hash/query state with:

```text
#job-intelligence/job-taxonomy
  ?source_site=offertoday
  &source_classification_id=offertoday%3A118000
  &source_subclassification_id=offertoday%3A118016
  &posted_date_from=2026-07-01
  &posted_date_to=2026-07-22
  &pending_limit=50
  &reason=source_catalog_provenance_missing
  &page=1
```

Existing `q` and `cursor` remain supported for generic queue navigation. The
route parser normalizes arrays and dates, rejects malformed values by dropping
only the invalid scope field, and preserves the scoped banner when selecting
an item or changing pages.

### Provenance inspection

Add a trusted-local read endpoint under Job Intelligence Governance:

```text
POST /api/v1/job-intelligence/governance/source-catalog-provenance/inspect
```

Request:

```json
{
  "scope": {
    "source_site": "offertoday",
    "source_classification_ids": ["offertoday:118000"],
    "source_subclassification_ids": ["offertoday:118016"],
    "posted_date_from": "2026-07-01",
    "posted_date_to": "2026-07-22"
  },
  "limit": 50
}
```

The response includes:

- the selected/effective/excluded counts for the current scope;
- the active revision ID, sequence, and fingerprint;
- repairable job/path counts and IDs;
- missing-path, unknown-identity, source-mismatch, and revision-drift counts;
- stable `write_blockers` and a user-facing readiness message.

The endpoint is read-only. It resolves the active revision server-side and
calls the Pending Enrichment Selection module followed by
`SourceCatalogProvenanceRepair.inspect` for only the relevant
`source_catalog_provenance_missing` IDs.

### Provenance apply

```text
POST /api/v1/job-intelligence/governance/source-catalog-provenance/apply
```

Request includes the same scope, the inspected repairable Job IDs, the
revision ID, the exact expected fingerprint, and `confirmed: true`.

The route re-resolves the current scope, reconstructs a fresh repair report,
checks that the submitted revision/fingerprint and repairable set still match,
then calls `SourceCatalogProvenanceRepair.apply`. A stale pointer, incomplete
coverage, changed pending set, or fingerprint mismatch returns a conflict or
validation error and writes nothing for the failed batch.

Response includes:

```json
{
  "changed_jobs": 5,
  "changed_paths": 5,
  "skipped_jobs": 3,
  "batches_committed": 1,
  "recheck": {
    "effective_item_count": 5,
    "excluded_item_count": 3,
    "excluded_reasons": ["source_classification_paths_missing"]
  }
}
```

The UI never treats `changed_jobs` as AI eligibility until the subsequent
preflight-backed preview confirms it.

## 6. Frontend interaction design

### AI Enrichment

- Keep the existing source → classification → subclassification cascade.
- When a parent classification is selected, show the number of descendant
  options included; preserve source-qualified IDs.
- Replace the generic `Open Job Taxonomy Review` label with a contextual action
  such as `Review 8 excluded IT jobs`.
- Pass the current filter scope and exclusion reason through the hash.
- Keep `Run N filtered jobs` disabled only when the effective count is zero;
  after repair, refresh the preview and show the repaired/remaining split.

### Governance shell

- Keep the trusted-local warning, peer tabs, and summary counts.
- When scoped, show a prominent scope banner with source, category, reason, and
  a `Clear scope` action.
- Use 10 compact rows on the left. Show `Page 1 of N`, Previous, Next, and a
  labeled numeric page input. Do not render 50 large cards.
- Keep the right column visible and aligned at the top. On narrow screens,
  show the queue first and an explicit `Review selected item`/Back affordance.
- Empty scoped results explain that the item was resolved or the scope changed;
  they do not look like a broken blank panel.

### Detail panel

For `source_catalog_provenance_missing`:

1. Show a plain-language explanation and the number of affected current-scope
   jobs.
2. Explain that the source classification path exists but lacks a catalog
   revision binding; explicitly state that assigning a Canonical Subcategory
   does not repair this.
3. Offer `Check whether this batch can be repaired`.
4. Render report counters and blockers in a compact status card.
5. Enable `Confirm provenance repair` only when the report is write-allowed;
   require an explicit confirmation that the current source revision and
   fingerprint were reviewed.
6. After apply, show repaired/remaining counts and `Return to AI Enrichment`.

For `source_classification_paths_missing`, show the same explanation shell but
replace repair with `Source classification data must be recollected`. Keep
canonical assignment buttons hidden for both source-evidence reasons.

Technical evidence, the hash, UUIDs, raw path references, recommendations, and
audit timeline are collapsed by default and remain available for expert users.
Other canonical taxonomy reasons retain the existing assignment/insufficient
evidence decision flow.

## 7. Compatibility and safety

- Preserve the existing canonical decision endpoints and actions for reasons
  they actually handle.
- Preserve old governance hashes with `q`/`cursor`; missing new scope fields
  means an unscoped queue.
- Preserve cursor-based backend responses and existing Skill/Company contracts;
  page mode is additive.
- Preserve preview limit-before-exclusion, oldest-first order, and all-excluded
  no-dispatch behavior.
- Source Catalog repair remains trusted-local, report-first, fingerprint-pinned,
  active-pointer-fenced, and auditable.
- No schema migration is expected; new request/response schemas and read routes
  are additive.

## 8. Test seams

- Unit-test Pending Enrichment Selection through its public interface for source
  scope, descendants, dates, oldest-first, limit-before-exclusion, and mixed
  exclusions.
- Test provenance inspect/apply at the HTTP seam with complete coverage,
  blockers, partial repair, active revision drift, fingerprint mismatch, and
  exact replay.
- Test route parsing/serialization for scoped arrays, dates, reason, page, and
  backwards-compatible unscoped hashes.
- Test GovernanceQueue page input validation, previous/next boundaries, selected
  item persistence, and narrow layout state.
- Test the right panel's reason-specific actions: no misleading canonical
  decision for source provenance reasons, explicit repair flow, collapsed
  technical evidence, and partial-result return action.
- Run the frontend application in a browser-capable test or equivalent manual
  browser QA at desktop and narrow widths, including the deep-link flow from AI
  Enrichment and the page-number jump.
