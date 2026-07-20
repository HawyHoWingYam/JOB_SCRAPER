# Versioned Crawl Scope and Automation control design

## Module boundaries

This child adds four backend modules:

- `CrawlScopeService`: canonicalize, preview, resolve, and assess catalog impact.
- `AutomationService`: current Automation projection, immutable revisions, lifecycle, and optimistic concurrency.
- `DispatchPlanService`: server-backed review, finite target snapshots, and atomic dispatch.
- `TaskControlBoardProjectionService`: normalized Automation/run/catalog/readiness views.

Existing `CrawlJobDispatchService` remains the durable Crawl Job/event/outbox launcher but receives an already frozen plan payload. Existing `CrawlJobCancellationService` remains the cancellation authority.

## Versioned contracts

### Authored Crawl Scope

```json
{
  "version": 1,
  "source_site": "jobsdb",
  "reviewed_catalog_revision_id": "e6d8...uuid",
  "mode": "rules",
  "rules": [
    {"kind": "exact", "classification_id": "jobsdb:6281"}
  ]
}
```

```json
{
  "version": 1,
  "source_site": "ctgoodjobs",
  "reviewed_catalog_revision_id": "d4a1...uuid",
  "mode": "all",
  "rules": []
}
```

Validation:

- `mode=all` requires no rules.
- `mode=rules` requires at least one Exact/Subtree rule.
- Every ID must be source-qualified for the same Source and present in the reviewed revision.
- Rule kind must be supported by the node.
- Canonicalization deduplicates rules and removes descendants/exacts already covered by a selected subtree.
- Display labels, canonical aliases, and empty values never become identities/defaults.

`reviewed_catalog_revision_id` records the operator's authoring context. It is not an execution lock for future Automation runs.

### Resolved Run Scope

```json
{
  "version": 1,
  "source_site": "jobsdb",
  "catalog_revision_id": "current-published-uuid",
  "authored_scope": {},
  "selected_classifications": [
    {
      "classification_id": "jobsdb:6281",
      "native_label": "Information & Communication Technology",
      "native_path": ["Information & Communication Technology"]
    }
  ],
  "classification_expansion_hash": "sha256",
  "query_targets": [
    {
      "version": 1,
      "adapter": "jobsdb.classification",
      "classification_id": "jobsdb:6281",
      "native_id": 6281
    }
  ],
  "query_target_count": 1,
  "warnings": []
}
```

The resolver traverses the normalized published revision itself: all mode begins at the revision's declared all-scope roots; Subtree walks the selected descendant closure; Exact keeps only the selected node. It selects each queryable classification once, then calls the Source adapter for each ordered node. OfferToday uses `default_to_it=False` here and cannot add categoryless keyword targets. The resolved payload stores the ordered expansion hash and is immutable/secret-free. The worker receives it; history renders its label/path snapshot even if a later catalog changes.

### Listing settings

```json
{
  "version": 1,
  "crawl_mode": "headless",
  "page_depth": 3,
  "run_page_cap": 75
}
```

`estimated_max_pages = query_target_count * page_depth`. Preparation rejects when estimate exceeds operator cap or system ceiling. Runtime still checks an aggregate page counter before every request, so an adapter bug cannot exceed the plan.

### Detail Backlog Scope and settings

```json
{
  "version": 1,
  "crawl_mode": "headless",
  "backlog_scope": {
    "kind": "crawl_scope",
    "scope": {}
  },
  "limit": {
    "kind": "entire_snapshot"
  }
}
```

Other backlog scope variants:

```json
{"kind":"source_backlog"}
{"kind":"listing_batch","source_listing_crawl_job_id":"uuid"}
```

Explicit limit:

```json
{"kind":"stop_after","detail_run_cap":500}
```

`entire_snapshot` selects the full eligible set only if count is at or below the system absolute cap. `stop_after` selects at most that many deterministic distinct canonical `source_job_id` values. Recovery Segment size is resolved from pacing settings after the snapshot exists and may partition only that membership.

## Scope compatibility and catalog impact

`CrawlScopeService.assess_catalog_change` uses the same canonicalization/resolution code as dispatch.

Compatible without per-Automation review:

- label-only change;
- hierarchy move that preserves referenced identity/query semantics;
- new descendant under all/subtree when total workload remains within cap.

Requires review:

- referenced ID removed or made non-executable;
- selected node's query semantics changed;
- exact/subtree capability changed;
- alias change alters target deduplication;
- added descendants make estimated workload exceed cap.

Publication impact returns before/after selected labels, Query Targets, counts, cap result, and reason codes. Publication transaction writes `scope_review_required` only for incompatible Automations.

## Automation persistence and lifecycle

Extend `scrape_schedules` as the current Automation projection:

- `revision INTEGER NOT NULL`;
- `lifecycle_state`: `active|paused|archived|scope_review_required`;
- `scope_contract JSONB`;
- explicit `listing_page_depth`, `listing_run_page_cap`, `detail_run_cap`;
- `detail_backlog_scope JSONB`;
- existing phase/mode/cron/timezone/name/description;
- timezone-aware UTC `last_run_at`, `next_run_at`, `created_at`, `updated_at`, and `archived_at`; the IANA `timezone` controls cron interpretation only.
- `scope_review_reason JSONB`.

Legacy `category_ids/max_pages/detail_limit/is_active` are not authoritative after cutover and may be removed once old code is retired.

`automation_revisions`:

- Automation FK;
- monotonic revision;
- immutable full configuration/lifecycle snapshot;
- operation, actor, timestamp;
- unique `(automation_id, revision)`.

Every mutation locks the current row, compares `expected_revision`, validates the transition, increments revision, writes revision snapshot, updates current projection, and commits. APScheduler registration is an eventually consistent projection: an immediate best-effort reconcile plus the existing periodic reconcile recovers drift. Every due callback carries its registered Automation Revision and must lock/re-read the database row before plan creation; stale revision or non-active lifecycle skips dispatch and requests reconciliation. A stale in-process scheduler job can therefore never bypass committed database state.

Lifecycle:

```text
active -> paused | archived | scope_review_required
paused -> active | archived | scope_review_required
scope_review_required -> paused | active(after reviewed update) | archived
archived -> paused | active(after current-scope review)
```

Archive never cascades. Change `schedule_executions.schedule_id` to nullable `ON DELETE SET NULL` and retain plan/Automation snapshots on each execution; `crawl_jobs.schedule_id` already uses `SET NULL`. Permanent deletion is a separate archived-only transaction with a short-lived impact token: it deletes the current Automation and its configuration revisions, while detached Schedule Execution/Crawl Job/run history remains. The impact review states this exact boundary.

## Dispatch Plan persistence

`crawl_dispatch_plans`:

- UUID, state `prepared|consumed|expired`;
- source, phase, trigger kind;
- optional Automation ID and expected Automation Revision;
- active catalog revision;
- Authored/Resolved Scope JSON;
- listing/detail settings and readiness JSON;
- plan fingerprint and confirmation-token hash;
- prepared/expiry/consumed timestamps;
- optional Crawl Job ID.

`crawl_dispatch_plan_targets`:

- plan FK;
- source site;
- canonical `source_job_id`;
- deterministic selection order;
- eligibility fingerprint/status metadata;
- unique `(plan_id, source_job_id)`.

`crawl_dispatch_plan_target_rows`:

- plan-target FK and every contributing `crawl_job_listing` row FK;
- eligibility fingerprint/status at preparation;
- unique `(plan_target_id, crawl_job_listing_id)`.

`crawl_jobs` gains non-null-after-cutover `dispatch_plan_id` and `dispatch_plan_fingerprint`. Its JSON `request_payload` is a derived compatibility/audit projection and is not an executable source of scope, Query Targets, limits, or backlog membership.

Target rows are distinct canonical fetch identities; target-row mappings freeze every staging sibling claimed/outcome-updated for that identity. They are exact Backlog Snapshot truth and are never logged as lists. Consumed plans remain linked to history; expired unconsumed plans are cleaned after a retention window.

## Plan preparation

`prepare(SavedAutomationRun | OneOffRun)`:

1. Validate command and optional Automation Revision.
2. Load current published Source Catalog.
3. Canonicalize and resolve Authored Crawl Scope.
4. Resolve crawl mode/capability/pacing.
5. Calculate listing workload or select deterministic distinct detail targets and every eligible staging-row membership contributing to each target.
6. Lock/check active manual detail conflict when applicable.
7. Verify headed-worker/readiness and absolute caps.
8. Persist immutable plan, target membership, expiry, and confirmation token.
9. Commit without launching or changing listing/detail statuses.

A blocked request may return a non-dispatchable review projection without a confirmation token. Conflict details include current Crawl Job ID/status/progress and cancel capability.

## Plan dispatch

`dispatch(plan_id, confirmation_token)`:

1. Lock plan; require `prepared`, unexpired, matching token.
2. Require the plan catalog revision is still the Source's active published revision.
3. If saved Automation, lock it and require the expected Automation Revision/lifecycle.
4. Recheck runtime readiness and active detail conflicts.
5. For detail, require every planned target and mapped staging row is still eligible and atomically claim that exact membership; any drift rejects the whole plan as stale.
6. Create pending Schedule Execution when applicable.
7. Create queued Crawl Job with `dispatch_plan_id`, `dispatch_plan_fingerprint`, and compatibility `request_payload` snapshot.
8. Persist requested event and outbox command.
9. Mark plan consumed/link Crawl Job and commit once.
10. Launch/publish after commit through existing infrastructure.

