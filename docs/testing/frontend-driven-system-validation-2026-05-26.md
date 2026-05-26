# Frontend-Driven System Validation - 2026-05-26

## Objective

Validate the current JobsDB workspace from the frontend inward:

- confirm the frontend renders and routes correctly
- confirm the frontend can reach the expected backend APIs
- confirm backend responses line up with database and Redis state
- record failures, blockers, and follow-up actions in one place

Current contract note:

- the `Operator Health` feature was removed later in this session
- the current validation surface is `Dashboard`, `Job Browser`, `Companies`, `AI Enrichment`, `Scheduler`, and `Settings`

## Runtime Under Test

- Workspace path: `C:\Users\hawy.ho.HYAKUNOUSHA\Documents\github\job_scraper\JOB_SCRAPER`
- Frontend target: `http://127.0.0.1:5173`
- Backend target: `http://127.0.0.1:8000`
- PostgreSQL target: `localhost:5433`
- Redis target: `localhost:6379`
- Compose file: `docker-compose.yml`

## Test Phases

### Phase 0 - Environment Alignment

Purpose:

- ensure the running frontend and backend processes reflect the current workspace code
- confirm the worker-profile services needed by the UI are up

Commands:

```powershell
docker compose ps
docker compose restart backend-api frontend-ui
docker compose --profile workers ps
```

Pass criteria:

- `backend-api` and `frontend-ui` restart cleanly
- `backend-api` exposes `/health`
- `frontend-ui` serves the current workspace UI on `:5173`

### Phase 1 - Guardrail Automated Tests

Purpose:

- catch obvious regressions before manual UI validation

Commands:

```powershell
npm --prefix frontend test -- --run
npm --prefix frontend run build
python -m pytest backend/tests/test_health_api.py backend/tests/test_database_integrity_service.py backend/tests/test_database_integrity_report.py backend/tests/test_capabilities_api.py backend/tests/test_scheduler_dispatcher.py backend/tests/test_crawl_jobs_api.py backend/tests/test_ai_settings_api.py backend/tests/test_retrieval_api.py backend/tests/test_recommendations_api.py -q
```

Pass criteria:

- frontend tests pass
- frontend production build passes
- targeted backend tests pass

### Phase 2 - API Smoke Validation

Purpose:

- verify the endpoints the frontend depends on are reachable before interactive testing

Endpoints:

- `GET /health`
- `GET /api/v1/stats/overview`
- `GET /api/v1/ai/overview`
- `GET /api/v1/settings/ai`
- `GET /api/v1/capabilities`

Pass criteria:

- each route returns the expected status code
- each payload matches the frontend that currently consumes it

### Phase 3 - Frontend UI Validation

Purpose:

- exercise the system from the operator-facing UI

Views:

- Dashboard
- Job Browser
- Companies
- AI Enrichment
- Scheduler
- Settings

Pass criteria:

- each view loads without a blank screen
- each view reaches its backing APIs
- visible counts and state badges are coherent with backend data
- mobile navigation remains usable on a narrow viewport

### Phase 4 - Data Plane Validation

Purpose:

- verify backend summaries shown in the UI match database and Redis state

Checks:

- `python backend/scripts/report_database_integrity.py --format markdown`
- PostgreSQL table presence and key counts
- Redis key count

Primary database objects:

- `jobs`
- `job_embeddings`
- `event_outbox`
- `scrape_schedules`
- `schedule_executions`
- `crawl_jobs`
- `enrichment_runs`
- `companies`

Pass criteria:

- database integrity report runs successfully
- UI-visible backlog and integrity metrics match read-only data checks

## Execution Log

### Phase 0 - Environment Alignment

Status: Completed

Notes:

- Ran `docker compose ps`.
- Ran `docker compose restart backend-api frontend-ui`.
- Ran `docker compose --profile workers ps`.
- Confirmed `frontend-ui` still serves `http://127.0.0.1:5173`.
- Confirmed `backend-api` now reflects current workspace code.
- `GET /api/v1/operator/health` no longer returns `404` after the restart.
- `GET /health` now returns a real runtime summary with `status=degraded` because the operator payload is `critical`, not because the route is missing.

### Phase 1 - Guardrail Automated Tests

Status: Completed

Notes:

