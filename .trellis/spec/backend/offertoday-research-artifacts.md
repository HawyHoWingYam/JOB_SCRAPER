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
