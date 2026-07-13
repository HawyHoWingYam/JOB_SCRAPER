# OfferToday Phase A-B cursor pagination bake-off

## Goal

Complete implementation-plan Tasks 1-8: preserve rejected Plan 2 v1 evidence, add cursor-correct v2 listing contracts and replay, and produce a deterministic-review-ready bounded five-variant pagination bake-off without changing production defaults.

## Background

- Live UI evidence proves the listing protocol is response-cursor based and currently returns an effective page size of 10.
- The rejected stateless Plan 2 candidate had stable counts but unstable ID sets; its fixed-cohort Jaccard was `0.8683001531393568`.
- The worktree already contains interrupted Phase A/B-shaped edits. Each must be audited against the source plan and tests before it is retained.
- Authoritative requirements are implementation-plan Sections 1-7, research-spec Phases A/B, and the Plan 2 decision's immutable artifact index.

## Requirements

1. Freeze v1 candidate serialization, hashes, experiment routing, fixture behavior, and strict replay before adding v2 behavior.
2. Add immutable typed cursor, request-policy, transport-result, page-result, page-evidence, and `DiscoveryCandidateV2` contracts with exact validation and redacted evidence.
3. Preserve the existing production payload defaults while allowing explicit page size and validated cursor inputs that build fresh payload dictionaries.
4. Add a condition-local cursor state machine with exact retry replay, cursor isolation, terminal plus empty-confirmation semantics, browser-loss restart rules, and zero staging on any contract/identity/gap failure.
5. Keep `resultList` and `suppleRcdList` as separate validated identity/conservation cohorts; supplemental rows are evidence-only in Phase A/B.
6. Keep browser transport free of cursor state while exposing typed payload ownership and a non-sensitive context hash; implement and close all three frozen runtime lifecycles.
7. Persist v2 event and artifact evidence without raw secrets, then independently replay ordering, cursor continuity, logical/physical attempts, IDs, cohorts, conservation, no-write evidence, budgets, and terminal status.
8. Implement the five frozen variants, deterministic randomized order, two-repeat comparison, frozen duplicate-reduction and stability thresholds, and fail-closed candidate selection.
9. Implement `pagination-bakeoff`, `compare-pagination`, and `freeze-discovery-candidate` with exact baseline, offline/live, parent-artifact, budget, exit-code, and immutable-artifact rules.
10. Run deterministic verification and obtain the Phase A/B live review gate before spending any live request budget.

## Constraints

- Phase B uses categories `(118000, 112000, 127000)`, two repeats, five variants, and at most 10 logical pages per condition.
- Each repeat permits at most 150 logical listing pages, 300 physical attempts, zero detail attempts, and zero product writes.
- The endpoint stays `/wapi/geek/recommend/search/list`; `rcdType` is omitted.
- Material duplicate reduction means at least 10 percentage points absolute and at least 20% relative versus `stateless-current`.
- Candidate gates include minimum same-condition Jaccard `>= 0.95`, union no worse than control at no more than 2x logical request cost, and zero cursor/gap/identity/conservation/unclassified-full-zero-new failures.
- Runtime artifacts remain ignored and uncommitted; unrelated dirty-worktree changes are preserved.

## Acceptance Criteria

- [x] V1 canonical payload/hash tests and exact experiment-routing tests pass; locally available Plan 2 artifacts retain identical generic and strict replay results.
- [x] V1 and v2 candidate/artifact payloads reject cross-parsing and unknown versions fail closed.
- [x] Exact cursor/page scalar, immutability, effective-page-size, supplemental-cohort, and secret-redaction tests pass.
- [x] Cursor retries reuse one logical request and identical input/fingerprint; cursor advancement happens only after successful validation.
- [x] Cursor/session/page-size/identity/gap failures make zero condition staging calls, and browser-loss recovery restarts from page 1.
- [x] Runtime context hashes are stable within a context, change after restart, and every lifecycle closes on success and failure.
- [x] V2 strict replay accepts complete fixtures and rejects forged hashes, leaked sessions, missing/duplicated/reordered attempts, changed cursor inputs, budget drift, and write evidence.
- [x] Bake-off decision tests cover pass, every rejection gate, tie/order independence, and no-candidate outcomes.
- [x] CLI tests prove pre-browser baseline validation, exact budgets, offline comparison/freezing, immutable parent binding, distinct exit codes, and fail-closed selection.
- [x] The focused deterministic suite, full backend suite, production-default guards, and `git diff --check` pass before live review.
- [x] If live execution is approved, two fresh matching baselines precede each repeat and every output passes generic plus strict replay.
- [x] Phase B ends with either one independently recomputed accepted v2 candidate or an explicit no-candidate stop; production defaults remain unchanged.

## Out of Scope

- Phase C endpoint/partition probing, cursor-correct full census, broad-IT/planner work, detail canaries, recovery soak, and production adoption.
- Any live request before deterministic review or any automatic progression after a rejected decision.
