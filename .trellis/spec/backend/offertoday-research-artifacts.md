# OfferToday Research Artifact Contracts

## Scenario: Verified parent artifacts and fail-closed experiment replay

### 1. Scope / Trigger

Use this contract when adding or consuming an OfferToday research artifact,
experiment name, baseline parent, comparison parent, or CLI command under
`backend/runtime/offertoday-research/`.

The trigger is cross-layer: a CLI exports filesystem evidence, a later command
loads that evidence as a parent, and the stage gate must reconstruct the
semantic result. A valid file hash alone does not prove that the experiment's
event sequence or decision is valid.

Runtime artifacts are ignored and uncommitted. Durable source code and tests
own the schema and replay rules.

### 2. Signatures

```text
python backend/scripts/offertoday_research.py baseline
python backend/scripts/offertoday_research.py verify-artifact --artifact <dir>
python backend/scripts/offertoday_research_census.py verify-run --artifact <dir>
```

```python
verify_research_artifact(artifact_dir: Path) -> ArtifactVerificationResult
verify_live_research_run(artifact_dir: Path) -> LiveRunVerification
load_baseline_artifact(artifact_dir: Path) -> BaselineArtifactEvidence
require_matching_baselines(first_dir: Path, second_dir: Path) -> MatchingBaselineGate
```

Every exact experiment name handled by `verify_live_research_run()` must route
to one semantic verifier. Unknown names and versions fail closed.

### 3. Contracts

All artifacts used as inputs must pass both layers:

1. `verify_research_artifact()` validates the manifest and recorded file
   hashes.
2. `verify_live_research_run()` validates the exact experiment schema and
   independently replays its semantic evidence.

A `foundation-baseline` artifact has:

- manifest metadata `experiment="foundation-baseline"`;
- manifest metadata `data_hash` equal to the snapshot `data_hash`;
- exactly one `research.baseline` event used by the baseline loader;
- typed snapshot counts with non-negative exact integers;
- lowercase SHA-256 snapshot and inventory hashes; and
- a manifest run ID preserved by `BaselineArtifactEvidence`.

Two live parents must have distinct run IDs and identical snapshot hash,
inventory hash, and frozen count evidence. The live command rechecks the
current database before starting its browser/runtime.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Missing or hash-mismatched artifact file | Generic verification fails; CLI exit `5` |
| Unknown experiment or version | Strict replay issue `unsupported_live_experiment`; exit `5` |
| Baseline metadata/event/snapshot contract invalid | Strict replay issue `invalid_foundation_baseline`; exit `5` |
| Baseline manifest run ID disagrees with loaded evidence | `baseline_run_id_mismatch`; exit `5` |
| Same baseline run supplied twice | Reject before browser startup |
| Snapshot, inventory, or frozen counts differ | Reject before browser startup |
| Current database differs from matching baselines | Reject before browser startup |
| Valid comparison rejects every candidate | Preserve artifact; exit `3`, not exit `5` |
| Auth/WAF/IP/cursor/identity/gap hard stop during live work | Preserve strict-replayable prefix; exit `4` |

Do not include exception messages containing paths, sessions, cookies, CSRF
tokens, authorization values, or raw cursor values in durable artifact fields.

### 5. Good / Base / Bad Cases

- **Good:** Two distinct `foundation-baseline` artifacts pass generic and
  strict replay, match each other, and match the current database. The live
  command may open the browser.
- **Base:** A comparison is structurally and semantically valid but selects no
  candidate. Keep it as rejected evidence and return exit `3`.
- **Bad:** `verify-artifact` passes for a baseline, but `verify-run` reports
  `unsupported_live_experiment`. The baseline is not eligible as a parent;
  add exact semantic routing and regression coverage before live execution.

### 6. Tests Required

For every new or changed experiment route, assert:

- the exact experiment name dispatches to the intended verifier;
- an unknown next version fails closed;
- one complete fixture passes generic plus strict replay;
- at least one semantic tamper passes file parsing but fails strict replay;
- parent reuse, mismatch, and current-database drift stop before live
  dependencies are created; and
