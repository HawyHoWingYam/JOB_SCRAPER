# AI Enrichment workflow design

## Boundaries

Preserve the backend-owned eligibility, oldest-first selection, queue slot, cooperative stop and failed-only retry semantics. Keep exactly two monitor slots and the existing monitor-before-filter visual order. Add read-only history and selected-run inspection after the primary console.

## Scope and preview

Tag each preview with its filter/limit/acknowledgement signature. Input changes immediately invalidate launch and old preview presentation. Show matching, selected within the limit, effective and excluded counts separately. Explain that preview reserves no jobs. Creation feedback uses only returned run counts and links to its exact persisted ID, including zero supported work.

Filter metadata failure retains prior options and offers retry. All-pending acknowledgement remains transient and requires the existing explicit confirmation.

## Run identity and follow-up

Use `#ai?run=<id>` for selected inspection. Fetch the existing single-run and run-items endpoints; list the latest 20 runs separately from the two-slot monitor. Waiting rows remain discoverable in history. Item status filtering uses the existing API; failed items show error and attempt evidence. Never invent job-route scoping or reinterpret exclusions as failures.

Link crawl-triggered runs to the exact Crawl Task and runtime waiting to Settings. Place mutation feedback above the console so it is visible near monitoring and launching; accepted mutation and later refresh failure remain distinct. Retry/resume receipts identify the returned new run.

## Compatibility and rollback

No new backend API or storage schema. Existing `#ai` and persisted ordinary filters remain valid. Frontend-only rollback, no migration. Query changes are read-only and never launch or retry automatically.
