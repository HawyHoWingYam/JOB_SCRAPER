# AI Enrichment Run Operations

## 1. Scope / Trigger

Use this contract when changing job-enrichment candidate selection, run scheduling, monitoring, retry, stop, startup recovery, or `/api/v1/ai` endpoints. Company enrichment is separate.

## 2. Signatures

- DB: `enrichment_runs.cancelled_items INTEGER NOT NULL DEFAULT 0`; `enrichment_runs.excluded_items INTEGER NOT NULL DEFAULT 0`; `stop_requested_at TIMESTAMP NULL`.
- DB backstop: partial unique index `ux_enrichment_runs_one_active` over a constant where status is `pending`, `running`, or `stopping`.
- Service: `create_manual_pending_run(limit, filters)`, `preview_pending_jobs(filters, limit)`, `request_stop(run_id)`, `promote_next_ready_waiting_run()`.
- API: `GET /ai/pending/filter-options`, `POST /ai/pending/preview`, `POST /ai/runs`, `POST /ai/runs/{id}/stop`, `POST /ai/runs/{id}/retry-failed`.
- Taxonomy policy: `CanonicalTaxonomyPreflight(db).inspect(job)` returns
  `CanonicalTaxonomyPreflightResult(status="supported" | "excluded",
  reasons=tuple[str, ...], context=CanonicalClassifierContext | None)` from
  preserved Source Classification Paths and the active reviewed mapping
  release. `result.reason` is the stable comma-joined persisted reason.

## 3. Contracts

- Active states: `pending`, `running`, `stopping`; automatic work blocked by the slot is durable `waiting`.
- Terminal states: `completed`, `completed_with_failures`, `completed_with_exclusions`, `failed`, `cancelled`.
- Filter request fields: source/classification/subclassification arrays, inclusive posted-date bounds, limit `1..5000`, and ephemeral `all_pending_acknowledged`.
- Candidate fields use OR within a field and AND across fields. Exclude deleted, non-AI-eligible, already enriched, and jobs reserved by waiting/active run items.
- AI eligibility requires a persisted `job_source_attribute_projections` row.
  Legacy Source classification scalars remain display/filter compatibility
  fields and never make a Job canonical-classifier eligible.
- Create orders candidates by `jobs.created_at ASC, jobs.id ASC`. Preview does not reserve IDs.
- Preview returns `selected_item_count`, `effective_item_count`, `excluded_item_count`, and grouped `excluded_items` details containing source classification ID/name, count, reason, and job IDs. The selection limit applies before exclusions; excluded jobs do not trigger implicit replacement candidates.
- A created run persists excluded jobs as `enrichment_run_items.status = "excluded"` with the stable reason in `error_message`; `pending_items` counts only supported jobs. Run projections expose `excluded_items` and `excluded_details`.
- Run execution publishes `enrichment.run.requested` only when `request_run_execution()` returns true. An all-excluded run is terminal `completed_with_exclusions`, has `execution_result = "no_supported_items"`, and never dispatches a worker event.
- Preview and create run the same canonical preflight. A worker repeats preflight
  immediately before changing a pending item to running, so mapping/catalog
  changes after reservation fail closed without crossing the LLM boundary.
- Preflight is read-only and may exclude an unevaluated Job without creating a
  review. `AIEnrichmentService`, the outer enrichment transaction owner, calls
  `CanonicalJobTaxonomy.evaluate(...)` for blocking evidence, persists the
  active review/outbox with the rest of the enrichment transaction, then
  commits once.
- The item `error_message` stores `CanonicalTaxonomyPreflightResult.reason`.
  `/api/v1/ai` exclusion projections group and display that persisted reason;
  they must not re-run canonical policy, consult static defaults, or derive a
  new reason from legacy scalar labels.