- Ran `npm --prefix frontend test -- --run`.
- First full frontend run had one timeout in `src/components/settings/AISettingsPage.test.jsx` for `switches providers and submits only the selected provider fields`.
- Re-ran that single test in isolation and it passed in `~1.9s`.
- Re-ran the full frontend suite and it passed cleanly: `19` files, `153` tests.
- Ran `npm --prefix frontend run build` and it passed.
- Ran `python -m pytest backend/tests/test_health_api.py backend/tests/test_operator_health_api.py backend/tests/test_database_integrity_service.py backend/tests/test_database_integrity_report.py backend/tests/test_capabilities_api.py backend/tests/test_scheduler_dispatcher.py backend/tests/test_crawl_jobs_api.py backend/tests/test_ai_settings_api.py backend/tests/test_retrieval_api.py backend/tests/test_recommendations_api.py -q`.
- Targeted backend pytest passed: `62` tests.
- Current interpretation: frontend test suite is green, but one settings test showed an initial timing-sensitive run before passing on rerun.

### Phase 2 - API Smoke Validation

Status: Completed

Notes:

- Initial pre-check before alignment showed `GET /health` returned healthy.
- Initial pre-check before alignment showed `GET /api/v1/operator/health` returned `404`.
- After Phase 0 restart, `GET /api/v1/operator/health` returned `200` with a populated `database` object.
- After Phase 0 restart, `GET /health` returned `status=degraded` and embedded the operator summary.
- Confirmed `GET /api/v1/stats/overview` returned `200` with `total_jobs=3` and `pending_enrichment=3`.
- Confirmed `GET /api/v1/ai/overview` returned `200` with `pending_jobs=3` and `active_runs=0`.
- Confirmed `GET /api/v1/settings/ai` returned `200` with persisted and effective runtime configuration payloads.
- Confirmed `GET /api/v1/capabilities` returned `200` and reported lexical, semantic, hybrid, and recommendation support as available.
- Confirmed the operator payload reports `status=critical` and `database.status=critical`.

### Phase 3 - Frontend UI Validation

Status: Completed

Notes:

- Dashboard loaded correctly and matched API data:
  - `Total Jobs Acquired = 3`
  - `AI Enriched Profiles = 0`
  - `Pending Enrichment = 3`
- AI Enrichment loaded correctly and matched API data:
  - `Pending Jobs = 3`
  - `Active Runs = 0`
  - `Failed Jobs = 0`
  - two persisted run cards rendered in the monitor
- Operator Health loaded correctly and rendered the new database panel:
  - `Overall Status = critical`
  - `Database status = critical`
  - `Staged unpublished rows = 5,436`
  - `Staged-to-published ratio = 1,812`
  - `Taxonomy seed state = Empty`
  - `Advisory schema findings = 5`
- Job Browser loaded correctly:
  - default scope rendered `3` records
  - opening the first job card opened the detail modal
  - the detail modal rendered source classification, company context, description, and related jobs
- Companies loaded correctly:
  - `Visible results = 2`
  - `Descriptions ready = 0`
  - opening `Acme Health` rendered the company detail dialog
- Settings loaded correctly:
  - runtime shell rendered
  - jobs profile showed `Anthropic / deepseek-v4-flash`
  - companies profile showed `Custom / gpt-5.2`
  - concurrency showed `10`
- Scheduler loaded with a real degraded state instead of a blank page:
  - `Scheduler dispatch unavailable`
  - `Scheduler owner: scheduler-worker`
  - `Heartbeat: unknown`
  - progress cards still rendered
- Mobile validation at `390x844` passed for the top navigation:
  - icon buttons did not overlap
  - scheduler page remained readable on the narrow viewport
- Follow-up remediation:
  - updated `frontend/src/components/scraper/ScheduleManager.jsx` to use the shared `/api/v1/operator/health` client instead of `${API_URL}/health`
  - updated `frontend/src/components/scraper/ScheduleManager.test.jsx` to mock the direct operator-health payload shape
  - reran targeted frontend tests for `ScheduleManager`, `OperatorHealthPage`, and `App`; all passed
  - reran the full frontend suite; `19` files and `153` tests passed
  - reran `npm --prefix frontend run build`; it passed
  - restarted `frontend-ui` and rechecked Scheduler in a fresh browser tab
  - post-fix Scheduler now renders the `Pipeline attention required` banner with operator issues
  - post-fix browser console no longer logs the previous `Unexpected token '<'` JSON parse error on Scheduler

### Phase 4 - Data Plane Validation

Status: Completed

Notes:

