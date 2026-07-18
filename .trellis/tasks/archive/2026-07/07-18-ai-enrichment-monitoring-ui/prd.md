# AI Enrichment monitoring-first UI redesign

## Goal

Redesign the AI Enrichment operations console so an operator can determine within five seconds what is running, how much work remains, what has failed, and whether intervention is required, then safely launch a filtered batch when no run is active.

## Background

- The current page presents three large summary cards, a queue-control panel, a duplicated three-metric backlog ribbon, and a fixed two-card run monitor.
- Queue actions and explanatory copy currently occupy more first-screen space than run monitoring.
- The current pending action selects a global oldest-first backlog by numeric limit only.
- The current page exposes manual execution by Target Job UUID, although this is not part of the operator's workflow.
- Persisted enrichment runs already expose status, progress, success/failure counts, current work, elapsed time, remaining items, and blocking reasons. They do not expose trustworthy throughput, ETA, last-progress time, or stall detection.

## Requirements

### R1. Monitoring-first information hierarchy

- The first viewport must prioritize current run state over launch controls without using a full-width hero card.
- A compact top status strip must contain exactly: pending backlog versus AI-eligible total, active run count, and failed-job count.
- The existing large summary cards, lower backlog/failure/active ribbon, and Queue Overview last-completed UUID tile must be removed.
- The primary workspace must use approximately equal-width columns with Run Monitor on the left and Filtered Run controls on the right.
- On narrow screens, Run Monitor must stack above Filtered Run controls.
- Operator copy must be concise. Architecture explanations and repeated instructional paragraphs must be removed; consequence-focused guidance remains for high-risk actions.
- The UI must not claim inferred health, stall detection, throughput, or ETA without a supporting backend signal.

### R2. Two-slot run monitor

- The monitor must always render exactly two task slots.
- When one active run exists, the slots contain that active run and the most recent terminal run.
- When no active run exists, the slots contain the two most recent terminal runs.
- If fewer than two qualifying runs exist, the missing slot remains visible as an accessible empty state.
- Terminal statuses are completed, completed with failures, failed, and cancelled.
- Each populated card must prioritize status and progress while keeping its run UUID visible with a copy affordance for debugging.
- A failed or completed-with-failures card must expose retry for that specific run. Successful and cancelled cards expose no retry action.
- Retry controls must not appear in the Filtered Run panel.

### R3. Filtered pending enrichment

- Operators must be able to launch AI enrichment for a server-selected subset of pending jobs.
- Eligible candidates are non-deleted, AI-eligible jobs with no completed AI enrichment.
- The MVP filters are multi-select source site, searchable multi-select source classification, searchable multi-select source subclassification, inclusive posted-date range, and maximum Pending Limit.
- Values within one filter field use OR semantics; populated fields combine with AND semantics.
- Classification options must respond to selected sources, and subclassification options must respond to selected sources and classifications.
- The server must return a preview count for the current filters. The effective launch count is `min(matching count, Pending Limit)`.
- Submission must re-evaluate filters on the server; preview is informative and does not lock a stale set of IDs.
- When candidates exceed Pending Limit, selection must use deterministic oldest-backlog ordering: `created_at ASC, id ASC`.
- At least one ordinary filter is required unless the operator explicitly enables all-pending mode.
- All-pending mode must be visually distinct, require consequence-focused confirmation, and never persist.
- The launch button must include the effective bounded count, for example `Run 500 filtered jobs`.
- Ordinary filter selections, posted-date range, and Pending Limit must persist after submission and page reload until Reset is used.

### R4. Global single-active-run invariant

- At most one job-enrichment run may own the active execution slot across automatic post-scrape, filtered manual, and retry sources.
- Active lifecycle states are pending, running, and stopping. Waiting automatic work may be persisted separately but must not execute concurrently or consume a third monitor slot.
- Filtered create and retry requests must be rejected while the active slot is occupied.
- The invariant must hold across concurrent API requests and worker processes, not only through frontend button disabling.
- Automatic post-scrape work that arrives while the slot is occupied must be retained for later execution rather than dropped or run concurrently.

### R5. Cooperative Stop

