# OfferToday global detail backlog recovery

## Goal

Make the normal OfferToday detail recovery flow mean “recover the global
OfferToday backlog” when no listing batch is selected, while retaining listing
batch scope as an advanced option for targeted repair. Large backlogs must
continue across bounded runs until exhausted, and task status/progress must not
claim full completion after only one capped or manually interrupted cohort.

## Background and confirmed evidence

- Crawl task `01f6c38c-c830-491a-a206-47e48f104d65` submitted
  `source_listing_crawl_job_id=null`, `category_ids=[118000]`, and
  `detail_limit=5000`.
- The task first froze `282` distinct targets, processed `180`, then stopped at
  detail index `181` after OfferToday returned `ip_blocked` / code `-1000035`.
  A resume froze a new `102`-target cohort and completed it, after which the
  task was marked `completed`.
- The task touched `326` staging rows for `282` distinct source jobs. `257`
  rows belonged to listing batch `ce7f0e74-a42c-44d4-9927-36fc99b8ad45` and
  `69` belonged to another batch; this is why task row counts do not equal one
  listing batch's `8,035 staged` rows.
- The batch listing UI reports staging-row status counts. Its `8,035 staged`
  value is a batch inventory, not an automatic detail target count
  (`backend/app/repositories/crawl_job_listing_repository.py:351-473`).
- When an unbound OfferToday detail request carries `[118000]`, the runtime
  expands that category family and filters on
  `source_classification_id IN (...)`
  (`backend/app/sources/offertoday/search_space.py:247-256`,
  `backend/app/repositories/crawl_job_listing_repository.py:247-263`).
  Most pending rows in the affected batch have `source_classification_id=NULL`,
  so they are invisible to this global category query.
- A `NULL` staging classification does not mean the eventual Job lacks a
  category. Pending rows retain `job_functions` in `listing_payload`; detail
  success merges listing and detail payloads, and
  `build_offertoday_canonical_job()` derives the first OfferToday job-function
  code/name for the published Job (`backend/app/services/offertoday_detail_pipeline.py:450-462`,
  `backend/app/sources/contracts.py:183-266`). Live samples include non-IT
  functions such as finance and procurement.
- The previous task intentionally implemented the opposite default: newest
  eligible listing batch by default, with global category backlog as an
  explicit option. This task supersedes that operator-facing default while
  preserving explicit batch-bound recovery semantics.
- Crawl task `88ff0eb8-5c27-4a24-bf61-0a917727a67a` exposed a separate
  recovery failure: the worker reported that the reusable OfferToday browser
  session was unavailable; clicking `Open Browser` then reported that the
  manual-action helper was unavailable.
- These are two different boundaries. OfferToday reuse depends on the live
  browser registry/CDP session, while `Open Browser` depends on the host helper
  listening at the configured helper URL (currently defaulting to
  `http://127.0.0.1:47652`). The frontend currently treats a transport error
  as a generic helper-unavailable message, and runtime capabilities do not
  prove helper reachability before exposing the action.

## Requirements

### R1. Global scope is the normal default

- An empty `source_listing_crawl_job_id` in OfferToday detail mode means global
  OfferToday backlog recovery.
- The frontend must not auto-select the newest listing batch.
- Listing Batch Scope remains available as an advanced, explicit selector for
  operators repairing one historical listing run.
- New detail requests persist an explicit `detail_scope` value of `global` or
  `listing_batch`; resume requests preserve that value and the original batch
  ID when present.
- The UI copy must distinguish “Global OfferToday backlog” from
  “Listing batch scope” and must not imply that a batch is selected when it is
  not.

### R2. Global candidates include the intended backlog

- Global recovery must include eligible pending, failed, and
  manual-action-required OfferToday detail rows that are not blocked by a
  terminal or identity-conflict sibling.
- Rows with `source_classification_id=NULL` must not be silently excluded from
  the default global scope. The confirmed global scope includes every
  eligible OfferToday category and unclassified row.
- Candidate grouping must remain by canonical `source_job_id`, so duplicate
  historical staging rows result in one detail fetch.
- An explicitly selected listing batch must continue to bypass category
  narrowing and include eligible null-classification rows from that batch only.

### R3. Bounded continuation

- `detail_limit=5000` remains the maximum number of distinct detail targets in
  one execution segment.
- If eligible global backlog remains after a successful segment, the system
  must create or schedule a continuation segment automatically until no
  eligible targets remain.
- Continuation must preserve global scope, source, statuses, deduplication,
  and the original recovery intent; it must not silently switch to a newest
  listing batch.
- A segment that stops for manual action, IP/WAF block, or another recoverable
  operator intervention must preserve completed progress and expose a partial
  or manual-action state. It must not claim the backlog is exhausted.
