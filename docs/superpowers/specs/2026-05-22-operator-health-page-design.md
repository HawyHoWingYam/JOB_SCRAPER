# Operator Health Page Design

> Status: Accepted for implementation planning
> Date: 2026-05-22
> Batch: 3

## Problem Statement

The project now has meaningful runtime health signals spread across multiple surfaces, but operators still have to infer overall system posture from a mix of `/health`, scheduler banners, queue lag symptoms, and backend behavior. After Batch 2, scheduler-worker ownership is explicit, but the operator experience is still fragmented: there is no dedicated health page, no unified read model for runtime summaries, and no single place to inspect queue backlog, dead-letter posture, manual-action backlog, or headed crawl readiness.

This creates two problems:

1. Operators cannot quickly answer whether the system is healthy enough to trust automation.
2. Developers keep adding one-off health banners instead of converging on one operator contract.

Batch 3 addresses visibility and triage first. It does not yet add remediation actions such as retry, acknowledge, or restart.

## Goals

- Add one authoritative operator health contract that backend and frontend can both rely on.
- Add a dedicated operator health page in the existing frontend shell.
- Surface scheduler, worker, queue, backlog, outbox, dead-letter, and headed runtime status in one place.
- Preserve partial visibility when one subsection is unavailable instead of failing the whole page.
- Reuse and extend the current `/health` aggregation logic rather than creating a second disconnected health system.

## Non-Goals

- No retry, acknowledge, requeue, or restart actions in this batch.
- No React Router migration in this batch.
- No full audit-event write model for recovery actions in this batch.
- No persistent headed browser heartbeat/history model in this batch.
- No deep remediation workflows for dead-letter or manual-action items in this batch.

## Current Context

### Frontend

- The app still uses local `activeView` state in `frontend/src/App.jsx` rather than React Router.
- `Sidebar.jsx` controls navigation with view IDs such as `dashboard`, `jobs`, `companies`, `ai`, `scheduler`, and `settings`.
- `ScheduleManager.jsx` already consumes `/api/v1/capabilities` and `/health` to render scheduler and operator banners.
- `frontend/src/api/client.js` now exists and provides shared JSON parsing, timeout, and `detail` extraction behavior.

### Backend

- `backend/app/api/health.py` already aggregates Redis queue and database freshness signals into `build_operator_health_summary()` and returns them from root `/health`.
- `backend/app/services/runtime_capabilities_service.py` already reuses those health summaries for `/api/v1/capabilities`.
- Batch 2 added `scheduler_runtime_heartbeats` and scheduler-worker freshness reporting.
- Ingest dead-letter events still go directly to `stream.job.ingest.dead_letter` and are not modeled as first-class DB remediation rows.
- Manual-action detail backlog is visible indirectly through crawl progress and `crawl_job_listings.detail_status = manual_action_required`.
- Headed crawl runtime has host-side startup scripts and a dedicated headed worker stream, but no persisted heartbeat table yet.

## Considered Approaches

### Approach A: Health-First Unified Summary Page (Recommended)

Add a dedicated operator page backed by one normalized operator summary. Extend the current health aggregation to include scheduler, crawl worker visibility, dead-letter counts, manual-action backlog, headed runtime summary, and outbox posture.

Why this is recommended:
- It builds directly on Batch 2 rather than bypassing it.
- It gives immediate operator value with bounded backend risk.
- It creates a stable contract that later recovery/remediation features can consume.
- It avoids premature workflow/action design before read models are stable.

Trade-off:
- The page will be read-only first, so operators still execute recovery elsewhere.

### Approach B: Recovery-First Workflow Surface

Build recovery previews, script execution wrappers, resume/cancel/requeue audit trails, and manual-action workflow state before creating a broader health page.

Trade-off:
- Stronger process control, but weak overall observability.
- Harder to prioritize because operators still lack one place to see what is broken.

### Approach C: Dead-Letter-First Remediation Surface

