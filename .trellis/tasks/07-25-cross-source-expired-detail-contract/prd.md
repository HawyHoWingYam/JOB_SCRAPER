# Audit expired detail jobs across sources

## Goal

Audit and normalize terminal-unavailable handling for expired detail job IDs across JobsDB, CTGoodJobs, and OfferToday without blocking the focused CTGoodJobs regression fix.

## Background

- Expired detail IDs are an expected source lifecycle outcome, not necessarily an access block or parser/schema failure.
- CTGoodJobs has a terminal-unavailable contract but missed the live `jd--expired` page marker; the focused P1 task `../07-25-ctgoodjobs-detail-parser-recovery` owns that regression.
- OfferToday already maps its known terminal detail response to a non-retryable per-item outcome and continues the batch.
- JobsDB has no confirmed equivalent expired-detail classification and requires evidence gathering before behavior is changed.

## Requirements

- Inventory the positive expired/deleted signals for each source and distinguish them from WAF, auth, IP blocking, schema anomalies, and transient failures.
- Define a shared behavioral invariant: explicit expired detail targets become terminally unavailable per item, do not invoke manual browser recovery, and do not stop the remaining batch.
- Preserve source-specific evidence and reason codes rather than guessing expiration from missing fields alone.
- Add source-owned fixtures and tests for every confirmed signal before changing runtime behavior.
- Do not duplicate or delay the focused CTGoodJobs P1 fix.

## Acceptance Criteria

- [ ] JobsDB, CTGoodJobs, and OfferToday expired-detail contracts are documented with evidence-backed signals and gaps.
- [ ] Every implemented signal has a deterministic fixture and distinguishes expired from blocked/unknown pages.
- [ ] Explicit expired targets transition to terminal unavailable and the batch continues.
- [ ] Missing job/company fields alone do not prove expiration.
- [ ] Cross-source progress and retry semantics remain consistent.

## Dependency

- The CTGoodJobs P1 task may land first. This audit must treat its final contract/tests as existing behavior and must not reimplement or revert them.
