# Retry transient JobsDB listing disconnects

## Goal

Prevent a single transient JobsDB listing transport disconnect from failing an
otherwise healthy Crawl Job, while keeping retries bounded and preserving the
existing cancellation, access-block, and logical request-budget contracts.

## Background

- Crawl Job `4a85d315-bd02-42c6-b0d0-83a4517c898f` failed after about nine
  seconds with `Server disconnected without sending a response.`
- The worker had already preserved 8 staged listings and skipped 53 existing
  identities before `httpx.RemoteProtocolError` escaped from the JobsDB listing
  request and terminated the standalone executor with exit code 1.
- JobsDB listing currently makes one HTTP attempt per logical page and has no
  bounded transport retry at that boundary.

## Requirements

- Retry only transient JobsDB listing transport exceptions, including a server
  disconnect before response headers are returned.
- Use a small, bounded number of attempts with cancellation-aware backoff.
- Do not retry HTTP status failures, JobsDB access-block/manual-action errors,
  response parsing failures, programming errors, or cancellation requests.
- Keep one logical listing page equal to one dispatch request-budget claim;
  internal transport retries must not reduce the planned page scope.
- Emit a structured retry log only when another attempt will actually occur,
  without logging raw exception messages or response bodies.
- Preserve already committed listing pages and existing terminal failure
  behavior when all transport attempts are exhausted.

## Acceptance Criteria

- [x] A synthetic `httpx.RemoteProtocolError` followed by a valid response
      succeeds and uses the same client/request parameters.
- [x] Repeated transient disconnects stop at the configured attempt bound and
      re-raise the final transport exception.
- [x] HTTP errors, manual-action errors, malformed payloads, and cancellation
      are not consumed by the retry loop.
- [x] Retry waiting uses the injected cancellation-aware sleep seam.
- [x] Focused JobsDB pagination, runtime, access recovery, and logging tests
      pass, followed by scoped lint, compilation, and backend regression tests.

## Notes

- This task changes JobsDB listing transport resilience only. The separate
  OfferToday stale-execution watchdog task remains independent and unmodified.
