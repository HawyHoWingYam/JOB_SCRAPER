# Adapter Boundary: JobsDB Adapter

## Current Responsibilities

The JobsDB adapter handles JobsDB Hong Kong category IDs, listing/detail scraping, JobsDB parser contracts, canonical job conversion, listing-stage staging payloads, detail repair, and original JobsDB URL reconstruction.

## Current Implementation Map

- Config and crawl mode defaults: `backend/app/config.py`
- JobsDB parser/contracts: `backend/app/sources/jobsdb/parsers.py`, `backend/app/sources/contracts.py`
- JobsDB spiders: `backend/crawler/job_crawler/spiders/jobsdb_spider.py`, `jobsdb_headed_spider.py`
- Browser detail scraper: `backend/app/scraper/jobsdb_browser_detail_scraper.py`
- Detail repair service/script: `backend/app/services/jobsdb_detail_repair_service.py`, `backend/scripts/backfill_jobsdb_details.py`
- Jobs API URL serving: `backend/app/api/jobs.py`

Shared scraper primitives such as `backend/app/scraper/category_scraper.py`, `job_detail_scraper.py`, `backend/app/crawl_modes.py`, and `backend/app/utils/source_identity.py` are not JobsDB-only adapter modules even when JobsDB currently uses them.

## Data and Control Flow

JobsDB category IDs are numeric and default to headed crawl mode. Listing phases fetch JobsDB search pages, parse listing payloads, and stage rows keyed by `source_site=jobsdb` and `source_job_id`. Detail phases read staged listing targets, fetch browser detail pages, parse Redux/detail payloads, build canonical JobsDB jobs, and mark listing detail state.

Canonical conversion writes source-aware identity fields while still preserving compatibility job IDs. Detail repair selects degraded JobsDB rows by `source_site`, fetches detail data again, and applies richer title/company/description/salary/date fields to existing jobs.

## Tests and Coverage

- `backend/tests/test_jobsdb_spider.py`
- `backend/tests/test_jobsdb_headed_spider.py`
- `backend/tests/test_jobsdb_browser_detail_scraper.py`
- `backend/tests/test_jobsdb_detail_repair_service.py`
- `backend/tests/test_jobsdb_parsers.py`

## Known Gaps or Risks

- JobsDB anti-bot and interstitial handling remains weaker than the generic manual-action path. Browser detail fetch currently returns `None` for interstitial HTML instead of raising a resumable manual-action error.
- Listing/detail staging exists, but source identity still depends on adapter discipline across staging rows, canonical conversion, ingest, and repair.
- Parser coverage asserts representative payload shape, but there is no parser completeness metric for required fields across live samples.
- Detail repair is service/script-backed; operators do not yet have an app workflow for candidate selection, retry, or result review.
- Numeric category metadata is static in code and can drift from JobsDB source taxonomy.

## Optimization Backlog

- Add manual-action parity with CTgoodjobs for JobsDB interstitials, including resumable payloads for detail-stage blocks.
- Harden two-phase listing/detail staging around source-aware identity, retry accounting, and duplicate suppression.
- Add parser completeness reporting for title, company, location, description, salary, posted date, and source URL fields.
- Add an operator path for JobsDB detail repair with preview, run history, and per-row repair outcome visibility.
- Version or snapshot JobsDB category metadata separately from runtime code.

## Follow-up Audit Questions

- Should JobsDB detail repair become part of the main scrape progress UI or remain an operator maintenance action?
- Which fields should make a JobsDB row eligible for repair: missing description only, stale details, or any degraded canonical field?
- Should JobsDB interstitials block the whole crawl job or only pause the affected listing/detail target?