- PostgreSQL read-only checks passed through MCP.
- Redis read-only checks passed through MCP.
- Direct host-side script execution initially failed when the scripts inherited container-only hostnames (`postgres-db`, `redis-mq`).
- Re-ran host-side scripts with:
  - `DATABASE_URL=postgresql://admin:dev_password@localhost:5433/jobsdb`
  - `REDIS_URL=redis://localhost:6379/0`
- Generated report files:
  - `docs/testing/generated-database-integrity-report-2026-05-26.md`
  - `docs/testing/generated-operator-health-report-2026-05-26.json`
- `operator_health_report.py --json` produced valid output and returned exit code `2`, which is expected for `critical` status rather than a script crash.
- `report_database_integrity.py` generated a markdown report with `status=critical`.
- Database counts matched the frontend and API views:
  - `jobs = 3`
  - `companies = 2`
  - `job_embeddings = 3`
  - `event_outbox published = 1371`
  - `crawl_job_listings completed = 50`
  - `crawl_job_listings pending = 5386`
  - `redis dbsize = 6`
- Key integrity findings confirmed by both API and SQL/report output:
  - missing table `scheduler_runtime_heartbeats`
  - missing column `schedule_executions.request_payload_snapshot`
  - `5436` staged unpublished listing rows
  - taxonomy seed tables are empty
  - ANN vector index is not present on `job_embeddings.embedding`

### Phase 5 - Remediation And Revalidation

Status: Completed

Notes:

- Updated `backend/scripts/bootstrap_db.py` so bootstrap convergence now also:
  - adds `schedule_executions.request_payload_snapshot` when missing
  - backfills `request_payload_snapshot` from `crawl_jobs.request_payload` where possible
  - relies on ORM table creation for `scheduler_runtime_heartbeats`
- Updated `backend/tests/test_bootstrap_db.py` and reran:
  - `python -m pytest backend/tests/test_bootstrap_db.py backend/tests/test_scheduler_dispatcher.py backend/tests/test_operator_health_api.py backend/tests/test_database_integrity_service.py -q`
  - result: `28` tests passed
- Applied bootstrap to the live database with `docker compose up db-bootstrap`.
- Seeded taxonomy data with `docker compose exec backend-api python /app/scripts/seed_taxonomy.py --execute`.
- Verified live database convergence after remediation:
  - `scheduler_runtime_heartbeats` now exists
  - `schedule_executions.request_payload_snapshot` now exists
  - `job_domains = 25`
  - `skill_categories = 8`
  - `skills = 88`
  - `scheduler_runtime_heartbeats` row count = `1`
  - `schedule_executions` row count = `0`, so there were no historic execution rows available to backfill
- Rebuilt and restarted worker-profile services:
  - `scheduler-worker`
  - `ingest-worker`
  - `enrichment-worker`
- Worker image findings:
  - `scheduler-worker` came up healthy after schema convergence
  - `ingest-worker` and `enrichment-worker` needed explicit image rebuild plus forced container recreation before they picked up the current workspace code
- Post-recreate worker behavior improved materially:
  - `ingest-worker` no longer exits on missing `source_company_id` when a company-name fallback is available
  - `enrichment-worker` no longer exits on late `job.ingested` events for terminal crawl-auto runs and now logs `skipped late job.ingested`
- Frontend revalidation after remediation:
  - Scheduler page now shows `Heartbeat: fresh`
  - Scheduler page still shows `Pipeline attention required`, but this now reflects real queue pressure instead of schema breakage
  - Operator Health page now shows:
    - `Scheduler Summary -> Automation available = Yes`
    - `Database status = degraded`
    - `Taxonomy seed state = Ready`
- Current runtime state after remediation:
  - structural scheduler/database issues are fixed
  - taxonomy empty-state issue is fixed
  - operator overall status remains `critical` because active backlog and embedding lag still exist
  - the largest remaining blockers are:
    - `crawl_job_listings` pending detail backlog
    - embedding coverage backlog
    - headed runtime still not configured

### Phase 6 - Operator Health Removal

Status: Completed

Notes:

