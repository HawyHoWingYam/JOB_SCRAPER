# Verification evidence

Date: 2026-07-15 (Asia/Hong_Kong)

## Offline quality gates

- Backend focused regression suite:
  `python -m pytest -q backend/tests/test_cross_source_ip_recovery.py backend/tests/test_cross_source_crawl_logging.py`
  -> **35 passed**.
- Frontend source-aware guidance:
  `npm test -- src/components/scraper/ipBlockGuidance.test.js`
  -> **4 passed**.
- Ruff across all task-touched Python modules -> **passed**.
- `python -m compileall -q backend/app backend/scripts backend/tests` ->
  **passed**.
- Frontend production build -> **passed**.
- Scoped ESLint for `ipBlockGuidance.js`, its test, and `CrawlTasksPage.jsx`
  -> **passed**.
- `git diff --check` -> **passed**.

Full frontend `npm run lint` remains red on **16 errors and 3 warnings** in
pre-existing unrelated files. The eight reported `ScrapeProgressPanel.jsx`
unused-prop errors reproduce against the HEAD version of that file; this task
does not change that legacy prop surface.

## Container verification

- Rebuilt/restarted only `backend-api` and `frontend-ui` with
  `docker compose up -d --build backend-api frontend-ui`; Postgres and Redis
  data were not reset.
- `backend-api` -> healthy; `GET http://localhost:8000/health` returned
  `{"status":"healthy","service":"backend-api"}`.
- `frontend-ui` -> healthy; `GET http://localhost:3000` returned HTTP 200.
- Backend focused suite inside the rebuilt container -> **35 passed**.
- Frontend helper suite inside the rebuilt container -> **4 passed**.
- Recent backend logs contained no `Traceback`, `ERROR`, or `CRITICAL` entry.

## Live bounded OfferToday IP-block smoke

Created one listing-only task with one explicit keyword (`python`) and
`max_pages=1`:

```text
crawl_job_id = c46031b5-a084-4c27-8b81-b0ea9699238d
status = manual_action_required
issue_class = ip_blocked
issue_code = -1000035
issue_stage = browser_session
pages_processed = 0
job_ids_collected = 0
listings_staged = 0
```

The canonical durable event is `crawl.manual_action_required`. Its normalized
payload contains the full verification URL, exact code, source-aware change-IP
message/instructions, and `resume_supported=true`. The task snapshot projects
`ip_blocked=true`. Backend operational logs show:

```text
SCRAPE_LISTING_MANUAL_ACTION ... classification=ip_blocked code=-1000035 ...
SCRAPE_LISTING_DONE ... outcome=manual_action_required ... pages_processed=0 ...
SCRAPE_EXECUTOR_MANUAL_ACTION ... classification=ip_blocked code=-1000035 ...
```

Log URL query/fragment values were removed while the durable event retained the
full operator evidence. No later listing page or detail request was issued.

## Intentionally pending live evidence

- The live task remains `manual_action_required`; no automatic polling or
  resume was performed.
- A real same-task OfferToday Resume can only be verified after the operator
  changes/clears the public IP/network and explicitly clicks Resume. Offline
  regression coverage proves the same-task listing redispatch and completed
  detail-target exclusion contracts meanwhile.
- CTGoodJobs/JobsDB IP blocks were verified with synthetic responses and in the
  rebuilt backend container. The live public IP was not deliberately banned.
- A visual browser smoke could not run because this session exposed no browser
  binding. API projection, helper tests, scoped lint, and production build are
  green.
