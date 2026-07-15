# Implementation plan: OfferToday global detail backlog recovery

## Execution mode

- Implement directly in the main Codex session after this task is activated.
- Keep unrelated dirty-worktree changes untouched.
- Do not run a large live OfferToday recovery; use deterministic fixtures and
  repository/runtime tests.
- No database migration or historical event rewrite is planned.

## Ordered implementation checklist

### 1. Normalize the detail scope contract

- [ ] Add the two-value scope contract (`global` and `listing_batch`) in the
      standalone request path and validate invalid combinations early.
- [ ] Update `_apply_request_payload_defaults()`, `_resolve_detail_scope()`,
      `_build_runtime_request_payload()`, and manual-action resume context in
      `backend/scripts/offertoday_standalone_crawl.py`.
- [ ] Make a missing scope normalize to `listing_batch` when a batch ID is
      present, otherwise `global`; do not retain the old category-filtered
      legacy branch.
- [ ] Ensure `listing_batch` always has a non-empty
      `source_listing_crawl_job_id`, while `global` omits or nulls it.
- [ ] Update `CrawlJobDispatchService.resume_crawl_job()` and its resume-context
      recovery helpers so a resume copies the persisted scope and original
      batch ID, without querying or selecting the newest batch.
- [ ] Keep the existing detail resume status behavior unless the new
      continuation state explicitly requires a change: manual-action resumes
      still target the recoverable manual/pending rows, while a later operator
      run can explicitly include failed rows.

### 2. Make candidate loading scope-aware

- [ ] Extend the `CrawlJobRuntime.load_detail_targets()` boundary to pass the
      resolved `detail_scope` rather than inferring global behavior from
      `category_ids` alone.
- [ ] Update `resolve_offertoday_detail_category_ids()` and its callers so a
      new global scope and an explicit batch scope both return no category
      predicate for detail selection.
- [ ] Update the repository candidate query so:
      - `global` filters only `source_site=offertoday` plus eligible statuses
        and the existing terminal/identity-conflict sibling blocker;
      - `listing_batch` filters the selected listing crawl-job ID;
      - both scopes include `source_classification_id IS NULL` rows; and
      - category IDs never narrow a detail query.
- [ ] Preserve canonical `source_job_id` grouping, authoritative-row and
      duplicate-row handling, identity audits, complete-job reconciliation,
      and the existing status ordering.
- [ ] Expose the pre-slice distinct eligible target count and the post-slice
      segment target count to the detail controller. Keep `detail_limit` a
      distinct source-job cap, not a staging-row cap.

### 3. Split one detail segment from task completion

- [ ] Refactor `_run_detail_phase()` in
      `backend/scripts/offertoday_standalone_crawl.py` into a segment operation
      that performs the current load/reconcile/fetch/persist work but does not
      unconditionally emit final `crawl.completed`.
- [ ] Add an outer same-task controller that keeps one durable crawl-job ID and
      repeatedly loads the next eligible segment with the persisted scope.
- [ ] For every segment, persist or emit:
      - `detail_scope`;
      - `segment_index`;
      - distinct eligible targets before slicing;
      - segment target count;
      - cumulative segment/fetch counts; and
      - continuation state.
- [ ] After a successful segment, refresh the eligible distinct backlog before
      deciding whether to continue. Continue until the query is empty; do not
      infer exhaustion solely from a segment being smaller than 5,000.
- [ ] Ensure completed, terminal, reconciled, and successful targets cannot be
      selected by the next segment, including duplicate staging siblings.
- [ ] Ensure a retryable failed target stops automatic continuation, keeps
      completed progress, writes a failed/partial task outcome, and exposes
      the remaining failed/manual/pending breakdown.
- [ ] Ensure an IP/WAF/manual-action stop keeps completed progress, writes
      `manual_action_required`, and never emits final `crawl.completed` for the
      same segment.
- [ ] Emit final `crawl.completed` only after a refreshed eligible query is
      empty (or an explicit operator-end path is implemented and tested).

### 4. Persist truthful metrics and projection data

- [ ] Extend detail segment and task snapshots with scope, segment counters,
      `detail_backlog_pending`, `detail_backlog_failed`,
      `detail_backlog_manual_action_required`, and
      `detail_backlog_remaining`.
- [ ] Keep all detail progress denominators in distinct canonical
      `source_job_id` units. Do not use `detail_run_completed` or staging-row
      counts as fetched-job totals.
- [ ] Preserve the existing manual-action payload and identity evidence while
      adding the scope needed for same-task resume.