- CLI exits distinguish accepted (`0`), valid rejected (`3`), hard stop (`4`),
  and invalid evidence (`5`).

Baseline routing is covered by
`test_verify_live_run_accepts_foundation_baseline` and
`test_verify_live_run_rejects_invalid_foundation_baseline`. Matching and drift
behavior is covered by the baseline tests in
`test_offertoday_research_stage_gate.py` and the pre-browser CLI tests.

### 7. Wrong vs Correct

#### Wrong

```python
if verify_research_artifact(baseline_dir).valid:
    start_browser()
```

This proves only file integrity. A semantically invalid or unsupported parent
can still enter the live chain.

#### Correct

```python
generic = verify_research_artifact(baseline_dir)
strict = verify_live_research_run(baseline_dir)
if not generic.valid or not strict.valid:
    raise ValueError("baseline evidence is not replayable")

gate = require_matching_baselines(first_dir, second_dir)
require_current_database(gate)
start_browser()
```

The exact helper used for the current-database comparison may vary by CLI, but
the ordering does not: generic verification, semantic replay, matching parent
gate, current-database gate, then live dependencies.

## Scenario: Phase C endpoint and partition research artifacts

### 1. Scope / Trigger

Use this contract when changing the research-only endpoint or partition
catalogs, probe commands, comparison command, or any of these exact artifact
experiments:

- `endpoint-contract-probe-v1`;
- `partition-probe-v1`; and
- `partition-comparison-v1`.

These experiments are opt-in research infrastructure. A deferred upstream issue
may allow later deterministic implementation to continue, but deferral is not
acceptance. The task that owns a future live run, product write, census, or
production adoption must authorize that action separately.

### 2. Signatures

```text
python backend/scripts/offertoday_research_census.py probe-endpoints \
  --phase-b-comparison-artifact <dir> \
  --endpoint-contract-id <id> --endpoint-contract-id <id> \
  --baseline-artifact <dir> --baseline-artifact <dir> \
  --auth-state <path> \
  --confirm-live-research

python backend/scripts/offertoday_research_census.py probe-partitions \
  --endpoint-probe-artifact <dir> \
  --endpoint-contract-id <id> \
  --partition-id <id> [--partition-id <id> ...] \
  --max-pages-per-condition <1..10> \
  --baseline-artifact <dir> --baseline-artifact <dir> \
  --auth-state <path> \
  --confirm-live-research

python backend/scripts/offertoday_research_census.py compare-partitions \
  --partition-probe-artifact <dir> [--partition-probe-artifact <dir> ...]
```

```python
build_phase_c_probe_artifact_payload(...) -> dict[str, Any]
validate_phase_c_probe_artifact_payload(payload) -> tuple[...]
build_partition_probe_parent_projection(...) -> tuple[...]
build_partition_comparison_artifact_payload(parents) -> dict[str, Any]
validate_partition_comparison_artifact_payload(payload) -> tuple[...]
verify_phase_c_artifact(artifact_dir: Path) -> PhaseCArtifactVerification
phase_c_artifact_reference(artifact_dir: Path) -> PhaseCArtifactReference
```

### 3. Contracts

- Every probe supplies an explicit endpoint contract. V1 accepts only omitted
  `rcdType`; it never inherits production `rcdType=7`.
- `recommend-search-list-v1` owns the known search cursor/terminal adapter.
  `recommend-list-envelope-v1` keeps cursor and terminal capability
  `unverified`; `hasMore` and `total` are diagnostic there.
- The immutable partition catalog contains 31 top-level and 431
  query-distinct leaf partitions. The 31 same-code aliases remain category
  evidence but never generate duplicate requests.
- A probe envelope owns exact `parent`, `baseline`, `execution`, `policy_hash`,
  `execution_hash`, and `no_write` projections. `no_write` requires identical
  pre/post snapshot, product-data, and inventory hashes, zero details, zero
  product writes, and `staging_mode="noop"`.