Promote ingest dead-letter handling to a first-class operator feature before widening health coverage.

Trade-off:
- Valuable for ingestion correctness, but too narrow for the current operator gap.
- Does not solve scheduler, outbox, queue, headed runtime, or manual-action visibility.

## Recommended Architecture

Batch 3 will implement Approach A.

### High-Level Shape

- Keep root `/health` as the lightweight health endpoint used by infra and existing callers.
- Add `/api/v1/operator/health` as the dedicated operator contract for frontend consumption.
- Move aggregation logic behind a backend operator health service so both endpoints use the same normalized data.
- Add a new frontend `OperatorHealthPage` mounted inside the existing `activeView` shell and reachable from the sidebar.

### Core Principle

One authoritative operator summary, many consumers:
- `/health` returns the root health view with embedded operator summary.
- `/api/v1/capabilities` continues consuming selected operator state.
- `ScheduleManager` can continue showing narrow banners from the same contract.
- The new operator page renders the full contract without re-deriving logic client-side.

## Backend Design

### New Route

Add a dedicated router, likely `backend/app/api/operator.py`, mounted under `/api/v1/operator`.

Initial endpoint:
- `GET /api/v1/operator/health`

This endpoint returns the full operator summary contract intended for human-facing UI. It is separate from root `/health` so frontend code can evolve without coupling to infra-oriented root endpoint semantics.

### New Service Boundary

Introduce a backend service module, likely `backend/app/services/operator_health_service.py`, to own summary construction. The current `build_operator_health_summary()` logic in `backend/app/api/health.py` should become a thin wrapper around this service.

Responsibilities of the new service:
- compose worker status
- compose queue status
- compose backlog status
- compose scheduler status
- compose headed runtime status
- compose freshness metrics
- derive normalized issues and overall severity

This service should accept no HTTP-layer types. It should return plain dicts or typed Pydantic response models.

### Operator Health Contract

The contract should include these top-level sections:

- `status`
  - `healthy | degraded | critical`
- `generated_at`
  - UTC ISO timestamp for when the summary was built
- `issues`
  - flat human-readable issue list for quick display
- `workers`
  - worker-specific status summaries
- `queues`
  - queue-specific lag and pending summaries
- `scheduler`
  - scheduler-worker ownership/freshness summary from Batch 2
- `headed_runtime`
  - best-effort headed crawl runtime summary
- `backlogs`
  - summarized backlog counters for operational triage
- `freshness`
  - newest job, embedding, scheduler reconcile, and similar timestamps

### Workers Section

Batch 3 worker rows should include at least:
- `ingest-worker`
- `enrichment-worker`
- `embedding-worker`
- `scheduler-worker`
- `crawl-headed-worker` when applicable
- retrieval and recommendation sidecars as runtime units, even if they are HTTP sidecars rather than stream consumers

Each worker entry should expose:
- `status`
- `reason`
- `stream` or `endpoint` where relevant
- `group`
- `pending`
- `lag`
- `consumers`
- `last_heartbeat_at` where available
- `last_error` where available

For workers without persisted heartbeat models, `status` remains derived from currently observable signals. The contract should be explicit about which fields are unavailable instead of implying false precision.

### Queues Section

Extend existing Redis group summaries and add dead-letter visibility.

Required entries:
- ingest command stream/group summary
- lifecycle stream/group summaries
- crawl headed command stream/group summary if configured
- dead-letter stream summary for `stream.job.ingest.dead_letter`

Fields per queue:
- `length`
- `pending`
- `lag`
- `consumers`
- `oldest_message_age_seconds` when practical, otherwise defer with `null`

Batch 3 can treat dead-letter stream length as the minimum viable signal even if age metrics are not yet cheap to compute.

### Scheduler Section

Reuse Batch 2 scheduler contract directly, including:
- `owner`
- `worker_name`
- `available`
- `manual_run_available`
- `heartbeat_status`
- `last_heartbeat_at`
- `last_reconcile_at`
- `active_schedule_count`
- `registered_job_count`
- `reason`
- `last_error`