- [ ] Update API snapshot projection so segment progress and remaining global
      backlog are shown as separate values. A manual-action or failed state
      must not be projected as exhausted.

### 5. Change the normal frontend workflow

- [ ] Remove the `ScheduleManager.jsx` effect that applies
      `findNewestEligibleListingBatch()` to OfferToday detail mode.
- [ ] Allow OfferToday detail submission with no category and no batch; submit
      `detail_scope=global` and an empty/null batch ID.
- [ ] Keep the batch selector as an advanced, explicit control. Selecting a
      batch submits `detail_scope=listing_batch` and its ID.
- [ ] Update option/help text to say `Global OfferToday backlog (default)` and
      `Listing Batch Scope (advanced)`; remove language claiming newest-batch
      default behavior.
- [ ] Keep listing-mode category validation and non-OfferToday detail rules
      unchanged.
- [ ] Update progress/task UI to show scope, current segment, remaining global
      backlog, and failed/manual-action counts without changing existing
      non-OfferToday or legacy numeric fallbacks that are still used by the
      current API surface.

### 6. Add focused regression coverage

- [ ] Backend payload/resume tests cover global default, explicit batch scope,
      invalid scope combinations, no newest-batch injection, and scope
      preservation after manual-action resume.
- [ ] Repository/runtime tests cover global pending/failed/manual rows,
      null classifications, explicit batch-only selection, duplicate
      `source_job_id` grouping, sibling blockers, reconciliation, and the
      distinct-target limit.
- [ ] Standalone crawl tests cover one successful segment followed by
      continuation, final exhaustion, retryable-failure stop, manual-action
      stop, cumulative metrics/events, and no false completion.
- [ ] Canonical/detail-pipeline tests cover a null staging classification with
      non-IT `listing_payload.job_functions`, plus the no-function case staying
      null without synthetic global/IT assignment.
- [ ] Frontend tests cover an empty default selector, no newest-batch auto
      selection, submitted `detail_scope`, explicit batch payload, and segment
      versus backlog display. Add focused test files where the current
      checkout has no existing ScheduleManager/ScrapeProgressPanel coverage.
- [ ] Manual-action helper tests cover helper health truthfulness, transport
      failure from `Open Browser`, actionable manual-start/retry guidance, and
      the distinction between missing live-browser reuse and a down helper.
- [ ] Frontend helper-state tests cover disabled `Open Browser`, health retry,
      copyable manual-start guidance, and re-enabling after helper recovery.
- [ ] Verify helper offline does not disable `Resume Fresh`; cover its separate
      headed/browser-runtime failure path.
- [ ] Return the configured helper URL, health URL, and a copyable manual-start
      command from runtime capabilities; keep the command platform-aware.
- [ ] Wire helper health polling and Retry into the manual-action UI; enable
      `Open Browser` only after the helper is reachable.
- [ ] Test helper health success, helper offline, transport failure, retry
      recovery, and no implicit crawl resume without starting a real background
      service in deterministic tests.
- [ ] Verify that opening the browser does not implicitly resume the crawl.

## Validation commands

Run from the repository root after implementation:

```powershell
python -m pytest backend/tests/test_cross_source_crawl_logging.py backend/tests/test_cross_source_ip_recovery.py -q
python -m pytest backend/tests/test_offertoday_global_detail_backlog.py -q
python -m ruff check backend/app backend/scripts
python -m compileall -q backend/app backend/scripts
```

Run the focused frontend tests and build using the repository's existing
frontend package scripts (including any newly added focused test files), then:

```powershell
git diff --check
```

Before reporting completion, run the relevant full backend/frontend regression
suites that are available in the checkout and verify that no unrelated dirty
paths were staged or modified.

## Review gates and rollback points

1. **Scope gate:** request payload, resume payload, repository query, and UI
   agree on `global` versus `listing_batch` before continuation work begins.
2. **Segment gate:** one segment preserves the current detail behavior and
   cannot mark the task completed by itself.
3. **Continuation gate:** a deterministic >5,000 fixture exhausts through
   multiple segments without duplicate fetches; failure/manual action stops
   with remaining counts.
4. **Projection gate:** API/UI counters use canonical IDs and distinguish
   segment progress from backlog remaining.

Rollback can be performed in this order if a gate fails:

1. disable the outer continuation loop while retaining the tested segment
   function;
2. revert frontend default/payload changes;
3. revert global candidate scope changes; and
4. retain additive metrics/events only if they remain harmless to current
   snapshots.