- Live-capable command ordering is fixed: explicit confirmation and plan
  validation, structural validation of an explicit Playwright storage-state
  file, generic plus strict parent replay, exactly two distinct matching
  baselines, current-database recheck, then service/runtime construction.
- The validated storage-state bytes are SHA-256 bound to every condition-local
  headless runtime and rechecked before each runtime construction. Provenance
  records only `session_mode="saved-session"` and `session_state_sha256`; the
  path, cookies, local-storage values, and state contents never enter evidence.
- Partition comparison parents must have distinct run and manifest identities
  and matching catalog, endpoint-contract, execution-policy, and baseline-state
  hashes. The comparison normalizes conditions into catalog order.
- Comparison recomputes unions, overlap, unique contribution, logical/physical
  cost, and the successful-request marginal curve from normalized job IDs.
  `total` and marginal saturation never waive terminal, empty-confirmation,
  gap, identity, or conservation gates.
- Phase C artifacts contain no candidate or selected production policy. Raw
  session IDs, cursor values, cookies, CSRF/authorization values, profile paths,
  and CDP endpoints are redacted or rejected.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Missing `--confirm-live-research`, `--auth-state`, or explicit probe input | Argparse/usage exit `2`; no dependency construction |
| Missing, unreadable, malformed, or changed storage state | Evidence exit `5`; no database/runtime construction and no path/content evidence |
| Invalid or unsupported parent artifact | Evidence exit `5`; no runtime construction |
| Baseline reuse/mismatch or current-database drift | Evidence exit `5`; no runtime construction |
| Valid probe/comparison with no accepted condition | Keep strict-valid artifact; exit `3` |
| Auth/WAF/IP/identity/contract hard stop | Keep a completed-condition prefix; exit `4` |
| Snapshot, inventory, staging-mode, detail, or product-write drift | Strict replay fails; exit `5` |
| Unknown next experiment version or missing/extra payload field | Fail closed; exit `5` |
| Duplicate/mismatched comparison parent | Reject before artifact export |
| `total` is large or the last-100 curve is saturated | Diagnostic only; cannot set `accepted=true` |

### 5. Good / Base / Bad Cases

- **Good:** Two strict-valid partition probes use the same contract, policy,
  catalog, baseline state, and SHA-bound saved-session runtime. Offline
  comparison recomputes a retained partition and exports a strict-valid report
  without constructing live dependencies.
- **Base:** Browse envelope probing reaches its page budget while cursor
  semantics remain unverified. Export the inconclusive strict-valid artifact
  and return exit `3`.
- **Bad:** A caller records `session_mode="saved-session"` while constructing a
  fresh headless runtime without the validated state, treats `data.total`,
  `hasMore`, page-cap completion, or a high marginal curve as proof of
  exhaustion, or feeds Phase C output to a candidate-freeze path.

### 6. Tests Required

- `test_offertoday_partition_research.py`: catalog counts/order/hashes, alias
  exclusion, exact budgets, 0.5% contribution threshold, hard gates, and
  diagnostic-only `total`/saturation.
- `test_offertoday_partition_stage_gate.py`: all three complete fixtures,
  unknown versions, missing/extra fields, rehashed semantic tampering, parent
  reuse/policy mismatch, no-write drift, event drift, and secret evidence.
- `test_offertoday_research_live_service.py`: endpoint separation, explicit
  partition order, budget ceilings, no-op staging, and prefix preservation.
- `test_offertoday_research_census_cli.py`: confirmation, parent/baseline/current
  DB gates before runtime, saved-session validation/runtime binding/redaction,
  strict export, exit codes, offline comparison, and no candidate output.
- Re-run existing Phase B ignored artifacts through both `verify-artifact` and
  `verify-run`; their hashes and rejected meaning must remain unchanged.

### 7. Wrong vs Correct

#### Wrong

```python
if response["data"]["total"] > 0 or response["data"]["hasMore"] is False:
    accepted = True
    freeze_candidate()
```

This converts diagnostics into exhaustion proof and crosses the research-only
boundary.

#### Correct

