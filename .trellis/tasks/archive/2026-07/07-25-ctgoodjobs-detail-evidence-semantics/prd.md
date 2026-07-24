# Fix CTGoodJobs detail evidence and task recovery semantics

## Goal

Prevent CTGoodJobs detail runs from deterministically dropping source-attribute
evidence, and make crawl-task status/actions respect the boundary between an
independent listing run and an independent detail run.

## User value

CTGoodJobs detail jobs can be saved successfully, completed listing tasks stay
completed regardless of downstream detail activity, and Task Details no longer
offers a recovery workflow the operator does not use.

## Confirmed facts

- Task `9ea826f8-6824-4518-b464-1a865f576b65` is an independent CTGoodJobs
  detail run. Every observed item failed with
  `missing_source_attribute_evidence`; the run had zero successful/saved items.
- `backend/app/sources/ctgoodjobs/parsers.py:624-659` creates valid
  `source_attribute_evidence`.
- `backend/app/scraper/ctgoodjobs/merge.py:91-120` reconstructs the merged
  payload from an allowlist but omits that evidence.
- `backend/app/sources/contracts.py:360-381` transports only the evidence found
  in the merged payload, and `backend/app/workers/run_ingest_worker.py:269-274`
  rejects a missing payload.
- The listing task `1d018b6b-80f3-4dcc-95b2-1172bbcb3e67` has no frozen detail
  snapshot. Its staged rows were being consumed by the independent detail task.
- `backend/app/services/crawl_task_snapshot_service.py:606-617` currently lets
  downstream row state project a completed listing task as
  `completed_with_downstream_backlog`.
- `frontend/src/components/scraper/CrawlTaskDetails.jsx:68-78` exposes a
  “Start detail recovery run” action from that operator state, while
  `frontend/src/components/scraper/CrawlTasksPage.jsx:414-425` later refuses to
  create a draft unless the source run is a detail run with a remaining frozen
  snapshot.
- Manual browser verification does not require a new recovery run. A task in
  `manual_action_required` resumes the same task through `fresh_profile` or
  `reuse_open_browser` and preserves its checkpoint.

## Requirements

- R1. CTGoodJobs merge must preserve `source_attribute_evidence`, preferring
  detail evidence and falling back to listing evidence only when detail evidence
  is absent.
- R2. The production parse → merge → canonical path must deliver the exact
  evidence payload to ingest; missing or malformed evidence must remain a hard
  ingest error.
- R3. A listing run's operator state must be derived from its listing workload,
  not from mutable detail statuses on rows later consumed by an independent run.
  A successfully completed listing run remains `completed`.
- R4. Detail-run backlog semantics remain frozen-snapshot based. This change
  must not weaken the existing distinction between `remaining_count` and
  `future_eligible_count`.
- R5. Remove “Start detail recovery run” from Task Details and remove the
  corresponding frontend draft/action path if it has no remaining caller.
- R6. Preserve the normalized manual-action recovery panel and same-task Resume
  strategies used for human browser verification.
- R7. Preserve frozen-snapshot storage, backend reclaim behavior, and task
  history even though the operator-facing recovery-run entry point is removed.
- R8. Do not cancel, repair, migrate, or resume historical crawl tasks. The
  operator will start a new crawl after deployment.

## Acceptance criteria

- [x] A CTGoodJobs detail fixture passing through parse/merge/canonical retains
  valid `source_attribute_evidence` and can reach the ingest projection seam.
- [x] Merge tests prove detail evidence wins and listing evidence is a fallback.
- [x] A completed listing task with staged rows owned by an active downstream
  detail task is projected as `completed`, not as a backlog/recovery state.
- [x] A terminal detail task with a frozen snapshot still reports authoritative
  remaining/future counts according to the existing backend contract.
- [x] Task Details contains no “Start detail recovery run” action for listing or
  detail tasks, and no inert callback remains wired from the page.
- [x] `manual_action_required` tasks still expose Fresh Profile and capability-
  gated Reuse Open Browser controls.
- [x] Targeted backend and frontend regression suites, lint/type checks, and
  builds pass.

## Out of scope

- Cancelling or recovering task `9ea826f8-6824-4518-b464-1a865f576b65` or any
  other historical task.
- Adding listing→detail task links or a three-state downstream-task UI.
- Adding “Start new detail run from this listing batch.”
- Removing frozen snapshots or backend recovery/reclaim primitives.
- Changing JobsDB/OfferToday evidence adapters or manual verification flows.
