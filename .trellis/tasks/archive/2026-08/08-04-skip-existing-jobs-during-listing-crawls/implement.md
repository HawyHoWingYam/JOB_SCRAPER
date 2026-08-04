# Implementation plan: skip existing jobs during listing crawls

## 1. Load conventions and establish tests

- Read the backend spec index, database/error/metrics guidelines, and the amended
  OfferToday production contract before editing.
- Add focused failing tests for shared runtime staging and detail-target gating:
  existing/new mixtures, source isolation, fail-closed lookup, and all three sources.
- Change OfferToday tests so incomplete published Jobs are skipped while terminal and
  identity-conflict behavior remains unchanged.

## 2. Enforce the shared runtime invariant

- Make `stage_listing_batch` bulk-load published Jobs for every source with lookup
  errors propagated.
- Skip every published identity before listing upsert; retain current-crawl duplicate
  handling and OfferToday safety precedence.
- Make `load_detail_targets` perform the same unconditional fail-closed defensive
  lookup so legacy staged rows cannot trigger duplicate detail fetches.
- Keep metrics aligned with discovered IDs versus filtered work.

## 3. Make all authored execution paths truthful

- Author `skip_existing=true` in dispatch-plan request payloads.
- Update JobsDB, CTGoodJobs, and OfferToday standalone/frozen runtime plans so direct,
  one-off, scheduled, resumed, and historical-false payload paths cannot disable the
  runtime invariant.
- Preserve parse compatibility where useful without retaining a force-refresh mode.
- Update dispatch/standalone tests for all three sources.

## 4. Implement guarded historical cleanup

- Add a dry-run-default remediation command restricted to the two approved task/source
  pairs and all listing statuses.
- Validate terminal task/source identity, calculate matching/retained IDs, and print a
  deterministic preview.
- Validate and preview the exact two approved JobsDB detail plans, their complete
  membership, the consumed plan's cancelled crawl-job link, and absence of Schedule
  Execution or third-plan references.
- Add explicit apply mode that detaches the preserved cancelled crawl job, deletes the
  two plans and all membership, deletes matching listing rows, and replaces metrics in
  the same transaction, with post-change assertions before commit.
- Unit/integration test dry-run, exact scoping, all-status deletion, missing-row
  preservation, no Job/event mutation, exact metrics replacement, rollback on
  mismatch, and idempotency.

## 5. Update the executable contract

- Amend `.trellis/spec/backend/offertoday-production-crawl.md` to replace
  incomplete-existing repair staging with universal published-existing skipping.
- Record universal fail-closed, source-aware listing filtering and the dedicated-repair
  boundary without weakening terminal/identity protections.

## 6. Validate before data mutation

- Run focused runtime, dispatch, standalone, cleanup, and OfferToday suites.
- Run Ruff/format checks on touched Python, compile checks, relevant backend regression
  tests, and `git diff --check`.
- Run the cleanup command in dry-run mode and compare its task/source/matched/retained
  results with independent read-only SQL.

## 7. Apply and verify cleanup

- Only after all code/tests and dry-run checks pass, run explicit apply once.
- Verify both crawl jobs retain only IDs absent from `jobs`, no Job/event/execution row
  changed, metrics equal surviving-row snapshots, and `pages_processed` is absent.
- Do not dispatch detail work; hand the retained backlog IDs back to the operator for a
  later manual detail task.

## Rollback points

- Before cleanup apply: code can be reverted normally; the database is unchanged.
- During cleanup apply: any assertion rolls back the entire transaction.
- After commit: deleted listing payloads are intentionally not recoverable from this
  task, so the approved dry-run output is the final safety gate.

## Completion evidence

- Focused runtime/dispatch/listing/cleanup suite: `74 passed, 3 skipped`;
  projection/API regression suite: `39 passed`.
- Cleanup dry-run fence: CTGoodJobs `2,095` matched / `995` retained; JobsDB
  `2,670` matched / `1,133` retained.
- Apply committed one transaction: `4,765` listing rows, two approved Dispatch
  Plans, and `7,606` target-row memberships physically deleted.
- Post-apply dry-run matched `0` rows for both tasks. Independent SQL confirmed
  `0` remaining published-identity matches, `2,128` retained listing rows, `7,912`
  Jobs, `327` scoped events, `2` scoped executions, and `0` approved plans.
- Cancelled crawl job `bd343e54-a79d-4547-9fd5-57a7f49f5510` remains present with
  its deleted Dispatch Plan ID/fingerprint cleared.
- A post-cleanup projection regression was found and fixed: the preserved cancelled
  job now carries an explicit `removed_dispatch_plan` tombstone. Both
  `/api/task-control-board?source_site=jobsdb` and `/api/crawl-jobs/tasks` return 200;
  ordinary missing authority remains fail-closed.
