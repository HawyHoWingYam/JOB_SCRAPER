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

## Live Phase C Checkpoint (2026-07-14)

- The deterministic Phase D implementation was committed as `965c4bcc` and
  `ab3d5148` before live evidence capture. Focused Phase A-D tests passed
  `494` cases and the complete backend suite passed `1350` cases from the
  committed implementation.
- Endpoint probe `02bd9816-6b54-4433-8598-2895d4dba541` is generic-valid and
  strict-valid. Its `recommend-search-list-v1` condition recorded three clean
  contract-verified pages, 30 distinct IDs, zero gaps/identity/conservation
  differences, and the expected bounded `page_cap`. The unverified browse
  envelope returned empty pages and remains ineligible.
- Partition probe `1943d7e6-2fc6-4f5d-946d-801085d10860` is generic-valid and
  strict-valid but rejected. Technical Writing (`118018`) returned nine
  filter-matching `resultList` IDs on page 1, then switched to a
  supplemental-only cursor chain. Across ten pages it produced 100 distinct
  IDs (9 result plus 91 supplemental), ten new IDs per page, `hasMore=true`,
  no terminal signal, and stopped at the frozen page cap.
- Both live probes used the SHA-bound saved-session state, noop staging, zero
  detail attempts, zero product writes, and identical start/end snapshot,
  inventory, and product-data hashes. Comparison and policy freeze were not
  run after the partition rejection.
- The live result disproves the planning assumption that a low-count leaf can
  prove whole-envelope exhaustion within ten pages. It does not prove that
  supplemental recommendations may be discarded, counted as category matches,
  or allowed to govern partition exhaustion. Phase D live execution remains
  gated on an explicit versioned supplemental-cohort contract amendment.

## Approved Dual-Cohort Decision (2026-07-14)

- `resultList` is the authoritative cohort for each filtered category or leaf
  partition. Supplemental recommendations must not be counted as matches for
  that partition and must not prevent the result cohort from proving its own
  endpoint-specific exhaustion.
- `suppleRcdList` remains required discovery evidence. It must be deduplicated
  into a separately versioned global recommendation cohort with its own cursor,
  terminal, stability, and contribution gates; it may not be silently dropped.
- The final stable reference denominator is eligible only when its exact
  result-partition union and any admitted global supplemental union are both
  hash-bound and accepted under their own contracts. An incomplete
  supplemental gate must remain visible rather than being represented as zero
  contribution.
- Historical Phase A-D classes, payloads, experiment names, hashes, and the two
  2026-07-14 live artifacts remain immutable. The dual-cohort amendment is
  additive and versioned.
- Once the result-partition contract passes its replacement Phase C gate,
  result-only Phase D runs may proceed as explicitly partial research while the
  supplemental global gate remains incomplete. Partial runs cannot be accepted,
  cannot freeze a stable denominator, and cannot authorize Phase E-H or
  production adoption.

## Replacement Dual-Cohort Live Checkpoint (2026-07-14)

- Replacement preflight reverified the Phase B parent, endpoint parent, and
  both baseline artifacts with generic plus strict replay. The saved-session
  bytes still matched the SHA-256 frozen by the earlier live parents, and every
  live command passed the current-database gate before runtime construction.
- Result-probe attempt `eb6fcd53-774e-41e8-9539-b4a81699208c` made three
  bounded listing requests and completed the Technical Writing condition, but
  artifact projection failed because the shared Phase D condition type
  re-derived a top-level partition from leaf category `118018`. It produced no
  artifact and was closed as a sanitized failed research run. The fix carries
  the exact requested partition ID across the runner-to-artifact boundary,
  verifies its category-code match, and leaves legacy candidate-level 31/3
  partition guards unchanged.
- Replacement result probe `67fbb753-430c-4ad2-b7c4-5fa3d4a013b0` is
  generic-valid, strict-valid, and accepted. Three logical/physical requests
  recorded nine Technical Writing result IDs, 21 separately preserved
  supplemental IDs, and two cursor-continuous result-empty confirmation pages
  with zero gap, identity, conservation, rollover, or unclassified failures.
  Only the nine result IDs were would-stage rows in noop mode.
- Frozen result policy `99829af2-a91a-46a8-beb1-0f5a215b64f9` is
  generic-valid and strict-valid with policy hash
  `181c8b29f7277b95cceff819ce747b2290f66207827f5e4eb68e957e917b1ace`.
  It binds `result-transition-confirmation-v1` and exactly two confirmation
  pages to the accepted result-probe parent.
- Supplemental runs `4f2c9ca4-f96a-4c55-b3b8-5c35688b8a14`,
  `b75ef983-8160-4f07-a14c-e2a032b8f13e`, and
  `e1e9d69a-0719-4bad-9e38-46d9e2a3e10c` are each generic-valid and
  strict-valid rejected evidence. In every run, the first frozen seed
  `112000` produced 100 result IDs and zero supplemental IDs across ten clean
  logical/physical requests, then stopped at the page cap. Fail-fast prefix
  semantics correctly prevented the later two seeds from being represented as
  observed.
- Every accepted/rejected replacement artifact used noop staging, zero detail
  attempts, zero product writes, and identical start/end snapshot, inventory,
  and product-data hashes. No supplemental comparison, complete dual-cohort
  candidate, Phase D census/fixed repeat, staging write, or downstream phase
  was run.
- The three-run rejection disproves the frozen v1 assumption that a broad
  top-level seed can reach the supplemental phase within ten pages. A future
  amendment must version supplemental-phase reachability separately from
  cross-seed stability; it may not widen this v1 budget, relabel result rows as
  supplemental, or reinterpret the rejected artifacts.

