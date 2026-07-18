# Design: AI Enrichment monitoring-first console

## Scope and boundaries

This is a cross-layer redesign of the job-enrichment console. It changes:

- PostgreSQL run lifecycle metadata and active-run enforcement.
- `EnrichmentRunService` selection, scheduling, cancellation, and monitor projections.
- `/api/v1/ai` request/response contracts.
- `AIEnrichmentPage` layout, controls, local persistence, and actions.

It does not change company enrichment, crawl cancellation, the AI provider implementation, Job Browser filtering, or add inferred ETA/health signals.

## Existing evidence

- Pending selection is centralized in `EnrichmentRunService.create_manual_pending_run()` and already applies eligibility plus oldest-first ordering (`backend/app/services/enrichment_run_service.py:213`).
- Public create currently supports unfiltered `pending`, explicit `batch job_ids`, and governance `query` modes (`backend/app/api/ai.py:42`, `backend/app/api/ai.py:287`).
- Monitor selection uses creation adjacency rather than an explicit active-plus-terminal contract (`backend/app/services/enrichment_run_service.py:599`).
- A database-only `cancel_run()` exists but does not signal in-process workers and is documented for unclaimed runs (`backend/app/services/enrichment_run_service.py:753`).
- Run execution preloads items into an in-memory asyncio queue and starts each item without checking a persisted stop request (`backend/app/services/enrichment_run_service.py:1016`).
- The frontend has no reusable general multi-select; its current AI page owns the queue and monitor state locally (`frontend/src/components/ai/AIEnrichmentPage.jsx:260`).

## Domain terms

- **Candidate**: non-deleted, AI-eligible job whose `ai_enriched_at` is null and that is not already reserved by a nonterminal run.
- **Waiting run**: durable automatic post-scrape work retained until it can acquire the execution slot. It is not shown as a monitor card.
- **Active run**: the one run in `pending`, `running`, or `stopping` that owns the global execution slot.
- **Terminal run**: `completed`, `completed_with_failures`, `failed`, or `cancelled`. Unknown statuses are not silently treated as terminal.
- **Cooperative Stop**: reject new item starts, let already-running external calls settle, then cancel untouched items and finalize the run.

## Data model and lifecycle

### EnrichmentRun changes

Add:

- `cancelled_items INTEGER NOT NULL DEFAULT 0`
- `stop_requested_at TIMESTAMP NULL`

Recognized lifecycle states become:

```text
waiting -> pending -> running -> completed | completed_with_failures | failed
                    \-> stopping -> cancelled
pending --------------------------> cancelled
```

`waiting` is used for retained automatic work that cannot yet acquire the slot. Manual filtered and retry requests return `409 Conflict` instead of creating a waiting run when the slot is occupied.

Add a PostgreSQL partial unique index over a constant expression for rows whose status is `pending`, `running`, or `stopping`. This is the database backstop for one active slot. Service methods also acquire a transaction-scoped PostgreSQL advisory lock before checking/promoting/creating active runs so callers receive deterministic domain errors instead of raw uniqueness failures.

The Alembic migration and `backend/scripts/bootstrap_db.py` convergence path must both add the columns/index because local Docker startup uses bootstrap against restored schemas.

### Automatic work retention

Post-scrape runs are created as `waiting` while their crawl/ingest gate is unresolved or another run owns the slot. Existing job IDs and run items remain durable. When the crawl gate is ready, a shared promotion method acquires the global lock and transitions the oldest ready waiting run to `pending` only if the slot is free.

Every terminal path—normal completion, failure, retry completion, immediate pending cancellation, and cooperative cancellation—attempts to promote the next ready waiting automatic run. The same idempotent `promote_next_ready_waiting_run()` entry point also runs after crawl/ingest gate changes, at enrichment-worker startup, and from a bounded recurring worker maintenance sweep. A lock conflict or transient publication failure leaves the run waiting for a later sweep; no job IDs are dropped.

Candidate queries exclude jobs reserved by run items belonging to `waiting`, `pending`, `running`, or `stopping` runs. This prevents filtered runs from duplicating durable automatic work. Overview backlog and preview use the same reservation rule.

## Filter contract

### Shared request model

Define one Pydantic model used by preview and create:

```json
{
  "filters": {
    "source_sites": ["jobsdb", "ctgoodjobs"],
    "source_classification_names": ["Information Technology"],
    "source_subclassification_names": ["Software Engineering"],
    "posted_date_from": "2026-07-01",
    "posted_date_to": "2026-07-18"
  },
  "limit": 500,
  "all_pending_acknowledged": false
}
```

Normalization and validation occur at the API boundary:

- Trim and deduplicate arrays; source IDs are canonicalized through the existing source catalog.
- Empty arrays become absent constraints.
- Dates are inclusive and `from <= to`.
- `limit >= 1` and is bounded by a documented server maximum.
- At least one filter is required unless `all_pending_acknowledged=true`.

`EnrichmentRunService` owns one candidate-query builder. Preview uses it for `COUNT(DISTINCT jobs.id)`; create uses the same builder plus `ORDER BY jobs.created_at ASC, jobs.id ASC` and `LIMIT`.

### API endpoints

- `GET /api/v1/ai/pending/filter-options`
  - Returns distinct source/classification/subclassification combinations from current candidates as a compact hierarchy.
  - The frontend cascades the already-loaded hierarchy locally; no request is needed for each selection.
- `POST /api/v1/ai/pending/preview`
  - Accepts the shared filter payload.
  - Returns `matching_pending_count`, `effective_item_count`, normalized filters, and whether all-pending acknowledgement is required.
- `POST /api/v1/ai/runs`
  - `mode=pending` accepts the same filter payload and limit.
  - Re-runs candidate selection transactionally and creates the run from the resulting IDs.
  - Returns `409` with stable code `active_run_exists` when the slot is occupied.
