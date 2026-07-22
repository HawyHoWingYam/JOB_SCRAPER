# Design: AI Enrichment bootstrap and Source Catalog provenance recovery

## 1. Boundaries

The fix has three cooperating boundaries:

1. **Execution authority → Source Job Attributes**
   Versioned crawl workers already possess an immutable, source-scoped
   `catalog_revision_id` in their `ExecutionAuthorityV1`. That pinned revision
   must be attached to collected Source Classification Paths before
   `SourceJobAttributes.project(...)` persists them. A worker without a
   versioned Dispatch Plan must not silently guess the active revision.

2. **Historical provenance repair**
   A separate read/repair service handles existing OfferToday paths whose
   revision FK is NULL. It validates the selected published revision against
   every persisted node identity before writing. Repair is operator-invoked and
   requires the expected revision ID/fingerprint to prevent catalog drift.

3. **AI console read projection**
   Overview and monitor responses use compact run projections because the
   console consumes counters, titles, timestamps, statuses, and exclusion
   details—not the full `job_ids` arrays. Detail/status endpoints retain their
   existing full run payload compatibility unless a consumer proves otherwise.

## 2. Data flow

```text
Dispatch Plan authority
  -> source-scoped catalog revision ref
  -> parsed Source Job Attribute evidence
  -> SourceJobAttributes.project()
  -> path revision FK + canonical taxonomy preflight
  -> AI pending preview/run

Historical paths with NULL revision
  -> read-only coverage report
  -> operator confirms pinned published revision
  -> bounded provenance repair through SourceJobAttributes
  -> source-attribute outbox events
  -> canonical preflight can evaluate repaired jobs

AI console
  -> compact /ai/overview and /ai/runs?monitor=true payloads
  -> existing truthful partial/degraded rendering and polling
```

## 3. Versioned ingest wiring

- Add one typed helper for applying a source catalog revision to evidence paths.
  It fills only missing path revisions, validates source and fingerprint, and
  rejects an already-populated mismatched revision.
- Keep parsers pure and retain optional revision parameters for direct parser
  callers/tests. The persistence boundary supplies the authoritative revision
  from the crawl plan rather than querying a live source.
- For the Redis ingest worker, resolve the immutable authority from the
  `crawl_job_id` before projecting evidence. Versioned events use the plan's
  revision; legacy jobs without a Dispatch Plan retain their current
  provenance-limited behavior.
- For the direct OfferToday detail pipeline, pass the detail runtime's pinned
  revision into the same projection boundary. The `DetailRuntimePlan` must
  expose the revision identity needed by the pipeline.
- Do not use the current active pointer as an implicit fallback for a
  versioned/legacy crawl. This preserves the rule that collected evidence is
  bound to the revision actually used by the crawl.

## 4. Historical repair service

Add a dedicated service beside Source Job Attributes, separate from the
existing read-only `SourceJobAttributeRebuildInspector`:

### Read-only inspection

- Input: source site, explicit published revision ID, optional job/date scope.
- Load the revision and build an identity set from its normalized catalog
  payload (`classification_id` values), preserving the source-qualified IDs.
- Inspect persisted classification paths in bounded batches.
- Classify each job as repairable only when every path needing repair has all
  node identities covered by the selected revision and the path belongs to the
  selected source.
- Report repairable jobs/paths, already-bound paths, unknown identities,
  source mismatches, missing paths, and the exact revision/fingerprint. The
  report is deterministic and performs no writes.

### Apply

- Require the caller to provide the expected revision ID and fingerprint from
  the report. Lock/re-read the active pointer and abort on drift.
- Recheck coverage inside the write transaction; never trust a stale report.
- Update only NULL path revision FKs. Existing non-NULL paths are not silently
  rewritten.
- Use a public `SourceJobAttributes` repair method as the transaction boundary.
  It validates the revision, updates projection version/hash metadata, and
  emits one `job.source_attributes_changed` outbox event per changed job. It
  must be idempotent when rerun against already repaired paths.
- Commit in bounded batches and expose changed/skipped/rejected counts. A
  failure rolls back the current batch and leaves later batches untouched.
- Provide an explicit operator script with report-only default and a separate
  confirmation flag for writes. The implementation task must run the report
  against the local corpus but must not apply the 9,458-job repair
  automatically.

## 5. Compact AI API projection

- Add an `include_job_ids` option to the internal run serializer.
- `/ai/overview` and `/ai/runs?monitor=true` set it to false; run detail,
  status, and existing non-monitor list consumers preserve the current field.
- Keep exclusion details, counts, current/latest titles, run IDs, and terminal
  status unchanged so the frontend behavior and governance deep links remain
  truthful.
- Add a backend regression assertion that monitor/overview payloads omit
  `job_ids` while detail serialization still includes it.

## 6. Compatibility and safety

- No schema migration is required: `source_catalog_revision_id` is already a
  nullable FK and the existing projection version/hash columns are available.
- Canonical preflight remains the only gate into the LLM boundary. Repair does
  not assign canonical taxonomy or bypass mapping coverage.
- Existing `completed_with_exclusions`, retry, limit-before-exclusion, and
  oldest-first semantics remain unchanged.
- Existing parser tests without a revision continue to produce valid,
  provenance-limited evidence; versioned persistence tests cover the attached
  revision path.

## 7. Rollback / operational controls

- Compact response changes are endpoint-local and can be reverted without
  touching stored data.
- The repair command is report-first, pins an expected revision, writes in
  bounded transactions, and records standard source-attribute outbox events.
  Do not run `--apply` until the report is reviewed and the task's quality gate
  passes.
- If repair must be stopped, stop between batches. Already repaired paths are
  safe to rerun; no duplicate projection event is emitted for an exact replay.
- No destructive reset, taxonomy activation, or live source/network access is
  part of this task.