```python
saved_session = require_saved_session_state(args.auth_state)
parent = phase_c_artifact_reference(parent_dir)  # generic + strict replay
require_current_database(require_matching_baselines(first, second))
execution = service.run_partition_probe(
    plan=frozen_plan,
    staging_sink=noop_sink,
    runtime_factory=bind_saved_session_runtime_factory(
        OfferTodayBrowserRuntime,
        saved_session,
    ),
)
payload = build_phase_c_probe_artifact_payload(
    execution=execution,
    parent=parent,
    baseline=baseline,
    no_write=no_write,
)
```

The comparison command later consumes only strict-valid parent projections and
produces a report; it never constructs a discovery candidate.

## Scenario: Phase D cursor-correct census artifacts

### 1. Scope / Trigger

Use this contract when changing the Phase C policy freeze, cursor-correct
census/fixed-repeat commands, Phase D staging evidence, stability comparison,
or any of these exact experiments:

- `discovery-policy-candidate-v2`;
- `cursor-full-census-v2`;
- `cursor-fixed-repeat-v2`; and
- `cursor-census-stability-comparison-v2`.

These paths are additive. They must not widen the historical
`discovery-candidate-v2`, `full-census`, `fixed-condition-repeat`, or
`census-stability-comparison` payloads or hashes.

### 2. Signatures

```text
python backend/scripts/offertoday_research_census.py freeze-discovery-policy \
  --phase-b-comparison-artifact <dir> \
  --endpoint-probe-artifact <dir> \
  --partition-probe-artifact <dir> [--partition-probe-artifact <dir> ...] \
  --partition-comparison-artifact <dir>

python backend/scripts/offertoday_research_census.py census-v2 \
  --candidate-artifact <dir> \
  --baseline-artifact <dir> --baseline-artifact <dir> \
  --run-index <1|2|3> --window-id <id> \
  --auth-state <path> \
  --staging-mode <noop|reconciled> --confirm-live-research \
  [--confirm-staging-writes]

python backend/scripts/offertoday_research_census.py repeat-fixed-v2 \
  --candidate-artifact <dir> \
  --baseline-artifact <dir> --baseline-artifact <dir> \
  --run-index <1|2|3> --window-id <id> \
  --auth-state <path> \
  --staging-mode <noop|reconciled> --confirm-live-research \
  [--confirm-staging-writes]

python backend/scripts/offertoday_research_census.py compare-stability-v2 \
  --census-artifact <dir> --census-artifact <dir> --census-artifact <dir> \
  --fixed-repeat-artifact <dir> --fixed-repeat-artifact <dir> \
  --fixed-repeat-artifact <dir> [--active-holdout-id <source-job-id> ...]
```

```python
build_discovery_policy_candidate_v2(...) -> DiscoveryPolicyCandidateV2
build_phase_d_run_evidence(...) -> PhaseDRunEvidence
phase_d_run_artifact_payload(...) -> dict[str, Any]
build_phase_d_comparison_artifact_payload(...) -> dict[str, Any]
verify_phase_d_artifact(artifact_dir: Path) -> PhaseDArtifactVerification
```

### 3. Contracts

- Policy freeze verifies the exact chain
  `valid-rejected Phase B comparison -> endpoint probe -> supplied partition
  probes -> accepted partition comparison`. The supplied partition-probe
  projection set must equal the comparison parent set; matching only an
  endpoint ID is insufficient.
- The selected endpoint condition proves the registered cursor/terminal
  contract through non-empty page evidence with zero per-page contract errors,
  gaps, identity conflicts/issues, or conservation difference. Because the
  endpoint probe is deliberately capped at three pages on category `118000`, a
  clean contract-verified `page_cap` observation is eligible for endpoint
  selection; it is not exhaustion evidence.
- Every retained partition condition separately proves natural exhaustion,
  terminal state, empty confirmation, contribution, and zero gaps, identity
  conflicts/issues, or conservation difference. Deferred Phase B issues `4`
  and `5` remain provenance, not acceptance.
