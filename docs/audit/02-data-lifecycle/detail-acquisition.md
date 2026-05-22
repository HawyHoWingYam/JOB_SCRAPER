# Data Lifecycle: Detail Acquisition

## Current Responsibilities

Detail acquisition fetches full job descriptions and rich job fields after listing discovery. It supports source-specific parsers, headed browser sessions, and manual action workflows.

## Current Implementation Map

- Workers: `backend/app/workers/run_crawl_worker.py`, `run_headed_crawl_worker.py`
- Source detail code: `backend/app/scraper/jobsdb_browser_detail_scraper.py`, `backend/app/scraper/ctgoodjobs/*`
- Spiders: `backend/crawler/job_crawler/spiders/jobsdb_headed_spider.py`, `ctgoodjobs_headed_spider.py`
- Manual action: `backend/app/scraper/manual_action.py`

## Data and Control Flow

Detail crawl jobs consume command stream messages, fetch details, update listing row detail status, and emit progress plus ingest events. Manual action exceptions surface blocked URL, browser profile path, and resume context through durable crawl job events.

## Tests and Coverage

- `backend/tests/test_jobsdb_headed_spider.py`
- `backend/tests/test_ctgoodjobs_spider.py`
- `backend/tests/test_ctgoodjobs_headed_spider.py`
- `backend/tests/test_progress_api.py`
- `frontend/src/components/scraper/ScrapeProgressPanel.test.jsx`

## Known Gaps or Risks

- Detail acquisition has the highest dependency on external anti-bot behavior.
- Resume context must preserve enough source listing batch state to avoid widening scope unexpectedly.
- Hosted headless and local headed execution have different operational assumptions.
- Host-side headed crawling is the expected full-detail path for protected pages, while container headless streams remain operationally different.
- Manual action events can remain actionable indefinitely without expiry/escalation rules.

## Optimization Backlog

- Define a detail-status state machine with allowed transitions for pending, in progress, completed, failed, skipped, manual action, cancelled, and stale.
- Publish a per-source/per-mode capability matrix so operators know when headed browser detail acquisition is required.
- Add expiry, escalation, and retry accounting to manual-action detail runs.
- Preserve source listing batch scope explicitly on resume so blocked detail runs cannot accidentally broaden to category-wide work.

## Follow-up Audit Questions

- Should detail fetch capability be represented per source and per runtime mode?
- Should blocked manual action events expire or remain actionable forever?
- Should detail status transitions be enforced in one repository method only?
