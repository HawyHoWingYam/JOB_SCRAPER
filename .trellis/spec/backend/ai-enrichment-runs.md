# AI Enrichment Run Operations

## 1. Scope / Trigger

Use this contract when changing job-enrichment candidate selection, run scheduling, monitoring, retry, stop, startup recovery, or `/api/v1/ai` endpoints. Company enrichment is separate.

## 2. Signatures

- DB: `enrichment_runs.cancelled_items INTEGER NOT NULL DEFAULT 0`; `stop_requested_at TIMESTAMP NULL`.
- DB backstop: partial unique index `ux_enrichment_runs_one_active` over a constant where status is `pending`, `running`, or `stopping`.
- Service: `create_manual_pending_run(limit, filters)`, `preview_pending_jobs(filters, limit)`, `request_stop(run_id)`, `promote_next_ready_waiting_run()`.
- API: `GET /ai/pending/filter-options`, `POST /ai/pending/preview`, `POST /ai/runs`, `POST /ai/runs/{id}/stop`, `POST /ai/runs/{id}/retry-failed`.

## 3. Contracts

- Active states: `pending`, `running`, `stopping`; automatic work blocked by the slot is durable `waiting`.
- Terminal states: `completed`, `completed_with_failures`, `failed`, `cancelled`.
- Filter request fields: source/classification/subclassification arrays, inclusive posted-date bounds, limit `1..5000`, and ephemeral `all_pending_acknowledged`.
- Candidate fields use OR within a field and AND across fields. Exclude deleted, non-AI-eligible, already enriched, and jobs reserved by waiting/active run items.
- Create orders candidates by `jobs.created_at ASC, jobs.id ASC`. Preview does not reserve IDs.
- Monitor returns active + latest terminal, or latest two terminal; never waiting.
- Cooperative Stop permits running items to finish, blocks new conditional starts, cancels untouched pending items, and preserves completed/failed/cancelled counts.

## 4. Validation & Error Matrix

- Empty filters without acknowledgement -> `422`.
- Unsupported source, reversed dates, or unsafe limit -> `422`.
- Manual filtered create/retry while active -> `409`, `detail.code=active_run_exists`, `detail.run_id=<id>`.
- Missing run -> `404`; retry with no failed items -> `400`.
- Pending/waiting Stop -> immediate `cancelled`; running Stop -> `stopping`; terminal Stop -> idempotent projection.

## 5. Good / Base / Bad Cases

- Good: two source values plus one classification select the oldest matching unreserved jobs.
- Base: automatic work arriving while active becomes waiting and is promoted by a terminal path or worker maintenance.
- Bad: changing an in-memory queue flag without checking persisted run status before every item start.

## 6. Tests Required

- Assert normalization, eligibility/reservation exclusion, inclusive dates, preview/create parity, and UUID tie-break ordering.
- Assert active conflict and the PostgreSQL partial index/advisory-lock race in a PostgreSQL-capable environment.
- Assert Stop blocks the next pending item while an already-running item can persist success/failure.
- Assert startup recovery cancels `stopping`, preserves `waiting`, and monitor selection stays at two.
- Assert public batch/job-ID mode and `/ai/enrich-job/{job_id}` remain absent while `/jobs/manual` still auto-enriches.

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
