# OfferToday Phase C research infrastructure implementation plan

## Authorization boundary

- This plan is for review only until `task.py start` is explicitly approved.
- Phase 2 is inline: the main Codex session implements and checks directly; no implement/check sub-agents are dispatched.
- Implementation and deterministic tests are authorized only after review. Real `probe-endpoints`, `probe-partitions`, Phase D, staging writes, candidate freezing, and production-default changes remain prohibited in this child.
- Preserve all unrelated dirty-worktree changes, including the current deletions under `.debug/`.

## Ordered implementation checklist

### 1. Freeze compatibility guards first

- [ ] Load `trellis-before-dev` and the backend OfferToday artifact spec before editing code.
- [ ] Reconfirm that every planned backend source/test path is clean in the current worktree.
- [ ] Add or strengthen golden tests for current production defaults before changing shared code:
  - payload defaults are `pageSize=50`, `rcdType=7`, and no cursor fields;
  - default listing/search-space ordering and endpoint semantics are unchanged;
  - standalone crawl does not supply a Phase C request policy;
  - existing Phase B experiment names/hashes/replay routing are unchanged.
- [ ] Run the guard tests RED/GREEN independently so later refactors cannot silently move production.

Review gate: production behavior is captured by tests without changing implementation.

### 2. Normalize the official category hierarchy

- [ ] Expand `OfferTodayCategory` registry data from the historical official snapshot at commit `ed03f114fb8bc73eeb11139d82325a7944802701`; do not restore the deleted capture files.
- [ ] Preserve the existing flat public API and L1 ordering while adding recursive catalog helpers, source/version metadata, and canonical hashing.
- [ ] Validate exact integer fields, levels, parent ownership, nonblank names, source order, same-code aliases, and duplicate query identities.
- [ ] Derive `OFFERTODAY_IT_CATEGORY_CODES` from the hierarchy and prove its existing 23-value order remains unchanged.
- [ ] Add catalog/partition tests for 31 L1, 462 L2, 31 aliases, 431 query-distinct leaves, and canonical hash stability.

Review gate: all existing search-space/calibration tests pass, and no production query shape changes.

### 3. Add endpoint-specific contract adapters

- [ ] Add immutable endpoint contract descriptors and canonical hashes in `listing_contract.py`.
- [ ] Keep the existing parser as the compatibility path; add explicit search and browse adapter dispatch for Phase C only.
- [ ] Mark browse cursor/terminal capability `unverified`; support bounded envelope observation without claiming search cursor semantics.
- [ ] Add optional contract identity to research request policy with conditional canonical serialization so legacy IDs remain unchanged.
- [ ] Make the runner reject endpoint/contract/URL/request/response mixing before staging when an explicit contract is present.
- [ ] Add fixture and unit coverage for exact scalar validation, omitted `rcdType`, wrong endpoint, cross-adapter payloads, response URL mismatch, unsupported browse cursor, and legacy compatibility.

Review gate: listing contract/runner tests pass, and locally available Phase B artifacts still strict-replay unchanged.

### 4. Build pure partition research contracts

- [ ] Create `backend/app/sources/offertoday/research/partition_research.py`.
- [ ] Implement strict dataclasses and canonical serializers for endpoint plans, partition definitions, probe executions, parent projections, comparisons, and decisions.
- [ ] Generate top-level and leaf partition catalogs from the registry; exclude same-code aliases from request partitions.
- [ ] Implement exact plan-derived budgets, deterministic ordering, distinct-ID set metrics, contribution ratio `0.005`, overlap/cost metrics, and last-100 marginal curves.
- [ ] Keep the v1 high-value override catalog empty but validate the typed override/rationale mechanism.
- [ ] Ensure `total` is diagnostic-only and saturation cannot set terminal/acceptance fields.
- [ ] Add `backend/tests/test_offertoday_partition_research.py` with good/base/bad cases and canonical-hash golden values.

Review gate: pure tests cover accepted, rejected, inconclusive, duplicate, mismatched-parent, short-curve, and 100-request curve cases without database/runtime imports.

### 5. Add Phase C semantic replay

- [ ] Create `backend/app/sources/offertoday/research/partition_stage_gate.py` for the three new experiment schemas.
- [ ] Route exact experiment names through `verify_live_research_run()` and fail unknown next versions closed.
- [ ] Reuse typed page/cursor evidence decoders and shared artifact verification; do not copy raw payload casts into CLI code.
- [ ] Independently recompute plan/budget hashes, parent projections, no-write evidence, union/overlap/contribution/cost/marginal metrics, and decisions.
- [ ] Add `backend/tests/test_offertoday_partition_stage_gate.py` covering complete fixtures, unknown versions, missing/extra fields, rehashed semantic tampering, parent mismatch/reuse, event mismatch, and cursor/session secret leaks.

Review gate: every new fixture passes generic plus strict replay, and all semantic tamper cases pass generic verification but fail strict replay.

### 6. Implement service orchestration with no-op staging

- [ ] Add `run_endpoint_probe()` and `run_partition_probe()` to `OfferTodayResearchLiveService`; pass frozen plans instead of deriving defaults inside the service.
- [ ] Enforce condition order, explicit endpoint contracts, plan-derived stop/retry policies, budgets, hard-stop behavior, and no-op staging.
- [ ] Preserve strict-replayable completed-condition prefixes on hard stop and never checkpoint mid-condition.
- [ ] Extend live-service tests with fake runtimes/sinks proving endpoint separation, explicit partition selection, budget ceilings, no staging, no detail, and no product writes.

Review gate: service tests use only fakes and do not start Playwright, Docker, or a real database.

