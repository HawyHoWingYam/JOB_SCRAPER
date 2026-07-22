# Design: Make scoped Job Intelligence Governance review actionable

## 1. Design intent

Issue 13 is a comprehension problem at the boundary between AI Enrichment and
Job Intelligence Governance. The scoped queue already resolves the correct
bounded selection and already exposes the matching count, but it renders each
row as a UUID and leaves the detail column with generic empty-state copy.

The design makes the existing batch contract legible without changing the
selection authority or provenance repair behavior:

1. Add operator-facing Job title and Company name to the canonical review read
   contract through one batched lookup per queue page/detail request.
2. Carry the source classification's human label through the AI-to-governance
   deep link as display-only metadata; source-qualified IDs remain authoritative.
3. Present title/company in queue rows, keep UUID/evidence in collapsed technical
   detail, and add scoped batch-entry guidance before the operator selects a row.

## 2. Boundaries and non-goals

### In scope

- Canonical Job Taxonomy review list/detail response fields for `job_title` and
  `company_name`.
- Backend read-model composition and typed frontend/backend fixture parity.
- AI Enrichment exclusion-link display metadata for the source classification label.
- Governance route round-tripping of that display metadata.
- Queue identity rendering, technical UUID placement, scoped banner guidance,
  and scoped empty-detail guidance.
- Focused API, route, AI Enrichment, queue, governance-page, and contract tests.

### Out of scope

- Changes to pending selection ordering, scope filters, page size, or batch limits.
- Changes to provenance inspection/apply endpoints, repair fences, or fail-closed
  preflight behavior.
- Automatic selection of the first row, bulk selection controls, or per-row repair.
- New Job/Company endpoints, database migrations, or source catalog lookups from
  the governance page.
- Changes to Skill Candidates or Company Industries row contracts.

## 3. Cross-layer contracts

### Canonical review item payload

Extend `CanonicalReviewItemView` and `CanonicalReviewItemSchema` with optional
fields:

```json
{
  "job_title": "Senior Backend Engineer",
  "company_name": "Example Company"
}
```

The fields are optional at the API boundary so a deleted/incomplete historical
Company row cannot make an otherwise valid review item unreadable. Normal
collected Jobs have a non-null title and a required Company relationship. No
existing decision, version, evidence, or deep-link field changes.

`CanonicalTaxonomyReader.list_review_items()` keeps its existing review-row
query, ordering, cursor, and count semantics. After selecting the current page,
it performs one bulk Job/Company projection query keyed by the page's Job IDs,
then composes the labels into the views. `get_review_item()` performs the same
single projection lookup for its one Job. This avoids an N+1 relationship loop
and avoids adding a new relationship to the immutable review model.

### Scoped handoff display metadata

The AI exclusion link adds a URL-encoded `source_classification_label` value
alongside the existing source-qualified classification ID. The route parser
normalizes it to `sourceClassificationLabel`, and the serializer round-trips it.
The label is rendered as informational text only. It is never sent to
`fetchCanonicalReviewItems`, `EnrichmentRunService`, or provenance repair as a
filter or authority.

The scope remains authoritative through the existing values:

```text
source_site
source_classification_id
source_subclassification_id
posted_date_from
posted_date_to
pending_limit
reason
job_id
```

### Frontend presentation contract

- The Job Taxonomy queue label is `job_title`, with a stable fallback when the
  field is absent.
- Queue metadata shows `company_name` and the existing reason; the UUID is not
  the primary visible selection cue.
- `EvidencePanel` shows title/company as the human identity and exposes the
  exact `job_id` inside the existing `View technical evidence` details.
- When a scope exists, the existing scope banner shows source, human category
  label, technical category ID, reason, and the existing `Showing N of M
  matching items` queue count remains visible.
- The scope banner adds a concise explanation that any row is a valid evidence
  entry point and that provenance inspection/repair is batch-scoped. The empty
  detail panel repeats the shorter form. No first row is auto-selected.

## 4. Data flow

