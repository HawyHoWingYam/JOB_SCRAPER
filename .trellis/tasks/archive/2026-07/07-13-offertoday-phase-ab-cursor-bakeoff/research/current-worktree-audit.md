# Current worktree audit

## Snapshot

- Audited on 2026-07-13 at `HEAD=507f85d5` on branch `codex/offertoday-it-coverage-20260702`.
- The repository had 65 pre-existing uncommitted status entries when the session began. Unrelated changes must remain untouched.
- Phase A/B-shaped work already existed in eight modified source files, three new source modules, four modified tracked test modules, and two new ignored test modules.
- The broad `backend/tests/*` ignore rule hides new test modules; intended new tests will require explicit force-add at commit time, but no staging/commit is authorized by this planning step.

## Verified Baseline

- Current focused Phase A/B command: `557 passed in 87.30s`.
- All 12 artifacts in the Plan 2 decision's primary artifact index exist locally.
- All 12 passed `offertoday_research.py verify-artifact` and `offertoday_research_census.py verify-run` under the current worktree.
- The current `git diff --check` is clean apart from line-ending warnings.

## Implemented Shape Worth Retaining

- `listing_contract.py` contains cursor, request policy, transport result, page result, and redacted page evidence types.
- The payload builder accepts explicit page size/cursor while retaining default `pageSize=50`.
- The runner carries a condition-local cursor, defers v2 staging until condition acceptance, and records separate result/supplemental ID cohorts.
- The runtime exposes typed listing transport and a generated browser-context hash without storing a cursor.
- The live service owns the three frozen Phase B lifecycle variants.
- `pagination_bakeoff.py` freezes five variants, three categories, order randomization, repeat summaries, comparison metrics, and thresholds.
- `pagination_stage_gate.py` adds exact v2 experiment dispatch while legacy artifacts still replay.
- The CLI exposes `pagination-bakeoff`, `compare-pagination`, and `freeze-discovery-candidate` skeletons.

## Confirmed Gaps Against Tasks 1-8

1. Direct cursor construction coerces a non-string `session_id`; v2 parsing silently converts malformed present `hasMore`/`total` values to `None` instead of failing exact validation.
2. V2 durable page evidence lacks each cohort's typed identity pairs and explicit response cursor-field presence.
3. Supplemental rows are checked for missing/invalid identity but do not participate in the same cross-row/cross-page encrypted-ID conflict analysis as result rows.
4. Browser-loss restart-from-page-1 and deduplication are not implemented in the runner/service path.
5. `restart-each-page` opens a new runtime for every physical attempt, so a transient retry changes browser context instead of preserving the logical page's context.
6. `run_pagination_bakeoff()` does not hard-stop on `cursor_contract_violation`.
7. Live CLI hard-stop/runtime exceptions do not currently export replayable partial-failure evidence.
8. The v2 strict verifier does not yet independently prove request-fingerprint stability, exact page/attempt sequence, failed-attempt cursor non-advancement, retry context stability, restart lifecycle cardinality, terminal-plus-empty-confirmation semantics, condition event payloads, or internal row/new/duplicate/overlap derivations.
9. Comparison/candidate replay does not enforce exact event shapes, and candidate freezing does not enforce that exactly one variant passed.
10. The bake-off test module covers only a subset of required individual rejection reasons and has no tie/order-independence coverage.
11. No dedicated tests currently exercise the three new CLI commands or the new pagination strict verifier's tamper cases.

## Implementation Order

1. Strengthen the typed contract and page-evidence schema with focused red tests.
2. Complete supplemental identity/conflict and cursor runner invariants, then add browser-loss/retry lifecycle behavior.
3. Correct service hard-stop/cleanup semantics.
4. Make strict replay independently recompute every derived invariant and add tampered artifact fixtures.
5. Remove duplicated comparison logic or route both in-memory and payload comparison through one shared decision engine.
6. Complete CLI success/rejection/partial-failure/offline tests and artifact export behavior.
7. Run focused, full-backend, production-default, legacy-artifact, and diff checks before any live review.
