# Technical design

## Boundaries

This change has two responsibilities:

1. Bring the JobsDB and CTGoodJobs standalone detail executors back onto the
   current `IngestWorkerService` persistence contract.
2. Make a detail execution stop after a deterministic persistence/programming
   failure while preserving the existing retryability contract for frozen
   detail rows.

The source parsers, canonical job builders, dispatch-plan snapshot authority,
manual-action policy, and the current Job Intelligence taxonomy remain outside
this change. In particular, the removed Company Industry projection is not
restored: current persistence ends with `project_source_attributes()` after
Company and Job upserts.

## Persistence contract

Both source executors keep one database transaction around the supported
projection sequence:

```text
canonical detail
  -> build/upsert Company
  -> build/upsert source Job
  -> project source attributes
  -> commit
```

Any exception before commit rolls the transaction back. Detail completion is
recorded only after this transaction commits, so a published Job and its detail
row cannot be reported as complete before supported projections succeed.

Tests and fakes must expose only the current interface. Removing the stale fake
`project_company_industry()` call is part of the regression guard because the
fake currently hides executor/service drift.

## Exception boundary

The detail loop distinguishes failures by where and what they represent rather
than by matching error-message text:

- Source fetch/parse/content outcomes that are already modeled by source-level
  exceptions retain their target-specific failed, terminal-unavailable, or
  manual-action behavior.
- `InvalidIngestPayloadError` remains a target-content outcome for CTGoodJobs,
  including the existing consecutive-content-anomaly pause policy.
- Cancellation always propagates to the existing cancellation settlement.
- Unexpected exceptions from canonical persistence/projection are run-fatal.
  The current target may be marked failed once for operator evidence, then the
  exception propagates to the executor boundary; later targets are not
  attempted.

The implementation should establish this separation structurally, preferably
with a small persistence helper or explicit run-fatal wrapper, instead of a
growing allow/deny list of exception strings.

## Failed-run settlement

`CrawlJobRuntime.mark_failed()` currently records only the terminal Crawl Job
event. Cancellation, launch failure, and heartbeat timeout separately reuse
`CrawlJobCancellationService.release_running_detail_rows()` to reset only rows
that satisfy all of these conditions:

- `last_detail_crawl_job_id` belongs to the failed Crawl Job;
- `detail_status` is still `running`;
- when present, the row belongs to the Crawl Job's frozen dispatch plan.

Add a runtime-level failed-detail settlement operation that performs the
equivalent terminal transition and release in one database transaction. Its
observable payload records the released-row count and, when rows exist, a
recovery event with the row records. The operation preserves completed,
terminal-unavailable, manual-action, and already-failed rows; only unresolved
`running` membership returns to `pending`.

The executor's outer failure handler uses this settlement for detail runs and
keeps the existing `mark_failed()` path for listing runs. Cancellation remains
owned by the cancellation supervisor and must not be converted into failure.

## Data flow

```text
target starts -> row running -> fetch/parse -> persist transaction
                                      |              |
                                      |              +-> commit -> row completed
                                      |
                                      +-> modeled target error -> settle target -> continue/pause
                                      |
                                      +-> unexpected persistence error
                                            -> rollback
                                            -> mark current target failed once
                                            -> abort loop
                                            -> atomically fail Crawl Job
                                               and release remaining running rows
```

## Compatibility and operations

- No schema migration or historical event rewrite is required.
- The operator-cancelled CTGoodJobs Crawl Job is not restarted or mutated.
- Existing successful/failed target evidence remains intact.
- A later detail run can select the explicitly failed target according to the
  existing retry statuses and can select released `pending` targets normally.
- Rollback is code-only: revert the executor boundary and runtime settlement;
  no persisted compatibility method or taxonomy data needs cleanup.

## Classification observation ownership

Complete catalog synchronization owns crawl query metadata such as CTGoodJobs
`url_path`. Incremental classification-path observation during detail ingest
owns captured identity, label, and hierarchy evidence but must merge any
provided metadata into the existing row instead of replacing authoritative
query metadata with an empty payload. Newly observed path-only nodes may still
start with empty query metadata and remain unavailable as crawl-authoring
choices until a complete catalog sync supplies executable metadata.

## Trade-offs

- Marking the first affected target failed gives precise evidence but means it
  is retried through the failed-status path while untouched rows use pending.
  This matches current retry eligibility and avoids erasing the trigger.
- Centralizing row release in runtime settlement avoids duplicating SQL in both
  executors. It also keeps ownership and frozen-plan filtering identical to
  cancellation/watchdog recovery.
- Narrow exception handling requires explicit modeled source failures. That is
  preferable to treating unknown programming defects as ordinary bad content.