- `census-v2` freezes all 31 top-level categories. `repeat-fixed-v2` freezes
  exactly `(118000, 112000, 127000)`. Both use page size `10`, condition-local
  saved-session runtimes, `500` logical pages per condition, and at most `3`
  attempts per page. Request-policy `repeat_index` remains `1`; artifact
  `run_index` records runs `1..3`.
- Live ordering is fixed: explicit CLI confirmation and staging-mode checks,
  structural validation of an explicit Playwright storage-state file, strict
  candidate replay, exactly two distinct matching baselines, current-DB
  recheck, then observation service, staging sink, service, and browser/runtime
  construction.
- The validated storage-state bytes are SHA-256 bound to every condition-local
  headless runtime and rechecked before each runtime construction. Provenance
  records only `session_mode="saved-session"` and `session_state_sha256`; the
  state path and contents are forbidden from durable evidence.
- Reconciled staging requires `--confirm-staging-writes`, `skip_existing=True`,
  canonical-ID deduplication, and exact discovered-to-published/preexisting/
  created/deferred conservation. No-op staging records would-stage rows without
  mutating product data.
- A partial completed-condition prefix remains a valid strict artifact but is
  never an accepted run. Durable run evidence records a sanitized
  `failure_reason`; raw exception messages, sessions, cursors, cookies, tokens,
  profiles, and CDP paths are forbidden.
- End-product snapshot and activity-event reads have independent completeness
  evidence. A missing end snapshot is represented by `null` end hashes plus
  `end_snapshot_captured=false`; missing activity evidence records
  `activity_evidence_captured=false`. Neither state may be accepted.
- Offline comparison accepts only three already-accepted census parents and
  three already-accepted fixed-repeat parents with distinct runs/manifests and
  one candidate artifact. It constructs no DB, repository, staging, service,
  or runtime dependency.
- Census capture span must be at least `21,600` seconds across at least two
  window IDs. Fixed repeats must share one window ID and span at most `3,600`
  seconds. The stable reference is IDs seen in at least two censuses plus the
  separately hash-bound active holdout IDs; the full union remains diagnostic.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Missing live confirmation or `--auth-state`, wrong baseline count, or reconciled mode without write confirmation | Argparse/usage exit `2`; no dependency construction |
| Missing, unreadable, malformed, or changed storage state | Evidence exit `5`; no database/runtime construction and no path/content evidence |
| Wrong candidate/parent version, broken lineage, baseline drift, unaccepted comparison parent, or strict replay failure | Evidence exit `5`; no later dependency construction |
| Selected endpoint has clean page evidence and stops at the frozen three-page cap; every retained partition is exhausted | Candidate is eligible to freeze; the endpoint cap supplies contract evidence only |
| Any retained partition stops at a page cap or lacks terminal/empty confirmation | Evidence exit `5`; do not freeze a candidate |
| Complete strict run that misses a non-hard acceptance gate | Preserve artifact; exit `3` |
| Auth/WAF/IP/cursor/session/endpoint/page/budget hard stop or sanitized unexpected live failure | Preserve completed prefix; exit `4` |
| Product drift, missing end snapshot/activity evidence, or observation finalization failure | Preserve sanitized strict prefix; exit `5` |
| All live run gates pass | Accepted artifact; exit `0` |
| All six accepted parents pass timing, Jaccard `>= 0.95`, CV `<= 0.05`, and zero-failure gates | Stable reference frozen; exit `0` |
| Six valid parents fail a comparison decision gate | Preserve rejected comparison; exit `3` |

### 5. Good / Base / Bad Cases

- **Good:** The selected endpoint reaches its three-page cap with a verified
  contract and clean page evidence, while every retained partition separately
  reaches cursor-confirmed exhaustion. The frozen strict v2 candidate then
  drives all census conditions through the SHA-bound saved-session runtime,
  and reconciled rows partition exactly by canonical ID. The artifact replays
  and returns `0`.
- **Base:** A structurally valid run completes but conservation or another
  non-hard gate rejects it. Preserve the strict artifact and return `3`; do not
  feed it to `compare-stability-v2`.