This remains the authoritative scheduler view for both the operator page and scheduler UI.

### Headed Runtime Section

Batch 3 does not invent a new persisted headed runtime table. Instead it exposes a best-effort summary derived from current configuration and runtime shape.

Fields:
- `configured`
- `browser_channel`
- `browser_user_data_dir_configured`
- `browser_user_data_dir_exists`
- `lock_port`
- `worker_group`
- `worker_status`
- `reason`

Important constraint:
- `last_browser_error`, `last_heartbeat_at`, and lock ownership are not yet first-class persisted runtime facts. These remain deferred until a later runtime-status batch adds storage for them.

This keeps the contract honest and useful without pretending we already have observability we do not yet persist.

### Backlogs Section

Batch 3 should expose operator-triage counters for:
- `pending_detail_rows`
- `failed_detail_rows`
- `manual_action_detail_rows`
- `outbox_pending`
- `outbox_failed`
- `dead_letter_count`
- `missing_current_embeddings`
- `ai_backlog_jobs` if already derivable cheaply

Manual-action backlog should come from persisted listing/detail status, not from ephemeral progress state.

### Freshness Section

Retain current job and embedding freshness and add:
- `scheduler_last_reconcile_at`
- `scheduler_last_heartbeat_at`
- `dead_letter_stream_seen_at` if cheaply derivable

### Severity Rules

Batch 3 should make severity derivation explicit in code.

Recommended rules:
- `critical`
  - queue lag beyond current critical condition
  - pending messages beyond current critical condition
  - scheduler missing/stale only if automation is expected and not intentionally absent
- `degraded`
  - dead-letter count > 0
  - outbox failed > 0
  - manual-action backlog > 0
  - missing embeddings > 0
  - headed runtime misconfigured when headed crawling is supported but not operable
- `healthy`
  - no critical/degraded issue triggered

Do not collapse all non-healthy cases into a single reason. Preserve individual issues so the page can explain why a system is degraded.

## Frontend Design

### Navigation Integration

The frontend currently uses `activeView` in `App.jsx`. Batch 3 should stay within that model.

Changes:
- add a new `operator` view ID to `Sidebar.jsx`
- lazy-load `OperatorHealthPage` in `App.jsx`
- keep existing views unchanged

No React Router migration in this batch.

### New API Client

Add a dedicated frontend API helper, likely `frontend/src/api/operatorHealth.js`, built on top of `apiFetchJson()` from `frontend/src/api/client.js`.

Responsibilities:
- fetch `/api/v1/operator/health`
- preserve timeout behavior
- normalize fetch-layer failures into one error string

### New Page

Add `frontend/src/components/operator/OperatorHealthPage.jsx` and a matching CSS file.

The page should render these sections:
- overall status header
- issue summary list
- worker status grid
- queue status grid
- scheduler card
- headed runtime card
- backlog metrics section
- freshness section

### UX Behavior

- manual refresh button
- visible `last updated` timestamp from `generated_at`
- partial rendering when some subsections are missing or null
- clear `Unavailable` copy instead of blank gaps
- no destructive actions in Batch 3

### Visual Direction

Follow the current dashboard/operator visual language rather than inventing a new system.
- reuse glass-panel/card patterns
- reuse status color semantics already present in dashboard and scheduler components
- keep layout readable on desktop and mobile
- prefer grouped operational cards over a giant raw JSON table

### Interaction with Existing Scheduler UI

`ScheduleManager` already shows scheduler and operator banners. Batch 3 should not replace that local guidance. Instead:
- keep the local scheduler warning banner
- align it to the same contract used by `OperatorHealthPage`
- allow later deep-linking to operator view, but do not require deep-link infrastructure in this batch

## Data Access and Query Plan

Batch 3 should prefer cheap aggregated queries over detailed row hydration.

