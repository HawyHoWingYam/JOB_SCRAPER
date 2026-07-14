# OfferToday Phase D cursor-correct census implementation plan

## Authorization Boundary

- The user's request authorizes planning and deterministic implementation of Task 11 after this artifact review and `task.py start`.
- Phase C live probes, Phase D live requests, listing-staging writes, and long-window scheduling remain separate command-level gates because exact predecessor inputs do not yet exist.
- Work inline in the main Codex session. Preserve all unrelated changes and runtime artifacts.

## Deterministic Checkpoint (2026-07-13)

- Steps 1-7 are implemented and verified. The focused Phase A-D suite passed
  `494` tests; the complete backend suite passed `1350` tests; Ruff,
  compilation, historical generic/strict replay for 11 artifacts, and
  `git diff --check` passed.
- A 2026-07-14 live-gate audit corrected the policy-freeze boundary: the
  three-page endpoint probe may provide clean contract-verified `page_cap`
  evidence, while retained partition conditions remain responsible for
  terminal exhaustion and empty confirmation. The CLI regression now freezes
  successfully from that realistic split evidence.
- The same audit found that `saved-session` was frozen in Phase C/D evidence
  while the default runtime still opened a fresh headless context. Phase C and
  Phase D live commands now require and structurally validate `--auth-state`
  before database/runtime construction, SHA-bind it to every condition-local
  runtime, and record only `session_state_sha256` in provenance.
- Step 8 remains pending after a reviewed bounded Phase C attempt. Endpoint
  artifact `02bd9816-6b54-4433-8598-2895d4dba541` is strict-valid and contains
  eligible bounded search-contract evidence. Partition artifact
  `1943d7e6-2fc6-4f5d-946d-801085d10860` is strict-valid but rejected after the
  Technical Writing result cohort ended at nine IDs and a supplemental-only
  stream continued to the ten-page cap. No comparison, candidate freeze,
  Phase D request, staging write, or long-window schedule was executed.
- The next implementation checkpoint is a reviewed, versioned supplemental
  cohort amendment. Do not widen the ten-page cap, reinterpret `total`, or
  discard supplemental IDs merely to make the rejected probe pass.
- The user approved a dual-cohort model: `resultList` is partition-authoritative
  and `suppleRcdList` feeds a separately gated global recommendation cohort.
  Final completeness remains ineligible if the admitted supplemental union is
  unresolved or represented as an implicit empty set.
- The user approved result-only Phase D execution as explicitly partial
  research after the amended result contract passes. Partial artifacts must be
  rejected as stable-denominator, Phase E-H, or production parents until the
  supplemental global gate also passes.

## Additive Deterministic Checkpoint (2026-07-14)

- The exact ten dual-cohort experiments/commands are implemented with strict
  dispatch, pure replay, result-only partial guards, complete candidate/run
  types, and six-parent combined comparison. No historical v1/v2 payload or
  request-policy hash changed.
- Ruff and Python compilation pass for every touched source/test. The amended
  focused Phase A-D/compatibility suite passed `570` cases before the final
  fault-prefix additions; the complete backend suite then passed `1431`
  cases, including all new tests.
- All `20` locally present non-baseline historical artifacts pass generic plus
  strict replay, including the two live Phase C artifacts. Of `45` historical
  baseline directories, `29` pass current strict replay and `16` older schema
  baselines remain generic-valid but pre-existing strict-invalid; no baseline
  verifier behavior changed in this amendment.
- Quality review added regression guards for valid rejected CV values above
  `1`, baseline/no-write projection mismatch, rehashed six-parent run payloads,
  saved-session paths in provenance, and post-run snapshot/finalization fault
  artifacts.
- No replacement Phase C request, Phase D request, staging write, candidate
  freeze, or downstream live action was executed. The next gate is exact
  command and request-budget review.

## Replacement Live Checkpoint (2026-07-14)

- The first replacement attempt exposed a leaf-partition projection bug after
  three live requests. Run `eb6fcd53-774e-41e8-9539-b4a81699208c` was closed
  failed without an artifact. Exact partition identity now crosses the
  runner/artifact boundary and is validated against the requested category;
  the Technical Writing end-to-end CLI regression and 55 Phase D/dual-cohort
  pure/strict tests pass with Ruff and compilation checks.
- Result probe `67fbb753-430c-4ad2-b7c4-5fa3d4a013b0` and result policy
  `99829af2-a91a-46a8-beb1-0f5a215b64f9` are accepted, generic-valid, and
  strict-valid. The frozen result policy hash is
  `181c8b29f7277b95cceff819ce747b2290f66207827f5e4eb68e957e917b1ace`.
