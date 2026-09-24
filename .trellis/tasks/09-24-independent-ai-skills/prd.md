# Independent AI Skills and correction provenance

## Goal

Make ordinary AI enrichment publish a usable Skill baseline without creating or
calling Jev work. Establish evidence-aware precedence so later manually started
Jev corrections and operator decisions can be applied without destroying the
AI baseline or audit history.

## Requirements

- Remove inline Jev case creation, run creation, provider dispatch, and receipt
  projection from ordinary AI enrichment.
- Persist AI-extracted Skills through current taxonomy reconciliation: governed
  exact/alias matches become assignments; unresolved technical terms remain
  Candidate/Mention evidence; generic/rejected curation stays terminal.
- Record model provenance and current Job evidence identity for the AI baseline.
- Preserve distinct AI, Jev, and operator provenance needed by later children.
- Effective precedence is operator correction, current-evidence Jev correction,
  then current-evidence AI baseline. Changed evidence invalidates Jev currency
  without deleting history or triggering Jev.
- Empty success is distinct from unavailable or invalid processing.
- Neither AI nor Jev may create governed taxonomy nodes without explicit
  operator approval.

## Acceptance Criteria

- [ ] Ordinary AI enrichment with extracted Skills publishes assignments or
  Candidates when Jev is disabled, absent, or unconfigured.
- [ ] Ordinary enrichment creates zero Jev classifications, runs, reservations,
  attempts, or provider requests.
- [ ] Empty AI extraction clears only the applicable automated projection and
  is recorded as a successful empty baseline.
- [ ] Operator-owned decisions are not silently overwritten.
- [ ] A current Jev correction can add/remove AI Skills while the AI baseline
  remains traceable; changed evidence makes it stale without dispatch.
- [ ] Backend service/API tests and parent end-to-end scenarios pass.

## Dependencies and boundaries

- This child precedes manual batch orchestration and Jev Related Jobs.
- The parent task design is the source for cross-child contracts.
- This child does not add the unified UI or automatically backfill history.
