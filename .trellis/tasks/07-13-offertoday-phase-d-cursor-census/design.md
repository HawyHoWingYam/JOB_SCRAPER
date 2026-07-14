# OfferToday Phase D cursor-correct census design

## Architecture

Keep Phase D versioned and additive. The legacy `CensusCandidate`, `DiscoveryCandidateV2`, `census`, `repeat-fixed`, `compare`, and their strict verifiers remain frozen. New Phase D code uses four explicit experiment schemas:

1. `discovery-policy-candidate-v2` — offline Phase C policy freeze;
2. `cursor-full-census-v2` — one full 31-category run;
3. `cursor-fixed-repeat-v2` — one three-category fixed repeat; and
4. `cursor-census-stability-comparison-v2` — offline six-run decision plus stable reference denominator.

Use narrowly scoped modules rather than widening legacy payload decoders:

- `live_contracts.py` adds the separately named `DiscoveryPolicyCandidateV2` only.
- A new `phase_d.py` owns typed run evidence, zero-new-page classification, stable-denominator logic, and pure comparison.
- A new `phase_d_stage_gate.py` owns artifact schemas and strict replay.
- `stage_gate.py` performs exact experiment-name dispatch and fails unknown next versions closed.
- `OfferTodayResearchLiveService` adds v2 orchestration methods while legacy methods retain their signatures.
- `offertoday_research_census.py` owns CLI gates, database snapshots, artifact export, and exit codes.

## Candidate Composition

`DiscoveryPolicyCandidateV2` is a composition, not a mutation of the Phase B candidate class. Its canonical payload freezes:

- schema/candidate version and candidate hash;
- strict parent references and manifest hashes for Phase B lineage and Phase C comparison;
- endpoint contract ID/hash, adapter version, URL identity, verified cursor capability, and omitted/evidence-backed `rcdType`;
- request policy payload/hash, terminal policy, retry/pacing/session controls, and safety budgets;
- category catalog and partition catalog hashes;
- exact 31 top-level Phase D partition payloads in catalog order;
- retained Phase C partition IDs/evidence hashes separately from the mandatory top-level Phase D conditions;
- fixed-repeat category projection `(118000, 112000, 127000)`; and
- explicit unresolved/deferred issue provenance.

The freeze command reconstructs every value from strict parent payloads and checked-in registries. CLI arguments may select an input artifact but cannot override candidate controls.

## Live Data Flow

`explicit live/write confirmation + structurally valid saved-session state + strict candidate + two matching baselines + current DB recheck -> SHA-bound condition-local managed runtime -> cursor-correct runner -> validated page evidence -> optional reconciled listing staging -> completed-condition checkpoint -> immutable artifact -> generic verification -> strict replay`.

The CLI validates the Playwright storage-state JSON before database or runtime
construction, binds the resolved path to the runtime factory, and rechecks the
validated byte hash at every condition-local construction. Only
`session_mode="saved-session"` and `session_state_sha256` cross into provenance;
the path and state contents do not cross the artifact boundary.

The service iterates frozen conditions. Each condition gets a fresh managed runtime and one request policy bound to the frozen endpoint contract. On browser loss the runner/transport restarts the affected condition from page 1 and increments a restart index; IDs are deduplicated across the restarted prefix. A process restart resumes only after the last completed condition boundary.

## Staging and Product Invariants

No-op staging is used by deterministic tests and dry runs. Reconciled staging is permitted only with an explicit write flag and uses `skip_existing=True`. The artifact records rows seen/created/skipped, exact created/preexisting/published/deferred ID sets, and conservation equations.

Snapshots distinguish allowed listing-staging changes from forbidden Job/Company/product changes. Any Job or Company hash drift, detail attempt, publication transition, staging amplification, or conservation mismatch hard-stops and rejects the run.

## Zero-New Full-Page Classification

The pure Phase D layer recomputes page marginal IDs from ordered result and supplemental cohorts. A full effective row-set with zero new canonical IDs is accepted only when replayable evidence shows:

- the page belongs to the frozen cursor chain and its cursor transition advances;
- result and supplemental cohorts are preserved separately;
- the condition later reaches cursor-confirmed natural exhaustion without gaps/rollover; and
- the page is deterministically classified as a repeated recommendation/supplement window under a versioned rule.

All other full zero-new pages remain unclassified and fail the run. Classification never changes the ID union or substitutes for terminal exhaustion.

## Offline Comparison

The comparison loader generically and strictly verifies all six parents, reconstructs typed run evidence, and enforces distinct run/manifest IDs plus one candidate hash. It derives timing from provenance capture timestamps rather than CLI claims.

The stable reference set is `IDs with census frequency >= 2 UNION independently confirmed active holdout IDs`. Its canonical ID list/hash, the diagnostic full union, exact churn cohorts, gate values, and every parent projection are embedded in the comparison artifact. The verifier recomputes them independently.

## Compatibility and Rollback

All new behavior is reachable only through exact new CLI commands and experiment names. Production callers never construct a Phase D candidate. Rollback removes new dispatch routes without changing old artifacts, crawl history, schema, or defaults. Live artifacts are preserved even when rejected.
