# Cross-source IP-block recovery and crawl-stage observability implementation plan

## Execution rules

- Run this plan only after the user approves the three planning artifacts and
  `task.py start` moves the task to `in_progress`.
- Inline Codex mode implements and checks directly. Load `trellis-before-dev`
  before the first production-code edit and `trellis-check` after edits.
- Preserve all unrelated worktree changes and the intentional deletion in
  commit `10eabf5c`. Do not restore the legacy test suites.
- Use `apply_patch` for source/test/artifact edits.
- Stop and revise the design if a source cannot provide positive IP evidence
  without classifying generic network failures as IP blocks.

## Step 0. Reconfirm checkout and test baseline

- [ ] Record `git status --short`, current branch, and HEAD before editing.
- [ ] Confirm the active task is
      `.trellis/tasks/07-15-crawl-ip-block-stage-observability` and status is
      `in_progress`.
- [ ] Confirm `backend/tests` remains absent because of the intentional
      deletion; create only the new focused files named below.
- [ ] Read the exact production code before modifying it and recheck line drift
      against `prd.md` / `design.md` anchors.

Rollback point: no production changes yet.

## Step 1. Add compact red-state regression scaffolding

Files:

- Modify `.gitignore` only to unignore the three exact new backend test paths;
  do not remove the broad `backend/tests/*` rule or alter other existing dirty
  entries.
- Add `backend/tests/conftest.py` with backend import-path setup only.
- Add `backend/tests/test_cross_source_ip_recovery.py`.
- Add `backend/tests/test_cross_source_crawl_logging.py`.
- Add `frontend/src/components/scraper/ipBlockGuidance.test.js` after defining
  the pure helper contract expected from Step 7.

Test cases to write before implementation:

- [ ] OfferToday `page.evaluate()` rejects while `page.url` becomes
      `verify.html?code=-1000035`; expected result is typed `ip_blocked` manual
      action with the final URL and no transient retry.
- [ ] Other OfferToday verify redirects remain `waf_challenge`; generic failed
      fetch on a normal URL remains transient.
- [ ] CTGoodJobs and JobsDB 403/429 or explicit IP markers become
      source-correct `ip_blocked`; generic Cloudflare/human verification remains
      `waf_challenge`; DNS/timeout/parser errors remain non-IP.
- [ ] All three source payloads normalize to source-aware message/instructions,
      `resume_supported=true`, and preserve phase/scope.
- [ ] Listing and detail stop issuing later fake requests after IP evidence.
- [ ] JobsDB commits each successful fake page before a later IP stop and a
      same-task replay updates/deduplicates rather than adding rows.
- [ ] Detail replay selects manual-action/pending targets and excludes completed
      targets.
- [ ] Logging fakes prove page start/persisted result, every-detail start/result,
      retry/manual/failure immediacy, empty/early/final summary, common
      correlation fields, elapsed/counters, and secret/body exclusion.
- [ ] Frontend helper names the actual source and gives same-task change-IP plus
      Resume guidance.
- [ ] `git check-ignore -v` proves only the intended new backend test files are
      unignored; unrelated legacy test paths remain ignored.

Run and capture the expected red result:

```powershell
python -m pytest -q `
  backend/tests/test_cross_source_ip_recovery.py `
  backend/tests/test_cross_source_crawl_logging.py

Push-Location frontend
npm test -- src/components/scraper/ipBlockGuidance.test.js
Pop-Location
```

Rollback point: remove only the new focused test files if their contract is
proved invalid before production edits, and remove only their exact `.gitignore`
negation entries.

## Step 2. Generalize the manual-action payload

Primary file:

- Modify `backend/app/scraper/manual_action.py`.

Work:

- [ ] Add optional `classification`, `code`, and compact `evidence` fields to
      `ManualActionRequiredError` without changing existing call signatures.
- [ ] Include non-null fields in `to_payload()` and mirror classification/code
      into `resume_context` for compatibility.
- [ ] Add source-display-name-aware session-recovery message/instruction
      builders for `ctgoodjobs`, `jobsdb`, and `offertoday`.
- [ ] Make `normalize_manual_action_payload()` use source-aware defaults while
      preserving any explicit persisted message/instructions/capability flags.
