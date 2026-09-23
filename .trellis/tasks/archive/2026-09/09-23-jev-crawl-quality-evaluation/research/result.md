# Phase 3B crawl-content quality evaluation result

Decision: **inconclusive**.

The offline implementation and deterministic data gates passed. The first paid
development case received OpenRouter HTTP 520, so the run stopped immediately
under the predeclared ambiguous-failure rule. No retry and no held-out request
was sent. This technical response is not a content-quality label.

## Completed evidence

- 19 strict controlled cases across JobsDB, CTGoodJobs, and OfferToday;
  English, Traditional Chinese, and mixed language; valid detail, short/empty,
  login wall, WAF, terminal page, listing/template, truncation, irrelevant
  boilerplate, missing evidence, and option-order stability.
- Deterministic known WAF/terminal states bypass paid work; transport/missing
  evidence remains insufficient. Candidate recall on controlled semantic
  problems is 1.0.
- Typed two-question runner, probabilities, evidence hashes, receipt metadata,
  cost accounting, and full-denominator metric tests pass.
- Two independent PostgreSQL read-only exports of 100 crawl-listing snapshots
  produced byte-identical minimized artifacts.
- No CrawlJob, event, listing, Job, repair, browser, dispatch, or product flag
  state was written.

## Paid stop

- Selected development Jev candidates: 6.
- Requests actually attempted: 1.
- Result: `unavailable`, safe error code `http_520`.
- New uncertain reservation: 50,000 microdollars.
- Held-out requests: 0.
- Ledger after stop: 402 spent, 400,000 uncertain reserved, 9,599,598 remaining.

## Quality gate

- Phase 3B focused tests: 10 passed.
- Complete Jev regression: 75 passed, 1 skipped.
- Ruff, Black, compileall, artifact replay, privacy boundary, and read-only
  database checks passed.

The result does not authorize production quality flags or automatic recovery.
