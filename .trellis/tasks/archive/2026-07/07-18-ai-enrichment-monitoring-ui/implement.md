# Implementation plan: AI Enrichment monitoring-first console

## Execution principles

- Implement backend lifecycle correctness before exposing new frontend actions.
- Keep preview and create on one shared candidate-query path.
- Keep each commit independently testable and avoid mixing lifecycle, filter, and layout changes.
- Do not activate this task until the user approves `prd.md`, `design.md`, and this plan.

## Ordered commits

### 1. Add enrichment lifecycle persistence and convergence

- Add `cancelled_items` and `stop_requested_at` to `EnrichmentRun`.
- Add lifecycle constants for waiting/active/terminal states.
- Add an Alembic migration and Docker bootstrap convergence for columns and the partial single-active index.
- Reconcile stale active rows before index creation using explicit startup-recovery behavior.
- Extend startup recovery for `pending`, `running`, and `stopping`; keep `waiting` durable and eligible for later promotion.
- Add model/migration tests or schema assertions.

Validation:

```bash
docker compose run --rm backend-api python -m pytest -q tests/test_ai_enrichment_runs.py -k "schema or lifecycle"
```

Rollback point: migration/index only; no API behavior changed yet.

### 2. Centralize filtered candidate selection

- Introduce normalized filter request models.
- Build one service candidate query for overview, options, preview, and create.
- Add source/classification/subclassification/date filtering, reservation exclusion, count preview, limit, and deterministic oldest-first ordering.
- Add filter-option hierarchy and preview API endpoints.
- Test empty filters, all-pending acknowledgement, multi-value OR, cross-field AND, inclusive dates, reserved jobs, and preview/create parity.

Validation:

```bash
docker compose run --rm backend-api python -m pytest -q tests/test_ai_enrichment_runs.py -k "filter or preview or candidate"
```

### 3. Enforce and schedule the global active slot

- Add transaction advisory-lock helpers and map unique-index conflicts to a stable domain conflict.
- Route manual filtered create, retry, and automatic promotion through the shared slot owner.
- Persist blocked automatic work as waiting and promote oldest ready work after terminal transitions, crawl/ingest gate changes, startup recovery, and the recurring worker maintenance sweep.
- Reject manual create/retry with `409 active_run_exists` while occupied.
- Add cross-session race tests and automatic-work retention tests.

Validation:

```bash
docker compose run --rm backend-api python -m pytest -q tests/test_ai_enrichment_runs.py -k "active or concurrent or waiting or promotion"
```

Rollback point: waiting/promotion behavior is isolated before Stop changes.

### 4. Implement cooperative Stop

- Add `POST /ai/runs/{run_id}/stop`.
- Make pending cancellation immediate and running cancellation transition through `stopping`.
- Add conditional item start checks against persisted run status.
- Finalize stopping runs with accurate completed/failed/cancelled counts and prevent normal finalization from overwriting cancellation.
- Promote waiting automatic work after terminal cancellation.
- Test API idempotency, in-flight completion, untouched-item cancellation, cross-process observation, and crawl independence.

Validation:

```bash
docker compose run --rm backend-api python -m pytest -q tests/test_ai_enrichment_runs.py -k "stop or stopping or cancel"
```

### 5. Make monitor selection explicit and remove single-ID behavior

- Replace adjacency-based monitor selection with active-plus-latest-terminal / two-latest-terminal queries.
- Serialize `cancelled_items` and stopping state.
- Remove `/ai/enrich-job/{job_id}`, public batch/job-ID create mode, and unused public explicit-ID service entry points.
- Keep internal post-scrape/retry wrappers around `_create_run`; they must pass through the appropriate slot or waiting policy.
- Retain legacy `/ai/enrich` with required all-pending acknowledgement and route it through the shared slot/filter service.
- Verify `/jobs/manual`, post-scrape creation, and retry remain intact.
- Add monitor and route-removal regression tests.

Validation:

```bash
docker compose run --rm backend-api python -m pytest -q tests/test_ai_enrichment_runs.py
```

### 6. Add frontend filter state and API integration

- Add an AI-page-scoped searchable multi-select and filter chips.
- Load option hierarchy, persist validated ordinary filters/limit, and keep all-pending acknowledgement ephemeral.
- Add debounced abortable preview and normalized create payload.
- Handle active-run 409, preview errors, empty matches, all-pending confirmation, and Reset.
- Remove Target Job UUID state, UI, request handler, and tests.

Validation:

```bash
docker compose run --rm frontend-ui npm test -- --run src/components/ai/AIEnrichmentPage.test.jsx
```

### 7. Redesign the monitoring-first page hierarchy

- Replace large stat cards and duplicate ribbon with the compact three-metric strip.
- Reverse the two-column content order: Run Monitor left, Filtered Run right.
- Reduce explanatory copy and preserve monitor-first responsive DOM order.
- Keep exactly two task cards, visible/copyable UUID, and concise status/progress summaries.
- Add accessible empty, loading, and degraded states.

Validation:

```bash
docker compose run --rm frontend-ui npm test -- --run src/components/ai/AIEnrichmentPage.test.jsx
docker compose run --rm frontend-ui npm run lint
```

### 8. Add inline Stop and retry card actions

- Bind Stop/Stopping to the active card.
- Bind retry to each visible retryable terminal card's own ID.
- Remove detached Retry Target/Retry Failed controls.
- Add confirmation, action-scoped feedback, polling refresh, and disabled-state tests.

Validation:

```bash
docker compose run --rm frontend-ui npm test -- --run src/components/ai/AIEnrichmentPage.test.jsx
```

### 9. Run full cross-layer verification

- Exercise preview -> create -> monitor -> stop/retry round trips.
- Verify restored PostgreSQL schema convergence and partial-index behavior.
- Run backend and frontend suites, lint, and frontend build.
- Manually inspect desktop and narrow layouts with zero, one, and failed active/terminal combinations.

Validation:

```bash
docker compose run --rm backend-api python -m pytest -q tests
docker compose run --rm frontend-ui npm test
docker compose run --rm frontend-ui npm run lint
docker compose run --rm frontend-ui npm run build
```

## Likely affected files

- `backend/app/models/enrichment_run.py`
- `backend/app/services/enrichment_run_service.py`
- `backend/app/api/ai.py`
- `backend/app/workers/run_enrichment_worker.py`
- `backend/scripts/bootstrap_db.py`
- `backend/alembic/versions/<new-enrichment-lifecycle-migration>.py`
- `backend/tests/test_ai_enrichment_runs.py` (new focused suite)
- `frontend/src/components/ai/AIEnrichmentPage.jsx`
- `frontend/src/components/ai/AIEnrichmentPage.css`
- `frontend/src/components/ai/AIEnrichmentPage.test.jsx`
- Optional AI-scoped filter component under `frontend/src/components/ai/`

## Review gates before activation

- User approves the final product behavior and planning artifacts.
- API payload and lifecycle states are reviewed for preview/create parity.
- The waiting automatic-work policy and single-active database backstop are accepted.
- Stop race tests cover cross-process requests and in-flight completions.
- No repository caller remains for public manual single-ID enrichment.
