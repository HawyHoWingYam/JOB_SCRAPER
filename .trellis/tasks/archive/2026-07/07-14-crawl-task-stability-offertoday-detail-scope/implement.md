# Implementation plan: Stable crawl tasks and OfferToday detail scope

## 1. Stable ordering

- [x] Add a repository integration test with conflicting `updated_at`,
      `queued_at`, and `created_at` values plus exact timestamp ties.
- [x] Change `list_crawl_task_page()` to
      `queued_at DESC, created_at DESC, id DESC`.
- [x] Verify total counts and offset page slicing remain correct.

## 2. Listing-bound detail launch and selection

- [x] Extend ScheduleManager tests for OfferToday detail mode: newest eligible
      batch defaults, explicit global backlog remains selectable, and explicit
      choices are not overwritten by async refresh.
- [x] Update the listing-batch control/copy and request summary to distinguish
      listing-bound scope from global category backlog.
- [x] Add dispatch/API tests that an OfferToday detail request persists the
      selected `source_listing_crawl_job_id`.
- [x] Extend runtime tests proving a bound batch includes eligible null-category
      keyword/hybrid rows, excludes other batches, groups duplicate IDs once,
      and ignores category narrowing.
- [x] Preserve and test the unbound expanded-category backlog path.
- [x] Extend resume tests proving listing scope survives IP-block recovery.

## 3. Distinct progress data contract

- [x] Add a batched repository/service summary for OfferToday cohort and attempt
      events with distinct source-job outcome precedence.
- [x] Cover success, terminal unavailable, non-recoverable failure, reconciled
      IDs, duplicate attempts, recoverable IP blocks, and multiple resume
      cohorts.
- [x] Wire the summary into paginated Crawl Tasks and active snapshot building
      without per-task queries.
- [x] Add additive distinct progress fields and keep raw-metric fallback for
      legacy tasks without cohort evidence.
- [x] Fix `jobs_saved` projection fallback to consider raw
      `metrics.jobs_saved`.
- [x] Add a regression fixture matching historical task `21436...` and assert
      target `1,311`, success `1,305`, terminal `6`, reconciled `95`, remaining
      `0`; assert the staging-row value `2,464` is not used as distinct progress.

## 4. Crawl Tasks UI

- [x] Add frontend fixtures/tests for running, manual-action, completed, and
      fallback detail tasks.
- [x] Render distinct fetched/target, terminal, reconciled, failed, and remaining
      chips in task rows.
- [x] Render the same semantic counters in Task Details.
- [x] Preserve listing-only partial labels and non-OfferToday summaries.

## 5. Verification

- [x] Run focused backend tests:
      `pytest backend/tests/test_crawl_job_runtime.py backend/tests/test_crawl_jobs_api.py backend/tests/api/test_crawl_task_snapshot.py backend/tests/api/test_crawl_job_monitoring.py`.
- [x] Run relevant OfferToday standalone/dispatch regressions discovered while
      implementing.
- [x] Run Ruff on touched Python files and `git diff --check`.
- [x] Run focused frontend tests:
      `npm test -- ScheduleManager.test.jsx CrawlTasksPage.test.jsx`.
- [x] Run the frontend production build.
- [x] Run the broader backend suite if focused checks pass and no environment
      blocker appears.
- [x] Query `4cee...` and `21436...` through the live API read-only to verify
      stable order and exact projected counters.

## 6. Rollback and operational review

- [x] Review the diff for unrelated dirty-worktree overlap before any commit.
- [x] Keep live OfferToday repair execution separate from deterministic checks.
- [x] Present a read-only listing-bound selection preview for `4cee...`; obtain
      explicit user confirmation before dispatching thousands of detail calls.

## Verification evidence

- Focused backend: `124 passed`.
- Full backend: `1454 passed` (`63` existing deprecation warnings).
- Focused frontend: `76 passed` across ScheduleManager and CrawlTasksPage.
- Full frontend: `267 passed`.
- Task-scoped ESLint: passed for the four touched scraper component/test files.
- Full frontend ESLint: blocked by `16` pre-existing errors in unrelated
  Dashboard, SkillTags, AI, settings, and ScrapeProgressPanel files; this task
  did not modify those files.
- Ruff on touched Python: passed.
- Frontend production build: passed.
- `git diff --check`: passed (line-ending notices only).
- Live read-only API: `21436...` projected `1311` target, `1305` succeeded,
  `6` terminal, `95` reconciled, `0` failed, `0` remaining; `4cee...` retained
  `9707` discovered, `6969` staged, `107/152` capped, and `2615/3040` requests.
- Live read-only selection preview for `4cee...`: `5956` eligible distinct IDs,
  `3845` new and `2111` repair, all with null source classification. No live
  detail crawl was dispatched.
