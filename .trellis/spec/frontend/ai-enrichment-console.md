# AI Enrichment Operations Console

## 1. Scope / Trigger

Use this contract when changing `AIEnrichmentPage`, its API payloads, run cards, polling, or filtered-run persistence.

## 2. Signatures

- Overview fields: `pending_jobs`, `manual_pending_jobs`,
  `needs_job_description`, `ai_eligible_jobs`, `active_runs`, `failed_jobs`.
- Monitor run additions: `cancelled_items`, `excluded_items`, `excluded_details`, `stop_requested_at`; `stopping` is active.
- Storage key: `ai-enrichment-filtered-run:v1` stores ordinary filters and limit only.

## 3. Contracts

- Render exactly one compact metric strip and two monitor slots.
- Visual order is Run Monitor before Filtered Run on desktop and narrow screens.
- A populated card shows/copies UUID; retry is card-local and only for failed/completed-with-failures.
- The displayed dimension is Origin: JobsDB, CTgoodjobs, OfferToday, and Manual
  Entry. The compatibility request/storage field remains `source_sites`.
- External origins cascade Origin -> Source Classification -> Source
  Subclassification, remain searchable, and clear hidden invalid selections.
  Manual-only scope hides both Source classification controls and never creates
  a fabricated Source path.
- Preview is debounced and aborts stale requests. Launch displays `effective_item_count` and is disabled for loading/error/zero/active/submitting.
- Preview also displays `excluded_item_count` and grouped `excluded_items` details (source category ID/name, count, reason); excluded jobs are not included in the launch count.
- Every exclusion deep link carries the detail's source-qualified
  `source_classification_id` as the Governance filter when the current AI
  filter is empty; the backend derives that detail from the preserved Source
  Classification Path root and uses legacy Job scalar fields only as a
  display fallback. The human-readable name remains display-only metadata. The
  link also carries the bounded `job_ids` and stable exclusion `reason` so a
  large batch is not expanded back to the entire pending source scope.
- Terminal `completed_with_exclusions` is an attention state, not a provider failure. Settled progress is `completed_items + failed_items + cancelled_items + excluded_items`; excluded items never enable retry.
- Run creation may return `execution_result = "no_supported_items"` with `run_status = "completed_with_exclusions"`; the monitor still renders the persisted exclusion report.
- All-pending acknowledgement never persists and requires a consequence-focused confirmation. Stop confirms in-flight work may finish.
- Storage remains `ai-enrichment-filtered-run:v1`; only filters and limit persist.
  Legacy-key reads may migrate to v1, but transient acknowledgement never does.

## 4. Validation & Error Matrix

- Filter-option failure -> retain prior options if present and show degraded feedback.
- Preview failure -> retain controls, disable launch, and do not guess a count.
- `409 active_run_exists` -> show active run ID and refresh monitor/overview.
- Storage read/write failure -> fall back to in-memory defaults; operations remain usable.
- Exclusion detail missing or malformed -> retain the count/status and render an empty detail list; never reinterpret the count as failed.
- A large bounded exclusion deep link keeps its exact Job IDs; never widen an
  empty or stale scope into the global Review queue.
- Explicit Manual-only Origin with no Source classifications -> submit
  `source_sites: ["manual"]`; never normalize it to an empty/all-pending filter.

## 5. Good / Base / Bad Cases

- Good: preview says 12 match/12 effective and button says `Run 12 filtered jobs`.
- Good: preview says `14 match · 12 will run · 2 excluded` and lists `Farming (offertoday:113000)` with its reason.
- Good: Manual Entry alone shows Manual pending and Needs job description
  metrics while Source Classification controls are absent.
- Base: fewer than two qualifying runs render accessible empty slot cards.
- Bad: a detached retry button that silently targets whichever failed run happens to be newest.
- Bad: rendering `completed_with_exclusions` through the failure summary or offering `Retry failed jobs (2)` for two excluded items.

## 6. Tests Required

- Assert compact metrics, two-slot combinations, empty slots, UUID copy, inline retry, Stop/Stopping, and cancelled summaries.
- Assert option cascade, stale-preview cancellation, normalized create payload, persistence/Reset, all-pending safety, and 409 feedback.
- Assert Manual Entry round-trip through v1 storage, Manual-only control hiding,
  explicit scoped payload, invalid/stale selection cleanup, and storage
  read/write failure fallback.
- Preserve active polling, visibility pause/resume, degraded partial refresh, production build, desktop two-column and narrow monitor-first checks.
- Assert `completed_with_exclusions` shows excluded metrics/details, reaches settled progress, and has no retry action; assert preview details preserve source IDs/names and reasons.

## 7. Wrong vs Correct

### Wrong

```jsx
<button onClick={() => retryFailedItems(retryTargetRun)}>Retry failed</button>
```

### Correct

```jsx
<button onClick={() => retryFailedItems(run)}>
  Retry failed jobs ({run.failed_items})
</button>
```

### Cross-layer exclusion rendering

#### Wrong

```jsx
const processed = run.completed_items + run.failed_items;
const canRetry = run.status !== 'completed';
```

#### Correct

```jsx
const processed = run.completed_items
  + run.failed_items
  + run.cancelled_items
  + run.excluded_items;
const canRetry = isRetryableTerminalRun(run);
```

Keep the persisted run status and exclusion reason visible. Exclusions are
non-attempted taxonomy decisions, not provider errors.
