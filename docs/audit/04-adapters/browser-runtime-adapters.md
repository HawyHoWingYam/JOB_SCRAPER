# Adapter Boundary: Browser Runtime Adapters

## Current Responsibilities

Browser runtime adapters isolate headed Playwright behavior, host browser profiles, manual-action payloads, resume context, anti-bot recovery, and host-side headed worker bootstrap.

## Current Implementation Map

- Legacy Playwright client export: `backend/app/scraper/playwright_client.py`, `backend/app/scraper/__init__.py`
- Source browser scrapers: `backend/app/scraper/jobsdb_browser_detail_scraper.py`, `backend/app/scraper/ctgoodjobs_browser_page_scraper.py`
- Manual-action contract: `backend/app/scraper/manual_action.py`
- Headed worker: `backend/app/workers/run_headed_crawl_worker.py`, `backend/scripts/run_headed_crawl_worker.py`
- Host setup and launch scripts: `backend/scripts/prepare_headed_crawl_worker_host.py`, `run_headed_crawl_worker_host.cmd`, `run_headed_crawl_worker_host.ps1`
- Config: `jobsdb_headed_*` fields in `backend/app/config.py`
- Progress and resume APIs: `backend/app/api/progress.py`, `backend/app/api/crawl_jobs.py`, `backend/app/services/crawl_job_dispatch_service.py`

## Data and Control Flow

Headed crawl jobs are routed to a headed worker stream and consumed by a host-side worker that validates browser channel, profile directory, and lock-port constraints. Browser scrapers use persistent Playwright contexts backed by a local user data directory. Manual-action errors serialize blocked URL, instructions, browser channel, browser profile path, resume support, and resume context to crawl progress and resume APIs.

The manual-action payload is generic, but automatic raising is currently strongest for CTgoodjobs human-verification pages. JobsDB detail interstitials are detected in the JobsDB browser detail scraper and return `None`, which marks a detail failure path rather than the same resumable manual-action path.

`playwright_client.py` is still exported but appears legacy/unused by current headed JobsDB and CTgoodjobs scraper paths.

## Tests and Coverage

- `backend/tests/test_host_headed_runtime_bootstrap.py`
- `backend/tests/test_headed_worker_runtime.py`
- `backend/tests/test_ctgoodjobs_browser_page_scraper.py`
- `backend/tests/test_ctgoodjobs_headed_spider.py`
- `backend/tests/test_jobsdb_browser_detail_scraper.py`
- `backend/tests/test_jobsdb_headed_spider.py`
- `backend/tests/test_crawl_worker.py`
- `backend/tests/test_crawl_jobs_api.py`
- `backend/tests/test_progress_api.py`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- `jobsdb_headed_*` settings are shared by CTgoodjobs and JobsDB browser runtime code, so the naming is source-specific while the runtime is source-neutral.
- `playwright_client.py` remains exported even though current source browser scrapers do not use it.
- Host browser runtime is not fully containerized and depends on a local Windows profile, host Python environment, browser channel, and single-worker lock port.
- Manual-action resume lacks a verified challenge completion signal and relies on operator retry.
- JobsDB interstitial handling does not yet raise the same resumable manual-action error shape as CTgoodjobs verification handling.

## Optimization Backlog

- Deprecate or remove the legacy `PlaywrightScraperClient` export after confirming no external import path depends on it.
- Introduce source-neutral headed browser settings with backward-compatible aliases for existing `jobsdb_headed_*` environment variables.
- Persist and expose headed runtime status for browser channel, profile path, lock state, last heartbeat, and last browser error.
- Add verified manual-action completion and retry accounting for resumed listing/detail work.
- Document `.cmd` and `.ps1` host-worker bootstrap paths as explicit local runtime dependencies.

## Follow-up Audit Questions

- Should headed browser profile/channel become operator-configurable in UI, or stay environment-only?
- Should manual-action resume be blocked until a verification probe confirms the page is usable?
- Which headed runtime failures should pause a crawl versus fail the crawl immediately?