- Removed the `Operator Health` frontend route, sidebar entry, page component, API client, backend route, backend service, CLI report script, and related tests.
- Updated `backend/app/api/health.py` so `/health` is now a plain service-health endpoint and no longer embeds operator runtime summary.
- Updated `backend/app/services/runtime_capabilities_service.py` so capabilities no longer expose `operator` or `operator_recovery` payloads.
- Removed `ScheduleManager`'s dependency on operator-health polling; scheduler runtime UX now depends on scheduler capabilities and scrape progress only.
- Revalidated live API behavior after restart:
  - `GET /health` returns `{"status":"healthy","service":"backend-api"}` when LLM providers are ready
  - `GET /api/v1/operator/health` now returns `404`
  - `GET /api/v1/capabilities` still returns scheduler, source, search, recommendation, and AI runtime metadata
- Database note:
  - no database rollback was performed for `scheduler_runtime_heartbeats` or `schedule_executions.request_payload_snapshot`
  - those structures still serve live scheduler/runtime behavior and schedule history, so removing them would break current non-operator flows
- Regression checks after removal:
  - targeted frontend tests passed
  - targeted backend tests passed
  - frontend build passed
  - frontend full suite passed on rerun: `18` files, `144` tests

### Phase 7 - Frontend Scheduler And AI Validation

Status: Completed

Notes:

- Scheduler frontend validation:
  - `Scheduler` page loads without the removed operator-health dependency
  - scheduler runtime panel shows `Heartbeat: fresh`
  - direct override remains usable
- JobsDB frontend crawl validation:
  - from `Scheduler -> Direct Override`, launched a `jobsdb` `listing` crawl in `headless` mode for category `6281` with `max_pages=1`
  - frontend progress showed `6281 - Headless -> Completed -> Scraped 32 jobs`
  - launched a `jobsdb` `detail` crawl from the same frontend with `detail_limit=1`
  - backend stored the matching crawl payload with `crawl_phase=detail`, `crawl_mode=headless`, `detail_limit=1`
  - in `Job Browser`, searched `Systems Architect, Network & Security` and opened the detail modal
  - frontend modal showed:
    - original job post `https://hk.jobsdb.com/job/92033660`
    - populated description content
    - source classification and sub-classification
- CTGoodJobs frontend crawl validation:
  - from `Scheduler -> Direct Override`, launched a `ctgoodjobs` `listing` crawl in `headless` mode for category `ctgoodjobs:021` with `max_pages=1`
  - frontend progress showed `ctgoodjobs:021 - Headless -> Completed -> Scraped 22 jobs`
  - switched to `Job Detail Crawl`, selected listing batch `aaf09881-122f-447d-8912-2d14aefc2f43`, and launched a `ctgoodjobs` detail crawl with `detail_limit=1`
  - backend stored the matching crawl payload with `crawl_phase=detail`, `crawl_mode=headless`, `source_listing_crawl_job_id=aaf09881-122f-447d-8912-2d14aefc2f43`
  - in `Job Browser`, searched `Database Administrator (DBA)` and opened the detail modal
  - frontend modal showed:
    - original job post `https://jobs.ctgoodjobs.hk/job/10123096/database-administrator-dba`
    - populated description content
    - company, location, and source classification fields
- AI Enrichment frontend validation:
  - opened `AI Enrichment`
  - changed `Pending Limit` to `1`
  - clicked `Run Pending`
  - frontend showed `Pending enrichment run submitted.`
  - run monitor reflected active runs and a new pending manual run
  - the latest `manual_pending` run completed successfully with `1` item
  - in `Job Browser`, searched `QA Engineer/ Senior QA Engineer` for the completed enriched job
  - frontend detail modal showed:
    - populated `AI Summary`
    - populated `Skills` (`Linux`)
    - populated `Job Taxonomy`
    - populated `Experience`
  - backend/enrichment-worker logs showed active LLM classification work, confirming the request path is live

### Phase 8 - Headed JobsDB And Automation Follow-up

Status: Completed

Notes:

- Initial JobsDB headed frontend failure:
  - from `Scheduler -> Direct Override`, launched a `jobsdb` `listing` crawl in `headed` mode for category `6281` with `max_pages=1`
  - frontend progress showed `6281 - Headed -> Completed -> Scraped 0 jobs`
  - backend stored a completed crawl job with `crawl_phase=listing`, `crawl_mode=headed`, `max_pages=1`
  - host-side headed worker remained running, but its log did not show any new crawl execution after the job was dispatched
  - initial assessment at this point was an API/runtime integration problem in the headed dispatch/consumption path, not a frontend submission failure
  - later evidence in Phase 9 narrowed this to stale crawl-job metrics rather than failed dispatch or failed host-worker consumption
