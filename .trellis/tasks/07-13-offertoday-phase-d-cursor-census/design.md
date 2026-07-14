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

## Live Rejection and Required Cohort Amendment

The 2026-07-14 Phase C evidence proves that the search endpoint has two
different discovery cohorts under one cursor chain:

```text
filtered resultList -> result exhaustion -> supplemental-only recommendations
```

For Technical Writing, the filtered cohort ended with nine results on page 1,
while `suppleType=1` and incrementing `supplePage` continued producing ten new
supplemental IDs per page through the ten-page cap. Treating the full envelope
as one category partition therefore makes category exhaustion depend on a
recommendation stream that is not demonstrably category-scoped. Treating the
first result count or `total` as exhaustion would violate the existing strict
terminal rules.

The user approved the first boundary: result rows remain
partition-authoritative while supplemental rows form one separately enumerated
global discovery cohort. Keeping supplemental rows inside every category was
rejected because the live stream was not demonstrably category-scoped or
bounded. Dropping supplemental rows was rejected because their unique active-ID
contribution remains unmeasured. Existing artifacts remain immutable and
strict-valid regardless of the additive amendment.

## Dual-Cohort Architecture

The amended data flow is:

```text
response envelope
  |-- resultList ------> result-partition evidence -> partition union
  `-- suppleRcdList ---> supplemental evidence -----> global recommendation union

accepted partition union + accepted global recommendation union
                         |
                         v
             stable reference denominator
