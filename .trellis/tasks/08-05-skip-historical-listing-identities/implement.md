# Implementation Plan

## 1. Lock the regression at the shared runtime seam

- [x] Extend the existing staging test fakes with current-run trigger lookup and
      historical-ID lookup, including call capture and injected failure.
- [x] Add a parameterized manual-run regression for JobsDB, CTGoodJobs, and OfferToday
      proving a historical identity is skipped and a new identity is staged.
- [x] Parameterize the historical row over all supported detail statuses: `pending`,
      `running`, `completed`, `failed`, `skipped`, `manual_action_required`,
      `identity_conflict`, and `terminal_unavailable`, while preserving OfferToday's
      identity-authority hard-stop contract where applicable.
- [x] Prove Source qualification, exclusion of the current crawl job, and unchanged
      scheduled-run historical behavior.
- [x] Add a historical-lookup failure test that asserts zero staged rows, zero commits,
      and one rollback.
- [x] Run the focused tests and confirm they fail for the missing historical policy.

## 2. Implement manual historical exclusion

- [x] Reuse the existing source-aware distinct historical-ID repository query; do not
      add per-ID queries or a schema migration.
- [x] Load the current crawl run, activate the policy only for `trigger_type=manual`,
      and exclude the current crawl ID from history.
- [x] Add the ordered historical-ID result field and exclude the Published/historical
      union before staging.
- [x] Adjust OfferToday classification so validated historical rows are skipped rather
      than converted into new-run repair targets, without weakening identity-conflict
      or terminal-unavailable handling.
- [x] Preserve raw/collected observation metrics and make staged/detail/existing-skip
      metrics reflect the accepted workload.

## 3. Verify behavior and compatibility

- [x] Run the focused runtime regression in the backend container; the local `uv`
      environment does not include `pytest`.
- [x] Run relevant OfferToday staging/runtime tests discovered by test selection.
- [x] Run raw-metrics, listing-runtime, and the complete formal backend test suite.
- [x] Run backend Ruff, Python compile, and diff checks required by the project quality
      gate.
- [x] Execute a deterministic database read-only overlap query against the two
      diagnosed pairs and retain the 993-of-995 and 1,112-of-1,140 pre-fix evidence;
      do not delete or modify those rows.
- [x] Review the final diff for unrelated changes in the already dirty worktree.

## Risk and Rollback Points

- The highest-risk branch is OfferToday historical identity validation versus repair
  classification. Keep its focused tests green before broader suites.
- If scheduled runs begin skipping historical rows, rollback the trigger-policy change
  before continuing; that is outside this task.
- No reusable cleanup command or schema migration belongs in the runtime
  implementation; the operator-approved one-off transaction is recorded below.

## 4. Apply the separately approved historical cleanup

- [x] Revalidate exact current/overlap counts, pending status, and zero Published Job,
      detail-owner, and Dispatch Plan references under a listing-table lock.
- [x] In one guarded transaction, hard-delete exactly 993 overlapping CTGoodJobs rows
      and 1,112 overlapping JobsDB rows from the later runs only.
- [x] Preserve Crawl Jobs, old-run rows, Published Jobs, events, and historical metrics.
- [x] Verify the later runs retain exactly 2 and 28 unique identities respectively,
      with zero overlap against the named old runs.