```text
AI preview exclusion detail
  ├─ source_classification_id ───────────────┐
  ├─ source_classification_name (display) ───┤
  └─ reason / filters / pending limit ───────┤
                                             v
                                  governance hash route
                                             ├─ IDs -> scoped queue API filters
                                             └─ label -> scope banner only

scoped queue API
  ├─ review rows + Job/Company bulk labels
  └─ existing total/page contract
                                             v
queue row: title + company + reason
                                             v
selected detail: title/company + collapsed UUID/evidence
                                             v
existing batch-level provenance inspect/apply flow
```

## 5. Compatibility and failure behavior

- No database migration is required; the read model joins existing `jobs` and
  `companies` data.
- Missing Job/Company display data falls back to a non-empty generic label while
  preserving the technical Job UUID in detail.
- A malformed or absent display label must not invalidate the scoped route or
  widen/narrow the authoritative ID-based query.
- Existing unscoped Job Taxonomy queues receive the new labels but no batch
  guidance. Skill and Company Industry adapters remain unchanged.
- Existing cursor/page pagination, queue focus behavior, narrow-layout Back
  behavior, decision versioning, audit, and provenance repair contracts remain
  unchanged.
- Rollback is additive and reversible: remove the display fields and presentation
  copy without touching persisted data or provenance repair writes.

## 6. Verification matrix

| Area | Verification |
|---|---|
| Backend read model | List and detail expose title/company; one bulk label lookup per page; existing ordering/filter/count remain stable |
| API schema/fixtures | Backend and frontend canonical fixtures remain exact copies and validate with optional label fields |
| AI handoff | Exclusion link includes the human category label while preserving existing IDs/reason/limit/date/job scope |
| Route | Parse/serialize round-trip retains the label; label is not included in queue API filters |
| Queue | Title/company replace UUID as the selection cue; reason remains metadata; empty/fallback values remain readable |
| Scoped guidance | Banner and empty detail distinguish item evidence from batch repair and retain source/category/reason context |
| Technical traceability | Selected detail exposes exact UUID and evidence under the existing technical-details disclosure |
| Regression safety | Existing canonical decisions, provenance repair, pagination, focus, and peer governance areas remain covered |

## 7. Approved recovery design

The review queue is an exception surface, not a manual replacement for
AI Enrichment. The recovery work therefore has two separate internal Modules
behind one guided operator entry point:

### Classifier recovery

`CanonicalTaxonomyReevaluation` accepts a source-qualified scope, an explicit
reason subset, and a preview fingerprint. The preview resolves the current
active taxonomy revision, active mapping revision, and exact bounded Job set.
Apply revalidates all three before dispatching asynchronous chunks. Each Job
is classified with the existing title/description and current constrained
target slice; Skills, Summary, and Experience are not re-run.

Valid existing targets with complete classifier provenance are accepted using
the existing canonical evaluator. Invalid or unresolved output remains an
active Review item. Transient provider errors are recorded as
`ai_upstream_failed`, retried up to three times per Job, and can be retried
again without becoming `classifier_output_invalid`.

### Source evidence recovery

`source_catalog_provenance_missing` continues through the existing inspect,
operator-confirm, fingerprint-pinned apply flow. `source_classification_paths_missing`
does not start a crawl from Governance; it reports the need for Source
recollection or Source Attribute rebuilding. Once Source evidence is repaired,
the same Canonical-only re-evaluation can process the now-eligible Jobs.

### Snapshot and transaction rules

The operator sees counts by reason and a sample before confirmation. The
server-bound snapshot contains the source-qualified IDs, dates, bounded Job
IDs, taxonomy revision, mapping revision, and a scope fingerprint. Any drift
causes a fresh preview. The asynchronous worker chunks the immutable snapshot,
uses stable idempotency keys, emits per-Job audit/outbox effects through the
existing governance transaction foundation, reports progress, and leaves
failed/unresolved Jobs visible for follow-up. No batch operation assigns one
target to every Job or marks the whole scope as insufficient evidence.