- **Bad:** A caller records `saved-session` without binding the validated
  storage state, supplies a strict partition comparison but swaps in a probe
  from another endpoint-probe parent, requires the bounded endpoint probe to
  exhaust category `118000`, treats a retained-partition page cap as
  exhaustion, compares an unaccepted run, or substitutes start hashes after an
  end-snapshot failure. Fail closed rather than manufacturing session,
  lineage, exhaustion, or unchanged-product evidence.

### 6. Tests Required

- `test_offertoday_phase_d.py`: locked candidate controls, 31/3 condition
  order, retry/cursor replay, zero-new-page classification, snapshot/activity
  completeness, timing, Jaccard/CV, holdouts, and stable-reference replay.
- `test_offertoday_phase_d_stage_gate.py`: all four experiment routes,
  complete fixtures, unknown versions, secret evidence, rehashed semantic
  tampering, and six-parent projection replay.
- `test_offertoday_research_live_service.py`: condition-local runtime, same
  request/cursor retry, page-1 restart after browser loss, prefix preservation,
  sink allowlist, and pre-staging validation.
- `test_offertoday_research_census_cli.py`: exact lineage equality, wrong
  versions, confirmation/baseline/current-DB ordering, no-op and reconciled
  staging, saved-session validation/runtime binding/redaction, exits
  `0/2/3/4/5`, missing snapshot/finalization prefix artifacts, offline-only
  comparison, a contract-verified capped endpoint paired with exhausted
  retained partitions, accepted-parent enforcement, and immediate strict
  verification after export.
- Re-run current Phase A-C focused tests and every locally used historical
  artifact through both generic and strict verification.

### 7. Wrong vs Correct

#### Wrong

```python
comparison = phase_c_artifact_reference(comparison_dir)
candidate = build_discovery_policy_candidate_v2(
    comparison_payload=load_json(comparison_dir),
    endpoint_contract_id=user_supplied_endpoint,
)
start_browser()
```

This trusts a top-level comparison without proving its concrete probe lineage,
permits a policy override, and constructs a live dependency before baselines
and the current DB are checked.

#### Correct

```python
saved_session = require_saved_session_state(args.auth_state)
phase_b = strict_phase_b_reference(phase_b_dir)
endpoint = strict_phase_c_reference(endpoint_dir)
probes = [strict_phase_c_reference(path) for path in probe_dirs]
comparison = strict_phase_c_reference(comparison_dir)
require_exact_phase_d_lineage(phase_b, endpoint, probes, comparison)
require_clean_endpoint_contract_observation(endpoint)  # page_cap is eligible
require_exhausted_retained_conditions(comparison)  # page_cap is ineligible
candidate = freeze_from_comparison_projection(comparison)

gate = require_matching_baselines(first_baseline, second_baseline)
require_current_database(gate)
start_condition_local_runtime(
    candidate,
    runtime_factory=bind_saved_session_runtime_factory(
        OfferTodayBrowserRuntime,
        saved_session,
    ),
)
```

The freeze owns the exact parent set and the live path crosses each evidence
gate before constructing runtime or write-capable dependencies.

## Scenario: Additive result and supplemental cohort research

### 1. Scope / Trigger

Use this contract when changing the post-rejection dual-cohort successor to
Phase C/D. It applies to result-partition exhaustion, global supplemental
stability, result-only partial runs, complete dual-cohort runs, and their
offline policy/comparison commands. Historical v1/v2 experiment names,
payloads, and hashes remain immutable.

### 2. Signatures

```text
probe-result-partitions-v2       -> result-partition-probe-v2
freeze-result-partition-policy-v1 -> result-partition-policy-v1
probe-supplemental-cohort-v1     -> supplemental-cohort-probe-v1
compare-supplemental-cohort-v1   -> supplemental-cohort-stability-comparison-v1
freeze-dual-cohort-policy-v3     -> dual-cohort-discovery-policy-candidate-v3

census-result-partial-v3         -> cursor-result-partial-census-v3
repeat-fixed-result-partial-v3   -> cursor-result-partial-fixed-repeat-v3
census-dual-cohort-v3            -> cursor-dual-cohort-full-census-v3
repeat-fixed-dual-cohort-v3      -> cursor-dual-cohort-fixed-repeat-v3
compare-stability-dual-cohort-v3 -> cursor-dual-cohort-stability-comparison-v3
```

