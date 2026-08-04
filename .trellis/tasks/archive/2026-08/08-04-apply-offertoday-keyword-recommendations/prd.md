# Apply OfferToday keyword pack recommendations

## Goal

Apply the evidence-backed OfferToday IT Keyword Pack recommendations from GitHub issue #49 to the current database catalog through its governed mutation workflow.

## Background

- The completed cross-source review analyzed 3,559 JobsDB, 3,178 CTGoodJobs, and 1,139 OfferToday IT Job Details.
- A fresh bounded OfferToday probe supplied canonical-ID evidence for the accepted additions.
- The current reviewed pack contains 127 enabled seed terms, including `Angular`, `pentest`, `penetration`, and `Dynamics`.
- Keyword changes are governed by the existing CSV export, preview, and single-use confirm workflow; direct database edits are not acceptable.

## Requirements

1. Add and enable these seven reviewed terms under `offertoday:118000`:
   - `Databricks`
   - `RPA`
   - `Spring Boot`
   - `Tableau`
   - `VMware`
   - `Dynamics 365`
   - `penetration testing`
2. Disable `pentest` without deleting its row or execution evidence.
3. Retain the broader existing terms `Dynamics`, `penetration`, and `Angular` to avoid reducing recall.
4. Do not add `Splunk`; it remains deferred until OfferToday canonical-ID evidence exists.
5. Preserve the prior 15 accepted additions and every unrelated keyword entry.
6. Apply the current database change only through CSV preview/confirm, verify the preview action set before confirmation, and retain the mutation audit trail.
7. Do not launch a crawl or write Job/JobDetail data as part of this task.

## Acceptance Criteria

- [x] A live catalog export/preview reports exactly seven adds and one disable, with no unrelated add/update/disable actions.
- [x] Confirmation succeeds through the governed workflow and creates auditable catalog state.
- [x] Post-confirmation catalog state has 133 enabled terms and retains the disabled `pentest` row.
- [x] No crawl is launched and no Job/JobDetail data is mutated.
- [x] Independent API and mutation-log assertions verify the resulting state.
- [x] GitHub issue #49 receives an implementation summary but remains open until explicit manual QA success.

## Out of Scope

- Adding `Splunk` or any other deferred candidate.
- Removing broad variants merely because a more specific phrase was added.
- Re-running the cross-source analysis or OfferToday listing probe.
- Modifying unrelated classification, crawl recovery, or frontend work already present in the working tree.
- Modifying the reviewed default initializer while its catalog service/API belongs to another active, uncommitted task; that synchronization must happen when the owning WIP is integrated.
