# AI Enrichment Run Operations

## 1. Scope / Trigger

Use this contract when changing job-enrichment candidate selection, run scheduling, monitoring, retry, stop, startup recovery, or `/api/ai` endpoints. Company enrichment is separate.

## 2. Signatures

- DB: `enrichment_runs.cancelled_items INTEGER NOT NULL DEFAULT 0`; `enrichment_runs.excluded_items INTEGER NOT NULL DEFAULT 0`; `stop_requested_at TIMESTAMP NULL`; `manual_job_evidence(job_id, evidence_hash, enriched_evidence_hash, operator_authored_fields, captured_at, updated_at)`.
- DB backstop: partial unique index `ux_enrichment_runs_one_active` over a constant where status is `pending`, `running`, or `stopping`.
- Service: `create_manual_pending_run(limit, filters)`, `preview_pending_jobs(filters, limit)`, `create_jev_skill_backfill_run(limit)`, `request_stop(run_id)`, `promote_next_ready_waiting_run()`.
- API: `GET /ai/pending/filter-options`, `POST /ai/pending/preview`, `POST /ai/runs`, `POST /ai/runs/{id}/stop`, `POST /ai/runs/{id}/retry-failed`.
- Evidence seam: `JobEnrichmentEvidence(db).inspect(job) -> JobEnrichmentInspection(status="supported" | "needs_job_description" | "excluded", reason, enrichment_input)`.

## 3. Contracts

- Active states: `pending`, `running`, `stopping`; automatic work blocked by the slot is durable `waiting`.
- Terminal states: `completed`, `completed_with_failures`, `completed_with_exclusions`, `failed`, `cancelled`.
- Filter request fields: source/classification/subclassification arrays, inclusive posted-date bounds, limit `1..5000`, and ephemeral `all_pending_acknowledged`.
- Candidate fields use OR within a field and AND across fields. Exclude deleted, non-AI-eligible, already enriched, and jobs reserved by waiting/active run items.
- External-Source AI eligibility requires a persisted
  `job_source_attribute_projections` row. Manual Entry eligibility instead
  requires `manual_job_evidence` and a non-blank Job description. Manual Entry
  never receives a Source Attribute Projection or Source Classification Path.
  Legacy Source classification scalars remain display/filter compatibility
  fields and never make a Job enrichment-evidence eligible.
- Overview, filter options, preview, run creation, and worker preflight use the
  same origin-aware evidence semantics. Blank-description Manual Jobs are
  counted as `needs_job_description`, not pending.
- A Manual Job is pending when it is unenriched or when
  `evidence_hash != enriched_evidence_hash`. Successful enrichment updates the
  derived intelligence and copies the current evidence hash in the same
  transaction; failure rolls back both and leaves stale intelligence visible.
- Manual operator-authored facts are immutable to enrichment. AI experience
  values fill only omitted min/max fields; conflicting extracted values are
  appended to `experience_evidence` and do not replace operator values.
- Create orders candidates by `jobs.created_at ASC, jobs.id ASC`. Preview does not reserve IDs.
- Jev Skill historical backfill is an explicit `jev_skill_backfill` run. Its
  preview is a free database read, orders oldest first, freezes at most the saved
  limit, skips Jobs reserved by another enrichment run, and skips an exact
  current Jev input fingerprint. Execution uses the normal outbox and worker but
  dispatches the dedicated Skill-only executor; it must not rerun summary or
  experience extraction.
- Preview returns `selected_item_count`, `effective_item_count`, `excluded_item_count`, and grouped `excluded_items` details containing source classification ID/name, count, reason, and job IDs. The selection limit applies before exclusions; excluded jobs do not trigger implicit replacement candidates.
- A created run persists excluded jobs as `enrichment_run_items.status = "excluded"` with the stable reason in `error_message`; `pending_items` counts only supported jobs. Run projections expose `excluded_items` and `excluded_details`.
- Run execution publishes `enrichment.run.requested` only when `request_run_execution()` returns true. An all-excluded run is terminal `completed_with_exclusions`, has `execution_result = "no_supported_items"`, and never dispatches a worker event.
- Preview, create, and worker execution use the same `JobEnrichmentEvidence`
  boundary. A missing external-Source projection or missing Manual evidence
  fails closed before the LLM boundary without consulting Job taxonomy state.
