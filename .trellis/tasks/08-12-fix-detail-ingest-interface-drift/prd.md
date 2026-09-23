# Fix cross-source detail ingest interface drift

## Goal

Restore JobsDB and CTGoodJobs detail persistence after an ingest-service
interface change, and prevent deterministic worker/programming failures from
being repeated across an entire detail batch.

## Background

- CTGoodJobs Crawl Job `444ee187-2af8-4877-8115-5ce36ce4680e` selected 990
  detail targets and remained active while every processed target failed.
- At diagnosis time it had 0 successful and 175 failed targets. Each persisted
  the same error: `'IngestWorkerService' object has no attribute
  'project_company_industry'`.
- `backend/scripts/ctgoodjobs_standalone_crawl.py:354` and
  `backend/scripts/jobsdb_standalone_crawl.py:782` still call that removed
  method. `IngestWorkerService` now exposes `project_source_attributes()`.
- CTGoodJobs catches generic per-target exceptions and continues, so a
  deterministic application defect can consume the complete frozen backlog.
- The operator cancelled the affected Crawl Job after diagnosis.

## Requirements

- R1. Update JobsDB and CTGoodJobs detail persistence to use the current ingest
  projection contract without restoring the removed legacy method.
- R2. Preserve atomic Job, Company, source-classification, employment-type, and
  any still-supported projection behavior at the existing persistence boundary.
- R3. Treat deterministic application/interface failures as run-fatal instead
  of marking every remaining target failed.
- R4. Keep ordinary target-specific failures isolated so one malformed or
  unavailable job does not abort a healthy batch.
- R5. Preserve cancellation, manual-action, terminal-unavailable, content
  anomaly, pacing, progress, and already committed output semantics.
- R6. Ensure a failed target remains recoverable by a later detail run and that
  unattempted frozen targets are released or remain eligible according to the
  existing terminal settlement contract.
- R7. Add regression coverage for both source executors and the fail-fast
  classification boundary.
- R8. Preserve authoritative crawl query metadata when detail ingest observes
  Source Classification path evidence, so collected Jobs cannot make a
  published classification non-executable.

## Acceptance Criteria

- [ ] A representative JobsDB detail persists through the current ingest
      projection API without `AttributeError`.
- [ ] A representative CTGoodJobs detail persists through the same current
      projection API without `AttributeError`.
- [ ] A deterministic missing-method/programming error aborts the detail run
      after the first affected target and settles the Crawl Job truthfully.
- [ ] Expected target-specific parse/content/unavailable failures retain their
      current continue-or-pause behavior.
- [ ] Cancellation and manual-action tests remain green, and committed detail
      outcomes are preserved.
- [ ] Focused cross-source detail tests, lint, type/compile checks, and the
      available backend regression suite pass.
- [ ] A CTGoodJobs detail observation cannot clear an existing native
      `url_path`, and the affected Information Technology node compiles after a
      validated catalog refresh.

## Out Of Scope

- Automatically restarting or resuming the cancelled production Crawl Job.
- Redesigning the complete Job Intelligence classification architecture.
- Treating source/network/manual-action failures as programming defects.