- [ ] Keep environment/profile/identity manual actions non-IP and preserve
      their current resume capability semantics.

Focused gate:

```powershell
python -m pytest -q backend/tests/test_cross_source_ip_recovery.py -k "manual_action or normalize"
```

Rollback point: shared payload changes are isolated here; revert this step if
legacy normalization or non-session actions change unexpectedly.

## Step 3. Fix the OfferToday verification redirect race

Files:

- Modify `backend/app/sources/offertoday/response_policy.py`.
- Modify `backend/app/scraper/offertoday_browser_runtime.py`.
- Modify `backend/scripts/offertoday_standalone_crawl.py` only where structured
  pause/log fields need the normalized payload.

Work:

- [ ] Add `network` to `OfferTodayTransportError.error_kind`.
- [ ] Around `page.evaluate()`, translate only rejected browser-fetch errors
      into `OfferTodayTransportError` carrying the post-error `page.url`.
- [ ] Parse exact verification-URL query code before the generic verify-path
      classifier; `-1000035` maps to `IP_BLOCKED`, other verify URLs map to
      `WAF_CHALLENGE`.
- [ ] Prove normal-page failed fetch remains transient and non-fetch Playwright
      errors still propagate.
- [ ] Ensure preflight/listing/detail manual payloads expose classification,
      code, blocked URL, phase, and source-aware instructions.
- [ ] Add immediate structured IP/manual-action log fields without printing the
      fetch options, headers, cookies, or body.

Focused gate:

```powershell
python -m pytest -q backend/tests/test_cross_source_ip_recovery.py -k offertoday
```

Rollback point: keep the shared contract but revert the OfferToday adapter if
the wrapper catches programming/context errors beyond rejected fetches.

## Step 4. Add CTGoodJobs IP/WAF evidence and pause logging

Files:

- Modify `backend/app/scraper/ctgoodjobs_browser_page_scraper.py`.
- Modify `backend/app/scraper/ctgoodjobs/html_fetcher.py` if the HTTP path uses
  the same positive evidence contract.
- Modify `backend/scripts/ctgoodjobs_standalone_crawl.py`.

Work:

- [ ] Capture `page.goto()` status plus final URL/title without changing the
      injectable page-content fetcher return type.
- [ ] Check explicit IP evidence before generic interstitial evidence.
- [ ] Emit typed `ip_blocked` immediately for confirmed 403/429/IP markers.
- [ ] Preserve generic interstitial retry behavior, then emit typed
      `waf_challenge` on exhaustion.
- [ ] Keep proxy-unavailable, display-unavailable, and profile-in-use actions
      distinct.
- [ ] Listing: persist prior pages, stop before later pages/detail, store a
      listing-phase resume context, and emit structured page/manual/summary
      logs.
- [ ] Detail: mark the current row manual-action, preserve prior completed rows,
      stop later targets, and emit a terminal result plus phase summary.
- [ ] Verify same-task page replay is idempotent through repository upsert and
      the database uniqueness contract.

Focused gate:

```powershell
python -m pytest -q backend/tests/test_cross_source_ip_recovery.py -k ctgoodjobs
```

Rollback point: source detector and executor edits can be reverted independently
without changing the shared payload schema.

## Step 5. Make JobsDB listing recoverable and classify detail blocks

Files:

- Modify `backend/app/scraper/category_scraper.py`.
- Modify `backend/app/scraper/job_detail_scraper.py`.
- Modify `backend/app/scraper/jobsdb_browser_detail_scraper.py`.
- Modify `backend/scripts/jobsdb_standalone_crawl.py`.

Work:

- [ ] Inspect listing HTTP response status/body before `raise_for_status()` and
      produce typed IP/WAF manual action only from positive evidence.
- [ ] Add an optional awaitable per-page sink to `scrape_category()` while
      preserving its aggregate return contract.
- [ ] In the standalone page sink, build payloads, atomically stage the page,
      update cumulative counters/events, and log the persisted page result
      before fetching the next page.
- [ ] Remove phase-end restaging of the full in-memory aggregate.
- [ ] Verify a normal completed crawl yields the same distinct staged IDs and
      metadata, and repeated same-task pages remain one row per source ID.