- Every active job-enrichment run, including automatic post-scrape runs, must expose Stop.
- Stop must prevent new items from starting after workers observe the request, allow already in-flight AI calls to settle and persist, and mark not-yet-started items cancelled.
- A pending run with no in-flight items may transition directly to cancelled.
- A running run must show a non-repeatable `Stopping...` state after Stop is requested and until terminal cancellation; a pending run with no in-flight work transitions directly to cancelled.
- Stop requires confirmation that in-flight items may still finish.
- Cancelled-run summaries must distinguish completed, failed, and cancelled counts; cancelled items are not failures.
- Stopping an automatic enrichment run must not cancel its source crawl.

### R6. Remove manual single-ID execution

- The Target Job UUID input and Run Job action must be removed from the AI Enrichment page.
- Public AI APIs and service entry points that manually start enrichment for one explicit Job UUID must be removed.
- The removal must not affect automatic post-scrape batches, filtered pending runs, failed-item retries, or the manual-job creation workflow.

## Acceptance Criteria

- [ ] AC1: The first viewport shows one compact three-metric strip, Run Monitor on the left, and Filtered Run on the right; mobile stacks monitoring first.
- [ ] AC2: Pending/active/failed metrics appear once and the old summary cards, queue ribbon, and last-completed tile are absent.
- [ ] AC3: With one active run, the monitor returns and renders that run plus the latest terminal run regardless of creation adjacency.
- [ ] AC4: With no active run, the monitor returns and renders the two latest terminal runs; it never grows beyond two slots, and missing runs render accessible empty slots.
- [ ] AC5: Every populated card visibly identifies and can copy its run UUID.
- [ ] AC6: Retry appears on each visible retryable terminal card and targets that card's run ID; successful/cancelled cards and Filtered Run controls have no retry action.
- [ ] AC7: Source, classification, subclassification, posted-date range, and limit can be combined, cleared, previewed, and submitted with field-level OR/cross-field AND semantics.
- [ ] AC8: Filter options cascade from source to classification to subclassification and remain searchable where large.
- [ ] AC9: Preview displays matching and effective counts; create re-evaluates the same normalized contract and selects only non-deleted, AI-eligible jobs whose `ai_enriched_at` is null and that are not reserved by nonterminal runs.
- [ ] AC10: Empty ordinary filters cannot launch unless all-pending mode is explicitly acknowledged and confirmed.
- [ ] AC10a: The launch button shows `min(matching count, Pending Limit)`, uses the matching count when below the limit, and is disabled for zero matches.
- [ ] AC11: Repeated limited runs drain matching candidates in deterministic `created_at ASC, id ASC` order.
- [ ] AC12: Ordinary filters and limit survive reload and Reset clears them; all-pending acknowledgement never survives submission or reload.
- [ ] AC13: Concurrent create, retry, and automatic-trigger attempts cannot produce two active job-enrichment runs.
- [ ] AC14: Automatic work arriving during an active run is retained and is eventually promoted after the slot becomes free, including after a worker restart, without appearing as a third monitor card.
- [ ] AC15: Active filtered/retry submission is disabled in the UI and both APIs return HTTP 409 with stable code `active_run_exists`.
- [ ] AC16: Stop prevents additional pending items from starting, allows in-flight items to finish, and ends with accurate completed/failed/cancelled counts.
- [ ] AC17: `Stopping...` and action confirmations communicate cooperative rather than instantaneous cancellation.
- [ ] AC18: Stopping automatic enrichment does not cancel or mutate the source crawl lifecycle.
- [ ] AC19: The Target Job UUID UI, public single-job AI endpoint, and public single-ID run mode are absent.
- [ ] AC20: Existing post-scrape enrichment, retry, manual-job creation, polling, degraded-refresh behavior, and terminal-run rendering continue to work.

## Out of Scope

- Throughput, ETA, last-progress timestamps, or inferred stalled/healthy classifications.
- Redesigning Job Browser filters or company enrichment.
- More than two visible run-monitor cards or a general run-history browser.
- Cancelling a source crawl when its AI enrichment run is stopped.
- Implementation before the user reviews and approves these planning artifacts.