## Requirements

R1-R7 preserve the already committed v2 deterministic baseline and its exact
compatibility contracts. R8 owns the additive dual-cohort successor required
for all new live evidence after the 2026-07-14 rejection. Where the old v2 live
shape assumes one envelope cohort, it remains replayable historical behavior
but is not eligible to bypass R8 or produce the final denominator.

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

### R8. Versioned dual-cohort discovery

- The exact additive experiments are `result-partition-probe-v2`,
  `result-partition-policy-v1`, `supplemental-cohort-probe-v1`,
  `supplemental-cohort-stability-comparison-v1`,
  `dual-cohort-discovery-policy-candidate-v3`,
  `cursor-result-partial-census-v3`,
  `cursor-result-partial-fixed-repeat-v3`,
  `cursor-dual-cohort-full-census-v3`,
  `cursor-dual-cohort-fixed-repeat-v3`, and
  `cursor-dual-cohort-stability-comparison-v3`. Exact-name dispatch must fail
  unknown aliases or future versions closed.

- Add an explicit result-partition cohort policy that records both response
  cohorts but admits only canonical `resultList` IDs to that partition's union,
  staging, contribution, and exhaustion decision.
- Prove result-cohort exhaustion from replayable endpoint/cursor evidence. A
  `total` value, page cap, marginal saturation, or the mere presence of
  supplemental rows is insufficient by itself.
- Add a separately budgeted supplemental-cohort experiment that measures seed
  sensitivity, cursor continuity, terminal behavior, unique contribution, and
  cross-run stability before one global recommendation cohort can be admitted.
- Preserve the exact source page and cohort provenance for IDs that appear in
  both result and supplemental streams; global deduplication must not erase
  cohort membership evidence.
- A rejected or incomplete supplemental experiment is valid evidence but may
  not be converted into an empty accepted cohort or a complete stable
  denominator.
- Result-only Phase D artifacts must carry an exact partial cohort scope and
  the unresolved supplemental parent/gate state. Strict replay must reject any
  attempt to mark them accepted or consume them as complete comparison,
  denominator, Phase E-H, or production parents.
- After the supplemental cohort is accepted, the complete Phase D comparison
  must recompute the time-aligned result union, supplemental union, overlap,
  and combined stable denominator. It may not relabel an earlier result-only
  artifact as complete without a new exact parent projection and decision.

## Acceptance Criteria

### Deterministic implementation gate

- [x] A strict `discovery-policy-candidate-v2` contract and offline freeze command accept clean contract-verified bounded endpoint evidence while rejecting missing, rejected, non-cursor, malformed, mixed-parent, tampered, or capped retained-partition evidence.
- [x] `census-v2`, `repeat-fixed-v2`, and `compare-stability-v2` are isolated from legacy commands and fail closed on the wrong candidate/artifact version.
- [x] Fake-runtime tests prove condition-local cursor behavior, same-input retry, page-1 restart after browser loss, exact budgets, pre-staging validation, hard-stop prefixes, and zero detail/product writes.
- [x] Strict replay recomputes candidate, run, staging, zero-new-page, comparison, timing, holdout, and stable-denominator decisions and rejects rehashed semantic tampering.
- [x] Current Phase A-C focused tests and locally present historical artifacts still verify unchanged; production-default guards pass.
- [x] Phase C/D live commands fail before database/runtime construction without a valid explicit storage state, bind its exact path to every runtime, and export only its SHA-256 proof.

### Amended live Phase D evidence gate

- [ ] One immutable accepted additive dual-cohort Phase C policy candidate
      exists and passes generic plus strict verification; the historical v2
      candidate type is not relabeled or mutated.
- [ ] Three accepted complete dual-cohort census artifacts span at least two
      windows separated by six hours.
- [ ] Three accepted complete dual-cohort fixed-repeat artifacts cover
      `(118000, 112000, 127000)` within one short window.
- [ ] All six complete artifacts share one exact additive candidate hash, and
      Jobs/Companies/defaults remain unchanged.
- [ ] The additive strict comparison passes every Phase D gate and freezes one
      stable reference denominator artifact.
- [ ] The dual-cohort contract proves result-partition exhaustion independently
      and either accepts a hash-bound global supplemental cohort or keeps the
      final denominator and production promotion explicitly gated.
- [ ] Any result-only Phase D research artifact is explicitly partial and is
      rejected as a stable-comparison, downstream-phase, or production parent.

## Out of Scope

- Phase E/F IT labeling and planner ablation, Phase G detail canaries, Phase H recovery/soak, and Task 18 production adoption; they consume accepted Phase D evidence in later children.
- Treating `total`, gross rows, page caps, marginal saturation, or one run as completeness proof.
- Rewriting rejected artifacts or silently falling back to legacy stateless pagination.

## Remaining Evidence Gates

- One accepted result-partition policy now exists, but all three strict
  supplemental probes rejected before reaching the supplemental phase. No
  supplemental comparison or complete dual-cohort candidate exists, so all
  complete Phase D commands remain gated.
- The next live amendment must prove a versioned supplemental entry/seed
  strategy can reach and terminate the supplemental cohort within its own
  bounded contract before any cross-seed stability claim or candidate freeze.
- Result-only Phase D research may begin only after its own amended Phase C
  contract passes and exact commands are reviewed. It remains partial until the
  separately visible supplemental global gate passes.
- Phase D acceptance, stable-denominator freeze, Phase E-H, and production
  adoption remain gated on accepted evidence from both cohorts.