- `POST /api/v1/ai/runs/{run_id}/stop`
  - Pending run: cancel immediately without exposing an observable stopping phase.
  - Running run: transition to `stopping`, set `stop_requested_at`, and return the updated projection.
  - Terminal run: idempotently return its existing projection.
- `POST /api/v1/ai/runs/{run_id}/retry-failed`
  - Retained, but now passes through the global slot gate and returns `409` if occupied.
- `GET /api/v1/ai/runs?monitor=true`
  - Explicitly returns one active plus latest terminal, or two latest terminal runs.
  - Terminal runs are ordered by `completed_at DESC`, then `created_at DESC`, then ID for deterministic ties.
  - Includes `cancelled_items` and recognizes `stopping` as active.

Remove public manual single-ID behavior:

- Remove Target UUID frontend submission.
- Remove `/api/v1/ai/enrich-job/{job_id}`.
- Remove public `mode=batch`/`job_ids` from `CreateRunRequest` and unused manual single/batch service entry points.
- Preserve internal `_create_run(job_ids=...)`, post-scrape creation, retry creation, and `/jobs/manual` behavior.

The legacy all-pending `/api/v1/ai/enrich` endpoint remains for compatibility, but its request must include explicit all-pending acknowledgement and it must route through the same normalized candidate query and global slot gate. It must not bypass the safety contract.

## Cooperative Stop execution design

The API only records intent; the worker owns finalization.

1. Stop transitions `running -> stopping` and commits.
2. Before an execution coroutine marks the next item `running`, it performs a conditional start that succeeds only when both run status is `running` and item status is `pending`.
3. Items already marked running continue through `enrich_job_id()` and persist success/failure normally even while the run is stopping.
4. Once all in-flight coroutine work settles, finalization re-reads the run status.
5. For `stopping`, all remaining pending items become `cancelled`; completed, failed, and cancelled counters are recomputed; the run becomes `cancelled`.
6. Normal finalization must never overwrite `stopping` or `cancelled` with `completed`.

The worker's conditional start and finalization are the correctness boundary. A process-local event alone is insufficient because Stop may be requested by another API/worker process.

## Frontend design

### Page structure

```text
AI Enrichment + short subtitle
Compact status strip: Backlog | Active | Failed

Run Monitor (left)             Filtered Run (right)
  Active + latest terminal       Source multi-select
  or latest two terminal runs    Classification multi-select
                                  Subclassification multi-select
                                  Posted date range
                                  Pending Limit
                                  Match/effective count
                                  Run filtered jobs
```

At the existing responsive breakpoint, the grid becomes one column with monitor first.

### Monitor cards

- Keep the existing progress and terminal-summary vocabulary, but reduce implementation copy.
- Show run UUID by default with a copy button and accessible confirmation.
- Active card: status, progress, processed/succeeded/failed/cancelled/remaining, current title or gate reason, elapsed time, and Stop.
- `stopping`: disable Stop and label it `Stopping...`.
- Retryable terminal card: inline `Retry failed jobs (N)` bound to its own run ID.
- Cancelled card: completed/failed/cancelled summary and no retry in this release.
- Missing qualifying runs render as accessible empty slot cards so layout and slot semantics remain stable.

### Filter controls

- Add an AI-page-scoped searchable multi-select rather than prematurely introducing a global component; reuse existing filter-chip visual conventions.
- Persist a versioned, validated filter object and limit in `localStorage`.
- Never persist all-pending acknowledgement.
- Debounce preview requests and cancel stale requests with `AbortController`; a late response must not replace a newer filter preview.
- Disable launch while preview is loading/invalid/empty, during submission, or while any active run exists.
- Reset clears controls, persisted state, preview, and all-pending acknowledgement.
- All-pending and Stop confirmations describe concrete consequences.

## Error handling

- `409 active_run_exists`: refresh overview/monitor and show the active run ID.
- Invalid filter/date/limit: field-level validation from the normalized API error.
- Preview failure: preserve controls, mark count unavailable, and disable launch rather than guessing.
- Partial overview/monitor refresh behavior remains degraded-but-visible as it is today.
- Filter-option failure: retain already loaded options when available; otherwise disable affected controls with a retry action.
- Stop/retry failure: keep the originating card visible and show action-scoped feedback.

## Compatibility and rollout

- Apply the migration/bootstrap convergence before deploying API or workers that emit `stopping`, `waiting`, or `cancelled_items`.
- Deploy backend before frontend so old UI remains compatible with extended monitor payloads.
- Removing public single-ID endpoints is an intentional breaking change; verify no repository consumer remains.
- Existing restored databases may contain multiple active rows. Migration/bootstrap must first reconcile stale active runs using existing startup-recovery rules, then create the partial unique index; do not silently delete run history.
- Rollback frontend independently by restoring the old component against additive backend fields. Backend rollback requires dropping the partial index/new columns only after no run is `waiting` or `stopping`.

## Validation strategy

- Service tests for filter normalization, candidate exclusion, date inclusivity, oldest-first selection, reservations, and preview/create parity.
- Concurrency tests with two sessions proving only one active slot can be acquired across create/retry/automatic promotion.
- Worker tests proving no item starts after Stop observation and in-flight results survive cancellation.
- API tests for option hierarchy, preview, 409 contracts, stop idempotency, monitor slot selection, and removed single-ID routes.
- Frontend tests for compact metrics, exact two-slot rendering, copy UUID, inline retry, Stop/Stopping, filter persistence, all-pending safety, stale-preview cancellation, and responsive DOM order.
- Existing frontend polling, degraded refresh, terminal summary, and StrictMode tests remain part of the regression gate.