- New Automation live path:
  - from `Scheduler`, created `JobsDB ICT E2E` from the frontend
  - frontend list updated and showed the new automation card
  - frontend `Execute` action queued a crawl job successfully
  - frontend `Logs` action opened execution history and showed a row with request snapshot details
  - while validating this flow, a backend scheduler bug was found:
    - `scheduler-worker` failed to persist APScheduler jobs because the registered callable was not serializable
    - fixed by switching APScheduler registration to a module-level entrypoint in `backend/app/services/scheduler_service.py`
    - rebuilt and recreated `scheduler-worker`
    - after the fix, scheduler logs showed `Added job \"run_scheduled_crawl_job\" to job store \"default\"`
    - `scrape_schedules.next_run_at` for `JobsDB ICT E2E` is now populated (`2026-05-26T18:00:00`)

### Phase 9 - JobsDB Headed Clean E2E Resolution

Status: Completed

Notes:

- Root cause:
  - `jobsdb` headed listing and detail dispatch/consumption were working.
  - listing crawls staged rows in `crawl_job_listings`, but the source listing crawl job did not sync `listings_staged` or `detail_*` counters into `crawl_jobs.metrics`.
  - detail crawls updated `crawl_job_listings.detail_status`, but did not update the source listing crawl job metrics.
  - the frontend therefore rendered the headed listing result as `Completed -> Scraped 0 jobs` even though downstream detail work was available.
- Backend remediation:
  - updated `backend/app/workers/run_crawl_worker.py` so listing persistence and detail status transitions recompute exact status counts from `crawl_job_listings`
  - synced the exact counts back into the source listing crawl job metrics through `increment_metrics`
  - preserved existing runtime metrics such as `pages_processed`, `items_emitted`, and `job_ids_collected`
- Regression coverage:
  - updated `backend/tests/test_crawl_worker.py` so listing-phase tests assert `listings_staged` and all `detail_*` counters
  - updated detail-phase tests so a completed detail crawl also updates the source listing crawl job metrics
- Frontend headed validation:
  - from `Scheduler -> Direct Override`, launched `jobsdb` headed detail against listing batch `4fce5e3f-6613-4506-ad36-5e04fcb2bd39` with `detail_limit=1`
  - while the run was active, the frontend showed `jobsdb crawl - Headed -> Scraping Details -> 1/1 jobs`
  - after the run completed, the Scheduler progress card showed `6281 - Headed -> Downstream Backlog -> 0/32 ingested -> 29 details pending`
  - opened `Job Browser` from the frontend and verified the newly ingested `Senior Programmer` detail modal
  - the modal showed original link `https://hk.jobsdb.com/job/92341496`, company `Sa Sa Cosmetic Company Limited`, populated AI summary, skills, taxonomy, experience, and populated description content
- Database evidence:
  - listing crawl job `4fce5e3f-6613-4506-ad36-5e04fcb2bd39` is `completed`
  - listing metrics are now `listings_staged=32`, `detail_pending=29`, `detail_completed=3`, `detail_running=0`, `detail_failed=0`, `detail_manual_action_required=0`
  - latest headed detail crawl job `ae79e2de-278f-49d6-8467-00c3bde7a258` is `completed`
  - latest headed detail metrics are `items_emitted=1`, `job_ids_collected=1`, `ingest_items_seen=1`, `ingest_jobs_created=1`
  - latest `jobsdb` job row is `source_job_id=92341496`, title `Senior Programmer`, and `description` is populated
- Fresh regression checks:
  - `python -m pytest backend/tests/test_crawl_worker.py backend/tests/test_progress_api.py backend/tests/test_crawl_jobs_api.py backend/tests/test_scheduler_dispatcher.py -q`: `31 passed`
  - `npm --prefix frontend test -- --run`: `18` files, `144` tests passed
  - `npm --prefix frontend run build`: passed

### Phase 10 - Detail And AI Backlog UI/UX Validation

Status: Completed

Notes:

- Frontend runtime note:
  - `frontend-ui` was restarted because the Vite dev server initially served a stale transformed `ScheduleManager.jsx` module that did not include the new backlog guidance text
  - after restart, `http://127.0.0.1:5173/src/components/scraper/ScheduleManager.jsx` included `Detail backlog run` and `backlog-guidance-panel`
