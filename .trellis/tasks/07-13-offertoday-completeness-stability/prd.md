# OfferToday completeness and stability implementation

## Goal

Implement and prove a cursor-correct OfferToday discovery and detail pipeline, then adopt it in production only after every staged evidence gate passes. Discovery recall and pipeline completion remain separate measurements throughout.

## Authoritative Inputs

- `docs/specs/2026-07-13-offertoday-completeness-and-stability-implementation-plan.md`
- `docs/specs/2026-07-13-offertoday-completeness-and-stability-research-spec.md`
- `docs/specs/2026-07-13-offertoday-plan2-census-decision.md`
- Current checkout, immutable research artifacts, strict replay output, and current database baselines are authoritative over prior conversation summaries.

## Background

- Plan 2 was valid rejected evidence: its fixed-cohort minimum Jaccard was `0.8683001531393568`, below `0.95`.
- The current UI uses response-derived cursor fields and an effective page size of 10; the rejected v1 crawler independently requested stateless pages with `pageSize=50`.
- The accepted 20-ID smoke proved useful detail transport behavior, but not the separate 99% detail acceptance gate.
- Existing Plan 2 artifacts and v1 candidate semantics must remain immutable and replayable.

## Requirements

1. Add versioned, immutable listing request, cursor, page-result, observation, and discovery-candidate contracts with exact scalar validation and secret-safe evidence.
2. Make cursor state condition-local, replay identical cursor inputs on retry, restart a condition after browser loss, and reject cursor/session/page-size violations before staging.
3. Keep result and supplemental cohorts separate until evidence classifies supplemental rows.
4. Preserve production defaults and all v1 artifact meanings while adding fail-closed v2 experiment routing and strict replay.
5. Execute the no-detail, no-product-write Phase B five-variant bake-off only after deterministic Phase A/B review and two matching database baselines per live repeat.
6. Keep phase results and acceptance gates explicit, but allow later research tasks to be created, planned, and implemented when an earlier unresolved issue is explicitly deferred by the user; deferral is not acceptance and must remain visible in downstream evidence.
7. Change production defaults only after three independent production-paced soak runs pass and a separate adoption review is complete.
8. Keep runtime artifacts ignored and uncommitted; preserve all unrelated dirty-worktree changes.

## Task Map

- Child 1: Phase A/B cursor contract and bounded pagination bake-off (implementation-plan Tasks 1-8).
- Child 2: Phase C endpoint and partition research infrastructure (Tasks 9-10), authorized as deterministic no-live work while Phase B Issues #4 and #5 remain unresolved but explicitly deferred.
- Future child: Phase D cursor-correct census (Task 11), scoped independently without treating Issues #4/#5 as a task-sequencing blocker; its exact live inputs and authorization belong to that child.
- Future child: Phase E/F IT reference and planner ablation (Tasks 12-13), scoped independently while carrying unresolved upstream evidence explicitly.
- Future child: Phase G detail bake-off and canaries (Tasks 14-15), scoped independently with its own live/write gates.
- Future child: Phase H recovery and soak (Tasks 16-17), scoped independently with its own live/write gates.
- Future child: production adoption (Task 18), scoped independently but still requiring an explicit adoption review before any default changes.

## Acceptance Criteria

- [ ] Listing pagination follows a validated response-derived cursor contract.
- [ ] The accepted discovery denominator comes from repeated cursor-correct evidence, not `total`, gross rows, page caps, or one run.
- [ ] Broad-IT precision, false-negative, and planner recall gates pass against the independent denominator.
- [ ] The 500-ID detail canary and all transaction/recovery gates pass.
- [ ] Three production-paced discovery-plus-detail soak runs each pass every gate independently.
- [ ] Every input and decision artifact passes generic hash verification and experiment-specific strict replay.
- [ ] Production defaults are tied to the accepted candidate hash and change only in the final adoption child.
- [ ] Existing Plan 2 artifacts still replay as rejected v1 evidence with unchanged candidate hashes and issues.
- [ ] Runtime artifacts remain ignored/uncommitted and unrelated worktree changes remain untouched.

## Out of Scope Until Gated

- Ungated full-census repetition, keyword expansion, higher concurrency, or full detail-backlog draining.
- Treating `data.total`, row sums, or empty stateless pages as completeness proof.
- Production fallback to the rejected stateless v1 policy after v2 adoption.

## Deferred Known Issues

- GitHub Issues #4 and #5 remain unresolved and must not be represented as passed.
- By explicit user decision, they do not block creation, planning, or implementation of later OfferToday tasks.
- Live execution, product-data writes, and production adoption remain governed by the explicit scope and review gates of their owning tasks.
