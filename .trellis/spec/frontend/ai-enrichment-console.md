# AI Enrichment Operations Console

## 1. Scope / Trigger

Use this contract when changing `AIEnrichmentPage`, its API payloads, run cards, polling, or filtered-run persistence.

## 2. Signatures

- Overview fields: `pending_jobs`, `ai_eligible_jobs`, `active_runs`, `failed_jobs`.
- Monitor run additions: `cancelled_items`, `stop_requested_at`; `stopping` is active.
- Storage key: `ai-enrichment-filtered-run:v1` stores ordinary filters and limit only.

## 3. Contracts

- Render exactly one compact metric strip and two monitor slots.
- Visual order is Run Monitor before Filtered Run on desktop and narrow screens.
- A populated card shows/copies UUID; retry is card-local and only for failed/completed-with-failures.
- Filters cascade source -> classification -> subclassification, remain searchable, and clear hidden invalid selections.
- Preview is debounced and aborts stale requests. Launch displays `effective_item_count` and is disabled for loading/error/zero/active/submitting.
- All-pending acknowledgement never persists and requires a consequence-focused confirmation. Stop confirms in-flight work may finish.

## 4. Validation & Error Matrix

- Filter-option failure -> retain prior options if present and show degraded feedback.
- Preview failure -> retain controls, disable launch, and do not guess a count.
- `409 active_run_exists` -> show active run ID and refresh monitor/overview.
- Storage read/write failure -> fall back to in-memory defaults; operations remain usable.

## 5. Good / Base / Bad Cases

- Good: preview says 12 match/12 effective and button says `Run 12 filtered jobs`.
- Base: fewer than two qualifying runs render accessible empty slot cards.
- Bad: a detached retry button that silently targets whichever failed run happens to be newest.

## 6. Tests Required

- Assert compact metrics, two-slot combinations, empty slots, UUID copy, inline retry, Stop/Stopping, and cancelled summaries.
- Assert option cascade, stale-preview cancellation, normalized create payload, persistence/Reset, all-pending safety, and 409 feedback.
- Preserve active polling, visibility pause/resume, degraded partial refresh, production build, desktop two-column and narrow monitor-first checks.

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