- `/ai/runs` run projections include `execution_dispatched` and `execution_result`; `/ai/enrich` uses the same explicit `no_supported_items` result for an all-excluded selection.
- Monitor returns active + latest terminal, or latest two terminal; never waiting.
- Cooperative Stop permits running items to finish, blocks new conditional starts, cancels untouched pending items, and preserves completed/failed/cancelled counts.

## 4. Validation & Error Matrix

- Empty filters without acknowledgement -> `422`.
- Unsupported source, reversed dates, or unsafe limit -> `422`.
- Manual filtered create/retry while active -> `409`, `detail.code=active_run_exists`, `detail.run_id=<id>`.
- Missing run -> `404`; retry with no failed items -> `400`.
- Pending/waiting Stop -> immediate `cancelled`; running Stop -> `stopping`; terminal Stop -> idempotent projection.
- Unmapped or explicitly excluded source taxonomy -> excluded before the LLM boundary, with no provider failure and no retry action.
- Missing Source Attribute projection/path, unpublished or mismatched active
  canonical revisions, missing mapping, conflicting mappings, and an empty
  canonical target slice -> excluded before the LLM boundary with the stable
  canonical reason persisted on the run item.
- All selected candidates excluded -> persisted `completed_with_exclusions`, zero pending work, no worker event, and `no_supported_items` API result.

## 5. Good / Base / Bad Cases

- Good: two source values plus one classification select the oldest matching unreserved jobs.
- Base: automatic work arriving while active becomes waiting and is promoted by a terminal path or worker maintenance.
- Bad: changing an in-memory queue flag without checking persisted run status before every item start.
- Good: a mixed run reports `total=2`, `pending=1`, `excluded=1`; only the supported item reaches the worker.
- Bad: converting `Unknown source classification` into an item-level `failed` result after the worker has started.

## 6. Tests Required

- Assert normalization, eligibility/reservation exclusion, inclusive dates, preview/create parity, and UUID tie-break ordering.
- Assert active conflict and the PostgreSQL partial index/advisory-lock race in a PostgreSQL-capable environment.
- Assert Stop blocks the next pending item while an already-running item can persist success/failure.
- Assert startup recovery cancels `stopping`, preserves `waiting`, and monitor selection stays at two.
- Assert public batch/job-ID mode and `/ai/enrich-job/{job_id}` remain absent while `/jobs/manual` still auto-enriches.
- Assert pending eligibility is based on `job_source_attribute_projections`,
  not legacy Source classification scalars.
- Assert preview/create parity uses `CanonicalTaxonomyPreflight`, persists the
  stable reason, and worker execution rechecks the same policy before item
  start/LLM dispatch.
- Assert `JobTaxonomyRegistry` and legacy default-path resolution are retired
  fail-closed seams and have no production call sites.
- Assert mixed and all-excluded pending selections expose grouped exclusion details, preserve item status/reason, and do not enqueue `enrichment.run.requested` for an empty supported workload.

## 7. Wrong vs Correct

### Wrong

```python
item.status = "running"  # no persisted run-state check
```

### Correct

```python
if run.status != "running" or item.status != "pending":
    return None
item.status = "running"
```

Flush item transitions before aggregate count queries when using the production `autoflush=False` session.

### Cross-layer taxonomy exclusion contract

#### Wrong

```python
handling = taxonomy_registry.get_handling(
    job.source_classification_id,
    job.source_classification_name,
)
if handling.status == "mapped":
    dispatch_to_llm(job)
```

This code grants legacy scalar/static-registry state canonical authority and
does not notice mapping/catalog changes after a run reserves the Job.

#### Correct

```python
preflight = CanonicalTaxonomyPreflight(db).inspect(job)
if preflight.status == "excluded":
    item.status = "excluded"
    item.error_message = preflight.reason
    # Do not enqueue the item or publish an empty worker request.
```

The preflight reads persisted Source Job Attributes and governed canonical
revisions only. It must not fetch a Source, require a live Source session, or
fall back to `jobs.source_classification_*`, `default_path`, or
`proposed_internal_domain` authority.