- Supplemental run indexes 1, 2, and 3 are strict-valid rejected artifacts:
  `4f2c9ca4-f96a-4c55-b3b8-5c35688b8a14`,
  `b75ef983-8160-4f07-a14c-e2a032b8f13e`, and
  `e1e9d69a-0719-4bad-9e38-46d9e2a3e10c`. Each stopped at the first seed's
  ten-page cap with 100 result IDs, zero supplemental IDs, ten logical
  requests, and ten physical attempts.
- All replacement artifacts preserve noop/no-detail/no-product-write and exact
  baseline hashes. Because all three supplemental parents rejected, the
  conditional comparison, complete candidate freeze, Phase D census/fixed
  repeats, and later phases were not run.
- Post-checkpoint verification passed `575` focused Phase A-D/dual-cohort
  tests and the complete backend suite passed `1431` tests. Ruff, Python
  compilation, scoped `git diff --check`, and generic plus strict replay for
  the 11 exact historical/live parent artifacts all passed.
- The next implementation step is a reviewed, versioned supplemental
  reachability amendment. Running the same v1 probe again or widening its
  budget cannot satisfy this gate.

## Ordered Checklist

### 1. Freeze compatibility and current evidence

- [x] Load the backend/shared Trellis specs and Phase 2.1 instructions before code edits.
- [x] Confirm every planned source/test path is clean relative to unrelated user changes.
- [x] Add golden guards for legacy candidate payloads/hashes, legacy command routing, existing strict replay, and current production defaults.
- [x] Strict-verify the locally present Phase B comparisons and historical v1 census/fixed/comparison artifacts without rewriting them.

Gate: old evidence and production behavior are captured before additive work.

### 2. Add the Phase C discovery-policy candidate

- [x] Add `DiscoveryPolicyCandidateV2` with exact scalar/list/hash validation and canonical serialization.
- [x] Implement pure candidate construction from strict Phase C comparison projections and checked-in endpoint/partition registries.
- [x] Enforce accepted retained evidence, cursor-capable endpoint policy, mandatory 31 top-level Phase D condition order, exact fixed cohort, terminal/budget rules, and deferred-issue provenance.
- [x] Add `discovery-policy-candidate-v2` artifact builder/validator/summary and strict replay.
- [x] Add offline `freeze-discovery-policy`; reject all invalid/rejected/mixed/tampered parents and produce no partial candidate.

Gate: a synthetic valid parent can freeze and replay; current real runtime inventory correctly cannot freeze because Phase C parents are absent.

### 3. Add pure Phase D evidence and comparison contracts

- [x] Create typed condition/run/page classification evidence for full census and fixed repeat.
- [x] Recompute cursor exhaustion, per-page marginals, result/supplement cohorts, rollovers, zero-new full pages, request budgets, and candidate/condition hashes.
- [x] Add exact three-plus-three comparison, six-hour census-window validation, one-hour fixed-window validation, Jaccard/CV/churn/cost metrics, holdout binding, and stable-reference construction.
- [x] Keep legacy `stability.py` outputs unchanged; reuse only stable pure helpers whose semantics match exactly.

Gate: pure tests cover pass/fail thresholds, timing edges, duplicate IDs, tampering, empty holdouts, and every zero-valued failure gate.

### 4. Add Phase D strict artifact replay

- [x] Create `phase_d_stage_gate.py` for the candidate, full census, fixed repeat, and comparison experiments.
- [x] Validate exact manifest/event/payload fields and recompute all hashes, parent projections, budgets, snapshots, classifications, and decisions.
- [x] Route exact experiment names through `verify_live_research_run()`; unknown versions fail closed.
- [x] Add rehashed semantic-tamper tests and secret-leak tests.

Gate: generic verification can pass a re-exported tampered artifact while Phase D strict replay rejects it.

### 5. Implement condition-local live service orchestration

- [x] Add `run_census_v2()` and `run_fixed_repeat_v2()` without changing legacy methods.
- [x] Build conditions only from the frozen candidate and endpoint/partition registries.
- [x] Enforce one condition-local runtime/cursor chain, same-input retry, page-1 restart after browser loss, completed-condition checkpoints, exact budgets, and hard-stop prefixes.
- [x] Support only the no-op sink or explicitly confirmed reconciled sink; reject arbitrary sinks.
- [x] Prove cursor/page validation precedes staging and no detail/product path is invoked.

Gate: fake-runtime/service tests pass for normal, retry, browser-loss, contract-failure, budget, and staging modes.

### 6. Add v2 CLI commands and artifacts

- [x] Add `census-v2`, `repeat-fixed-v2`, and `compare-stability-v2` parsers and dispatch.
- [x] Require explicit valid saved-session state for Phase C/D live commands, bind it to every runtime, and keep its path/contents out of artifacts.
- [x] Require exact candidate version, live confirmation, two matching baselines, current DB recheck, explicit run index, and separate staging-write confirmation.
- [x] Capture allowed staging reconciliation and forbidden Job/Company/product drift separately.
- [x] Export and immediately generic/strict verify each artifact; preserve exit codes `0/2/3/4/5`.
- [x] Keep comparison offline and prove it cannot construct database, browser, runtime, repository, or staging dependencies.