- Detail backlog UI validation:
  - opened `Scheduler -> Direct Override` from the frontend
  - switched `Crawl Phase` to `Job Detail Crawl`
  - frontend showed `Detail backlog run`
  - frontend explanation: `Use this to turn staged listing URLs into full job records with description, salary, company, and location details.`
  - selected JobsDB listing batch `4fce5e3f-6613-4506-ad36-5e04fcb2bd39`
  - frontend showed the selected backlog counters before submission:
    - `29 pending`
    - `32 staged`
    - `3 completed`
  - set `Detail Batch Size` to `1`
  - clicked `Engage Scanner` from the frontend
  - backend stored crawl job `760cddf0-7fd8-41de-b6b0-04d9383ce2b5` with `crawl_phase=detail`, `crawl_mode=headed`, `detail_limit=1`, and `source_listing_crawl_job_id=4fce5e3f-6613-4506-ad36-5e04fcb2bd39`
  - after completion, reopening the same Scheduler flow showed:
    - `28 pending`
    - `32 staged`
    - `4 completed`
- AI backlog UI validation:
  - opened `AI Enrichment` from the frontend
  - frontend showed `AI backlog run`
  - frontend explanation: `Processes up to the pending limit from jobs without AI insights, then writes summaries, skills, taxonomy, and experience fields back to Job Browser.`
  - frontend showed `3,033 jobs waiting for AI enrichment`
  - set `Pending Limit` to `1`
  - clicked `Run Pending` from the frontend
  - frontend showed `AI backlog run submitted for up to 1 pending jobs.`
  - backend stored manual enrichment run `5ac3311a-a116-4378-b205-05586ad2ea43` with `source_type=manual_pending`, `total_items=1`, `completed_items=1`, `failed_items=0`, and `status=completed`
  - after completion, the frontend queue overview showed `3,032 jobs waiting for AI enrichment`
  - database count confirmed AI enriched rows increased from `1,330` to `1,331`, and pending rows decreased from `3,033` to `3,032`
- Runtime state observed during validation:
  - two older `crawl_auto` enrichment runs remain in `pending` state:
    - `3f9cc61a-bdbc-4328-95f4-dc0bedda5a07`, `1259` pending items, created `2026-05-26 05:23:54`
    - `f90ed32d-1b84-4aa4-9bc7-fd64a92f69d3`, `1701` pending items, created `2026-05-26 05:24:42`
  - the frontend correctly reports these as `Active Runs`, while manual `Run Pending` still completes independently
- Regression checks:
  - `npm --prefix frontend test -- --run src/components/settings/AISettingsPage.test.jsx`: `1` file, `11` tests passed
  - focused backlog UI tests passed before live frontend validation:
    - `npm --prefix frontend test -- --run src/components/scraper/ScheduleManager.test.jsx src/components/ai/AIEnrichmentPage.test.jsx`: `48` tests passed
  - fresh full frontend suite after live validation:
    - `npm --prefix frontend test -- --run`: `18` files, `146` tests passed
    - `npm --prefix frontend run build`: passed
  - fresh backend regression after live validation:
    - `python -m pytest backend/tests/test_crawl_worker.py backend/tests/test_progress_api.py backend/tests/test_crawl_jobs_api.py backend/tests/test_scheduler_dispatcher.py backend/tests/test_health_api.py backend/tests/test_capabilities_api.py -q`: `37 passed`

### Phase 11 - Orphaned Crawl-Auto Enrichment Run Recovery

Status: Completed

Notes:

- Root cause:
  - two older `crawl_auto` enrichment runs were still `pending` with `started_at=NULL`
  - neither run had a recorded `enrichment.run.requested` outbox event
  - `request_crawl_auto_run_if_ready()` only requested auto enrichment when `items_emitted > 0` and `ingest_items_seen >= items_emitted`
  - this blocked two legitimate terminal cases:
    - terminal crawls where `ingest_items_seen + failed/dead-lettered items` settled the crawl
    - legacy failed crawls where a pending `crawl_auto` run already had run items, but `items_emitted` was `0`
- Backend remediation:
  - updated `backend/app/services/enrichment_run_service.py` so failed/dead-lettered ingest rows count toward the settled-ingest gate
  - allowed terminal crawls with existing pending `crawl_auto` run items to request execution even when `items_emitted=0`
  - added `cancel_run()` to clear unclaimed stale runs without converting their items into failed jobs
  - added `backend/scripts/recover_orphaned_crawl_auto_runs.py` with `preview`, `request`, and `cancel` actions
