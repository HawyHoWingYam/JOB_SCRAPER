# Manual Job Detail Pacing Contract

## Scenario: Source-specific manual detail pacing

### 1. Scope / Trigger

Use this contract for manually dispatched `crawl_phase=detail` tasks for
JobsDB, CTGoodJobs, and OfferToday. Listing, full-phase, and schedule-backed
dispatches do not receive this pacing snapshot.

### 2. Signatures

```http
GET  /api/v1/settings/scraper-pacing
PUT  /api/v1/settings/scraper-pacing/{source_site}
POST /api/v1/settings/scraper-pacing/{source_site}/reset
```

```text
scraper_pacing_settings(
  source_site PK,
  interval_min_seconds,
  interval_max_seconds,
  burst_size,
  burst_pause_seconds,
  updated_at
)
```

```python
DetailPacingController.before_attempt() -> int
build_detail_pacing_controller(...) -> DetailPacingController | None
```

### 3. Contracts

- The supported persisted rows are exactly `jobsdb`, `ctgoodjobs`, and
  `offertoday`; each source is updated independently.
- Defaults are 1-3 seconds, burst size 20, and burst pause 30 seconds.
  Both Alembic upgrade and `scripts/bootstrap_db.py` seed missing rows.
  Bootstrap uses `ON CONFLICT DO NOTHING` and must never overwrite an operator
  edit.
- Manual detail dispatch locks the selected source settings row, checks for an
  existing same-source active manual detail task, and stores the resolved value
  under `CrawlJob.request_payload.detail_pacing` in the same transaction.
- Active conflict statuses are `queued`, `dispatching`, `running`,
  `manual_action_required`, and `cancelling`. Schedule-backed rows
  (`schedule_id IS NOT NULL`) are outside this exclusion.
- Resume preserves `request_payload.detail_pacing` verbatim. Mutable cumulative
  position is `CrawlJob.metrics.detail_attempt_count`; it is restored before
  the next attempt but is not projected as a UI pacing parameter.
- Historical tasks without a valid snapshot project `detail_pacing=null`.
  Never substitute current global settings into task history.
- Attempt 1 is immediate. Before later attempts, a completed burst replaces
  the ordinary random interval with the burst pause. Pacing happens before
  each actual detail transport attempt, including CTGoodJobs and OfferToday
  retries. Existing retry backoff remains separate.
- The controller delegates waits to `CrawlCancellationToken.sleep`, whose
  slices are at most one second. Listing navigation, warmup/session checks, and
  manual verification navigation do not call the controller.

The source settings row is the transaction mutex for same-source dispatch.
Do not add a partial unique active-task index until legacy duplicate active
statuses have been audited and cleaned; existing production history can
contain several `manual_action_required` rows for one source.

### 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| interval below 0.1 or above 60 | HTTP 422 / schema validation error |
| minimum exceeds maximum | HTTP 422 / schema validation error |
| burst size outside 1-1000 | HTTP 422 / schema validation error |
| burst pause outside 0-3600 | HTTP 422 / schema validation error |
| unsupported source | HTTP 422 |
| same-source active manual detail task | HTTP 409; create no task |
| different source active detail task | dispatch may proceed |
| listing or schedule-backed dispatch | no snapshot and no detail conflict query |
| invalid or absent historical snapshot | `detail_pacing=null` |
| cancellation during a pacing wait | stop before the next outbound request |

### 5. Good / Base / Bad Cases

- **Good:** OfferToday attempt 1 runs immediately, transient retry 2 waits the
  configured interval, and attempt count becomes 2 before the retry fetch.
- **Base:** A historical JobsDB detail task has no snapshot; Crawl Tasks shows
  pacing as not recorded instead of showing today's global values.
- **Bad:** CTGoodJobs sleeps once per target outside `fetch_page_html`; internal
  retries then bypass pacing.
- **Bad:** Bootstrap inserts defaults with an upsert update and silently resets
  operator-edited values after every restart.

### 6. Tests Required

- `test_scraper_pacing_settings.py`: exact sources/defaults, independent
  update/reset, all safety boundaries, and unknown fields.
- `test_scraper_pacing_migration.py`: exact three-row seed and downgrade.
- `test_scraper_pacing_dispatch.py`: snapshot immutability, conflict statuses,
  and listing exclusion.
- `test_scraper_pacing_dispatch_postgres.py`: two concurrent same-source
  dispatches produce exactly one created task and one conflict.
- `test_detail_pacing_controller.py`: first attempt, ordinary interval, burst
  replacement, zero pause, and resumed cumulative position.
- CTGoodJobs and OfferToday retry tests assert one controller admission per
  fetch attempt and no listing admission.
- `test_crawl_task_snapshot_service.py`: valid snapshot, historical null,
  malformed null, and hidden attempt counter.

### 7. Wrong vs Correct

#### Wrong

```python
for target in targets:
    await asyncio.sleep(current_global_interval)
    await fetch_with_internal_retries(target)
```

This delays the first request, misses retries, ignores cancellation, and lets
global edits rewrite the effective behavior of an existing task.

#### Correct

```python
controller = build_detail_pacing_controller(
    request_payload=crawl_job.request_payload,
    crawl_job_id=crawl_job.id,
    crawl_runtime=runtime,
    cancellation_owner=worker,
)

for attempt in retry_attempts:
    if controller is not None:
        await controller.before_attempt()
    await fetch_detail(attempt)
```

The task-owned snapshot controls every real attempt, while the persisted
cumulative count and cancellation token preserve behavior across Resume.
