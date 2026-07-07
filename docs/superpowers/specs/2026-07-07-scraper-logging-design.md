# Scraper Logging Design

Date: 2026-07-07
Status: Proposed

## Goal

Reduce low-signal Docker log spam and add useful, searchable crawl diagnostics without making the whole backend run at `DEBUG`.

## Problem Summary

Two log streams are currently drowning out useful crawl output:

1. `backend-api` health checks call `refresh_llm_status()` on every `/health` request, which clears the cached client and reinitializes the jobs and companies LLM clients. Docker health checks run every 10 seconds, so the same provider initialization messages repeat forever.
2. `scrapyd` still emits Twisted access logs for `GET /daemonstatus.json`, so the container health check produces a repeating access line even though the request is expected and low value.

At the same time, the scraper paths do not emit enough targeted diagnostics when they:

- discover listing job IDs
- start detail fetches
- finish detail fetches
- fail or require manual action
- persist detail results into the ingest pipeline

## Goals

- Keep default backend logging at the existing `LOG_LEVEL`.
- Add a separate `SCRAPER_LOG_LEVEL` for crawl and ingest diagnostics.
- Suppress noisy health-check-driven logs without hiding genuine failures.
- Make single-job traces easy to search in Docker Desktop using stable message prefixes and `key=value` fields.

## Non-Goals

- Rework the entire logging stack into JSON logging.
- Change Docker Desktop behavior or depend on Docker Desktop-specific features.
- Add new crawl behavior unrelated to observability.

## Recommended Approach

### 1. Add a dedicated scraper log level

Introduce a new runtime setting and env var:

- `SCRAPER_LOG_LEVEL`
- default: inherits `LOG_LEVEL` when unset

`configure_logging()` will accept both the global level and scraper level. It will continue to configure the root logger as today, then explicitly set the scraper-facing logger families to the scraper level:

- `app.scraper`
- `app.sources`
- `app.workers.run_ingest_worker`
- optionally `app.api.crawl_jobs` and `app.services.crawl_job_dispatch_service` for crawl lifecycle summaries

This keeps the rest of the app quiet while allowing deep crawl tracing on demand.

### 2. Use stable, searchable scraper event messages

Scraper diagnostics will use stable event prefixes in the log message body instead of relying on `extra`, because the current plain-text formatter does not render `extra` fields.

Examples:

- `SCRAPE_LISTING_START source=jobsdb crawl_job_id=... category_id=...`
- `SCRAPE_LISTING_PAGE source=jobsdb crawl_job_id=... category_id=... page=3 jobs=32`
- `SCRAPE_DETAIL_START source=jobsdb crawl_job_id=... listing_id=... source_job_id=...`
- `SCRAPE_DETAIL_OK source=jobsdb crawl_job_id=... listing_id=... source_job_id=...`
- `SCRAPE_DETAIL_FAIL source=ctgoodjobs crawl_job_id=... listing_id=... source_job_id=... error=...`
- `SCRAPE_INGEST_RESULT source=jobsdb crawl_job_id=... listing_id=... source_job_id=... action=created job_id=...`

Level policy:

- `INFO`: crawl lifecycle and batch/page summaries
- `DEBUG`: per-job ID discovery and per-detail start/success traces
- `WARNING`/`ERROR`: fetch failures, manual action, unexpected parser/persistence issues

### 3. Stop backend health checks from reinitializing the LLM client

`/health` should become a read-only status endpoint. It should use cached status accessors instead of `refresh_llm_status()`.

Design choice:

- `health.py` will switch from `refresh_llm_status()` to `get_llm_status()`
- explicit refresh behavior remains available through settings/admin flows that already call the refresh path intentionally

This removes the `Initialized LLM provider ...` spam while preserving visibility into degraded state.

### 4. Silence scrapyd health-check access logs at the web server layer

The current `run_scrapyd_quiet.py` only lowers Twisted logger levels, but the repeating `GET /daemonstatus.json` line is emitted through the Twisted access logging path on the HTTP site.

The quiet runner should wrap or subclass the `twisted.web.server.Site` used by Scrapyd and override `log()` to no-op. This keeps startup and exception logging intact while suppressing low-value HTTP access lines from health checks.