- [ ] In headless detail, inspect response before flattening HTTP errors;
      propagate typed IP/WAF manual actions and keep ordinary failures as the
      existing non-manual result.
- [ ] In headed detail, retain navigation status/final URL/title and apply the
      same JobsDB evidence rules.
- [ ] Ensure the blocked target is manual-action, completed targets remain
      completed, and later targets are not requested.

Focused gate:

```powershell
python -m pytest -q backend/tests/test_cross_source_ip_recovery.py -k jobsdb
```

Rollback point: per-page staging is the highest-risk behavioral change. If its
final-row equivalence fails, stop and revise rather than falling back to a
non-recoverable phase-end buffer.

## Step 6. Complete the cross-source log matrix

Files:

- Modify the three standalone crawl scripts.
- Modify source fetchers/runners only where retry attempts are otherwise
  invisible.
- Reuse `backend/app/scraper/log_events.py`; do not add another logger helper
  unless a verified escaping/security defect requires it.

Work:

- [ ] Add `SCRAPE_LISTING_PAGE_START` before each remote page/query request.
- [ ] Preserve `SCRAPE_LISTING_BATCH_STAGED` as the persisted page result and
      add elapsed/cumulative fields.
- [ ] Add immediate listing page failure/manual-action logs and a
      `SCRAPE_LISTING_DONE` summary for normal, empty, partial, and early stop.
- [ ] Ensure every detail target across all three sources emits exactly one
      `SCRAPE_DETAIL_ITEM_START` and one terminal OK/FAIL/MANUAL_ACTION record
      with elapsed/outcome/cumulative fields.
- [ ] Add `SCRAPE_DETAIL_TARGETS_EMPTY` where absent and always emit
      `SCRAPE_DETAIL_DONE`.
- [ ] Add structured `SCRAPE_EXECUTOR_MANUAL_ACTION` and
      `SCRAPE_EXECUTOR_FAIL`; preserve `SCRAPE_EXECUTOR_START/DONE`.
- [ ] Keep durable OfferToday detail progress at its bounded checkpoint cadence
      while operational logs remain per target.
- [ ] Audit all new fields for secrets, response bodies, and unbounded ID lists.

Focused gate:

```powershell
python -m pytest -q backend/tests/test_cross_source_crawl_logging.py
```

Rollback point: individual log additions are behavior-neutral and can be
trimmed without rolling back pause/resume correctness.

## Step 7. Make task projection and UI guidance source-aware

Files:

- Modify `backend/app/services/crawl_task_snapshot_service.py` only if a
  normalized payload fallback is needed.
- Add `frontend/src/components/scraper/ipBlockGuidance.js`.
- Modify `frontend/src/components/scraper/CrawlTasksPage.jsx`.
- Modify `frontend/src/components/scraper/ScrapeProgressPanel.jsx`.

Work:

- [ ] Ensure any source's normalized `ip_blocked` manual action projects the
      same issue class/code/stage while preserving source and message.
- [ ] Extract a pure source-aware guidance helper and remove hard-coded
      OfferToday text from both frontend surfaces.
- [ ] Keep existing explicit Resume/Open Browser/Fresh Profile controls and
      status gating; add no automatic polling/resume behavior.
- [ ] Verify CTGoodJobs, JobsDB, OfferToday, and unknown-source fallback text.

Focused gate:

```powershell
Push-Location frontend
npm test -- src/components/scraper/ipBlockGuidance.test.js
npm run build
Pop-Location
```

Rollback point: frontend helper/components can roll back independently; backend
manual-action state remains authoritative.

## Step 8. Focused quality gate

- [ ] Run all new backend tests together.
- [ ] Run the focused frontend test and production build.
- [ ] Run Ruff on every touched Python file.
- [ ] Compile touched Python modules.
- [ ] Run `git diff --check`.
- [ ] Review the diff for unrelated files, accidental legacy-test restoration,
      response-body logging, and duplicate durable events.

Commands:

```powershell
python -m pytest -q `
  backend/tests/test_cross_source_ip_recovery.py `
  backend/tests/test_cross_source_crawl_logging.py

python -m ruff check `
  backend/app/scraper/manual_action.py `
  backend/app/scraper/offertoday_browser_runtime.py `
  backend/app/sources/offertoday/response_policy.py `
  backend/app/scraper/ctgoodjobs_browser_page_scraper.py `
  backend/app/scraper/ctgoodjobs/html_fetcher.py `
  backend/app/scraper/category_scraper.py `
  backend/app/scraper/job_detail_scraper.py `
  backend/app/scraper/jobsdb_browser_detail_scraper.py `
  backend/scripts/ctgoodjobs_standalone_crawl.py `
  backend/scripts/jobsdb_standalone_crawl.py `
  backend/scripts/offertoday_standalone_crawl.py `
  backend/app/services/crawl_task_snapshot_service.py `
  backend/tests/test_cross_source_ip_recovery.py `
  backend/tests/test_cross_source_crawl_logging.py

python -m compileall -q backend/app backend/scripts backend/tests

Push-Location frontend
npm test -- src/components/scraper/ipBlockGuidance.test.js
npm run build
Pop-Location

git diff --check
```

There is intentionally no legacy full-suite command because commit `10eabf5c`
removed those suites by user decision.

## Step 9. Container and bounded runtime verification

- [ ] Rebuild/restart the affected backend/frontend services without resetting
      Postgres or unrelated runtime state.
- [ ] Verify backend and frontend health.
- [ ] Run a bounded normal-path page/detail smoke for each source and inspect
      the approved log cadence.
- [ ] Use synthetic/fake responses for CTGoodJobs/JobsDB IP-block integration;
      do not deliberately get a live IP banned.
- [ ] While the current OfferToday IP evidence remains naturally reproducible,
      run one bounded headless preflight/listing task and prove it reaches
      `manual_action_required`, `classification=ip_blocked`, source-aware UI/API
      guidance, and no later listing/detail requests.
- [ ] After the operator changes IP, use the explicit Resume API/button on the
      same task and prove staged/completed work is retained and only remaining
      work proceeds.
- [ ] Inspect logs for page start/result, per-detail start/result, elapsed,
      counters, manual action, and final summary.

Suggested commands (adjust exact compose service names to current checkout):

```powershell
docker compose up -d --build backend-api frontend-ui
Invoke-RestMethod http://localhost:8000/health
Invoke-WebRequest http://localhost:3000 -UseBasicParsing
docker logs backend-api --since 10m 2>&1 |
  Select-String -Pattern 'SCRAPE_(EXECUTOR|LISTING|DETAIL)'
```

Runtime mutation gate: create/resume only bounded crawl tasks needed for this
verification; never reset existing crawl data or force a live block.

## Step 10. Contract/spec update and finish preparation

- [ ] Use `trellis-check` for the final requirement-by-requirement audit.
- [ ] Update `.trellis/spec/backend/offertoday-production-crawl.md` so the live
      redirect-race handling remains executable project knowledge.
- [ ] Add a concise cross-source IP/manual-action and log-cadence contract to
      the appropriate backend spec (fill `logging-guidelines.md` if this task
      establishes the first real project convention).
- [ ] Re-run the focused quality gate after spec edits.
- [ ] Record verified runtime evidence and any unverified live-resume condition.
- [ ] Review `git status` and stage/commit only task-owned files during Trellis
      Phase 3; leave unrelated dirty files untouched.

## Requirement-to-evidence map

| Requirement | Primary evidence |
|---|---|
| R1 OfferToday redirect classification | OfferToday fake-page regression plus bounded live preflight |
| R2 cross-source logs | `test_cross_source_crawl_logging.py` plus container log inspection |
| R3 safety/signal quality | secret/body exclusion assertions and diff/log review |
| R4 compatibility | JobsDB final-row equivalence/idempotence tests, existing API/build smoke |
| R5 pause and same-task recovery | six source/phase stop tests, explicit resume tests, bounded same-task runtime verification |

## Final review gate before activation

Before `python ./.trellis/scripts/task.py start`, verify:

- [ ] `prd.md`, `design.md`, and `implement.md` agree on explicit Resume,
      positive IP evidence, JobsDB per-page staging, and log cadence.
- [ ] No open product question remains.
- [ ] The user has reviewed and approved these artifacts.
- [ ] Inline mode is active, so no `implement.jsonl` / `check.jsonl` curation is
      required.
