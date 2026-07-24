# Technical design

## Boundaries

This task changes two independent seams that produced one misleading operator
experience:

1. CTGoodJobs detail payload integrity from parser through ingest.
2. Crawl-task projection and frontend actions at the listing/detail run boundary.

It does not join listing and detail runs into one lifecycle and does not change
same-task manual-action Resume behavior.

## CTGoodJobs evidence flow

`parse_detail_page` remains the evidence producer and the ingest worker remains
the strict validator. `merge_ctgoodjobs_job` must carry
`source_attribute_evidence` using the existing detail-first `_choose` rule. The
canonical builder then transports the payload unchanged.

The regression seam should exercise merge plus canonical construction with a
realistic evidence payload. Parser/adapter tests continue to own extraction
correctness; ingest tests continue to own schema validation.

## Task projection

Operator-state derivation must branch on the authoritative run phase:

- listing runs use listing-workload completion/partial semantics;
- detail runs use their frozen `detail_snapshot.remaining_count` contract;
- mutable staging-row detail statuses do not turn a completed listing run into a
  detail backlog owner.

Raw staging statistics may remain visible as diagnostics, but they cannot alter
the listing task's operator state or authorize detail recovery.

## Frontend actions

Remove the terminal “Start detail recovery run” panel/action from Task Details.
Remove the page callback and draft builder when they are no longer referenced,
plus tests that encode the removed behavior. Do not remove:

- the `ManualActionRecoveryPanel`;
- Fresh Profile / Reuse Open Browser same-task Resume;
- frozen-snapshot decoding or read-only metrics.

## Compatibility and data

No database migration is required. Existing crawl jobs and frozen snapshots are
left untouched. Backend snapshot fields remain backward compatible; only the
derived operator state for listing runs becomes phase-correct.

## Rollback

The evidence change can be reverted independently from the projection/UI
change. No persistent-data rollback is necessary. A failed rollout is handled by
reverting code and starting a new operator-created crawl, not mutating old runs.