This behavior should stay scoped to the scrapyd container helper instead of affecting backend logging.

## Component Changes

### Backend configuration

- `backend/app/config.py`
  - add `scraper_log_level: str | None`

- `backend/app/logging_config.py`
  - extend `configure_logging()` to accept/configure the scraper-specific level
  - keep current noisy third-party suppression

### Backend health path

- `backend/app/api/health.py`
  - switch to cached LLM status reads

### Scraper instrumentation

- `backend/app/scraper/category_scraper.py`
  - log listing crawl start
  - log page-level counts
  - log discovered job IDs at `DEBUG`

- `backend/app/scraper/job_detail_scraper.py`
  - log per-job detail start/success/failure
  - log batch summary for `fetch_multiple_jobs()`

- `backend/app/scraper/jobsdb_browser_detail_scraper.py`
  - log per-job browser detail start/success
  - log manual-action-required transitions with job ID context

- `backend/app/scraper/ctgoodjobs/html_fetcher.py`
  - keep retry warnings
  - add request-stage start/success traces at scraper level

- `backend/app/scraper/ctgoodjobs/list_scraper.py`
  - log page/category summary and discovered IDs

- `backend/app/scraper/ctgoodjobs/detail_scraper.py`
  - log detail start/success around HTML fetch and parse

### Pipeline persistence visibility

- `backend/app/workers/run_ingest_worker.py`
  - enrich the existing ingest result log with `crawl_job_id`, `listing_id` when present, and persisted `job_id`
  - add optional `DEBUG` trace around listing-to-published-job attachment

- `backend/app/api/crawl_jobs.py`
- `backend/app/services/crawl_job_dispatch_service.py`
  - retain concise `INFO` lifecycle logs so crawl start context is visible even when per-job tracing is off

### Scrapyd container helper

- `backend/scrapy_project/run_scrapyd_quiet.py`
  - replace logger-only suppression with HTTP access log suppression at the Site layer

## Data Flow

1. Docker starts backend and scrapyd.
2. Docker health checks hit `/health` and `/daemonstatus.json`.
3. Backend health now reads cached LLM state, so no repeated provider initialization happens.
4. Scrapyd health checks no longer emit access lines.
5. When a crawl runs:
   - API/service logs the crawl dispatch summary at `INFO`
   - listing scrapers log page summaries at `INFO`
   - listing scrapers log discovered job IDs at `DEBUG`
   - detail scrapers log start/result per `source_job_id` at `DEBUG`/`WARNING`
   - ingest logs the persistence result with enough IDs to correlate the scrape with the stored job row

## Error Handling

- If `SCRAPER_LOG_LEVEL` is invalid, fall back to `LOG_LEVEL`.
- Health endpoint must not raise merely because an LLM profile is degraded; it should report degraded state the same way it does today.
- Scrapyd quiet-mode changes must fail closed toward normal startup logging rather than breaking Scrapyd boot.
- Scraper instrumentation must never change crawl control flow; logging failures should not stop fetch or ingest paths.

## Testing Plan

Follow TDD with focused regression tests:

1. `health.py`
   - prove `/health` no longer calls `refresh_llm_status()`
   - verify degraded responses still work from cached status data

2. `logging_config.py`
   - verify scraper logger families respect `SCRAPER_LOG_LEVEL`
   - verify unset `SCRAPER_LOG_LEVEL` falls back to `LOG_LEVEL`

3. scraper logging
   - add targeted `caplog` tests around JobsDB and CTGoodJobs logging entry points
   - verify `SCRAPE_DETAIL_*` and `SCRAPE_LISTING_*` messages include expected IDs

4. ingest worker logging
   - verify result logs include correlation fields for `crawl_job_id`, `source_job_id`, and persisted `job_id`

5. scrapyd quiet runner
   - unit-test the quiet-site wrapper or monkeypatch to ensure access `log()` is suppressed

## Rollout Notes

- Default deployment can leave `SCRAPER_LOG_LEVEL` unset and behavior will match the current global log level.
- Local debugging can set:
  - `LOG_LEVEL=INFO`
  - `SCRAPER_LOG_LEVEL=DEBUG`

This gives detailed crawl traces without turning every backend component noisy.
