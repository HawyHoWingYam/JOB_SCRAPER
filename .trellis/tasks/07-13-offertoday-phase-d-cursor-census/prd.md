# OfferToday Phase D cursor-correct census

## Goal

Implement and prove the Phase D cursor-correct full-site census path from an immutable Phase C discovery-policy candidate. The task owns deterministic contracts, offline candidate freeze, live census/fixed-repeat orchestration, strict replay, deduplicated listing-only staging, stability comparison, and the stable reference denominator. It must stop rather than manufacture Phase D evidence when the Phase C policy gate has not passed.

## Authoritative Inputs

- `docs/specs/2026-07-13-offertoday-completeness-and-stability-implementation-plan.md`, especially Task 11 at lines 541-571.
- `docs/specs/2026-07-13-offertoday-completeness-and-stability-research-spec.md`, especially Phase D at lines 262-286.
- The strict-valid artifacts under `backend/runtime/offertoday-research/`, current database baselines, and current checkout are authoritative over conversation summaries.

## Confirmed Starting State

- Phase B comparison runs `7a35b33e-580d-4aae-85d7-8a1ac9fb2b9b` and `5f9d2ae3-4933-4e71-baf7-6ac541c13142` are valid rejected evidence: neither selected a pagination candidate. Issues #4 and #5 remain explicitly deferred, not accepted.
- Phase C deterministic infrastructure is committed at `c68e0f5d`, but no Phase C live artifact or frozen Phase C discovery policy exists in the runtime artifact inventory.
- `DiscoveryCandidateV2` at `backend/app/sources/offertoday/research/live_contracts.py:24` freezes only the three-category Phase B pagination decision. It has no endpoint-contract ID/hash, partition catalog/hash, retained partition set, or full Phase D condition order and therefore cannot be treated as the Phase D predecessor.
- Legacy `census`, `repeat-fixed`, and `compare` still consume `CensusCandidate` through `OfferTodayResearchLiveService.run_census()` at `backend/app/services/offertoday_research_live_service.py:501`; changing their schema or semantics would invalidate historical evidence.
- Phase C comparison evidence exposes strict-replayable endpoint, policy, baseline, partition, terminal, contribution, and parent hashes. `PartitionComparison.accepted` only means at least one condition was retained; Phase D must apply stronger freeze rules.
- The earlier Plan 2 comparison used the user-approved 15-minute sampling-window amendment. The newer authoritative Phase D specification independently requires at least two census windows separated by six hours; the old amendment does not overwrite Phase D.

## Requirements

### R1. Phase C predecessor closure

- Add an offline `freeze-discovery-policy` command that consumes only generic-valid and strict-valid Phase C endpoint/partition comparison evidence.
- Reject freezing unless the comparison is accepted, every retained condition has a verified cursor-capable endpoint contract, cursor-confirmed terminal state, required empty confirmation, zero gaps/identity/conservation differences, and contribution or versioned high-value evidence.
- Freeze the exact endpoint adapter identity, request/cursor/terminal policy, Phase D condition order, official partition definitions, catalog hash, pacing, page/attempt budgets, fixed cohort, source artifact projections, and parent manifest hashes.
- Preserve the valid-rejected Phase B lineage and unresolved Issues #4/#5 in candidate provenance; deferral must never appear as acceptance.
- Use a new `DiscoveryPolicyCandidateV2` payload and `discovery-policy-candidate-v2` experiment. Do not mutate the existing `DiscoveryCandidateV2`, `CensusCandidate`, or their experiment schemas/hashes.

### R2. Exact Phase D condition contract

- The full census condition set contains every one of the 31 official top-level category partitions in deterministic catalog order under one frozen cursor-capable endpoint policy. Any additional retained Phase C partitions are separately named and hash-bound; they cannot replace a top-level condition.
- The fixed-repeat cohort is exactly `(118000, 112000, 127000)` projected from the same candidate, endpoint, request policy, and condition definitions.
- Every condition uses a condition-local browser/cursor chain. Retry replays the identical request/cursor fingerprint. Browser loss restarts only that condition from page 1 and deduplicates canonical IDs; no cursor is resumed across a browser/process boundary.
- A page cap is a safety budget only. Hitting it is not exhaustion and makes the run ineligible.

### R3. Versioned live commands and budgets

- Add separate `census-v2` and `repeat-fixed-v2` commands that accept only a strict-valid frozen `discovery-policy-candidate-v2` artifact.
- Each Phase C probe and Phase D live command requires `--confirm-live-research`, an explicit structurally valid `--auth-state`, exactly two distinct matching baselines, and a current-database recheck before browser/runtime construction.
- Bind the validated storage-state bytes to every condition-local runtime, recheck their SHA-256 before construction, and record only `session_mode` plus `session_state_sha256`; no state path or contents may enter durable evidence.
- Require an explicit run index. Three census artifacts and three fixed-repeat artifacts must have distinct run IDs and one identical candidate hash.
- Do not use a blocking sleep. Run scheduling is external; artifact capture times are the evidence used by offline comparison.
- Stop immediately on auth/WAF/IP, cursor/session/endpoint/page contract, identity, gap, conservation, baseline, budget, product snapshot, or secret-leak failure while preserving a strict-replayable completed-condition prefix.

### R4. Listing-only staging and conservation

