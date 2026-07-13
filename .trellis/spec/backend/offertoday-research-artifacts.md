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
  --confirm-live-research

python backend/scripts/offertoday_research_census.py probe-partitions \
  --endpoint-probe-artifact <dir> \
  --endpoint-contract-id <id> \
  --partition-id <id> [--partition-id <id> ...] \
  --max-pages-per-condition <1..10> \
  --baseline-artifact <dir> --baseline-artifact <dir> \
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
  validation, generic plus strict parent replay, exactly two distinct matching
  baselines, current-database recheck, then service/runtime construction.
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
| Missing `--confirm-live-research` or explicit probe input | Argparse/usage exit `2`; no dependency construction |
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
  catalog, and baseline state. Offline comparison recomputes a retained
  partition and exports a strict-valid report without constructing live
  dependencies.
- **Base:** Browse envelope probing reaches its page budget while cursor
  semantics remain unverified. Export the inconclusive strict-valid artifact
  and return exit `3`.
- **Bad:** A caller treats `data.total`, `hasMore`, page-cap completion, or a
  high marginal curve as proof of exhaustion, or feeds Phase C output to a
  candidate-freeze path.

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
  DB gates before runtime, strict export, exit codes, offline comparison, and no
  candidate output.
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
parent = phase_c_artifact_reference(parent_dir)  # generic + strict replay
require_current_database(require_matching_baselines(first, second))
execution = service.run_partition_probe(plan=frozen_plan, staging_sink=noop_sink)
payload = build_phase_c_probe_artifact_payload(
    execution=execution,
    parent=parent,
    baseline=baseline,
    no_write=no_write,
)
```

The comparison command later consumes only strict-valid parent projections and
produces a report; it never constructs a discovery candidate.
