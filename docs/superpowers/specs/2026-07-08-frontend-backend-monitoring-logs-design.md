# Frontend and Backend Monitoring Logs Design

Date: 2026-07-08
Status: Approved in chat, pending user review of this written spec
Primary files:
- `backend/app/logging_config.py`
- `backend/app/main.py`
- `backend/app/api/progress.py`
- `backend/tests/test_logging_config.py`
- `backend/tests/test_progress_api.py`
- `frontend/src/api/client.js`
- `frontend/src/api/client.test.js`
- `frontend/src/components/scraper/ScheduleManager.jsx`
- `frontend/src/components/scraper/ScrapeProgressPanel.jsx`
- `frontend/src/components/JobBrowser.jsx`
- `frontend/src/main.jsx`

## Overall Objective

Improve monitoring visibility across both the backend and frontend without introducing a new telemetry stack.

The goal is to make the current system easier to operate when:

- an API request fails or becomes slow
- the scrape progress SSE stream disconnects, idles out, or receives malformed data
- an operator action such as launch, resume, or cancel fails in the UI
- backend logs need to be correlated with a specific frontend request or browser session

This iteration should strengthen the existing logging model rather than replace it.

## Iteration Scope

This iteration is a lightweight observability pass across the scraper control plane and its frontend surfaces.

In scope:
- backend request-correlation and request-summary logging
- backend progress-stream lifecycle logging
- backend crawl-control summary logs where operator actions matter
- frontend structured console logging for API, SSE, and operator-action failures
- a shared correlation ID model so frontend and backend events can be searched together
- focused test coverage for the new monitoring behavior

Out of scope:
- introducing JSON logging or a third-party observability service
- changing the scraper execution model or crawl business logic
- instrumenting every route in the application with verbose logs
- redesigning the scraper UI

## Current State

The repo already has meaningful scraper diagnostics on the backend:

- `SCRAPE_*` log events cover listing, detail, and ingest stages
- `SCRAPER_LOG_LEVEL` exists and can raise crawl visibility without raising all backend noise
- crawl dispatch and request creation already emit concise lifecycle summaries

The main gaps are now around the control plane and browser-facing surfaces:

- backend API logs do not consistently expose a request-level correlation ID
- progress-stream lifecycle events are mostly implicit, which makes disconnects and idle closures harder to investigate
- frontend failures are mostly raw `console.error(...)` calls with inconsistent fields
- frontend and backend events are hard to correlate during the same operator session

## Design Summary

Keep the existing plain-text logging style and extend it with searchable `key=value` summaries and stable event names.

The recommended approach is a combined pass across frontend and backend:

1. add request and stream correlation IDs
2. add low-noise backend request and SSE lifecycle logs
3. replace scattered frontend error logs with a small structured monitoring helper

This preserves the repo's current logging style while making real incidents much easier to trace end to end.

## Backend Design

### 1. Request correlation middleware

Add a small FastAPI middleware that:

- reads `X-Request-ID` from the incoming request when present
- generates a request ID when absent
- stores the ID on `request.state`
- echoes the ID back on the response header

The middleware should emit summary logs only when they are useful:

- any `5xx` response
- requests whose duration crosses a slow-request threshold
- selected control-plane routes where operator workflows matter, even on success

Expected fields:
- `request_id`
- `method`
- `path`
- `status`
- `duration_ms`

This should improve supportability without turning every successful low-latency request into log spam.

### 2. Progress stream lifecycle logging

The scrape progress stream is central to the operator workflow and deserves explicit lifecycle logs.

Add stream-level events for:

- stream opened
- stream parse or generation failure
- stream idle close
- stream closed by client disconnect when detectable

Also add a low-frequency snapshot summary that logs only when the visible workload changes meaningfully, such as:

- active job count changes
- backlog job count changes
- the stream transitions from active to idle

This avoids a log line every second while still making the stream state visible in production.

### 3. Crawl-control summary logs

Keep the existing crawl request and dispatch logs, but tighten operator-facing summaries around the control plane:

- create crawl job
- resume crawl job
- cancel crawl job
- progress bootstrap failures or runtime-capability lookup failures when those affect operators

Expected crawl summary fields where available:
- `request_id`
- `crawl_job_id`
- `source_site`
- `crawl_phase`
- `crawl_mode`
- `schedule_id`
- `source_listing_crawl_job_id`

These logs should stay at `INFO` for state transitions and `WARNING` or `ERROR` for failures.

## Frontend Design

### 1. Add a small monitoring helper

Create a small frontend utility that standardizes structured console output.

Recommended shape:
- `logInfo(event, fields)`
- `logWarn(event, fields)`
- `logError(event, fields)`

This helper should:

- normalize fields into a consistent object payload
- stamp logs with a stable prefix such as `APP_MONITOR`
- avoid throwing if a field cannot be serialized cleanly

The goal is not browser telemetry ingestion. The goal is making local browser diagnostics searchable and consistent.

### 2. API request logging in `apiFetchJson`

`frontend/src/api/client.js` should become the main frontend API monitoring point.