- Phase D may use `OfferTodayReconciledListingStagingSink` only behind an explicit staging-write confirmation; no-op mode remains available for deterministic tests and dry runs.
- Reconcile and deduplicate by canonical `jobId`; repeated pages/partitions/runs must not amplify staging rows.
- Jobs and Companies remain byte-for-byte unchanged. No detail request, publication, Company mutation, or production-default change is permitted.
- Cursor/page contract validation must occur before rows reach either staging sink.

### R5. Complete v2 evidence

- Define new immutable artifacts for `cursor-full-census-v2`, `cursor-fixed-repeat-v2`, and `cursor-census-stability-comparison-v2` with fail-closed strict replay.
- Record exact candidate/contract/catalog/condition hashes, condition outcomes, cursor-confirmed exhaustion, per-page marginal IDs, result versus supplemental cohorts, request/attempt counts, staging reconciliation, and product snapshots.
- Record every full effective row-set page with zero new IDs. Classify it only from replayable cohort, cursor-progress, later-page, and terminal evidence; otherwise increment `unclassified_zero_new_full_pages` and reject the run.
- Record unexplained session rollovers explicitly even when the runner already hard-stops them.
- Durable evidence contains only hashes/redacted cursor continuity; raw session IDs, cookies, CSRF/authorization values, CDP/profile paths, or other secrets are forbidden.
- A `saved-session` claim is eligible only when provenance contains the SHA-256 of the exact validated state bound to the runtime; the storage-state path and contents remain forbidden.

### R6. Offline comparison and stable reference denominator

- Add an offline `compare-stability-v2` command requiring exactly three accepted v2 census artifacts and three accepted v2 fixed-repeat artifacts with distinct run IDs and one candidate hash.
- Verify that the three censuses span at least two capture windows separated by `>= 21,600` seconds. Verify the three fixed repeats share one short-window identifier and report their exact capture span; freeze an executable maximum of 3,600 seconds unless the authoritative spec is amended before live execution.
- Recompute exact union/intersection, pairwise added/removed cohorts, fixed-cohort minimum Jaccard, population unique-count CV, request/time cost, all failure counts, rollovers, and zero-new classifications without trusting summaries.
- Accept only when every condition is cursor-confirmed exhausted, fixed-cohort Jaccard is `>= 0.95`, unique-count CV is `<= 0.05`, and all unresolved gaps, identity conflicts/issues, conservation differences, unclassified failures, unexplained rollovers, and unclassified zero-new full pages equal zero.
- Freeze the stable reference denominator as canonical IDs present in at least two of the three accepted census runs plus an optional, separately hash-bound set of independently confirmed active holdout IDs. Keep the full union diagnostic only.

### R7. Compatibility and operational boundaries

- Existing Plan 2 and Phase A-C artifact names, payload schemas, hashes, CLI behavior, and strict replay remain unchanged.
- Production payload defaults, standalone crawl behavior, API/frontend, migrations, Compose, and environment defaults remain unchanged.
- Runtime artifacts remain ignored and uncommitted; unrelated dirty-worktree changes remain untouched.
- Implementing the deterministic path does not authorize Phase C probes, Phase D live traffic, staging writes, later Phase E-H live work, or production adoption. Each live/write step must use the exact reviewed command and inputs owned by its task gate.

## Acceptance Criteria

### Deterministic implementation gate

- [x] A strict `discovery-policy-candidate-v2` contract and offline freeze command accept clean contract-verified bounded endpoint evidence while rejecting missing, rejected, non-cursor, malformed, mixed-parent, tampered, or capped retained-partition evidence.
- [x] `census-v2`, `repeat-fixed-v2`, and `compare-stability-v2` are isolated from legacy commands and fail closed on the wrong candidate/artifact version.
- [x] Fake-runtime tests prove condition-local cursor behavior, same-input retry, page-1 restart after browser loss, exact budgets, pre-staging validation, hard-stop prefixes, and zero detail/product writes.
- [x] Strict replay recomputes candidate, run, staging, zero-new-page, comparison, timing, holdout, and stable-denominator decisions and rejects rehashed semantic tampering.
- [x] Current Phase A-C focused tests and locally present historical artifacts still verify unchanged; production-default guards pass.
- [x] Phase C/D live commands fail before database/runtime construction without a valid explicit storage state, bind its exact path to every runtime, and export only its SHA-256 proof.

### Live Phase D evidence gate

- [ ] One immutable accepted Phase C discovery-policy candidate exists and passes generic plus strict verification.
- [ ] Three accepted cursor-full-census-v2 artifacts span at least two windows separated by six hours.
- [ ] Three accepted cursor-fixed-repeat-v2 artifacts cover `(118000, 112000, 127000)` within one short window.
- [ ] All six artifacts share one exact candidate hash, and Jobs/Companies/defaults remain unchanged.
- [ ] The strict comparison passes every Phase D gate and freezes one stable reference denominator artifact.

## Out of Scope

- Phase E/F IT labeling and planner ablation, Phase G detail canaries, Phase H recovery/soak, and Task 18 production adoption; they consume accepted Phase D evidence in later children.
- Treating `total`, gross rows, page caps, marginal saturation, or one run as completeness proof.
- Rewriting rejected artifacts or silently falling back to legacy stateless pagination.

## Open Gates

- Exact Phase C live probe artifacts do not yet exist. Deterministic implementation may proceed, but `freeze-discovery-policy` and all Phase D live commands must remain unusable until their strict predecessor evidence and command-level live/write review exist.
