# Versioned Crawl Scope and Automation control contract

## Goal

Replace ambiguous `category_ids` and overloaded workload fields with versioned Authored/Resolved Crawl Scope, auditable Automation lifecycle, immutable Dispatch Plans, finite detail Backlog Snapshots, and an approved destructive Crawl Control Data cutover.

## Background

- Current Automations store flat `category_ids`, `max_pages`, `detail_limit`, and one `is_active` flag. Updates overwrite unconditionally and delete cascades execution history (`backend/app/models/schedule.py:9-108`; `backend/app/repositories/schedule_repository.py:88-149`).
- Current dispatch rebuilds a mutable payload from the latest schedule, but `ScheduleExecution.request_payload_snapshot` provides an existing run-freeze seam (`backend/app/services/crawl_job_dispatch_service.py:112-129,203-288`).
- Current OfferToday detail behavior treats `detail_limit` as a per-segment cap and can chase a changing backlog; this task intentionally replaces that operator contract (`.trellis/spec/backend/offertoday-production-crawl.md:676-697`).
- Cancellation already preserves committed work and requires `cancelling → cancelled`; this task must not weaken it.

## Requirements

### Scope and revision contracts

- `AuthoredCrawlScopeV1` contains `source_site`, `reviewed_catalog_revision_id`, and either `mode=all` or non-empty canonicalized rules of `exact`/`subtree` with source-qualified IDs.
- All/default behavior is explicit. An empty rules list is invalid and never means a source-specific fallback.
- Scope preview and future Automation dispatch resolve against the current published revision. The resulting immutable `ResolvedRunScopeV1` contains the actual revision, selected-node snapshots, deduplicated non-secret Query Targets, target count, and warnings.
- Label/move-only changes may remain compatible. Missing/non-executable referenced nodes, changed selected-query semantics, or cap-breaking expansion return `scope_review_required`.
- Catalog publication/rollback impact uses the same resolver as dispatch; no UI/backend duplicate logic.

### Workload and detail selection

- Listing configuration uses `page_depth` per Query Target plus aggregate `run_page_cap`; estimated maximum must fit both the operator cap and system ceiling before dispatch, and runtime enforces the cap across all targets.
- Detail configuration uses complete-run `detail_run_cap`; internal Recovery Segment size remains pacing/runtime configuration and cannot increase the run total.
- `DetailBacklogScopeV1` is one of `source_backlog`, `crawl_scope`, or `listing_batch`. It cannot silently switch to the newest batch or apply hidden category narrowing.
- Entire-backlog execution freezes exact eligible membership, count, and cutoff in a Backlog Snapshot under the absolute safety cap. Later-eligible items remain for a later run.
- Backend snapshot/progress/history projections expose run cap, selected count, processed outcomes, remaining-in-snapshot, and live future backlog as distinct concepts. React must not reconstruct them from raw events.

### Dispatch and Automation lifecycle

- Manual review creates a short-lived, single-use `DispatchPlan` containing the exact resolved scope, execution settings, readiness, Automation Revision if any, and detail target membership. Creating a plan launches no external crawl.
- Dispatch consumes only that plan. Expired, already-consumed, Automation-version-stale, runtime-unready, or no-longer-eligible plans reject with a structured stale/blocking result.
- Scheduled Automations prepare and consume an equivalent plan atomically.
- Every scheduler callback revalidates the registered/current Automation Revision and lifecycle under database lock; stale in-process APScheduler registration may lag reconciliation but cannot dispatch.
- Crawl Jobs persist Dispatch Plan ID/fingerprint, and workers load the consumed immutable plan as execution authority. Compatibility `request_payload` cannot override scope, targets, or limits; resume context is a separate overlay.
- Crawl Job, Schedule Execution, requested event/outbox command, plan consumption, resolved snapshot, and detail target claims commit in one transaction before launch.
- Automation has monotonic revision and lifecycle `active | paused | archived | scope_review_required`. Immutable Automation Revision snapshots support audit and compare-and-swap updates.
- Edit affects future dispatch only. Pause blocks future schedules only and Resume does not backfill. Archive blocks dispatch and preserves revisions/runs; Restore revalidates current scope.
- Permanent deletion is archived-only and requires a fresh impact token. It removes Automation configuration/revisions but detaches and preserves Schedule Execution, Crawl Job, and run history through immutable snapshots.
- `Run saved configuration` never edits the Automation; `Run with changes` is a One-off plan.
- Listing and detail Automations remain independent; matching-detail creation copies only safe source/scope context.
- Run cancellation remains in the existing Crawl Job lifecycle and preserves `cancelling → cancelled`, committed outputs, and retryable unfinished detail rows.

