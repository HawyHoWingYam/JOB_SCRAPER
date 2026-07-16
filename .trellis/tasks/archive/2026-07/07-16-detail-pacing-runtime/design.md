# Design: Source-specific detail pacing runtime

## Persistence and Service Boundary

`scraper_pacing_settings` owns saved values and a unique normalized `source_site`.
A single service owns defaults, normalization, validation, get/update/reset, and
resolution for dispatch. Missing rows defensively resolve to defaults with a
bounded warning, but migrations seed all supported rows.

API responses return explicit numeric fields and source identity. The frontend
never calculates effective defaults independently.

## Dispatch Snapshot and Concurrency Guard

Only manual `crawl_phase=detail` dispatch resolves pacing. In the same dispatch
transaction, query/lock active same-source detail CrawlJobs and reject conflicts
before creating the new job. Store the resolved typed object under
`request_payload.detail_pacing`.

Resume preserves this object verbatim. Mutable cumulative `detail_attempt_count`
is stored in runtime metrics/state after each admitted attempt and is restored
when the same task resumes. Task projection must not expose this counter as a UI
pacing metric.

## Shared Pacing Controller

The controller accepts immutable config, restored attempt count, random source,
sleep function, cancellation token, and progress persistence callback.

Before an outbound attempt it:

1. checks cancellation;
2. if this is not the first cumulative attempt, chooses either burst pause or a
   random ordinary interval;
3. sleeps in <=1-second cancellation-aware slices;
4. checks cancellation again;
5. admits and persists the next attempt position immediately around the fetch
   boundary so retries and failures are counted exactly once.

The caller tells the controller whether more work remains, preventing a final
pause. OfferToday's existing retry loop invokes the controller per fetch and
retains its retry classification/backoff ownership; no outer retry is added.

## API Projection

Task snapshot reads only `request_payload.detail_pacing`. A missing object yields
an explicit null/not-recorded projection. Current global values are never a
fallback for task history.

## Tests

Use fake random/sleep/token/persistence dependencies. Include constant interval,
burst pause zero, retries, terminal outcomes, cancellation during long sleep,
manual resume at attempt 17, and final attempt at a burst boundary.