Every live command requires `--confirm-live-research`, a structurally valid
`--auth-state`, and exactly two distinct matching baseline artifacts. Phase D
commands additionally require `--run-index`, `--window-id`, and an explicit
`--staging-mode`. Reconciled staging requires
`--confirm-staging-writes`.

### 3. Contracts

- `resultList` is the partition-authoritative cohort. The runner stages only
  result rows and uses `result-transition-confirmation-v1`: two successful,
  cursor-continuous result-empty pages in one restart chain. `total`, page
  caps, and marginal saturation never prove result exhaustion.
- Exact partition identity is first-class evidence. A probe may target an
  official leaf partition, so runner-to-artifact projection must carry the
  requested partition ID and validate that its registered category code equals
  the listing condition category. It must not reconstruct partition identity
  with `top_level_partition(category_id)`. Historical v2 Phase D runs remain
  top-level-only through their exact candidate partition projection.
- `suppleRcdList` is preserved as a separate global cohort. One probe uses
  exactly three frozen catalog seeds, ten logical pages per seed, and three
  attempts per page. One comparison consumes exactly three strict probe
  parents with run indexes `1,2,3`.
- Reaching the supplemental phase and measuring supplemental stability are
  separate gates. If a seed still returns result rows at its page cap, preserve
  the strict rejected prefix and do not claim that later seeds, an empty
  supplemental cohort, or cross-seed stability were observed. A successor
  seed/entry strategy requires a new version and bounded reachability evidence;
  it cannot widen or reinterpret the rejected v1 contract.
- Probe wrappers bind the exact strict parent, two-baseline projection, and
  `PhaseCNoWriteEvidence`. The no-write start snapshot and inventory hashes
  must equal the baseline projection before the wrapper is valid.
- A complete v3 candidate binds both policy hashes and the strict result
  policy, supplemental comparison, and valid-rejected Phase B artifact hashes.
  A rejected supplemental comparison is valid evidence but cannot freeze a
  candidate.
- Result-only Phase D artifacts permanently encode `accepted=false`,
  `stable_reference_frozen=false`, and `downstream_eligible=false`. Complete
  loaders and comparisons reject them even when their result research prefix
  is complete.
- Complete comparison consumes exactly three accepted census and three
  accepted fixed-repeat parents. Parent `payload_hash` is the canonical hash
  of the embedded typed run projection, so strict replay can recompute it;
  `manifest_hash` preserves the immutable filesystem parent identity.
- Census windows span at least `21,600` seconds and at least two window IDs.
  Fixed repeats share one window and span at most `3,600` seconds. Result,
  supplemental, and combined fixed-cohort Jaccard must each be `>= 0.95`;
  combined unique-count CV must be `<= 0.05`.
- CV is a finite nonnegative number, not a `0..1` ratio. Values above `1` are
  valid rejected evidence and must still export and strict-replay.
- Saved-session provenance records only `session_mode` and
  `session_state_sha256`. `auth_state_path`, `storage_state_path`, cookies,
  raw sessions/cursors, tokens, profiles, and CDP endpoints are forbidden in
  durable evidence.
- Post-run snapshot, activity-read, or observation-finalization failures must
  preserve a sanitized strict-replayable completed-condition prefix and exit
  as evidence failure. Raw exception text never enters the artifact.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Missing confirmation/auth, wrong baseline count, or invalid staging confirmation | Usage exit `2`; no DB/runtime construction |