### APIs, errors, and cutover

- New Automation, One-off, preview, Dispatch Plan, board/history, and catalog-impact schemas share the same versioned domain payloads.
- Stable machine-readable errors distinguish version conflict, stale scope, cap exceeded, plan expired/stale, active detail conflict, catalog unpublished, and headed worker unavailable.
- Automation/scheduler instant columns and API values are timezone-aware UTC; the saved IANA timezone controls cron interpretation and display, including non-HKT/DST behavior.
- Legacy schedule/category endpoints may temporarily adapt to the new module, but no new code writes primitive `category_ids` or relies on empty-array defaults.
- Cutover runs in a maintenance window after published initial Source Catalogs exist: stop schedulers/workers/outbox/API writes, record preserve/reset counts, delete only pending crawl outbox and Crawl Control tables in FK-safe order, verify the Published Job Corpus, then resume.
- Source Catalog tables/revisions are retained. Jobs, Companies, canonical taxonomy, enrichment, skills, and embeddings are never deleted by this cutover.
- Because the reset is destructive, rollback after commit means restoring the pre-cutover database backup plus compatible code; a schema downgrade cannot recreate deleted control data.
- Fresh-DB bootstrap and existing-DB convergence/Alembic paths both create the new schema despite the repository's incomplete baseline.

## Acceptance criteria

- [ ] Authored and Resolved scope schemas are source-qualified, versioned, explicit, canonicalized, and shared across Automation/One-off/catalog impact.
- [ ] Exact, subtree, and all mode resolve deterministically against one published revision and produce immutable, non-secret Query Targets.
- [ ] Catalog changes classify compatible versus `scope_review_required` Automations with the same resolver used at dispatch.
- [ ] Listing preview/runtime distinguish Page Depth from Run Page Cap and cannot exceed the reviewed aggregate.
- [ ] Detail preview/runtime distinguish Detail Run Cap, Recovery Segment, Backlog Snapshot remaining, and live future backlog.
- [ ] Source/crawl-scope/listing-batch detail selection and exact Backlog Snapshot membership are covered for all supported Sources.
- [ ] Dispatch Plan review and confirmed execution cannot drift; stale/expired/double-consumed plans fail explicitly.
- [ ] Concurrent Automation edits, lifecycle transitions, and dispatch use compare-and-swap and preserve in-flight snapshots.
- [ ] Pause/Resume, Archive/Restore, permanent-delete review, Run saved configuration, and independent listing/detail semantics are covered.
- [ ] Cancellation regression tests preserve `cancelling → cancelled` and committed work.
- [ ] Board/run APIs expose normalized projections without requiring frontend raw-event/request parsing.
- [ ] The maintenance cutover removes only approved Crawl Control Data and proves retained corpus counts/FKs.
- [ ] Fresh bootstrap, existing DB migration/convergence, focused/full tests, and rollback rehearsal pass.
- [ ] The OfferToday/detail and normalized snapshot specs are updated only after implementation verification.

## Dependency and scope

- Depends on the executable published-catalog contract from `07-18-source-catalog-runtime-correctness`.
- Provides real Automation impact to `07-18-source-catalog-governance-ui` and all backend contracts consumed by `07-18-task-control-board-wizard-ui`.
- Frontend board, wizard, and governance-page rendering are out of scope.