Gate: CLI tests cover all usage/evidence/hard-stop/accepted/rejected paths with injected fakes.

### 7. Deterministic quality gate

- [x] Run focused Phase D plus existing Phase A-C tests.
- [x] Run Ruff/compile checks on touched files.
- [x] Run historical artifact generic and strict replay.
- [x] Run the complete backend suite and `git diff --check` when focused checks pass.
- [x] Inspect the diff for migrations, API/frontend, Compose/env, production caller/default, runtime artifact, or unrelated worktree changes.

Gate: deterministic implementation is complete and safe to review for live execution.

### 8. Command-level Phase C/Phase D live gate

- [x] Present the exact Phase C endpoint/partition commands, IDs, page/attempt budgets, baselines, and no-write invariant for review.
- [x] Run the bounded Phase C endpoint and partition probes; preserve and stop on the strict-valid partition rejection.
- [x] Add additive typed result-partition and global-supplemental policy
      contracts without changing any existing artifact or request-policy hash.
- [x] Freeze the exact additive experiment/type names from `design.md`; reject
      aliases and unknown future versions closed in strict dispatch.
- [x] Add pure result-cohort terminal replay using explicit cursor/cohort phase
      evidence and confirmation; reject `total`, page-cap, or saturation-only
      completion.
- [x] Add a bounded offline-configured supplemental seed/overlap experiment,
      exact request budgets, strict artifact replay, and valid-rejection paths.
- [x] Extend candidate and Phase D evidence through new exact experiment
      versions that bind both cohort policy hashes and preserve dual cohort
      provenance through union/comparison.
- [x] Add a typed result-only partial Phase D artifact/decision whose strict
      loader rejects stable comparison, downstream-phase, and production use.
- [x] Add complete dual-cohort parent projection and comparison tests proving
      that accepted supplemental evidence creates a new decision rather than
      mutating an earlier partial artifact.
- [x] Run focused compatibility, semantic-tamper, no-write, full backend, and
      historical replay gates before presenting any replacement live command.
- [x] Review the amended supplemental cohort/terminal contract and exact live
      budget before any replacement Phase C live request.
- [x] Run and strict-verify one accepted Technical Writing result probe, then
      freeze and strict-verify its result-partition policy.
- [x] Run all three frozen supplemental probes and preserve their strict-valid
      page-cap rejections without comparison or candidate freeze.
- [ ] Design and review a versioned supplemental reachability successor that
      can enter the supplemental phase before measuring seed stability.
- [ ] Run accepted amended Phase C probes/comparison and freeze one strict discovery-policy candidate; stop on valid rejection.
- [ ] Present exact Phase D candidate hash, three census commands, three fixed-repeat commands, staging mode, request budgets, and non-blocking schedule for review.
- [ ] Execute/verify all six runs in their required windows without sleeping inside one blocking command.
- [ ] Run offline comparison; freeze the stable reference denominator only if every Phase D gate passes.

Gate: accepted Phase D evidence exists. Otherwise preserve the valid rejection and keep downstream live phases gated.

## Validation Commands

Focused commands will include the new modules plus current regression coverage:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_phase_d.py `
  backend/tests/test_offertoday_phase_d_stage_gate.py `
  backend/tests/test_offertoday_listing_contract.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_partition_research.py `
  backend/tests/test_offertoday_partition_stage_gate.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_standalone_crawl.py

python -m ruff check <touched Python files>
python -m py_compile <touched Python source files>
python -m pytest -q backend/tests
git diff --check
```

Every local historical artifact used as evidence must also pass:

```powershell
python backend/scripts/offertoday_research.py verify-artifact --artifact <artifact>
python backend/scripts/offertoday_research_census.py verify-run --artifact <artifact>
```

## Risk and Rollback Points

- Do not widen existing candidate or artifact schemas; add distinct types/experiments.
- Stop if a shared-path edit changes a legacy hash or strict replay result.
- Keep Phase D pure comparison logic out of the CLI and database service.
- Do not classify zero-new pages from `total`, page caps, or marginal saturation.
- Do not run a live command or staging write merely because its parser exists.
- Preserve failed/rejected prefixes and artifacts; never patch evidence to pass.

## Review Before Activation

- PRD/design/implementation artifacts contain no unresolved repository-answerable question.
- The task explicitly closes the missing Phase C policy-freeze contract without claiming absent Phase C live evidence.
- Deterministic implementation can start now; live/write execution remains separately gated by exact inputs.
