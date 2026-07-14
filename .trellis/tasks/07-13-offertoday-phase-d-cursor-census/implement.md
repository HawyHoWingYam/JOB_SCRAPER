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
- Step 8 remains pending. No Phase C or Phase D live request, staging write, or
  long-window schedule was executed because no accepted Phase C predecessor
  artifact exists and the command-level live gate has not been reviewed.

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

- [ ] Present the exact Phase C endpoint/partition commands, IDs, page/attempt budgets, baselines, and no-write invariant for review.
- [ ] Run accepted Phase C probes/comparison and freeze one strict discovery-policy candidate; stop on valid rejection.
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