A stale failure does not partially claim targets or dispatch a smaller run. Scheduled dispatch executes prepare and consume in one transaction and therefore has no expiring human-review gap.

## Runtime consumption and progress

- Launcher/executor startup loads the consumed Dispatch Plan by Crawl Job ID, verifies the stored plan fingerprint and target schema version, and rejects missing/mismatched plans. It never rebuilds execution from a Schedule or trusts mutable `request_payload` fields. A later active-catalog switch does not invalidate an already consumed in-flight plan.
- Listing runtime iterates only plan Query Targets and enforces page depth plus one aggregate requested-page counter. Retained Scrapy callbacks may not auto-start detail work from listing results.
- Detail runtime reads only `crawl_dispatch_plan_targets` and their mapped rows, partitions them into internal Recovery Segments, and cannot query new eligible rows into the same run. JobsDB/CTgoodjobs listing-to-detail callback chaining is disabled for versioned plans; detail is a separately dispatched plan.
- Manual-action resume keeps the original plan/fingerprint/target membership and applies only a separate execution-generation/resume-context overlay; it must not rewrite scope or limits in the plan.
- Existing cancellation sets `cancelling`; acknowledgement releases still-running target/listing rows to pending and preserves completed outcomes.
- Snapshot service emits:
  - authored/resolved scope summary and catalog revision;
  - listing target count/page depth/run cap/pages requested;
  - detail snapshot target/fetched/saved/failed/unavailable/manual/remaining;
  - future eligible backlog separately from remaining-in-snapshot;
  - plan/Automation revision and lifecycle/readiness.
- Frontend consumers do not parse `request_payload` or raw event priorities.

## API

- `POST /api/v1/crawl-scopes/preview`.
- `GET/POST/PUT /api/v1/automations`.
- `POST /api/v1/automations/{id}/pause|resume|archive|restore`.
- `POST /api/v1/automations/{id}/delete-reviews`; archived-only permanent delete.
- `POST /api/v1/dispatch-plans`.
- `GET /api/v1/dispatch-plans/{id}`.
- `POST /api/v1/dispatch-plans/{id}/dispatch`.
- `GET /api/v1/task-control-board?source_site=...`.

Mutation requests carry `expected_revision`; responses return current revision and may also emit `ETag`. Conflict responses include current revision but not an unsafe auto-merge.

Stable errors:

- `AUTOMATION_REVISION_CONFLICT`
- `AUTOMATION_TRANSITION_INVALID`
- `SCOPE_REVIEW_REQUIRED`
- `SCOPE_RULE_INVALID`
- `WORKLOAD_CAP_EXCEEDED`
- `BACKLOG_SAFETY_CAP_EXCEEDED`
- `DETAIL_RUN_CONFLICT`
- `DISPATCH_PLAN_EXPIRED`
- `DISPATCH_PLAN_STALE`
- `DISPATCH_PLAN_ALREADY_CONSUMED`
- existing headed-worker/cancellation errors.

## Destructive cutover

### Preconditions

- New schema/model/bootstrap paths deployed and tested.
- All three initial Source Catalog Revisions explicitly published.
- Scheduler, Crawl workers, outbox publisher, and API mutations stopped.
- No external Scrapyd/local crawl process remains.
- Database backup and preserve/reset row-count report completed.

### FK-safe reset

Within a controlled maintenance transaction/batched script:

1. Delete only pending/unpublished crawl-related `event_outbox` rows, never unrelated enrichment messages.
2. Delete `crawl_job_listings`.
3. Delete `crawl_job_events`.
4. Delete `crawl_job_executions`.
5. Delete `schedule_executions`.
6. Delete `crawl_runs`.
7. Delete `crawl_dispatch_plan_target_rows`, `crawl_dispatch_plan_targets`, and `crawl_dispatch_plans` if any test/control records exist.
8. Delete `crawl_jobs`.
9. Delete `automation_revisions` and `scrape_schedules`.
10. Verify preserved Jobs, Companies, taxonomy, enrichment, skills, embeddings, and Source Catalog revisions.
11. Create a smoke Automation/One-off plan only after services restart.

The script records before/after counts and aborts if preserve-table counts change. It must account for the ORM/migration mismatch around `crawl_job_listings.crawl_job_id` and inspect actual DB constraints.

### Rollback

Before commit, rollback the transaction and keep services stopped. After commit, restore the backup and deploy compatible old code; no down migration can recreate deleted history.

## Spec compatibility

Only after snapshot/cap, normalized metrics, cancellation/recovery, and cross-source runtime tests pass and the spec diff is reviewed:

- update OfferToday production detail contract from live per-segment continuation to finite plan membership/complete-run cap;
- update normalized detail metrics with snapshot/future-backlog distinction;
- update frontend pacing/snapshot guidance;
- preserve cancellation and logging contracts.