- Live recovery:
  - dry-run selected exactly the two stale orphaned runs:
    - `3f9cc61a-bdbc-4328-95f4-dc0bedda5a07`, `1259` pending items
    - `f90ed32d-1b84-4aa4-9bc7-fd64a92f69d3`, `1701` pending items
  - executed `cancel` rather than `request` to avoid launching a `2960` item LLM batch
  - both runs are now `cancelled`
  - their `2960` run items are now `cancelled`
  - `pending_items=0`, `completed_items=0`, `failed_items=0` for both cancelled runs
  - jobs remain eligible for normal/manual pending enrichment
  - restarted `enrichment-worker` after the code change so future ready-gate behavior is loaded
- Frontend validation:
  - opened `AI Enrichment` from the frontend after recovery
  - frontend showed `0 ACTIVE RUNS`
  - monitor returned to latest completed run `5ac3311a-a116-4378-b205-05586ad2ea43`
  - old run ids `3f9cc61a...` and `f90ed32d...` no longer appeared as active/pending monitor entries
- Regression checks:
  - `python -m pytest backend/tests/test_enrichment_run_service.py backend/tests/test_recover_orphaned_crawl_auto_runs.py backend/tests/test_enrichment_worker.py -q`: `16 passed`
  - `npm --prefix frontend test -- --run src/components/ai/AIEnrichmentPage.test.jsx`: `25 passed`
  - `npm --prefix frontend run build`: passed

## Open Issues

- `crawl_job_listings` still has a large pending-detail backlog; the Scheduler UI now explains what the detail backlog does and shows selected batch counters before execution.
- `jobs` still has a large AI enrichment backlog; the AI Enrichment UI now explains what `Run Pending` does, reports the waiting-job count, and confirms the requested pending limit after submission.
- The two older `crawl_auto` enrichment runs no longer remain in active `pending` state; they were marked `cancelled` without increasing failed-job counts.
- `event_outbox` currently has no pending rows; latest database check showed all `12850` rows as `published`.

## Final Summary

Status: Completed

- `Operator Health` and its related frontend/backend code paths are removed.
- Frontend flows for `Scheduler`, `Job Browser`, `Companies`, `AI Enrichment`, and `Settings` still work after the removal.
- Scheduler/runtime database structures that are still needed outside the removed feature were kept in place:
  - `scheduler_runtime_heartbeats`
  - `schedule_executions.request_payload_snapshot`
- Frontend-driven crawl validation succeeded for both supported sources through the `headless` path:
  - `jobsdb` listing and detail requests were submitted from the frontend
  - `ctgoodjobs` listing and detail requests were submitted from the frontend
  - frontend detail modals confirmed source job links and populated descriptions for both a JobsDB and a CTGoodJobs sample
- Frontend-driven AI validation succeeded:
  - manual `Run Pending` submission succeeded from the UI
  - the run monitor updated
  - worker logs showed active LLM processing
  - the completed enriched job showed AI-written fields back in the frontend detail modal
- Frontend-driven `New Automation` validation succeeded after a backend fix:
  - create succeeded from the frontend
  - manual execute succeeded from the frontend
  - execution history opened from the frontend
  - scheduler registration bug was fixed and persisted schedules now receive `next_run_at`
- Frontend-driven `jobsdb` headed clean E2E now succeeds:
  - headed listing stages `32` rows and exposes downstream backlog in the Scheduler UI
  - headed detail direct override succeeds from the frontend with `detail_limit=1`
  - the source listing batch metrics update from `30` to `29` pending details after the fresh detail run
  - the newly ingested `Senior Programmer` job opens in `Job Browser` with source link, populated description, and AI-derived fields
- Backlog UI/UX validation succeeded from the frontend:
  - Scheduler detail mode explains the detail backlog and shows pending, staged, and completed counters for the selected listing batch
  - a frontend-submitted JobsDB headed detail run decremented the selected listing batch from `29` to `28` pending details and incremented completed details from `3` to `4`
  - AI Enrichment explains the AI backlog and confirms the selected pending limit after `Run Pending`
  - a frontend-submitted `manual_pending` AI run completed `1` item and reduced the AI pending count from `3,033` to `3,032`
- The remaining problems are operational backlog/runtime state rather than missing frontend flows:
  - large detail backlog
  - large AI enrichment backlog
  - Redis `stream.job.lifecycle` still has old pending entries for the `enrichment-workers` consumer group; these are stream hygiene and are separate from the frontend-visible AI active-run state