For each request:
- generate a `client_request_id`
- pass it to the backend through `X-Request-ID`
- record start time
- on failure, log the URL, method, request ID, duration, and normalized error detail
- on success, stay quiet by default unless the helper is later extended for debug mode

This keeps noisy success paths silent while making real failures much easier to investigate.

### 3. SSE logging for the scrape progress panel

`ScrapeProgressPanel.jsx` should emit structured monitoring logs for:

- stream open
- malformed SSE payload parse failure
- reconnect attempt after error
- stream closed due to backend idle close

Because `EventSource` does not reliably support custom request headers in this setup, the panel should generate a `client_stream_id` and send it as a query parameter. The backend can then include that ID in stream-lifecycle logs.

### 4. Operator-action failure logging

Replace the current ad hoc `console.error(...)` calls in high-value surfaces with the shared monitoring helper:

- `ScheduleManager.jsx`
- `ScrapeProgressPanel.jsx`
- `JobBrowser.jsx`

Important events:
- failed category bootstrap
- failed runtime-capabilities bootstrap
- failed listing-batch bootstrap
- failed progress bootstrap
- failed resume/cancel/manual-action operations
- failed filter-option bootstrap in the job browser

These logs should include enough context to tell what the operator was doing without reading the component internals.

### 5. Global browser error hooks

Add lightweight global listeners in `frontend/src/main.jsx` for:

- `window.error`
- `window.unhandledrejection`

These should log through the same helper with stable event names so unexpected uncaught failures are not lost.

## Correlation Model

Correlation is the core feature of this design.

### Request correlation

- frontend generates `client_request_id`
- frontend sends it as `X-Request-ID`
- backend middleware reuses it or generates one
- backend includes `X-Request-ID` on the response
- frontend logs the same ID on failures

### Stream correlation

- frontend generates `client_stream_id`
- frontend appends it to the SSE URL query string
- backend includes `client_stream_id` in stream lifecycle logs

### Crawl correlation

When a request or stream is tied to a crawl workflow, backend logs should also include:
- `crawl_job_id`
- `source_site`
- `schedule_id` when present

This gives three search handles:
- UI request or stream
- backend HTTP request
- crawl job lifecycle

## Noise Control and Error Handling

The extra visibility should not degrade the signal-to-noise ratio.

Backend rules:
- do not log every healthy request
- do not log every SSE tick
- use `WARNING` and `ERROR` only for abnormal paths

Frontend rules:
- do not log every successful fetch
- do not duplicate the same failure at multiple layers unless the second log adds new context
- keep logs resilient when `Error` objects or payloads are partially missing

Failure behavior:
- if correlation-ID generation fails, fall back to a timestamp-based ID rather than dropping monitoring
- if backend stream logging cannot resolve a client stream ID, continue streaming normally
- monitoring must never break control flow for fetches, SSE, or operator actions

## Testing and Verification

Add focused tests rather than broad snapshot churn.

Backend coverage:
1. request middleware uses an incoming `X-Request-ID` and returns it in the response
2. request middleware generates a request ID when absent
3. progress stream lifecycle helpers log idle-close or transition summaries without logging every tick
4. logging config tests still pass with the new request-monitoring setup

Frontend coverage:
1. `apiFetchJson` attaches a request ID header
2. `apiFetchJson` logs structured failure context on rejected or non-OK responses
3. `ScrapeProgressPanel` logs parse failures and reconnect paths through the helper
4. global error hooks register and forward uncaught errors through the helper

Verification commands for implementation:
- `python -m pytest -q backend/tests/test_logging_config.py backend/tests/test_progress_api.py backend/tests/api/test_health.py backend/tests/workers/test_run_ingest_worker_logging.py`
- `cd frontend && npm test -- src/api/client.test.js src/components/scraper/ScrapeProgressPanel.test.jsx`
- `cd frontend && npm run build`

## Implementation Steps

1. add backend request-correlation support and request-summary logging
2. extend progress-stream logging with lifecycle and low-frequency summary events
3. tighten backend crawl-control summaries where operator actions matter
4. add a shared frontend monitoring helper
5. instrument `apiFetchJson` with request IDs and structured failure logs
6. migrate scraper and browser surfaces away from raw `console.error(...)`
7. add global browser error and rejection logging
8. run focused backend tests, frontend tests, and frontend build verification

## Risks

- request-summary logging can become noisy if the slow-request threshold is too low
- stream logging can accidentally become per-tick logging if transition guards are wrong
- frontend monitoring can double-log the same error if `apiFetchJson` and component handlers both log identical data
- tests around browser globals and `EventSource` can become brittle if the helper is coupled too tightly to implementation details

Mitigation:
- log only slow, failing, or explicitly important requests
- keep stream summaries transition-driven
- let `apiFetchJson` own transport-level logging and let components log only contextual follow-up failures
- test helper calls and stable outcomes rather than exact console formatting

## Success Criteria

An operator or developer should be able to answer these questions quickly from current logs:

- which frontend action triggered the failing backend request
- whether the scrape progress stream connected, idled out, or started reconnecting
- which crawl job a failing control-plane request belonged to
- whether a failure is a browser-side issue, an API issue, or an SSE lifecycle issue
- what request or stream ID to search across frontend and backend logs
