# Crawl Control Automation Review Contract

## Scope

Use this contract when changing Automation create/update review, scheduled
listing workload projection, or scheduled detail eligibility previews.

## Contracts

- `POST /api/v1/automations/reviews` is read-only. It may resolve the current
  published Source Catalog, canonical scope, workload, detail eligible count,
  readiness, and schedule summary. It must not prepare/freeze a Dispatch Plan,
  create a revision, claim work, emit an event/outbox row, or call a Source.
- Automation create/update requires `review_fingerprint`. Immediately before
  mutation, the backend recomputes the review under current Catalog,
  Automation revision, readiness, and configuration state. A mismatch returns
  structured `AUTOMATION_REVIEW_STALE`; the caller must review again.
- The fingerprint includes authored/resolved scope, Catalog revision,
  configuration, workload/detail projection, readiness, warnings, and current
  Automation identity/revision. It excludes clock-only display values such as
  `checked_at` and `next_run_at`.
- Scheduled detail review is an estimate only and reports
  `snapshot_frozen=false`. Each due Automation run freezes its own future
  finite snapshot through Dispatch Plan authority.
- Edit review carries expected revision and a decoded `before` Automation.
  Existing compare-and-swap enforcement remains authoritative at write time.

## Forbidden patterns

- Do not call Dispatch Plan preparation from Automation review.
- Do not let React construct or hash a substitute review.
- Do not accept a stale fingerprint because the submitted configuration still
  parses or because only Catalog/readiness state changed.

## Verification

Run focused review service/API tests and Ruff on the touched Crawl Control
modules. Do not use the full backend suite for this seam.