- `AIEnrichmentService`, the outer enrichment transaction owner, extracts Job
  intelligence and Skill mentions, projects Governed Skills/Candidate evidence,
  then commits the enrichment result once.
- The item `error_message` stores the stable evidence reason. `/api/ai`
  exclusion projections group and display that persisted reason; they must not
  derive a replacement reason from legacy Source scalar labels.
- A missing Source Classification Path/projection requires recollection. It is
  not replaced by a Source-to-Canonical mapping check or a per-Job Canonical
  assignment action.
- Crawl authoring and enrichment filters use ordinary current top-level Source
  classifications. Child IDs preserved in Job evidence remain supplemental;
  neither level requires a Source-to-Canonical Job mapping.
- `/ai/runs` run projections include `execution_dispatched` and `execution_result`; `/ai/enrich` uses the same explicit `no_supported_items` result for an all-excluded selection.
- Monitor returns active + latest terminal, or latest two terminal; never waiting.
- Cooperative Stop permits running items to finish, blocks new conditional starts, cancels untouched pending items, and preserves completed/failed/cancelled counts.

## 4. Validation & Error Matrix

- Empty filters without acknowledgement -> `422`.
- Unsupported source, reversed dates, or unsafe limit -> `422`.
- Manual filtered create/retry while active -> `409`, `detail.code=active_run_exists`, `detail.run_id=<id>`.
- Missing run -> `404`; retry with no failed items -> `400`.
- Pending/waiting Stop -> immediate `cancelled`; running Stop -> `stopping`; terminal Stop -> idempotent projection.
- Missing Source Attribute projection/path -> excluded before the LLM boundary
  with the stable evidence reason persisted on the run item. Source paths do
  not require a Canonical Job mapping.
- All selected candidates excluded -> persisted `completed_with_exclusions`, zero pending work, no worker event, and `no_supported_items` API result.
- Manual Job has no description -> `needs_job_description`; exclude it from the
  runnable preview without fabricating a Source exclusion.
- Manual-only origin filter -> no Source Classification/Subclassification
  constraint is required and the explicit scope never falls through to all pending.

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
- Assert public batch/job-ID mode and `/ai/enrich-job/{job_id}` remain absent;
  `POST /jobs/manual` persists only and never creates or waits for an AI run.
- Assert pending eligibility is based on `job_source_attribute_projections`,
  not legacy Source classification scalars.
- Assert every Job with projected Source Attributes remains eligible for AI
  Enrichment regardless of Source-to-Canonical mapping availability.
- Assert Job-taxonomy preflight, registry, normalizer, mapping, assignment, and
  legacy default-path resolution modules are absent from production.
- Assert mixed and all-excluded pending selections expose grouped exclusion details, preserve item status/reason, and do not enqueue `enrichment.run.requested` for an empty supported workload.
- Assert Manual Entry origin has no Source paths; blank descriptions are counted
  separately; stale/current hashes drive pending state; omitted/matching/conflicting
  experience cases preserve operator authority; failure preserves stale state.

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

### Cross-layer evidence exclusion contract

#### Wrong

```python
if job.source_classification_id:
    dispatch_to_llm(job)
```

This code grants a legacy scalar authority that only the Source Attribute
Projection or Manual evidence record owns.

#### Correct

```python
inspection = JobEnrichmentEvidence(db).inspect(job)
if not inspection.supported:
    item.status = "excluded"
    item.error_message = inspection.reason
    # Do not enqueue the item or publish an empty worker request.
```

The inspection reads persisted Source Job Attributes or Manual evidence. It
must not fetch a Source, require a live Source session, require Canonical Job
taxonomy state, or fall back to `jobs.source_classification_*` authority.

For Manual Entry, the equivalent correct path is
`JobEnrichmentEvidence(db).inspect(job)`. Adding `source_site="manual"` to a
Source projection check or fabricating a Source Classification Path is forbidden.