### 7. Implement CLI and artifact export

- [ ] Add parsers and explicit dispatch for `probe-endpoints`, `probe-partitions`, and `compare-partitions`.
- [ ] Require `--confirm-live-research`, exact two-baseline gates, current-database recheck, strict-valid parents, explicit contract/partition inputs, and exact plan-derived budgets before constructing a runtime.
- [ ] Export `endpoint-contract-probe-v1`, `partition-probe-v1`, and `partition-comparison-v1` artifacts with canonical projections and immediate generic/strict verification.
- [ ] Keep `compare-partitions` offline; inject forbidden constructors in tests to prove it touches no live dependency.
- [ ] Preserve exit codes `0/2/3/4/5` according to accepted, usage, valid rejected/inconclusive, hard-stop, and invalid-evidence outcomes.
- [ ] Do not add `freeze-discovery-policy`; do not widen or invoke `freeze-discovery-candidate`.
- [ ] Extend CLI tests for parser validation, baseline reuse/mismatch/drift, parent rejection-as-valid-provenance, artifact export, strict replay, no-write snapshots, offline comparison, and no candidate output.

Review gate: all CLI paths are deterministic under injected fakes, and no test creates a real artifact under `backend/runtime/offertoday-research/`.

### 8. Final compatibility and no-write audit

- [ ] Add a focused Phase C guard module if existing tests cannot express all production-default invariants cleanly.
- [ ] Assert pre/post staging, Job, Company, inventory, and product-data hashes are identical for every probe outcome, including hard stops.
- [ ] Assert Phase C experiment output contains no candidate hash, selected policy, or candidate-frozen event.
- [ ] Assert the legacy ad hoc endpoint probe is not imported by the new CLI/service path.
- [ ] Re-run strict replay against the locally available Phase B repeat, comparison, and recomputation artifacts without modifying them.
- [ ] Inspect the final diff for accidental Compose/environment, production caller, `.debug/`, or runtime-artifact changes.

Review gate: requirement-by-requirement evidence maps to every PRD acceptance criterion.

## Validation commands

Run from `C:\Work\JOB_SCRAPER` without any live probe command:

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_listing_contract.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_search_space.py `
  backend/tests/test_offertoday_partition_research.py `
  backend/tests/test_offertoday_partition_stage_gate.py `
  backend/tests/test_offertoday_pagination_bakeoff.py `
  backend/tests/test_offertoday_pagination_stage_gate.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_standalone_crawl.py

python -m ruff check `
  backend/app/scraper/offertoday/category_registry.py `
  backend/app/sources/offertoday/listing_contract.py `
  backend/app/sources/offertoday/listing_runner.py `
  backend/app/sources/offertoday/search_space.py `
  backend/app/sources/offertoday/research/partition_research.py `
  backend/app/sources/offertoday/research/partition_stage_gate.py `
  backend/app/services/offertoday_research_live_service.py `
  backend/scripts/offertoday_research_census.py `
  backend/tests/test_offertoday_partition_research.py `
  backend/tests/test_offertoday_partition_stage_gate.py

python -m py_compile `
  backend/app/scraper/offertoday/category_registry.py `
  backend/app/sources/offertoday/listing_contract.py `
  backend/app/sources/offertoday/listing_runner.py `
  backend/app/sources/offertoday/search_space.py `
  backend/app/sources/offertoday/research/partition_research.py `
  backend/app/sources/offertoday/research/partition_stage_gate.py `
  backend/app/services/offertoday_research_live_service.py `
  backend/scripts/offertoday_research_census.py

python -m pytest -q backend/tests
git diff --check
```

Offline replay regression, only if the listed ignored artifacts remain present:

```powershell
$artifacts = @(
  'backend/runtime/offertoday-research/99876757-fce0-401f-adc8-e6fd3ae9aabc',
  'backend/runtime/offertoday-research/d301b397-bf2c-4424-a20b-0935f675f9cb',
  'backend/runtime/offertoday-research/7a35b33e-580d-4aae-85d7-8a1ac9fb2b9b',
  'backend/runtime/offertoday-research/5f9d2ae3-4933-4e71-baf7-6ac541c13142'
)
foreach ($artifact in $artifacts) {
  python backend/scripts/offertoday_research.py verify-artifact --artifact $artifact
  python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
}
```

Forbidden in this child:

```text
probe-endpoints
probe-partitions
pagination-bakeoff
census
repeat-fixed
freeze-discovery-candidate
freeze-discovery-policy
docker compose ... (for live OfferToday execution)
```

## Risk and rollback points

- The highest compatibility risk is adding endpoint identity to shared contracts. Conditional serialization must leave all legacy hashes unchanged; stop if a Phase B replay drifts.
- The official catalog is large. Generate it mechanically from the historical snapshot, then review counts/hashes; do not hand-edit hundreds of entries or restore user-deleted debug files.
- Do not duplicate page-evidence validation across modules. Reuse typed decoders or extract a narrowly shared helper with regression coverage.
- Keep CLI orchestration separate from pure comparison logic so offline commands cannot construct live dependencies.
- If any production-default guard changes unexpectedly, roll back the shared-path edit and move the behavior behind an explicit Phase C-only adapter.
- No database migration or data rollback is expected because this child performs no writes.

## Review before activation

Before `python ./.trellis/scripts/task.py start`, confirm:

- PRD, design, and implementation plan match the user's deferred-issue policy;
- no open product or risk decision remains;
- the child remains deterministic/no-live and contains no candidate freeze;
- the exact planned code paths are still clean relative to unrelated worktree changes; and
- the user explicitly approves implementation.