```

The runner continues to parse, identity-resolve, conserve, and record both
cohorts on every page. A result-partition policy admits only result IDs to that
partition's staging and contribution set. Its terminal adapter must prove the
transition from filtered results into a supplemental-only phase with
replayable cursor/cohort evidence and an explicit confirmation rule; it cannot
trust `total` or a page cap alone.

A separate supplemental experiment owns seed selection, cross-seed overlap,
cursor/terminal evidence, and global deduplication. Until bounded evidence
proves that one seed-independent global stream exists, no production candidate
may collapse several personalized or query-conditioned recommendation streams
into one cohort.

Versioning is additive. Existing Phase C v1 probes and
`discovery-policy-candidate-v2` retain their exact payloads and replay. New
result-partition, supplemental, comparison, and candidate experiment versions
own the dual-cohort policy hashes. Legacy callers use the unchanged envelope
policy by default.

## Frozen Additive Contract Names

The amendment uses the following exact experiment and type names. They are
new contracts; none aliases or widens a historical v1/v2 payload:

| Purpose | Experiment | Typed owner |
| --- | --- | --- |
| Bounded result-cohort Phase C evidence | `result-partition-probe-v2` | `ResultPartitionProbeExecutionV2` |
| Frozen result terminal/admission policy | `result-partition-policy-v1` | `ResultPartitionPolicyV1` |
| One bounded three-seed supplemental run | `supplemental-cohort-probe-v1` | `SupplementalCohortProbeExecutionV1` |
| Three-run seed/terminal/stability decision | `supplemental-cohort-stability-comparison-v1` | `SupplementalCohortStabilityComparisonV1` |
| Complete additive discovery candidate | `dual-cohort-discovery-policy-candidate-v3` | `DualCohortDiscoveryPolicyCandidateV3` |
| Result-only partial full census | `cursor-result-partial-census-v3` | `ResultPartialPhaseDRunV3` |
| Result-only partial fixed repeat | `cursor-result-partial-fixed-repeat-v3` | `ResultPartialPhaseDRunV3` |
| Complete dual-cohort full census | `cursor-dual-cohort-full-census-v3` | `DualCohortPhaseDRunV3` |
| Complete dual-cohort fixed repeat | `cursor-dual-cohort-fixed-repeat-v3` | `DualCohortPhaseDRunV3` |
| Complete stable-denominator decision | `cursor-dual-cohort-stability-comparison-v3` | `DualCohortPhaseDStabilityComparisonV3` |

`result-transition-confirmation-v1` is the exact runner terminal-policy ID.
It requires a cursor-continuous transition followed by two successful
result-empty confirmation pages in the same restart chain. It never reads
`total`, page-cap status, or marginal saturation. The first confirmation may
carry supplemental rows; the second must prove the cursor continued from the
first. A natural empty-envelope terminal is still recorded independently.

The supplemental probe freezes three distinct catalog-ordered seed partitions,
ten logical pages per seed, and three attempts per page. One artifact measures
within-run seed sensitivity; the comparison requires exactly three distinct
runs and recomputes cross-seed plus cross-run overlap. Empty, capped, or
non-terminal cohorts are valid rejected evidence and cannot become a frozen
empty policy.

## Second Live Rejection: Supplemental Reachability

All three frozen supplemental v1 runs stopped on the first catalog seed,
category `112000`. Each cursor chain returned ten full pages containing 100
distinct result IDs and no supplemental IDs. The run then hit its ten-page
safety cap, preserved one strict completed-condition prefix, and did not claim
that the unstarted `118000` or `127000` seeds were observed.

This is a reachability rejection, not a stability measurement. The v1 design
cannot answer whether supplemental streams are seed-independent because its
first broad result cohort does not reach the supplemental phase within the
frozen budget. Repeating the same bounded contract three times confirms the
failure mode but does not turn the missing two seeds into an empty cohort.

A successor must separate two gates:

1. prove that an exact versioned seed/entry projection reaches the
   supplemental phase under replayable cursor continuity; and
2. only then measure supplemental terminal behavior, contribution, cross-seed
   overlap, and cross-run stability.

The successor may use a separately evidenced low-count seed or an exact
result-exhaustion cursor projection, but that choice needs its own reviewed
contract and bounded calibration. It must not mutate v1, increase the v1 page
cap, skip result pages without evidence, or classify result IDs as global
supplemental IDs.

## Bug Analysis: Leaf Partition Identity Lost During Artifact Projection

### 1. Root Cause Category

- **Category:** B/D/E — cross-layer contract, test coverage gap, and implicit
  assumption.
- **Specific cause:** the additive CLI and service accepted arbitrary official
  leaf partition IDs, but `PhaseDConditionEvidence` reconstructed identity with
  `top_level_partition(category_id)`. The request correctly targeted leaf
  `118018`; the artifact layer erased that exact identity and failed after live
  execution.

### 2. Why Fixes Failed

1. Existing fake-runtime tests used only top-level `118000`, so every local
   layer appeared compatible while the reviewed Technical Writing command was
   untested end to end.
2. Passing an explicit partition ID into the projection helper fixed the
   surface call, but the shared condition dataclass still enforced top-level
   identity. Both boundary owners had to use exact registry lookup plus a
   category-code consistency check.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Carry exact partition ID through runner-to-artifact projection; never reconstruct it from category code | Done |
| P0 | Runtime validation | Require the official partition's category code to equal the listing condition category | Done |
| P0 | Test coverage | Run the CLI result-probe fixture with the exact Technical Writing leaf and assert request plus artifact identity | Done |
| P1 | Compatibility | Keep legacy v2 candidate-level exact 31/3 partition projections as the historical top-level guard | Done |
| P1 | Experiment design | Calibrate supplemental reachability before freezing a multi-seed stability contract | Pending successor design |

### 4. Systematic Expansion

- **Similar issues:** any additive path converting `category_id` back to a
  partition ID can erase leaf/query identity; exact partition IDs must be
  treated as first-class evidence.
- **Design improvement:** separate cohort reachability from cohort stability so
  a broad result prefix cannot prevent the experiment from stating what it did
  and did not measure.
- **Process improvement:** every reviewed live command using a non-default
  partition must appear literally in one end-to-end CLI fixture before the
  request budget is authorized.

### 5. Knowledge Capture

- [x] Add exact-partition and supplemental-reachability contracts to the
      backend OfferToday research artifact spec.
- [x] Add the leaf CLI regression and preserve legacy candidate guards.
- [x] Record the failed attempt, accepted result policy, and three strict-valid
      supplemental rejections in task artifacts.
- [ ] Review and version a successor supplemental reachability contract before
      any new live request.

## Partial Research Sequencing

The user approved result-only Phase D execution in parallel with unresolved
supplemental research, but only as a typed partial evidence class. The partial
artifact records the exact result policy, every result/supplement page cohort,
and the unresolved supplemental gate projection. Its decision is never
`accepted`; it cannot enter the stable-comparison loader or any Phase E-H or
production parent resolver.

Once a global supplemental policy is accepted, complete dual-cohort runs use
new exact experiment versions and parent projections. A complete comparison
recomputes result-only IDs, supplemental-only IDs, overlap, churn, timing, and
the combined denominator. It never mutates or upgrades an older partial
artifact in place.

The complete candidate binds `result_partition_policy_hash` and
`supplemental_cohort_policy_hash` plus the strict parent artifact hashes. A
result-only partial candidate projection binds the accepted result policy and
the unresolved supplemental gate reference, but is deliberately not a
`DualCohortDiscoveryPolicyCandidateV3`. This type separation is the primary
downstream guard: complete comparison and later-phase loaders accept only the
complete candidate and complete run experiments.

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
