# OfferToday Phase C research infrastructure

## Goal

Implement the deterministic, research-only infrastructure for Phase C Tasks 9-10 without running live probes, freezing a discovery candidate, writing product data, or changing production behavior. The result must make endpoint and partition research replayable and auditable while keeping unresolved GitHub Issues #4 and #5 visible but non-blocking for subsequent task sequencing.

## Background

- Phase B produced valid-but-rejected evidence and selected no discovery candidate. GitHub [Issue #4](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/4) tracks unstable repeated-run result sets, and [Issue #5](https://github.com/HawyHoWingYam/JOB_SCRAPER/issues/5) tracks the inability to prove cursor exhaustion within the frozen 10-page budget.
- The user explicitly deferred both issues on 2026-07-13. They remain unresolved known risks, but they no longer block creation, planning, or implementation of later OfferToday tasks. Deferral is not acceptance and must not rewrite immutable Phase B evidence.
- The original implementation plan gates Phase C on an accepted Phase B candidate. This child is an explicit sequencing amendment for deterministic infrastructure only; each later task still owns its live, write, and adoption authorization.
- The current parser at `backend/app/sources/offertoday/listing_contract.py:529` assumes one `resultList` / `suppleRcdList` / cursor schema, and `backend/app/sources/offertoday/listing_runner.py:881` invokes it without an endpoint-specific adapter. Search and browse are therefore routed through the same response contract today.
- The two checked-in real-page fixtures confirm a common row envelope for `/recommend/search/list` and `/recommend/list`, but the browse fixture contains no cursor fields. Browse cursor and terminal semantics are unverified and must not inherit search semantics.
- `backend/scripts/offertoday_endpoint_probe.py:1` is an ad hoc total-comparison diagnostic. It launches a fresh headless browser, has no baseline/no-write gate, emits no immutable artifact, and treats `total` as its main signal; it is not acceptable Phase C evidence.
- `backend/app/scraper/offertoday/category_registry.py:39` currently records only 31 L1 categories while `backend/app/sources/offertoday/search_space.py:171` separately hard-codes the IT descendants.
- The official filter snapshot committed at `ed03f114fb8bc73eeb11139d82325a7944802701` contains 31 L1 categories and 462 L2 nodes in both English and Traditional Chinese. Thirty-one L2 nodes are same-code `All ...` aliases of their parents, leaving 431 query-distinct leaf codes. The snapshot's deleted `.debug/` worktree paths must not be restored.
- Existing generic artifact verification and strict replay route through `verify_research_artifact()` and `verify_live_research_run()`; unknown experiment versions already fail closed.

## Requirements

### R1. Deferred issues and phase semantics

- Treat Issues #4 and #5 as unresolved, explicitly deferred, and non-blocking for later task creation, planning, and implementation.
- Preserve every failed Phase B metric and artifact meaning. No report or code path may imply that either issue passed.
- Keep the current child no-live. Later live requests, product writes, or production adoption require the explicit scope and review gate of the task that owns them.

### R2. Endpoint-specific contracts

- Represent `/wapi/geek/recommend/search/list` and `/wapi/geek/recommend/list` with separate immutable contract IDs, versions, request rules, response adapters, cursor capabilities, and terminal rules.
- Require an explicit endpoint contract for every new Phase C probe. Reject contract/URL, contract/condition, request/response, and cross-endpoint mixing before rows reach any staging sink.
- Keep `rcdType` omitted in the initial Phase C probe catalog. Additional exact-integer values require a versioned, evidence-backed contract amendment; booleans, floats, strings, and silent defaults are invalid.
- Mark the current browse cursor capability as `unverified`. Do not copy search cursor fields, empty-confirmation behavior, or terminal semantics into the browse adapter.
- Preserve the default legacy parser and every Phase A/B artifact hash and replay meaning when no Phase C contract is explicitly supplied.

### R3. Official category and partition catalogs

- Normalize the historical official snapshot into immutable registry nodes using only `code`, `name`, `parent_code`, `level`, and `children`.
- Preserve all 31 L1 and 462 L2 official nodes in source order, including the 31 same-code `All ...` aliases.
- Generate 31 top-level partitions and 431 query-distinct leaf partitions. Same-code aliases remain catalog evidence but must not produce duplicate requests.
- Give the category catalog and each partition catalog an explicit schema version and canonical SHA-256 hash; reject invalid levels, parent links, duplicate query partitions, empty names, non-exact integer codes, or order drift.
- Derive the existing IT descendant code set from the official registry without changing its order or production behavior.
- Do not add date/publish-time, language, or location partitions in this child. Those require a later bounded contract artifact proving support.

### R4. Research-only command surface

- Add `probe-endpoints`, `probe-partitions`, and offline `compare-partitions` commands under `backend/scripts/offertoday_research_census.py`.
- Make every live-capable probe require an explicit research confirmation, exactly two distinct matching baselines, a current-database recheck before runtime creation, a frozen input plan, and an exact request budget.
- Require explicit endpoint contract IDs and explicit partition IDs. `probe-partitions` must not silently expand to all 462 query shapes.
- Use `ResearchNoopListingStagingSink`; record would-stage counts but perform zero staging, Job, Company, or other product-data writes.
- Permit valid inconclusive or rejected probe/comparison artifacts. Page-cap, unresolved-gap, unverified-contract, and instability outcomes remain evidence instead of being converted to acceptance.
- Do not add `freeze-discovery-policy`, select a discovery candidate, or feed Phase C comparison output into the existing Phase B `freeze-discovery-candidate` command.

### R5. Partition comparison

- Compare only generic-verified and strict-replayed parent artifacts with matching catalog, endpoint-contract, policy, and baseline-state hashes and distinct run/manifest identities.
- Recompute exact distinct-ID unions, intersections, per-partition unique contribution, overlap, request cost, and the last-100-successful-request marginal curve from normalized evidence.
- Treat `data.total` only as drift diagnostics; never use it as a denominator, stop condition, contribution value, or acceptance signal.
- Mark a partition as numerically retainable only when it contributes at least `0.5%` of the active reference union. A high-value exception must come from a versioned code-reviewed override with a nonblank rationale; the initial override catalog is empty.
- Treat marginal saturation as an efficiency metric only. It cannot replace cursor-confirmed terminal state, empty confirmation, zero gaps/conflicts, or zero conservation difference.
- Produce a comparison decision/report but no `DiscoveryCandidateV2` and no selected/frozen policy.

### R6. Artifact and strict-replay contracts

- Add exact experiment routes for endpoint probe, partition probe, and partition comparison artifacts. Unknown next versions must fail closed.
- Store contract/catalog/policy hashes, exact ordered inputs, budgets, parent hashes, baseline hashes, no-write evidence, outcomes, and derived metrics in immutable secret-safe artifacts.
- Never persist raw session IDs, cursor values, cookies, CSRF tokens, authorization values, profile paths, or CDP endpoints. Hash/redact continuity evidence using the existing conventions.
- Require generic hash verification plus independent semantic replay for every new artifact and every parent consumed by comparison.
- Strict replay must reconstruct decisions from evidence and reject semantically tampered metrics even when the artifact has been re-exported with internally consistent file hashes.

### R7. Compatibility and production guards

- Preserve current production payload defaults (`pageSize=50`, `rcdType=7`, no cursor fields), listing-condition order, endpoint selection, standalone-crawl runner policy, Compose/environment configuration, and staging behavior.
- Keep existing v1/v2 fixtures, experiment names, canonical hashes, and strict verifiers unchanged.
- Leave the legacy ad hoc endpoint probe outside the authoritative evidence path; new commands must not import or call it.
- Preserve all unrelated dirty-worktree changes and do not restore the deleted `.debug/` files used only as historical source evidence.

## Acceptance Criteria

- [ ] [R1] Parent and child task records describe Issues #4/#5 as unresolved and deferred, never passed, and later task sequencing no longer depends on closing them.
- [ ] [R2] Search and browse have distinct contract IDs and adapters; cross-endpoint fixtures, URLs, cursor fields, or terminal rules fail before staging.
- [ ] [R2] Search's known cursor schema remains replayable while browse cursor capability remains explicitly `unverified` until a later live artifact establishes a new version.
- [ ] [R3] Catalog tests prove exactly 31 L1 nodes, 462 L2 nodes, 31 same-code aliases, 431 query-distinct leaves, stable source order, valid parent links, and stable canonical hashes.
- [ ] [R3] Partition generation produces exactly 31 top-level plus 431 leaf partitions with no duplicate request identity, and the existing ordered IT code tuple is unchanged.
- [ ] [R4] `probe-endpoints`, `probe-partitions`, and `compare-partitions` parse and dispatch through research-only code; no `freeze-discovery-policy` command is added.
- [ ] [R4] Probe tests prove baseline and current-database gates run before runtime creation, budgets cannot be exceeded, explicit input selection is required, and hard stops preserve replayable prefixes.
- [ ] [R4][R7] Every probe path uses a no-op staging sink and pre/post snapshots prove zero staging, Job, Company, or product-data changes.
- [ ] [R5] Comparison independently recomputes union, overlap, contribution, cost, and marginal metrics; `total` and saturation cannot make a partition accepted.
- [ ] [R5] A valid inconclusive/rejected comparison remains strict-valid and returns the established non-acceptance exit code without selecting a candidate.
- [ ] [R6] Complete endpoint, partition, and comparison fixtures pass generic verification plus strict replay; rehashed semantic tampering and unknown versions fail strict replay.
- [ ] [R6] Secret-leak tests cover raw cursor/session values and all existing forbidden credential patterns.
- [ ] [R7] Production-default guard tests prove unchanged payload, search-space, standalone-crawl, and configuration behavior; existing Phase B artifacts still strict-replay unchanged.
- [ ] No real OfferToday request, Phase D census, staging write, product write, candidate freeze, or production-default change occurs during this child.
- [ ] Focused and full backend deterministic suites, Ruff, `py_compile`, and `git diff --check` pass.

## Out of Scope

- Resolving, closing, or weakening the acceptance criteria of GitHub Issues #4 or #5.
- Running any new live OfferToday request during this child.
- Selecting or freezing a Phase C discovery candidate or policy.
- Running Phase D or any later live phase.
- Adding proven browse cursor semantics without live evidence.
- Adding date/publish-time, language, location, keyword, or detail partitions.
- Writing staging or product data.
- Modifying production defaults, Compose/environment settings, or adoption configuration.
- Restoring or committing runtime artifacts or the deleted `.debug/` capture files.