| Malformed/changed saved-session state or invalid parent | Evidence exit `5`; no DB/runtime construction |
| Probe no-write start state differs from its baseline | Strict replay fails; artifact is ineligible |
| Result completion depends only on `total`, cap, or saturation | Valid rejection or hard stop; never freeze result policy |
| Leaf request is projected as its top-level parent | Evidence failure; preserve the exact leaf ID across the boundary |
| First supplemental seed reaches page cap before supplemental rows | Strict-valid rejected prefix; no comparison or seed-stability claim |
| Supplemental comparison has other than three strict distinct parents | Usage/evidence failure; no candidate |
| Supplemental comparison is strict-valid but rejected | Preserve comparison; exit `3`; candidate freeze exits `5` |
| Partial run supplied to a complete loader/comparison | Evidence exit `5`; no dependency construction |
| Parent run projection hash differs after rehashing | Strict replay fails |
| Snapshot/activity/finalization failure after live work | Export sanitized strict prefix; exit `5` |
| Complete run hard-stops with replayable product evidence | Preserve strict prefix; exit `4` |
| Complete comparison misses a stability threshold, including CV `> 1` | Preserve strict-valid rejected comparison; exit `3` |
| Every complete Phase D gate passes | Freeze combined stable denominator; exit `0` |

### 5. Good / Base / Bad Cases

- **Good:** Three strict supplemental probes agree across seeds/runs and add a
  nonempty stable unique cohort. A complete candidate drives six accepted
  Phase D runs; the offline six-parent comparison recomputes both cohort unions
  and freezes the combined denominator.
- **Base:** Result research completes while supplemental evidence is missing or
  rejected. Preserve an explicit partial artifact and continue no downstream
  phase from it.
- **Bad:** Relabel a partial artifact as complete, treat an absent supplemental
  cohort as an accepted empty set, trust a self-rehashed parent projection, or
  serialize the saved-session path into provenance.

### 6. Tests Required

- `test_offertoday_listing_runner.py`: legacy default terminal behavior,
  two-page result confirmation, cursor continuity, restart reset, and no
  supplemental staging under the result policy.
- `test_offertoday_dual_cohort.py`: pure terminal replay, frozen budgets,
  three-run supplemental gates, candidate hashes, partial guards, complete
  timing/Jaccard/CV decisions, and valid rejection when CV exceeds one.
- `test_offertoday_dual_cohort_stage_gate.py`: every exact route, baseline to
  no-write binding, semantic tampering, parent run-projection hash replay,
  forbidden provenance paths, partial/complete separation, and six-parent
  replay.
- `test_offertoday_research_live_service.py`: result/supplemental routing,
  condition-local runtimes, exact condition order, prefix preservation, and
  no-op versus reconciled sink allowlists.
- `test_offertoday_research_census_cli.py`: every parser/dispatch route,
  pre-dependency auth/baseline guards, exact three supplemental parents,
  rejected candidate freeze, partial-parent rejection, saved-session SHA-only
  provenance, offline dependency isolation, post-run fault artifacts, and
  complete six-parent comparison. The result-probe path must use a real leaf
  partition fixture and assert that the exact partition ID and category survive
  request, artifact export, and strict replay.

### 7. Wrong vs Correct

#### Wrong

```python
if page.total == 9 or page_cap_reached:
    result_exhausted = True
candidate = freeze_candidate(result_policy, rejected_supplemental_as_empty=True)
```

This turns diagnostics into terminal proof and hides an unresolved cohort.

#### Correct

```python
terminal = evaluate_result_cohort_terminal(condition.pages)
if not terminal.result_exhausted:
    preserve_valid_rejection()

supplemental = compare_supplemental_cohort_probes_v1(strict_three_parents)
if not supplemental.decision.accepted:
    preserve_partial_scope_and_stop_candidate_freeze()

candidate = build_dual_cohort_discovery_candidate_v3(
    result_policy=result_policy,
    supplemental_comparison_payload=supplemental_payload,
    result_policy_artifact_hash=result_parent_hash,
    supplemental_comparison_artifact_hash=supplemental_parent_hash,
    phase_b_comparison_artifact_hash=phase_b_parent_hash,
)
```

The two cohorts remain separately replayable until the complete comparison
explicitly combines them.
