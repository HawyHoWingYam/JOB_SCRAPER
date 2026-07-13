# OfferToday completeness and stability design

## Source Design

The complete technical design is authoritative in Sections 4-5 of `docs/specs/2026-07-13-offertoday-completeness-and-stability-implementation-plan.md` and Phases A-H of the research specification. This task record captures the cross-child boundaries and compatibility rules.

## Boundaries

- `listing_contract.py` owns immutable request/cursor/page-result/evidence types and exact validation.
- `constants.py` constructs fresh payloads while preserving current production defaults until adoption.
- `listing_runner.py` owns condition-local cursor transitions, retries, stop semantics, cohort identity analysis, and pre-staging failure behavior.
- `offertoday_browser_runtime.py` owns authenticated transport and a non-sensitive browser-context identity, but no cursor state.
- Research services own browser lifecycles, bounded orchestration, no-op versus reconciled staging, and phase budgets.
- Research modules compute decisions from replayed evidence; strict verifiers independently recompute all accepted metrics.
- CLI commands enforce baseline, parent-artifact, budget, offline/live, and exit-code boundaries.

## Data Flow

`frozen condition + request policy + prior validated cursor -> fresh request payload -> typed transport result -> validated page result -> identity/conservation analysis -> durable redacted observation -> condition boundary -> replayed artifact summary -> strict verifier -> gated decision`.

Rows never reach a staging sink before response-contract, identity, gap, and conservation checks succeed. Raw session IDs, cookies, CSRF values, authorization data, profile paths, and CDP endpoints never enter durable evidence.

## Compatibility

- V1 `CensusCandidate`, experiment names, canonical hashes, fixture interpretation, and strict verifiers remain unchanged.
- V2 uses distinct experiment names, `candidate_version=2`, canonical payloads, hashes, and fail-closed dispatch.
- Production callers retain current stateless defaults until the final adoption child.

## Operational Safety

- Each live command requires two distinct matching baselines and a current-database recheck before browser startup.
- Phase B and C are no-product-write; Phase B also uses the no-op listing staging sink.
- Cursor/session violations, auth/WAF/IP blocks, identity errors, gaps, conservation differences, leaks, and budget overruns hard-stop the run.
- Durable checkpoints occur only at completed condition boundaries; browser loss restarts the condition from page 1 and deduplicates IDs.

## Rollout and Rollback

Each phase produces immutable evidence and an explicit accepted/rejected decision. A user-deferred issue remains visible but does not block later task creation, planning, or deterministic implementation; it is never rewritten as acceptance. Live execution and writes are authorized by the task that owns them. Final adoption retains a documented rollback to the previous production policy without deleting artifacts or rewriting crawl history.
