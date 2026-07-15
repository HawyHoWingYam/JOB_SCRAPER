# Implementation plan

## 1. CTGoodJobs classification and circuit breaker

- [x] Add focused tests for positive verification, HTTP/explicit terminal-unavailable evidence, missing-field non-classification, two consecutive identical anomalies, reset-on-success, and no-later-target behavior.
- [x] Add the conservative CTGoodJobs detail page-state classifier at the source/browser boundary without persisting response bodies.
- [x] Add `content_anomaly` to the resumable manual-action contract with non-IP operator message and instructions.
- [x] Add a runtime `terminal_unavailable` convenience transition over the existing generic outcome path.
- [x] Add the executor-local structural anomaly guard for `missing_job_content` and `missing_company_identity`.
- [x] Ensure the second anomaly uses the standard manual-action transition/event/final-summary path and stops the loop immediately.
- [x] Ensure resume context includes `failed`, `manual_action_required`, and `pending`; add a regression proving completed and terminal rows stay excluded.
- [x] Keep logs bounded and add assertions for classification/reason/cumulative counts and exactly one terminal result per attempted target.

## 2. Snapshot metrics normalization

- [x] Add backend snapshot tests for CTGoodJobs, JobsDB, and OfferToday covering live, completed, zero, failed, unavailable, manual-action, and remaining counts.
- [x] Add normalized numeric common fields in `crawl_task_snapshot_service.py`, preferring OfferToday distinct-cohort fields and generic detail-run fields for CTGoodJobs/JobsDB.
- [x] Preserve existing raw/source-specific fields and OfferToday segment/backlog projection.
- [x] Prove denominator conservation and that manual action remains included in remaining work while not inflating failed.
- [x] Prove historic records with missing run fields return safe numeric fallbacks.

## 3. Crawl Tasks rendering

- [x] Update `CrawlTasksPage` tests first for fixed common ordering, zero-value rendering, separate unavailable/manual-action chips, and OfferToday-only supplements.
- [x] Change `buildDetailMetricSummary` to render normalized common fields without duplicating backend fallback logic.
- [x] Retain listing-task metrics behavior and existing OfferToday scope labels.

## 4. Focused verification

- [x] Run backend recovery/classification tests:
  `pytest backend/tests/test_cross_source_ip_recovery.py -q`
- [x] Run backend executor/logging tests:
  `pytest backend/tests/test_cross_source_crawl_logging.py -q`
- [x] Run backend snapshot tests:
  `pytest backend/tests/test_crawl_task_snapshot_service.py -q`
- [x] Run any new CTGoodJobs parser/page-state test module directly.
- [x] Run Ruff on every touched Python file and compile touched backend modules with `python -m compileall`.
- [x] From `frontend/`, run `npm test -- CrawlTasksPage.test.jsx`.
- [x] From `frontend/`, run `npm run build`.
- [x] Run `git diff --check` and inspect the scoped diff without touching unrelated worktree changes.

## 5. Runtime verification

- [x] Rebuild/restart only the affected local backend/frontend services.
- [x] Query `/api/v1/crawl-jobs/tasks` and verify existing CTGoodJobs, JobsDB, and OfferToday detail records expose all normalized numeric fields.
- [x] Verify Crawl Tasks displays five common core metrics including zeros and retains OfferToday segment/backlog supplements.
- [x] Inspect bounded container logs for a synthetic/manual-action regression; do not deliberately trigger a live block.
- [x] If a natural CTGoodJobs verification occurs, confirm the same task pauses and no later target starts; otherwise report live challenge verification as not forced and rely on the deterministic fixture gate.

## 6. Review and rollback gates

- [x] Before runtime restart, review that no response body, cookie, token, or storage state is logged or persisted.
- [x] If classification tests reveal ambiguous expired markers, remove those markers and keep only HTTP/structured evidence rather than widening guesses.
- [x] If normalized metric conservation fails for historic tasks, keep old fields intact and adjust only the additive snapshot fallback.
- [x] No database migration is expected; rollback is a scoped code revert of classifier/guard, snapshot aliases, and frontend rendering.

## Verification results

- Backend full suite: `64 passed`.
- Focused CTGoodJobs recovery, logging, page-state, and cross-source snapshot
  suite: `54 passed`.
- Frontend full suite: passed; focused Crawl Tasks suite: `8 passed`.
- Frontend production build, touched-file ESLint/Prettier, Ruff, Python
  compilation, and `git diff --check`: passed.
- Rebuilt and recreated `backend-api` and `frontend-ui`; both are healthy.
- The interrupted CTGoodJobs task
  `5f6aa0bf-ec22-4f49-94c6-179667ec9316` was finalized as `failed` rather than
  left stale in `running`.
- Live `/api/v1/crawl-jobs/tasks` snapshots returned numeric common fields for
  CTGoodJobs, JobsDB, and OfferToday. OfferToday records retained segment and
  backlog projections, including task `88ff0eb8-5c27-4a24-bf61-0a917727a67a`.
- No live verification challenge was deliberately triggered; deterministic
  synthetic fixtures are the challenge release gate.