- A segment that leaves retryable `failed` targets must stop rather than loop
  forever; it must expose a failed/partial recovery state with the remaining
  failed count so a later operator-triggered recovery can retry them. This
  stop-on-failure behavior is confirmed for this task.
- The final recovery state may be `completed` only when the eligible target
  query is empty or the operator explicitly ends the recovery.

### R4. Truthful progress and scope ownership

- Progress denominators and completion counters use distinct canonical
  `source_job_id` units, not staging-row counts.
- The UI/API must distinguish segment progress from remaining global backlog.
- Explicit batch-bound recovery, detail identity handling, terminal outcomes,
  and non-OfferToday behavior remain unchanged.
- Historical task/event readability is not a requirement for this change;
  missing scope on an old detail payload may use the new global default rather
  than preserving the old category-filtered interpretation.
- Expanding global selection must not overwrite or erase the Job's real
  OfferToday classification. A staging row may remain unclassified while the
  published Job receives its classification from merged `job_functions` data.

### R5. Manual-action recovery has two explicit layers

- The UI/API must distinguish “no reusable browser session” from “manual-action
  helper unavailable”.
- `Open Browser` must perform or consume a real helper health/reachability
  check and show an actionable retry/manual-start state when the helper is
  down; it must not claim the browser profile itself is unavailable.
- No one-click launcher/supervisor is required. Helper startup remains a
  deliberate manual host operation, with a clear command and health URL shown
  by the UI. This avoids adding a resident process, installation step, or
  host-process control boundary.
- When the helper is unreachable, the UI shows an explicit `Helper offline`
  state, disables `Open Browser`, keeps a health-check retry, and shows a
  copyable manual-start instruction. The action becomes available again after
  health recovery.
- Helper availability must not disable `Resume Fresh`; Fresh Profile is an
  independent worker-side recovery strategy. If it cannot launch, the UI
  reports the separate headed/browser-runtime failure.
- Existing explicit operator control over opening the browser and resuming the
  crawl remains intact; helper startup must not silently resume a blocked crawl.

## Acceptance Criteria

- [ ] Opening OfferToday detail recovery leaves Listing Batch Scope empty by
      default; no newest batch is auto-selected.
- [ ] Submitting with an empty batch selector produces an explicitly unbound
      global OfferToday recovery request with durable `detail_scope=global`.
- [ ] A global recovery query includes pending/manual/failed rows with null
      classification and groups duplicate staging rows by canonical source job.
- [ ] A detail fetch for a null-classification staging row preserves the
      OfferToday `job_functions` classification on the published Job, including
      non-IT categories; it never assigns a synthetic global or IT category.
- [ ] A batch-bound recovery still filters by the selected listing batch and
      includes that batch's null-classification rows.
- [ ] A global backlog larger than `5,000` is processed through continuation
      segments without duplicate detail fetches or scope broadening.
- [ ] A recoverable IP/WAF/manual-action stop preserves progress and cannot
      produce a false final `completed` state.
- [ ] A failed segment stops automatic continuation, preserves progress, and
      exposes the remaining failed backlog for a later operator-triggered run.
- [ ] The final state is `completed` only after no eligible global targets
      remain, and the API/UI expose the remaining count during continuation.
- [ ] Task `88ff0eb8-5c27-4a24-bf61-0a917727a67a` can distinguish reusable
      session absence from helper unavailability; `Open Browser` exposes a
      real helper health/retry/manual-start path.
- [ ] When the helper is offline, the UI disables `Open Browser`, exposes a
      retryable health state and copyable manual-start instruction, then
      re-enables the action after health recovery.
- [ ] `Resume Fresh` remains available while the helper is offline and is only
      blocked by its own browser-runtime capability/error.
- [ ] The UI exposes a clear manual helper-start command and health URL, with a
      Retry action that rechecks the helper without affecting crawl execution.
- [ ] Focused backend and frontend regression tests cover empty/global scope,
      null classifications, explicit batch scope, duplicate rows, cap
      continuation, manual-action interruption, and final exhaustion.
- [ ] Existing OfferToday bound-scope, progress-projection, partial-listing,
      and non-OfferToday regression suites remain green.

## Scope boundaries

- Do not change OfferToday listing pagination, search-family coverage,
  response-cursor policy, or supplemental-row policy.
- Do not launch a large live OfferToday recovery as part of deterministic
  verification.
- Do not rewrite historical crawl events or add a database migration for this
  change; historical readability is explicitly out of scope.
- Preserve unrelated dirty-worktree changes and keep any eventual commit
  narrowly scoped.