Recommended sources:
- existing `build_operator_health_summary()` queries for jobs, outbox, enrichment, embeddings
- `crawl_job_listings` grouped counts for pending/failed/manual-action detail rows
- Redis `xlen`/`xinfo_groups` for queue posture
- `scheduler_runtime_heartbeats` for scheduler state
- runtime settings/config presence checks for headed runtime summary

Avoid:
- loading full listing row sets
- parsing large stream contents unless required for a minimal age signal
- introducing remediation tables in this batch

## Error Handling Strategy

### Backend

- If Redis is unavailable, return partial DB-derived operator data with `status = degraded` and explicit Redis issue strings.
- If DB aggregation fails, return partial queue-derived data with explicit DB issue strings.
- If a subsection cannot be computed, keep the whole contract valid and mark that subsection unavailable.

### Frontend

- If `/api/v1/operator/health` fails, render an error state for the page without affecting other views.
- If a subsection field is null or absent, render explicit fallback labels.
- Do not make the page all-or-nothing when only one metric group is unavailable.

## Testing Strategy

### Backend Tests

Add or extend tests for:
- `GET /api/v1/operator/health` contract shape
- scheduler stale/missing status propagation into operator summary
- dead-letter summary reporting
- manual-action backlog counts reporting
- headed runtime summary for configured vs missing profile path cases
- degraded vs critical severity derivation

Likely files:
- `backend/tests/test_health_api.py`
- new `backend/tests/test_operator_health_api.py` if route coverage becomes too large

### Frontend Tests

Add tests for:
- operator view appears in sidebar and app shell
- page fetches operator health API and renders grouped sections
- degraded/critical states show issue summaries clearly
- missing subsection fields render graceful fallback copy
- manual refresh re-fetches the operator payload

Likely files:
- `frontend/src/components/operator/OperatorHealthPage.test.jsx`
- `frontend/src/components/Sidebar.test.jsx`
- `frontend/src/App.test.jsx`

## File Plan

### Backend

Create:
- `backend/app/api/operator.py`
- `backend/app/services/operator_health_service.py`
- `backend/tests/test_operator_health_api.py` if needed

Modify:
- `backend/app/api/__init__.py`
- `backend/app/api/health.py`
- `backend/app/services/runtime_capabilities_service.py` only if the normalized operator contract needs a small alignment hook
- possibly repository/service modules if a small grouped-query helper is cleaner than inlining SQL in the operator health service

### Frontend

Create:
- `frontend/src/api/operatorHealth.js`
- `frontend/src/components/operator/OperatorHealthPage.jsx`
- `frontend/src/components/operator/OperatorHealthPage.css`
- `frontend/src/components/operator/OperatorHealthPage.test.jsx`

Modify:
- `frontend/src/App.jsx`
- `frontend/src/components/Sidebar.jsx`
- related app/sidebar tests

## Rollout Notes

- Batch 3 is intentionally additive. Existing `/health`, scheduler page behavior, and capabilities consumers keep working.
- The new `/api/v1/operator/health` route becomes the frontend's preferred operator read model.
- Root `/health` remains stable for container probes and current consumers.
- This batch prepares Batch 4, where recovery/remediation actions can attach to the new operator read model.

## Risks

- Health aggregation can become a dumping ground if new signals are added without boundaries. The dedicated service module is necessary to contain that growth.
- Headed runtime status may be over-interpreted unless the contract clearly labels inferred versus persisted data.
- If queue and backlog thresholds are implicit, the page will be noisy or misleading. Batch 3 should keep threshold logic explicit and test-covered.

## Success Criteria

Batch 3 is successful when:
- operators can open one page and understand current runtime posture without jumping between scheduler, logs, and implicit failures
- scheduler-worker state from Batch 2 is visible both locally and in a broader operator context
- queue lag, dead-letter count, manual-action backlog, and outbox posture are all visible in one contract
- the page is useful even when Redis or one subsystem is partially unavailable
- tests prove both backend contract shape and frontend rendering for healthy/degraded states

