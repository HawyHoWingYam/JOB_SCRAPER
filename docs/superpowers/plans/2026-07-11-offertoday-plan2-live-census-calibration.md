# OfferToday Plan 2 Live Census Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the stage-gated Plan 2 live research path, run one production-equivalent listing request plus a frozen 20-detail diagnostic smoke, then use verified evidence to calibrate and execute three reproducible 31-category listing censuses without changing production defaults.

**Architecture:** Keep the Plan 1 CLI offline-only and add a separate live research entry point backed by pure contracts, the shared `OfferTodayListingRunner`, the shared browser/detail classifiers, the existing crawl-job research ledger, and immutable artifacts. Tasks 1–8 are the immediate smoke deliverable; Tasks 9–15 remain hard-gated behind an accepted smoke and implement calibration, pilot, candidate freeze, full censuses, and stability comparison.

**Tech Stack:** Python 3.11+, asyncio, dataclasses, SQLAlchemy 2.0, PostgreSQL 15, Playwright, pytest/pytest-asyncio, Docker Compose, Git.

---

## Plan Boundary

This is Plan 2 of four evidence-gated plans. It implements Phase 2 of `docs/superpowers/specs/2026-07-10-offertoday-broad-it-coverage-reliability-research-design.md` and the approved Plan 2 design at `docs/superpowers/specs/2026-07-11-offertoday-plan2-live-census-calibration-design.md`.

Immediate scope:

- add the live-only research contracts, stage gate, ledger methods, smoke service, and CLI;
- recapture two matching read-only database baselines;
- make exactly one listing API attempt for category `118000`, endpoint `search`, `rcdType=7`, page 1;
- freeze the first 20 accepted distinct `(jobId, resolved_route_id, encrypted_job_id_source)` identities;
- fetch those 20 details sequentially with no retry and a three-second inter-request delay;
- persist only the tagged crawl job/events and the ignored research artifact;
- prove staging, Job, and Company state did not change; and
- stop after smoke review.

Later Plan 2 scope, implemented only after the smoke gate passes:

- a 24-request endpoint/`rcdType` calibration matrix;
- a three-page pilot over all 31 top-level categories;
- an immutable census candidate contract;
- three naturally exhausted full-site censuses across at least two windows; and
- a stability/cost decision record for Plan 3.

Excluded:

- Plan 3 broad-IT title rules, labels, confidence samples, and planner ablations;
- Plan 4 100/500 detail canaries, backlog drain, fault injection, and soak;
- automatic production default changes; and
- deletion or cleanup of historical rows.

## Execution Safety

The current worktree contains unrelated and overlapping user changes. Preserve them exactly. Do not run `git reset`, `git checkout`, `git restore`, whole-file replacement, or cleanup commands.

Before Task 1:

```powershell
git update-ref refs/codex/offertoday-plan2-base HEAD
git status --short
git diff -- .gitignore backend/app/scraper/offertoday_browser_runtime.py backend/scripts/offertoday_standalone_crawl.py backend/tests/test_offertoday_browser_runtime.py docker-compose.yml docker-compose.dev.yml
```

Expected: the base ref points to the approved Plan 2 design commit; unrelated dirty files remain visible. For a shared dirty file, use `git add -p`. New backend tests and docs are hidden by broad ignore rules, so add only named files with `git add -f`.

No task may start the next live stage automatically. Every live command exports and verifies partial evidence before returning. Runtime artifacts under `backend/runtime/offertoday-research/` remain ignored and must never be committed.

## Plan 1 Baseline

Authoritative Plan 1 implementation commit: `1d26c05aaa266ea2eb56550903417f6741905d5e`.

Last matching baseline evidence:

```text
staged_rows=15697
distinct_staged_ids=5573
published_jobs=2961
distinct_staged_unpublished_ids=2612
snapshot_hash=1527469841bf0e70273f439b82dbb854b24fc5f6dbb3661f3f1c9f8d0e5cb06c
inventory_hash=418d6791e0a20a45ccf5fc274b96640aa130a33d8f062578c63698cd87a6a081
```

These counts are historical provenance. An authorized replacement Task 8 recaptures two new matching baselines immediately before the live smoke.

## Task 8 Correction Gate

The original Task 8 attempt, run `fab9d8e1-4c12-4170-a539-c0a6cdbbca93`, failed because all ten returned listing rows were valid `jobId`-only rows under the corrected identity contract. It is immutable failed evidence, not an accepted smoke, and its artifact at `backend/runtime/offertoday-research/fab9d8e1-4c12-4170-a539-c0a6cdbbca93` must remain unchanged with manifest SHA-256 `1928423eed6cfd95e4cd2a3af3eb1d62c2ea6d460b122acb0ca0fefcfb4b548b`.

Before any replacement smoke, complete and verify the deterministic correction in `docs/superpowers/plans/2026-07-11-offertoday-jobid-only-identity-compatibility.md`, pass its offline review gates, and then obtain separate explicit user approval for exactly one replacement Task 8 smoke. The existing Task 8 execution steps below describe that replacement only; they are not authorization to run it. Task 8 remains unaccepted and Task 9 remains locked.

## File Map

### New Source Files

- `backend/app/sources/offertoday/research/stage_gate.py`: verify predecessor artifacts and matching baseline pairs.
- `backend/app/sources/offertoday/research/live_contracts.py`: live request budgets, detail observations, smoke decisions, bounded-stage results, and census candidate contracts.
- `backend/app/sources/offertoday/research/smoke.py`: exact smoke condition, distinct cohort freeze, result conversion, and pure acceptance evaluation.
- `backend/app/sources/offertoday/research/calibration.py`: bounded calibration/pilot matrices and candidate selection.
- `backend/app/sources/offertoday/research/stability.py`: set hashes, Jaccard, coefficient of variation, and cross-run comparison.
- `backend/app/services/offertoday_research_live_service.py`: one-browser smoke, bounded stage, and full-census orchestration.
- `backend/app/services/offertoday_research_staging_service.py`: globally reconciled, at-most-once research staging for pilot/census runs.
- `backend/scripts/offertoday_research_census.py`: stage-gated live CLI.

### New Tests

- `backend/tests/test_offertoday_research_stage_gate.py`
- `backend/tests/test_offertoday_research_smoke.py`
- `backend/tests/test_offertoday_research_live_service.py`
- `backend/tests/test_offertoday_research_census_cli.py`
- `backend/tests/test_offertoday_research_calibration.py`
- `backend/tests/test_offertoday_research_staging_service.py`
- `backend/tests/test_offertoday_research_stability.py`

### Existing Files to Modify

- `backend/app/sources/offertoday/research/contracts.py`: conditionally add Plan 2 metadata without changing Plan 1 payloads.
- `backend/app/sources/offertoday/research/artifacts.py`: hash the new live source/service/script paths.
- `backend/app/services/offertoday_research_observation_service.py`: generic ordered events and terminal run lifecycle.
- `backend/app/sources/offertoday/listing_runner.py`: deterministic optional page-delay range for later live stages.
- `backend/scripts/offertoday_standalone_crawl.py`: import the extracted production-equivalent staging sink without changing behavior.
- `backend/tests/test_offertoday_research_observation_service.py`
- `backend/tests/test_offertoday_research_artifacts.py`
- `backend/tests/test_offertoday_listing_runner.py`
- `backend/tests/test_offertoday_standalone_crawl.py`

## Fixed Contracts

```text
Smoke listing budget       = 1 API attempt
Smoke detail budget        = 20 API attempts
Smoke detail concurrency   = 1
Smoke detail retry         = 0
Smoke inter-request delay  = 3.0 seconds
Smoke condition            = category 118000, endpoint search, rcdType 7, page 1
Smoke persistence          = crawl_job + research events + artifact only
Smoke runner completion    = preserve page_cap/incomplete when the page has more data
Smoke experiment decision  = separate smoke_passed boolean
```

The smoke may return crawl-job status `completed` only when `listing_complete=false`, `expected_truncation=true`, and `smoke_passed=true` are persisted together. Census commands never receive that exception.

---

### Task 1: Extend Research Metadata Without Breaking the Offline Boundary

**Files:**
- Modify: `backend/app/sources/offertoday/research/contracts.py:7-22`
- Modify: `backend/app/sources/offertoday/research/artifacts.py:67-76`
- Modify: `backend/tests/test_offertoday_research_observation_service.py`
- Modify: `backend/tests/test_offertoday_research_artifacts.py`

- [ ] **Step 1: Write failing metadata compatibility tests**

Add:

```python
def test_plan1_metadata_payload_is_unchanged():
    metadata = ResearchMetadata(
        run_id="11111111-1111-1111-1111-111111111111",
        experiment="fixture",
        variant="saved-response",
        planner_version="abc123",
    )

    assert metadata.to_request_payload() == {
        "research": {
            "run_id": metadata.run_id,
            "experiment": "fixture",
            "variant": "saved-response",
            "planner_version": "abc123",
        }
    }


def test_plan2_metadata_adds_parent_and_exact_request_budget():
    metadata = ResearchMetadata(
        run_id="22222222-2222-2222-2222-222222222222",
        experiment="runtime-smoke",
        variant="search-rcdtype-7-fresh-headless",
        planner_version="def456",
        plan=2,
        parent_artifact_hash="a" * 64,
        request_budget={"listing": 1, "detail": 20},
    )

    assert metadata.to_request_payload()["research"] == {
        "run_id": metadata.run_id,
        "experiment": "runtime-smoke",
        "variant": "search-rcdtype-7-fresh-headless",
        "planner_version": "def456",
        "plan": 2,
        "parent_artifact_hash": "a" * 64,
        "request_budget": {"listing": 1, "detail": 20},
    }
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest -q backend/tests/test_offertoday_research_observation_service.py -k "metadata"
```

Expected: construction fails because the Plan 2 fields do not exist.

- [ ] **Step 3: Implement conditional Plan 2 metadata**

Use:

```python
@dataclass(frozen=True, slots=True)
class ResearchMetadata:
    run_id: str
    experiment: str
    variant: str
    planner_version: str
    plan: int | None = None
    parent_artifact_hash: str | None = None
    request_budget: dict[str, int] | None = None

    def to_request_payload(self) -> dict[str, Any]:
        research: dict[str, Any] = {
            "run_id": self.run_id,
            "experiment": self.experiment,
            "variant": self.variant,
            "planner_version": self.planner_version,
        }
        if self.plan is not None:
            research["plan"] = int(self.plan)
        if self.parent_artifact_hash is not None:
            research["parent_artifact_hash"] = self.parent_artifact_hash
        if self.request_budget is not None:
            research["request_budget"] = {
                str(key): int(value)
                for key, value in sorted(self.request_budget.items())
            }
        return {"research": research}
```

Add this validation:

```python
def __post_init__(self) -> None:
    if self.plan is not None and (type(self.plan) is not int or self.plan < 1):
        raise ValueError("plan must be a positive exact integer")
    if self.parent_artifact_hash is not None and not re.fullmatch(
        r"[0-9a-f]{64}",
        self.parent_artifact_hash,
    ):
        raise ValueError("parent_artifact_hash must be lowercase SHA-256")
    if self.request_budget is not None:
        for key, value in self.request_budget.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("request budget keys must be nonblank strings")
            if type(value) is not int or value < 0:
                raise ValueError("request budget values must be non-negative exact integers")
```

Import `re`. This rejects booleans as integer budgets.

- [ ] **Step 4: Add the new live paths to provenance**

Append these exact entries to `DEFAULT_RELEVANT_SOURCE_PATHS`:

```python
"backend/app/services/offertoday_research_live_service.py",
"backend/app/services/offertoday_research_staging_service.py",
"backend/scripts/offertoday_research_census.py",
```

The existing `backend/app/sources/offertoday` directory entry automatically includes the new pure modules.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_observation_service.py backend/tests/test_offertoday_research_artifacts.py
```

Expected: all tests pass; Plan 1 metadata serialization remains byte-for-byte unchanged.

- [ ] **Step 6: Commit Task 1**

```powershell
git add backend/app/sources/offertoday/research/contracts.py backend/app/sources/offertoday/research/artifacts.py backend/tests/test_offertoday_research_observation_service.py backend/tests/test_offertoday_research_artifacts.py
git diff --cached --check
git commit -m "feat(offertoday): define plan 2 research metadata"
```

---

### Task 2: Verify Two Matching Baselines Before Any Live Request

**Files:**
- Create: `backend/app/sources/offertoday/research/stage_gate.py`
- Create: `backend/tests/test_offertoday_research_stage_gate.py`

- [ ] **Step 1: Write failing stage-gate tests**

Cover valid artifacts, a tampered artifact, the same run ID used twice, count drift, snapshot-hash drift, inventory-hash drift, missing `research.baseline`, and multiple baseline observations.

Use this public contract in the tests:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BaselineArtifactEvidence:
    artifact_dir: Path
    run_id: str
    manifest_hash: str
    snapshot_hash: str
    inventory_hash: str
    counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class MatchingBaselineGate:
    first: BaselineArtifactEvidence
    second: BaselineArtifactEvidence

    @property
    def parent_artifact_hash(self) -> str:
        return self.second.manifest_hash
```

The valid test must assert both run IDs differ while snapshot hash, inventory hash, and counts match.

- [ ] **Step 2: Run the tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_stage_gate.py
```

Expected: import failure for `stage_gate.py`.

- [ ] **Step 3: Implement strict artifact loading**

Implement:

```python
_COUNT_KEYS = (
    "staged_rows",
    "distinct_staged_ids",
    "published_jobs",
    "distinct_staged_unpublished_ids",
    "pending_rows",
    "duplicate_staging_rows",
)


def load_baseline_artifact(artifact_dir: Path) -> BaselineArtifactEvidence:
    artifact_dir = Path(artifact_dir).resolve(strict=True)
    verification = verify_research_artifact(artifact_dir)
    if not verification.valid:
        raise ValueError(f"invalid baseline artifact: {artifact_dir}")
    manifest_path = artifact_dir / "manifest.json"
    observations_path = artifact_dir / "observations.jsonl"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    observations = [
        json.loads(line)
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    baseline_events = [
        event for event in observations
        if event.get("event_type") == "research.baseline"
    ]
    if len(baseline_events) != 1:
        raise ValueError("baseline artifact must contain exactly one research.baseline event")
    payload = baseline_events[0].get("payload")
    snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
    inventory = payload.get("run_start_inventory") if isinstance(payload, dict) else None
    if not isinstance(snapshot, dict) or not isinstance(inventory, dict):
        raise ValueError("baseline artifact is missing snapshot or inventory evidence")
    counts = tuple((key, int(snapshot[key])) for key in _COUNT_KEYS)
    return BaselineArtifactEvidence(
        artifact_dir=artifact_dir,
        run_id=str(manifest["run_id"]),
        manifest_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        snapshot_hash=str(snapshot["data_hash"]),
        inventory_hash=str(inventory["data_hash"]),
        counts=counts,
    )
```

Implement:

```python
def require_matching_baselines(
    first_dir: Path,
    second_dir: Path,
) -> MatchingBaselineGate:
    first = load_baseline_artifact(first_dir)
    second = load_baseline_artifact(second_dir)
    if first.run_id == second.run_id:
        raise ValueError("matching baseline gate requires two distinct run IDs")
    if first.snapshot_hash != second.snapshot_hash:
        raise ValueError("baseline snapshot hashes do not match")
    if first.inventory_hash != second.inventory_hash:
        raise ValueError("baseline inventory hashes do not match")
    if first.counts != second.counts:
        raise ValueError("baseline count evidence does not match")
    return MatchingBaselineGate(first=first, second=second)
```

- [ ] **Step 4: Run stage-gate and artifact tests**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_stage_gate.py backend/tests/test_offertoday_research_artifacts.py
```

Expected: all tests pass; no test opens a database or browser.

- [ ] **Step 5: Commit Task 2**

```powershell
git add backend/app/sources/offertoday/research/stage_gate.py
git add -f backend/tests/test_offertoday_research_stage_gate.py
git diff --cached --check
git commit -m "feat(offertoday): gate live research on matching baselines"
```

---

### Task 3: Define the Exact Smoke Cohort and Acceptance Decision

**Files:**
- Create: `backend/app/sources/offertoday/research/live_contracts.py`
- Create: `backend/app/sources/offertoday/research/smoke.py`
- Create: `backend/tests/test_offertoday_research_smoke.py`

- [ ] **Step 1: Write failing condition and cohort tests**

Tests must assert:

```python
def test_smoke_condition_is_the_locked_compatibility_control():
    assert build_runtime_smoke_condition() == OfferTodayListingCondition(
        search_family="runtime_smoke",
        category_id=118000,
        keyword="",
        endpoint="search",
        rcd_type=7,
    )


def test_freeze_detail_cohort_is_distinct_first_seen_and_accepted_only():
    result = listing_result(
        ordered_job_ids=("j1", "j2", "j3"),
        accepted_job_ids=("j1", "j3"),
        id_pairs=(pair("j1", "e1"), pair("j2", "e2"), pair("j3", "e3")),
    )

    assert freeze_detail_smoke_cohort(result, limit=20) == (
        DetailSmokeTarget(
            position=1,
            job_id="j1",
            encrypted_job_id="e1",
            encrypted_job_id_source="encryptJobId",
        ),
        DetailSmokeTarget(
            position=2,
            job_id="j3",
            encrypted_job_id="e3",
            encrypted_job_id_source="encryptJobId",
        ),
    )
```

Add cases for duplicate pairs, fewer than 20 pairs, zero/negative limits, and identity-conflict results.

- [ ] **Step 2: Write failing smoke-decision tests**

Use these exact public dataclasses:

```python
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.sources.offertoday.detail_identity import (
    OfferTodayDetailIdentity,
    OfferTodayEncryptedJobIdSource,
)


@dataclass(frozen=True, slots=True)
class DetailSmokeTarget:
    position: int
    job_id: str
    encrypted_job_id: str
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId"

    def __post_init__(self) -> None:
        if type(self.position) is not int or self.position < 1:
            raise ValueError("position must be a positive exact integer")
        OfferTodayDetailIdentity(
            job_id=self.job_id,
            encrypted_job_id=self.encrypted_job_id,
            encrypted_job_id_source=self.encrypted_job_id_source,
        )

    def to_payload(self) -> dict[str, Any]:
        identity_payload = {
            "job_id": self.job_id,
            "encrypted_job_id": self.encrypted_job_id,
            "encrypted_job_id_source": self.encrypted_job_id_source,
        }
        identity_canonical = json.dumps(
            identity_payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "position": self.position,
            **identity_payload,
            "job_id_hash": hashlib.sha256(self.job_id.encode()).hexdigest(),
            "encrypted_job_id_hash": hashlib.sha256(
                self.encrypted_job_id.encode()
            ).hexdigest(),
            "identity_resolution_hash": hashlib.sha256(
                identity_canonical.encode()
            ).hexdigest(),
        }


@dataclass(frozen=True, slots=True)
class DetailSmokeObservation:
    target: DetailSmokeTarget
    classification: str
    api_code: int | None
    started_at: str
    completed_at: str
    latency_ms: int
    identity_valid: bool
    parsed: bool
    has_title: bool
    has_company: bool
    has_description: bool
    stop_batch: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "target": self.target.to_payload(),
            "classification": self.classification,
            "api_code": self.api_code,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "latency_ms": self.latency_ms,
            "identity_valid": self.identity_valid,
            "parsed": self.parsed,
            "has_title": self.has_title,
            "has_company": self.has_company,
            "has_description": self.has_description,
            "stop_batch": self.stop_batch,
        }


@dataclass(frozen=True, slots=True)
class SmokeDecision:
    smoke_passed: bool
    stop_reason: str | None
    expected_truncation: bool
    frozen_count: int
    attempted_count: int
    terminal_count: int
    success_count: int
    unattempted_count: int


@dataclass(frozen=True, slots=True)
class LiveSmokeExecution:
    listing_result: ListingRunResult
    frozen_targets: tuple[DetailSmokeTarget, ...]
    detail_observations: tuple[DetailSmokeObservation, ...]
    decision: SmokeDecision
    would_stage_rows: int
    stage_calls: int
```

Test helpers must construct real runner contracts rather than mocks with a different shape:

```python
def pair(
    job_id: str,
    encrypted_job_id: str,
    encrypted_job_id_source: OfferTodayEncryptedJobIdSource = "encryptJobId",
) -> OfferTodayIdentityPair:
    return OfferTodayIdentityPair(
        job_id=job_id,
        encrypted_job_id=encrypted_job_id,
        encrypted_job_id_source=encrypted_job_id_source,
    )


def listing_result(
    *,
    ordered_job_ids: tuple[str, ...],
    accepted_job_ids: tuple[str, ...],
    id_pairs: tuple[OfferTodayIdentityPair, ...],
) -> ListingRunResult:
    return ListingRunResult(
        ordered_job_ids=ordered_job_ids,
        accepted_job_ids=accepted_job_ids,
        id_pairs=id_pairs,
        observations=(),
        condition_outcomes=(),
        identity_conflicts=(),
        identity_issues=(),
        gaps=(),
        stop_reason="page_cap",
        is_complete=False,
    )
```

Cases:

- 20 success observations pass;
- 19 success plus one `terminal_unavailable` pass;
- fewer than 20 frozen targets fail with `insufficient_valid_detail_targets`;
- auth, WAF, IP block, transport, invalid payload, or ID mismatch fails;
- a batch stop permits later unattempted targets but still fails;
- an unattempted target without a batch stop fails;
- listing gaps/issues/conflicts fail before details; and
- a successful nonterminal response without identity/parser/content flags fails.

- [ ] **Step 3: Run tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_smoke.py
```

Expected: imports fail for the new modules.

- [ ] **Step 4: Implement pure selection and evaluation**

`build_runtime_smoke_condition()` returns the locked condition. `freeze_detail_smoke_cohort()` iterates `ListingRunResult.id_pairs`, validates and preserves each pair's exact `encrypted_job_id_source`, filters by `accepted_job_ids`, deduplicates `job_id`, preserves first-seen order, and stops at the exact limit.

Add `listing_ready_for_detail_smoke(listing_result, frozen_targets)` and return true only for one successful page-1 attempt, `page_cap`, no gap/identity evidence, and exactly 20 frozen targets. The live service uses this predicate before detail request 1.

Implement the evaluator with these forbidden nonterminal outcomes:

```python
_SMOKE_FAILURE_KINDS = {
    "auth_expired",
    "waf_challenge",
    "ip_blocked",
    "transient_transport",
    "invalid_payload",
    "id_mismatch",
}
```

Only `success` and `terminal_unavailable` are acceptable. A success requires identity, parser, title, company, and description flags all true. Preserve the listing runner's `page_cap` and `is_complete=False`; set `expected_truncation=True` only for a successful page-1 `page_cap` with no gap/identity evidence.

Implement the decision in this order so a later count error cannot hide a listing or hard-stop failure:

```python
def evaluate_smoke(
    *,
    listing_result: ListingRunResult,
    frozen_targets: tuple[DetailSmokeTarget, ...],
    observations: tuple[DetailSmokeObservation, ...],
    required_target_count: int = 20,
) -> SmokeDecision:
    listing_attempts = listing_result.observations
    expected_truncation = (
        len(listing_attempts) == 1
        and listing_attempts[0].page == 1
        and listing_attempts[0].attempt == 1
        and listing_attempts[0].classification == "success"
        and listing_result.stop_reason == "page_cap"
        and listing_result.is_complete is False
        and not listing_result.gaps
        and not listing_result.identity_issues
        and not listing_result.identity_conflicts
    )
    if not expected_truncation:
        return _failed_decision(
            reason=f"listing_{listing_result.stop_reason}",
            expected_truncation=False,
            frozen=frozen_targets,
            observations=observations,
        )
    if len(frozen_targets) != required_target_count:
        return _failed_decision(
            reason="insufficient_valid_detail_targets",
            expected_truncation=True,
            frozen=frozen_targets,
            observations=observations,
        )
    expected_prefix = frozen_targets[: len(observations)]
    if tuple(item.target for item in observations) != expected_prefix:
        return _failed_decision(
            reason="detail_attempt_order_mismatch",
            expected_truncation=True,
            frozen=frozen_targets,
            observations=observations,
        )
    for item in observations:
        if item.classification in _SMOKE_FAILURE_KINDS:
            return _failed_decision(
                reason=item.classification,
                expected_truncation=True,
                frozen=frozen_targets,
                observations=observations,
            )
        if item.classification == "success" and not all(
            (
                item.identity_valid,
                item.parsed,
                item.has_title,
                item.has_company,
                item.has_description,
            )
        ):
            return _failed_decision(
                reason="incomplete_success_detail",
                expected_truncation=True,
                frozen=frozen_targets,
                observations=observations,
            )
        if item.classification not in {"success", "terminal_unavailable"}:
            return _failed_decision(
                reason=f"unexpected_detail_kind:{item.classification}",
                expected_truncation=True,
                frozen=frozen_targets,
                observations=observations,
            )
    if len(observations) != required_target_count:
        reason = (
            observations[-1].classification
            if observations and observations[-1].stop_batch
            else "unattempted_without_batch_stop"
        )
        return _failed_decision(
            reason=reason,
            expected_truncation=True,
            frozen=frozen_targets,
            observations=observations,
        )
    terminal_count = sum(
        item.classification == "terminal_unavailable" for item in observations
    )
    success_count = sum(item.classification == "success" for item in observations)
    return SmokeDecision(
        smoke_passed=True,
        stop_reason=None,
        expected_truncation=True,
        frozen_count=len(frozen_targets),
        attempted_count=len(observations),
        terminal_count=terminal_count,
        success_count=success_count,
        unattempted_count=0,
    )
```

Implement `_failed_decision()` once to calculate frozen/attempted/success/terminal/unattempted counts from its arguments.

- [ ] **Step 5: Run tests and verify GREEN**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_smoke.py backend/tests/test_offertoday_listing_runner.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 3**

```powershell
git add backend/app/sources/offertoday/research/live_contracts.py backend/app/sources/offertoday/research/smoke.py
git add -f backend/tests/test_offertoday_research_smoke.py
git diff --cached --check
git commit -m "feat(offertoday): define live smoke evidence contracts"
```

---

### Task 4: Add Ordered Detail Events, Terminal Lifecycle, and a Zero-Write Sink

**Files:**
- Modify: `backend/app/services/offertoday_research_observation_service.py:18-88`
- Create: `backend/app/services/offertoday_research_staging_service.py`
- Modify: `backend/tests/test_offertoday_research_observation_service.py`
- Create: `backend/tests/test_offertoday_research_staging_service.py`

- [ ] **Step 1: Write failing lifecycle tests**

Add tests proving:

```python
service.record_event("research.detail_cohort_frozen", {"count": 20})
service.record_detail_attempt({"position": 1, "classification": "success"})
service.finish_run(
    status="completed",
    summary={
        "listing_complete": False,
        "expected_truncation": True,
        "smoke_passed": True,
    },
)
```

The fake repository must receive ordered event names, `emitted_by="offertoday-research"`, a terminal `completed_at`, and metrics containing `smoke_passed`, `listing_complete`, and the frozen/attempted counts. Reject `completed` when the three smoke fields are not the exact accepted combination.

Add a failure case that persists only `unexpected_live_smoke_error:TypeError`, never the exception message.

- [ ] **Step 2: Write failing zero-write sink tests**

Define `ResearchNoopListingStagingSink` and assert:

```python
await sink.stage_page(condition=condition, page=1, rows=[{"job_id": "j1"}])
await sink.defer_identity_conflict(
    job_ids=("j1",),
    encrypted_job_ids=("e1", "e2"),
    reason="one_job_id_to_multiple_encrypted_ids",
)

assert sink.would_stage_rows == 1
assert sink.stage_calls == 1
assert sink.deferred_conflicts == (...,)
assert not hasattr(sink, "db")
assert not hasattr(sink, "repository")
```

The sink has no database or repository dependency.

- [ ] **Step 3: Run tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_observation_service.py backend/tests/test_offertoday_research_staging_service.py
```

Expected: missing methods/classes.

- [ ] **Step 4: Implement the lifecycle methods**

Add:

```python
def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
    if not event_type.startswith("research."):
        raise ValueError("research event type must start with 'research.'")
    self._append(event_type, listing_observation_to_payload(payload))


def record_detail_attempt(self, payload: dict[str, Any]) -> None:
    self.record_event("research.detail_attempt", payload)


def finish_run(
    self,
    *,
    status: str,
    summary: dict[str, Any],
    error_message: str | None = None,
) -> None:
    if self.crawl_job_id is None:
        raise ValueError("crawl_job_id is required before finishing a run")
    payload = listing_observation_to_payload(summary)
    if status == "completed" and payload.get("smoke_passed") is True:
        if payload.get("listing_complete") is not False:
            raise ValueError("completed smoke must preserve listing_complete=false")
        if payload.get("expected_truncation") is not True:
            raise ValueError("completed smoke must record expected truncation")
    self.crawl_job_repository.record_runtime_event(
        self.db,
        crawl_job_id=self.crawl_job_id,
        status=status,
        event_type="research.run_summary",
        payload=payload,
        emitted_by="offertoday-research",
        completed_at=utc_now(),
        error_message=error_message,
        metrics={
            key: payload[key]
            for key in (
                "smoke_passed",
                "listing_complete",
                "expected_truncation",
                "frozen_count",
                "attempted_count",
                "success_count",
                "terminal_count",
                "unattempted_count",
            )
            if key in payload
        },
        auto_commit=True,
    )
```

- [ ] **Step 5: Implement the no-op sink and rerun tests**

The sink stores immutable copies of call evidence and returns `None`; it must never import a model, repository, or session.

```powershell
python -m pytest -q backend/tests/test_offertoday_research_observation_service.py backend/tests/test_offertoday_research_staging_service.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

```powershell
git add backend/app/services/offertoday_research_observation_service.py backend/app/services/offertoday_research_staging_service.py backend/tests/test_offertoday_research_observation_service.py
git add -f backend/tests/test_offertoday_research_staging_service.py
git diff --cached --check
git commit -m "feat(offertoday): record live research smoke lifecycle"
```

---

### Task 5: Orchestrate One Listing and the Frozen 20-Detail Cohort

**Files:**
- Create: `backend/app/services/offertoday_research_live_service.py`
- Create: `backend/tests/test_offertoday_research_live_service.py`

- [ ] **Step 1: Write failing listing-budget tests**

Use an injected runtime and runner factory. Assert the service calls the runner once with:

```python
ListingStopPolicy(
    max_pages_per_condition=1,
    unique_job_cap=None,
    require_empty_confirmation=False,
)

ListingRetryPolicy(
    max_attempts_per_page=1,
    retry_delays_seconds=(),
    page_delay_seconds=0.0,
)
```

Assert the single condition equals `build_runtime_smoke_condition()`, the staging sink is `ResearchNoopListingStagingSink`, and no separate `check_session()` or `require_healthy_session()` call occurs.

- [ ] **Step 2: Write failing detail-loop tests**

Cover:

- 20 targets run in frozen order;
- every detail event has deterministic aware start/end timestamps, canonical and resolved-route identity hashes, and exact route provenance;
- exactly 19 sleep calls occur after 20 completed non-stopping attempts;
- each sleep is `3.0` seconds;
- no target is retried;
- code 2520 proceeds to the next target;
- auth/WAF/IP/ID mismatch stops and marks later targets unattempted;
- fewer than 20 listing targets triggers zero detail calls;
- unexpected `TypeError` propagates after no retry and no extra detail call; and
- the injected `OfferTodayBrowserDetailScraper` uses `runtime.fetch_detail_json`, so no second browser starts.

- [ ] **Step 3: Run tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_live_service.py
```

Expected: import failure for the live service.

- [ ] **Step 4: Implement `run_smoke()`**

Use this interface:

```python
class OfferTodayResearchLiveService:
    def __init__(
        self,
        *,
        runner_factory=OfferTodayListingRunner,
        detail_scraper_factory=OfferTodayBrowserDetailScraper,
        sleep=asyncio.sleep,
        clock=time.perf_counter,
        now=utc_now,
    ) -> None: ...

    async def run_smoke(
        self,
        *,
        runtime: OfferTodayBrowserRuntime,
        observation_service: OfferTodayResearchObservationService,
    ) -> LiveSmokeExecution: ...
```

Implement the method body as:

```python
async def run_smoke(
    self,
    *,
    runtime: OfferTodayBrowserRuntime,
    observation_service: OfferTodayResearchObservationService,
) -> LiveSmokeExecution:
    staging_sink = ResearchNoopListingStagingSink()
    runner = self._runner_factory(runtime)
    listing_result = await runner.run(
        conditions=(build_runtime_smoke_condition(),),
        stop_policy=ListingStopPolicy(
            max_pages_per_condition=1,
            unique_job_cap=None,
            require_empty_confirmation=False,
        ),
        retry_policy=ListingRetryPolicy(
            max_attempts_per_page=1,
            retry_delays_seconds=(),
            page_delay_seconds=0.0,
        ),
        observation_sink=observation_service,
        staging_sink=staging_sink,
        session_mode="fresh-headless",
    )
    frozen_targets = freeze_detail_smoke_cohort(listing_result, limit=20)
    observation_service.record_event(
        "research.detail_cohort_frozen",
        {
            "count": len(frozen_targets),
            "targets": [target.to_payload() for target in frozen_targets],
        },
    )
    observations: list[DetailSmokeObservation] = []
    if listing_ready_for_detail_smoke(listing_result, frozen_targets):
        detail_scraper = self._detail_scraper_factory(
            detail_json_fetcher=runtime.fetch_detail_json,
            headed=False,
        )
        for index, target in enumerate(frozen_targets):
            started_timestamp = self._now().isoformat()
            started_at = self._clock()
            detail_result = await detail_scraper.fetch_job_detail(
                target.job_id,
                encrypted_job_id=target.encrypted_job_id,
                encrypted_job_id_source=target.encrypted_job_id_source,
            )
            latency_ms = int(
                round(max(0.0, self._clock() - started_at) * 1000)
            )
            completed_timestamp = self._now().isoformat()
            observation = detail_result_to_observation(
                target=target,
                result=detail_result,
                started_at=started_timestamp,
                completed_at=completed_timestamp,
                latency_ms=latency_ms,
            )
            observations.append(observation)
            observation_service.record_detail_attempt(observation.to_payload())
            if observation.stop_batch:
                break
            if index + 1 < len(frozen_targets):
                await self._sleep(3.0)
    decision = evaluate_smoke(
        listing_result=listing_result,
        frozen_targets=frozen_targets,
        observations=tuple(observations),
    )
    return LiveSmokeExecution(
        listing_result=listing_result,
        frozen_targets=frozen_targets,
        detail_observations=tuple(observations),
        decision=decision,
        would_stage_rows=staging_sink.would_stage_rows,
        stage_calls=staging_sink.stage_calls,
    )
```

`LiveSmokeExecution` contains the untouched `ListingRunResult`, frozen targets, detail observations, decision, and no-op sink counters.

Convert each typed detail result with a pure helper:

```python
def detail_result_to_observation(
    *,
    target: DetailSmokeTarget,
    result: OfferTodayDetailFetchResult,
    started_at: str,
    completed_at: str,
    latency_ms: int,
) -> DetailSmokeObservation:
    canonical = result.canonical_detail or {}
    classification = result.classification
    return DetailSmokeObservation(
        target=target,
        classification=classification.kind.value,
        api_code=classification.code,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=latency_ms,
        identity_valid=(
            classification.kind is OfferTodayResponseKind.SUCCESS
            and result.canonical_detail is not None
        ),
        parsed=result.parsed_detail is not None,
        has_title=bool(str(canonical.get("title") or "").strip()),
        has_company=bool(str(canonical.get("company_name") or "").strip()),
        has_description=bool(
            str(canonical.get("description_text") or "").strip()
        ),
        stop_batch=classification.stop_batch,
    )
```

Record `research.detail_cohort_frozen` before request 1 and one `research.detail_attempt` after every classified response. Do not record raw cookies, headers, or exception messages.

Import `utc_now` from `app.utils.time`; tests inject a deterministic timestamp provider by adding `now=utc_now` to the service constructor and using `self._now()` in the method body.

- [ ] **Step 5: Run service, scraper, and runner tests**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_smoke.py backend/tests/test_offertoday_canonical_and_identity.py backend/tests/test_offertoday_listing_runner.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 5**

```powershell
git add backend/app/services/offertoday_research_live_service.py
git add -f backend/tests/test_offertoday_research_live_service.py
git diff --cached --check
git commit -m "feat(offertoday): orchestrate bounded live smoke"
```

---

### Task 6: Expose Fail-Closed Live `smoke` and Offline `verify-run` Commands

**Files:**
- Modify: `backend/app/sources/offertoday/research/stage_gate.py`
- Create: `backend/scripts/offertoday_research_census.py`
- Modify: `backend/tests/test_offertoday_research_stage_gate.py`
- Create: `backend/tests/test_offertoday_research_census_cli.py`

- [ ] **Step 1: Write failing parser and offline-boundary tests**

The initial parser exposes `smoke` and the network-free `verify-run`; later tasks add the other commands. Required arguments:

```text
smoke
  --baseline-artifact PATH   # exactly twice
  [--run-id UUID]
  [--artifact-root PATH]
  [--repo-root PATH]

verify-run
  --artifact PATH
```

Tests must assert:

- exactly two baseline artifacts are required;
- no category, endpoint, `rcdType`, retry, detail-limit, or pacing override exists for the first smoke;
- importing `backend/scripts/offertoday_research.py` still does not import Playwright or the live script;
- `--help` dispatches in a subprocess; and
- the live script imports browser modules only after backend bootstrap.

For `verify-run`, assert browser/runtime factories are never constructed. It must verify the manifest, require exactly one terminal `research.run_summary`, reject events after the summary, check request counts against metadata budgets, and check status/summary consistency.

- [ ] **Step 2: Write failing lifecycle tests**

Inject fake session/repository/runtime/service/artifact functions and prove:

1. matching baselines are verified before session creation or browser construction;
2. a run-start snapshot is captured before the browser;
3. the crawl job exists before the first fake network call;
4. run-end staging/published hashes must equal run-start hashes;
5. pass returns exit 0;
6. a non-hard smoke gate returns exit 3;
7. auth/WAF/IP/ID mismatch returns exit 4;
8. artifact mismatch returns exit 5;
9. an unexpected exception finalizes with type-only text, exports/verifies partial evidence, closes resources, then re-raises the same object;
10. `KeyboardInterrupt` also exports partial evidence and re-raises; and
11. browser cleanup precedes artifact export.

The terminal summary must contain exact `run_start_snapshot_hash`, `run_end_snapshot_hash`, `run_start_inventory_hash`, and `run_end_inventory_hash` fields so an external baseline can independently verify the no-write claim.

- [ ] **Step 3: Run tests and verify RED**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_census_cli.py
```

Expected: script import fails.

- [ ] **Step 4: Implement the CLI constants and dependency boundary**

Use:

```python
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INCOMPLETE = 3
EXIT_HARD_STOP = 4
EXIT_EVIDENCE_FAILURE = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live OfferToday Plan 2 research")
    commands = parser.add_subparsers(dest="command", required=True)
    smoke = commands.add_parser("smoke")
    smoke.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    smoke.add_argument("--run-id", default=None)
    smoke.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    smoke.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    verify = commands.add_parser("verify-run")
    verify.add_argument("--artifact", type=Path, required=True)
    return parser
```

Reject artifact counts other than two before constructing any dependency.

Implement `verify-run` before the database/browser branch:

```python
if args.command == "verify-run":
    result = verify_live_research_run(args.artifact)
    _print_json(result.to_payload())
    return EXIT_OK if result.valid else EXIT_EVIDENCE_FAILURE
```

Put the pure `verify_live_research_run()` implementation in `stage_gate.py`. It first calls `verify_research_artifact()`, then validates event order, one terminal summary, metadata request budgets, predecessor hash shape, and experiment-specific status rules. It never imports a browser, session factory, or ORM model.

Use this result contract:

```python
@dataclass(frozen=True, slots=True)
class LiveRunVerification:
    valid: bool
    issues: tuple[str, ...]
    experiment: str | None
    run_id: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": list(self.issues),
            "experiment": self.experiment,
            "run_id": self.run_id,
        }
```

- [ ] **Step 5: Implement fail-closed `run_smoke_command()`**

Use injected defaults in `main()` for tests:

```python
def main(
    argv: list[str] | None = None,
    *,
    session_factory=SessionLocal,
    repository: OfferTodayResearchRepository | None = None,
    runtime_factory=OfferTodayBrowserRuntime,
    service_factory=OfferTodayResearchLiveService,
    provenance_provider=capture_research_provenance,
    artifact_exporter=export_research_artifact,
    artifact_verifier=verify_research_artifact,
) -> int: ...
```

Lifecycle order:

```text
verify two parent artifacts
-> open DB
-> read staged/published run-start snapshots
-> create tagged running crawl job and research.run_started event
-> close DB transaction boundary
-> open one fresh-headless runtime
-> execute live service
-> close runtime
-> read run-end snapshots and require no staging/Job delta
-> finish crawl job with summary
-> load ordered events
-> close DB
-> capture provenance
-> export artifact
-> verify artifact
-> print one JSON result and return mapped exit code
```

Place artifact export in a `finally`-controlled helper that receives any partial event list. Persist only `unexpected_live_smoke_error:<ExceptionType>` for unexpected failures.

The live artifact metadata must include:

```python
{
    "experiment": "runtime-smoke",
    "crawl_job_id": run_id,
    "crawl_job_status": terminal_status,
    "parent_artifact_hash": baseline_gate.parent_artifact_hash,
    "request_budget": {"listing": 1, "detail": 20},
    "smoke_passed": decision.smoke_passed if decision is not None else False,
}
```

This gives `verify-run` an authoritative status to compare with the terminal summary.

- [ ] **Step 6: Run CLI and offline-regression tests**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_census_cli.py backend/tests/test_offertoday_research_stage_gate.py backend/tests/test_offertoday_research_cli.py backend/tests/test_offertoday_research_artifacts.py
```

Expected: all tests pass; the offline CLI remains browser-free.

- [ ] **Step 7: Commit Task 6**

```powershell
git add backend/app/sources/offertoday/research/stage_gate.py backend/scripts/offertoday_research_census.py backend/tests/test_offertoday_research_stage_gate.py
git add -f backend/tests/test_offertoday_research_census_cli.py
git diff --cached --check
git commit -m "feat(offertoday): expose plan 2 live smoke CLI"
```

---

### Task 7: Run the Pre-Live Deterministic Gate and Review the Smoke Implementation

**Files:**
- Verification only; production changes are allowed only when a failed test or review identifies a Plan 2 defect.

- [ ] **Step 1: Run the complete smoke-focused suite**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_staging_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_cli.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_canonical_and_identity.py
```

Expected: all tests pass with no xfail for request budget, stop conditions, identity, no-write behavior, partial export, or exception propagation.

- [ ] **Step 2: Re-run the Plan 1 focused contract suite**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_response_policy.py `
  backend/tests/test_offertoday_search_space.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_baseline.py `
  backend/tests/test_offertoday_research_conservation.py `
  backend/tests/test_offertoday_research_cli.py `
  backend/tests/test_offertoday_detail_pipeline.py `
  backend/tests/test_offertoday_standalone_crawl.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_canonical_and_identity.py `
  backend/tests/test_crawl_job_runtime.py `
  backend/tests/test_startup_recovery_service.py `
  backend/tests/test_offertoday_coverage_audit.py
```

Expected: all Plan 1 contracts remain green.

- [ ] **Step 3: Compile and lint the Plan 2 paths**

```powershell
python -m compileall -q `
  backend/app/sources/offertoday/research `
  backend/app/services/offertoday_research_live_service.py `
  backend/app/services/offertoday_research_staging_service.py `
  backend/scripts/offertoday_research.py `
  backend/scripts/offertoday_research_census.py

python -m ruff check `
  backend/app/sources/offertoday/research `
  backend/app/services/offertoday_research_live_service.py `
  backend/app/services/offertoday_research_staging_service.py `
  backend/scripts/offertoday_research_census.py `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_staging_service.py
```

Expected: exit code 0. Do not broaden lint cleanup into unrelated files.

- [ ] **Step 4: Audit the committed range and forbidden changes**

```powershell
git diff --check refs/codex/offertoday-plan2-base..HEAD
git diff --name-only refs/codex/offertoday-plan2-base..HEAD -- backend/alembic backend/app/models docker-compose.yml docker-compose.dev.yml .env .env.example
git status --short
```

Expected: no migration/model/Compose/env output; unrelated dirty files remain.

- [ ] **Step 5: Run two-stage review**

Request a spec review against the approved Plan 2 design, fix every gap, and re-review. Then request a code-quality review, fix every Critical/Important issue, and re-review. The review must explicitly confirm:

- offline CLI remains offline;
- exactly one listing and at most 20 details;
- no retries in the smoke;
- no smoke staging/Job/Company writes;
- same-browser detail fetching;
- partial artifact export on every exit;
- type-only unexpected failure persistence; and
- no later live stage starts automatically.

- [ ] **Step 6: Record the gate commit if review required changes**

If review changes were required, commit only those named files:

```powershell
git diff --cached --check
git commit -m "fix(offertoday): close live smoke review gaps"
```

If no changes were required, do not create an empty commit.

---

### Task 8: Capture Fresh Baselines and Execute the One-Listing/20-Detail Smoke

**Files:**
- Runtime evidence only under ignored `backend/runtime/offertoday-research/`.
- No source or test edits unless the smoke exposes a reproducible implementation defect.

> **Replacement-only gate:** Do not execute any step in this task until the deterministic compatibility plan is complete and reviewed and the user separately authorizes exactly one replacement smoke. The failed original run remains immutable evidence and does not satisfy Task 8.

- [ ] **Step 1: Confirm the database and browser prerequisites without contacting OfferToday**

```powershell
docker compose -f docker-compose.yml -f docker-compose.dev.yml ps postgres-db
git status --short --branch
Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue
```

Expected: PostgreSQL is healthy. No CDP listener is required because the approved smoke uses fresh headless mode. Do not start a crawl worker or manual browser for this smoke.

- [ ] **Step 2: Capture two new quiescent baselines**

Run this PowerShell block from the repository root:

```powershell
$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    $baseline1Raw = python backend/scripts/offertoday_research.py baseline `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research
    if ($LASTEXITCODE -ne 0) { throw "first baseline failed" }
    $baseline1 = $baseline1Raw | ConvertFrom-Json

    $baseline2Raw = python backend/scripts/offertoday_research.py baseline `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research
    if ($LASTEXITCODE -ne 0) { throw "second baseline failed" }
    $baseline2 = $baseline2Raw | ConvertFrom-Json

    if ($baseline1.run_id -eq $baseline2.run_id) { throw "baseline run IDs must differ" }
    if ($baseline1.data_hash -ne $baseline2.data_hash) { throw "baseline snapshot drifted" }
    if ($baseline1.inventory_data_hash -ne $baseline2.inventory_data_hash) { throw "baseline inventory drifted" }
} finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }
}
```

Expected: distinct run IDs and identical count/inventory hashes.

- [ ] **Step 3: Verify both baseline artifacts**

```powershell
$baselineArtifacts = @(
    Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
        ForEach-Object {
            $manifestPath = Join-Path $_.FullName 'manifest.json'
            if (Test-Path -LiteralPath $manifestPath) {
                $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
                if ($manifest.metadata.experiment -eq 'foundation-baseline') {
                    [pscustomobject]@{
                        Path = $_.FullName
                        CapturedAt = $manifest.provenance.captured_at
                    }
                }
            }
        } |
        Sort-Object CapturedAt -Descending |
        Select-Object -First 2
)
if ($baselineArtifacts.Count -ne 2) { throw "two baseline artifacts are required" }
python backend/scripts/offertoday_research.py verify-artifact --artifact $baselineArtifacts[0].Path
if ($LASTEXITCODE -ne 0) { throw "latest baseline artifact invalid" }
python backend/scripts/offertoday_research.py verify-artifact --artifact $baselineArtifacts[1].Path
if ($LASTEXITCODE -ne 0) { throw "previous baseline artifact invalid" }
```

Expected: both outputs contain `"valid": true`.

- [ ] **Step 4: Execute exactly one replacement live smoke command after authorization**

```powershell
$baselineArtifacts = @(
    Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
        ForEach-Object {
            $manifestPath = Join-Path $_.FullName 'manifest.json'
            if (Test-Path -LiteralPath $manifestPath) {
                $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
                if ($manifest.metadata.experiment -eq 'foundation-baseline') {
                    [pscustomobject]@{
                        Path = $_.FullName
                        CapturedAt = $manifest.provenance.captured_at
                    }
                }
            }
        } |
        Sort-Object CapturedAt -Descending |
        Select-Object -First 2
)
if ($baselineArtifacts.Count -ne 2) { throw "two baseline artifacts are required" }
$smokeRunId = [guid]::NewGuid().ToString()
$smokeArtifact = Join-Path 'backend/runtime/offertoday-research' $smokeRunId
$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    $smokeRaw = python backend/scripts/offertoday_research_census.py smoke `
        --baseline-artifact $baselineArtifacts[1].Path `
        --baseline-artifact $baselineArtifacts[0].Path `
        --run-id $smokeRunId `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research
    $smokeExit = $LASTEXITCODE
} finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $smokeArtifact 'manifest.json'))) {
    throw "smoke did not export its required partial artifact"
}
python backend/scripts/offertoday_research.py verify-artifact --artifact $smokeArtifact
if ($LASTEXITCODE -ne 0) { throw "smoke artifact invalid" }
[pscustomobject]@{
    RunId = $smokeRunId
    Artifact = $smokeArtifact
    ExitCode = $smokeExit
    Output = $smokeRaw
} | ConvertTo-Json -Depth 5
```

Interpret the result exactly:

```text
exit 0 = accepted smoke; continue only to artifact/DB verification
exit 3 = bounded smoke incomplete; stop Plan 2 live work
exit 4 = auth/WAF/IP/identity hard stop; stop Plan 2 live work
exit 5 = evidence or artifact failure; stop Plan 2 live work
```

Do not rerun automatically. A retry requires diagnosing the saved artifact and a new explicit live-run decision.

- [ ] **Step 5: Verify the smoke artifact even when the smoke did not pass**

```powershell
$smokeArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'runtime-smoke') {
                [pscustomobject]@{
                    Path = $_.FullName
                    CapturedAt = $manifest.provenance.captured_at
                }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $smokeArtifact) { throw "runtime-smoke artifact not found" }
python backend/scripts/offertoday_research.py verify-artifact --artifact $smokeArtifact.Path
```

Expected: `valid=true`. An invalid artifact is an evidence failure regardless of API outcome.

- [ ] **Step 6: Inspect the exact request and outcome counts offline**

```powershell
$smokeArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'runtime-smoke') {
                [pscustomobject]@{
                    Path = $_.FullName
                    CapturedAt = $manifest.provenance.captured_at
                }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $smokeArtifact) { throw "runtime-smoke artifact not found" }
$events = Get-Content (Join-Path $smokeArtifact.Path 'observations.jsonl') | ForEach-Object { $_ | ConvertFrom-Json }
$pageAttempts = @($events | Where-Object { $_.event_type -eq 'research.page_attempt' })
$detailAttempts = @($events | Where-Object { $_.event_type -eq 'research.detail_attempt' })
$summaries = @($events | Where-Object { $_.event_type -eq 'research.run_summary' })

if ($pageAttempts.Count -ne 1) { throw "smoke must contain exactly one listing attempt" }
if ($detailAttempts.Count -gt 20) { throw "smoke exceeded the 20-detail budget" }
if ($summaries.Count -ne 1) { throw "smoke must contain exactly one run summary" }
```

For exit 0, additionally require 20 detail attempts, `smoke_passed=true`, `listing_complete=false`, `expected_truncation=true`, and zero nonterminal failure classifications.

- [ ] **Step 7: Prove the smoke made no product-data writes**

Run this independent post-smoke block:

```powershell
$smokeArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'runtime-smoke') {
                [pscustomobject]@{
                    Path = $_.FullName
                    CapturedAt = $manifest.provenance.captured_at
                }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $smokeArtifact) { throw "runtime-smoke artifact not found" }
$summary = Get-Content (Join-Path $smokeArtifact.Path 'observations.jsonl') |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object { $_.event_type -eq 'research.run_summary' }
if (@($summary).Count -ne 1) { throw "exactly one smoke summary is required" }

$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    $post1 = (python backend/scripts/offertoday_research.py baseline `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "first post-smoke baseline failed" }
    $post2 = (python backend/scripts/offertoday_research.py baseline `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "second post-smoke baseline failed" }
} finally {
    if ($null -eq $previousDatabaseUrl) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:DATABASE_URL = $previousDatabaseUrl
    }
}

if ($post1.data_hash -ne $post2.data_hash) { throw "post-smoke snapshot drifted" }
if ($post1.inventory_data_hash -ne $post2.inventory_data_hash) { throw "post-smoke inventory drifted" }
if ($post2.data_hash -ne $summary.payload.run_end_snapshot_hash) { throw "external snapshot differs from smoke run-end" }
if ($post2.inventory_data_hash -ne $summary.payload.run_end_inventory_hash) { throw "external inventory differs from smoke run-end" }
```

Expected: both post-smoke baselines match each other and the smoke's run-end hashes. The live CLI's internal start/end assertion and this independent check together prove zero staging/Job/Company delta.

- [ ] **Step 8: Stop for the smoke review checkpoint**

Report:

- run ID and artifact path;
- listing classification, API code, row/valid-ID counts, and latency;
- frozen, attempted, success, terminal, failed, and unattempted detail counts;
- every non-success classification by target position;
- run-start/run-end database hashes;
- artifact verification result; and
- exact next-stage decision.

Do not execute Task 9 or any later live command until this report is accepted.

---

### Task 9: Add Deterministic Conservative Pacing and Bounded Stage Plans

**Files:**
- Modify: `backend/app/sources/offertoday/listing_runner.py:58-78,361-372,786-792`
- Create: `backend/app/sources/offertoday/research/calibration.py`
- Modify: `backend/tests/test_offertoday_listing_runner.py`
- Create: `backend/tests/test_offertoday_research_calibration.py`

This task starts only after a separately authorized replacement Task 8 smoke exits 0 and its smoke review is accepted. The original failed run does not satisfy this gate.

- [ ] **Step 1: Write failing page-delay range tests**

Add tests for:

```python
policy = ListingRetryPolicy(
    max_attempts_per_page=3,
    retry_delays_seconds=(5.0, 15.0),
    page_delay_seconds=0.0,
    page_delay_range_seconds=(3.0, 5.0),
)
runner = OfferTodayListingRunner(
    transport,
    sleep=fake_sleep,
    uniform=lambda lower, upper: 4.25,
)
```

Assert every successful page transition sleeps 4.25 seconds, retry sleeps remain exactly 5/15 seconds, invalid negative or reversed ranges fail at construction, and existing policies without a range remain unchanged.

- [ ] **Step 2: Implement the optional range**

Extend `ListingRetryPolicy`:

```python
page_delay_range_seconds: tuple[float, float] | None = None
```

Validate finite non-negative values and `lower <= upper`. Add `uniform: Callable[[float, float], float] = random.uniform` to the runner constructor. At a page transition:

```python
page_delay = retry_policy.page_delay_seconds
if retry_policy.page_delay_range_seconds is not None:
    lower, upper = retry_policy.page_delay_range_seconds
    page_delay = self._uniform(lower, upper)
if page_delay > 0:
    await self._sleep(page_delay)
```

- [ ] **Step 3: Write the exact calibration and pilot planners**

Tests must assert:

```python
build_calibration_conditions() == tuple(
    OfferTodayListingCondition(
        search_family="plan2_calibration",
        category_id=category_id,
        keyword="",
        endpoint=endpoint,
        rcd_type=rcd_type,
    )
    for category_id in (118000, 112000)
    for endpoint in ("search", "browse")
    for rcd_type in (7, None)
)
```

`build_pilot_conditions(endpoint, rcd_type)` must return exactly the canonical 31 `OFFERTODAY_CATEGORIES_L1` codes in registry order. Reject unknown endpoints and non-exact-integer `rcdType` values.

- [ ] **Step 4: Add bounded-stage acceptance**

Define:

```python
@dataclass(frozen=True, slots=True)
class BoundedConditionResult:
    condition: OfferTodayListingCondition
    listing_result: ListingRunResult
    planned_page_limit: int
    pages_observed: int
    accepted: bool
    rejection_reason: str | None
```

A condition is accepted when it either naturally exhausts within the bound or reaches the intentional `page_cap` after every planned page was successfully observed, with zero gaps/issues/conflicts and no batch-stop classification.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest -q backend/tests/test_offertoday_listing_runner.py backend/tests/test_offertoday_research_calibration.py
git add backend/app/sources/offertoday/listing_runner.py backend/app/sources/offertoday/research/calibration.py backend/tests/test_offertoday_listing_runner.py
git add -f backend/tests/test_offertoday_research_calibration.py
git diff --cached --check
git commit -m "feat(offertoday): plan bounded live calibration stages"
```

---

### Task 10: Implement and Gate the 24-Request Calibration Command

**Files:**
- Modify: `backend/app/services/offertoday_research_live_service.py`
- Modify: `backend/scripts/offertoday_research_census.py`
- Modify: `backend/tests/test_offertoday_research_live_service.py`
- Modify: `backend/tests/test_offertoday_research_census_cli.py`
- Modify: `backend/tests/test_offertoday_research_calibration.py`

- [ ] **Step 1: Write failing bounded-run service tests**

`run_bounded_conditions()` must invoke the shared runner once per condition so an intentional page cap does not prevent later calibration conditions. It stops the outer loop on the first rejected result. For each condition use page limit 3, no unique cap, empty confirmation disabled, three attempts, retry delays 5/15 seconds, and page-delay range 3-5 seconds.

Calibration uses `ResearchNoopListingStagingSink` and must preserve identical run-start/run-end staging and Job hashes. Its metadata budget is `listing_logical=24`, `listing_attempt_max=72`, and `detail=0`.

- [ ] **Step 2: Write failing calibration comparison tests**

Define `CalibrationVariantSummary` with endpoint, `rcdType`, logical pages, attempts, valid rows, distinct IDs, missing IDs, conflicts, latency, failure count, and unique IDs. Selection ordering is:

```text
accepted variants first
then fewer failures
then fewer identity defects
then more distinct IDs
then fewer attempts
then lower median latency
then endpoint and rcdType canonical order
```

Reject all variants when none is accepted; never choose by `data.total` alone.

Before ranking, reject an accepted variant when it uses more than twice the logical requests of another accepted variant but improves distinct-ID coverage against the calibration union by less than two percentage points. Persist the compared denominator and exact percentage-point delta.

- [ ] **Step 3: Add `calibrate` parser and predecessor gate**

Command:

```text
calibrate
  --smoke-artifact PATH
  --baseline-artifact PATH  # exactly twice
  [--run-id UUID]
  [--artifact-root PATH]
  [--repo-root PATH]
```

Require the smoke artifact summary to contain `smoke_passed=true`, exact listing/detail budgets, and a valid manifest. Run-start baselines must match again.

- [ ] **Step 4: Implement artifact/lifecycle behavior**

Reuse the Task 6 lifecycle helper. The calibration artifact records all 8 conditions and at most 24 logical pages plus bounded retries. It creates no detail requests. Preserve partial observations and stop immediately on auth/WAF/IP/identity hard stops.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_census_cli.py backend/tests/test_offertoday_research_calibration.py
git add backend/app/services/offertoday_research_live_service.py backend/scripts/offertoday_research_census.py backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_calibration.py
git add -f backend/tests/test_offertoday_research_census_cli.py
git diff --cached --check
git commit -m "feat(offertoday): calibrate live listing controls"
```

- [ ] **Step 6: Execute one calibration only after explicit smoke acceptance**

Run this single PowerShell block after the Task 8 review accepts the smoke:

```powershell
$smokeArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'runtime-smoke') {
                [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $smokeArtifact) { throw "accepted smoke artifact not found" }
python backend/scripts/offertoday_research_census.py verify-run --artifact $smokeArtifact.Path
if ($LASTEXITCODE -ne 0) { throw "smoke artifact did not pass verify-run" }

$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    $baselineA = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "calibration baseline A failed" }
    $baselineB = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "calibration baseline B failed" }
    if ($baselineA.data_hash -ne $baselineB.data_hash) { throw "calibration baseline snapshot drifted" }
    if ($baselineA.inventory_data_hash -ne $baselineB.inventory_data_hash) { throw "calibration baseline inventory drifted" }

    $runId = [guid]::NewGuid().ToString()
    $artifact = Join-Path 'backend/runtime/offertoday-research' $runId
    python backend/scripts/offertoday_research_census.py calibrate `
        --smoke-artifact $smokeArtifact.Path `
        --baseline-artifact $baselineA.artifact `
        --baseline-artifact $baselineB.artifact `
        --run-id $runId `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research
    $stageExit = $LASTEXITCODE
} finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue } else { $env:DATABASE_URL = $previousDatabaseUrl }
}
python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
if ($LASTEXITCODE -ne 0) { throw "calibration artifact invalid" }
if ($stageExit -ne 0) { throw "calibration did not pass; stop before pilot" }
```

Expected: verified accepted calibration artifact. Stop for review; do not start the pilot automatically.

---

### Task 11: Extract Globally Reconciled Staging and Implement the 31-Category Pilot

**Files:**
- Modify: `backend/app/services/offertoday_research_staging_service.py`
- Modify: `backend/scripts/offertoday_standalone_crawl.py:470-550`
- Modify: `backend/app/services/offertoday_research_live_service.py`
- Modify: `backend/scripts/offertoday_research_census.py`
- Modify: `backend/tests/test_offertoday_research_staging_service.py`
- Modify: `backend/tests/test_offertoday_standalone_crawl.py`
- Modify: `backend/tests/test_offertoday_research_live_service.py`
- Modify: `backend/tests/test_offertoday_research_census_cli.py`

- [ ] **Step 1: Move the production-equivalent staging payload builder under `app/`**

Write characterization tests around the current standalone `_build_listing_staging_payload()` and `OfferTodayCrawlStagingSink`. Move them without behavior changes to:

```python
build_offertoday_listing_staging_payload(...)
OfferTodayReconciledListingStagingSink(...)
```

Update standalone imports and prove its existing tests remain green.

- [ ] **Step 2: Enforce global at-most-once staging**

The research sink calls the existing `crawl_runtime.stage_listing_batch()` with `source_site="offertoday"` and `skip_existing=True`. OfferToday global reconciliation is already enforced inside that method; do not invent a second flag or duplicate its locking/query logic. Record:

```text
rows_seen
rows_created
published_source_job_ids
preexisting_staged_source_job_ids
created_source_job_ids
deferred_identity_conflict_ids
```

Tests must prove repeated conditions and repeated runs do not create another row for an existing canonical ID and that `rows_created / distinct newly staged <= 1.01`, including zero-denominator behavior.

- [ ] **Step 3: Add the `pilot` command**

Command:

```text
pilot
  --calibration-artifact PATH
  --baseline-artifact PATH  # exactly twice
  [--variant-rank 1]
  [--run-id UUID]
  [--artifact-root PATH]
  [--repo-root PATH]
```

The selected variant must come from the verified calibration artifact. Build exactly 31 conditions in registry order and run each to three pages or earlier natural exhaustion. No details are fetched.

Record the pilot budget as `listing_logical=93`, `listing_attempt_max=279`, and `detail=0`. A category that naturally exhausts before page 3 consumes fewer logical requests; the terminal summary records planned and actual values separately.

- [ ] **Step 4: Add pilot acceptance tests**

Require 31 condition results; each is either accepted bounded `page_cap` or natural exhaustion. Reject a missing category, duplicated category, gap, hard stop, identity issue/conflict, amplification violation, or artifact failure.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_staging_service.py backend/tests/test_offertoday_standalone_crawl.py backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_census_cli.py backend/tests/test_offertoday_research_calibration.py
git add backend/app/services/offertoday_research_staging_service.py backend/app/services/offertoday_research_live_service.py backend/scripts/offertoday_standalone_crawl.py backend/scripts/offertoday_research_census.py backend/tests/test_offertoday_standalone_crawl.py backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_calibration.py
git add -f backend/tests/test_offertoday_research_staging_service.py backend/tests/test_offertoday_research_census_cli.py
git diff --cached --check
git commit -m "feat(offertoday): run the bounded category pilot"
```

- [ ] **Step 6: Execute one pilot and stop for review**

```powershell
$calibrationArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'listing-calibration') {
                [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $calibrationArtifact) { throw "accepted calibration artifact not found" }
python backend/scripts/offertoday_research_census.py verify-run --artifact $calibrationArtifact.Path
if ($LASTEXITCODE -ne 0) { throw "calibration artifact invalid" }

$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    $baselineA = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "pilot baseline A failed" }
    $baselineB = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "pilot baseline B failed" }
    if ($baselineA.data_hash -ne $baselineB.data_hash) { throw "pilot baseline snapshot drifted" }
    if ($baselineA.inventory_data_hash -ne $baselineB.inventory_data_hash) { throw "pilot baseline inventory drifted" }

    $runId = [guid]::NewGuid().ToString()
    $artifact = Join-Path 'backend/runtime/offertoday-research' $runId
    python backend/scripts/offertoday_research_census.py pilot `
        --calibration-artifact $calibrationArtifact.Path `
        --baseline-artifact $baselineA.artifact `
        --baseline-artifact $baselineB.artifact `
        --variant-rank 1 `
        --run-id $runId `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research
    $stageExit = $LASTEXITCODE
} finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue } else { $env:DATABASE_URL = $previousDatabaseUrl }
}
python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
if ($LASTEXITCODE -ne 0) { throw "pilot artifact invalid" }
if ($stageExit -ne 0) { throw "pilot did not pass; stop before candidate freeze" }
```

Expected: verified accepted pilot with exactly 31 category outcomes. Inspect conservation and amplification in its terminal summary. Do not freeze or run a census automatically.

---

### Task 12: Freeze an Immutable Census Candidate

**Files:**
- Modify: `backend/app/sources/offertoday/research/live_contracts.py`
- Modify: `backend/app/sources/offertoday/research/calibration.py`
- Modify: `backend/scripts/offertoday_research_census.py`
- Modify: `backend/tests/test_offertoday_research_calibration.py`
- Modify: `backend/tests/test_offertoday_research_census_cli.py`

- [ ] **Step 1: Write failing candidate-contract tests**

Define:

```python
@dataclass(frozen=True, slots=True)
class CensusCandidate:
    endpoint: str
    rcd_type: int | None
    category_ids: tuple[int, ...]
    page_size: int
    max_pages_per_condition: int
    require_empty_confirmation: bool
    max_attempts_per_page: int
    retry_delays_seconds: tuple[float, ...]
    page_delay_range_seconds: tuple[float, float]
    session_mode: str
    fixed_repeat_category_ids: tuple[int, ...]
    source_artifact_hash: str
    rejected_variants: tuple[dict[str, Any], ...]

    @property
    def candidate_hash(self) -> str: ...
```

The hash is SHA-256 of sorted compact canonical JSON. Require exactly the 31 canonical categories, page size 50, max pages 500, empty confirmation true, three attempts, retry delays 5/15, pacing range 3-5, fresh-headless session unless a later separately approved session artifact proves another mode, and fixed-repeat categories `(118000, 112000, 127000)` for Information Technology, Engineering, and Science & Technology.

- [ ] **Step 2: Add `freeze-candidate` as a network-free command**

It accepts one verified pilot artifact, selects the accepted variant under the fixed comparison ordering, emits `candidate.json` inside a new artifact, verifies it, and makes no browser or database mutation.

- [ ] **Step 3: Test rejection evidence**

Every non-selected variant must include its exact failure, identity, cost, and latency evidence. A tie must resolve deterministically. Reject a pilot that did not cover all 31 categories.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_calibration.py backend/tests/test_offertoday_research_census_cli.py
git add backend/app/sources/offertoday/research/live_contracts.py backend/app/sources/offertoday/research/calibration.py backend/scripts/offertoday_research_census.py backend/tests/test_offertoday_research_calibration.py
git add -f backend/tests/test_offertoday_research_census_cli.py
git diff --cached --check
git commit -m "feat(offertoday): freeze the census candidate"
```

- [ ] **Step 5: Freeze one candidate from the accepted pilot**

```powershell
$pilotArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'category-pilot') {
                [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $pilotArtifact) { throw "accepted pilot artifact not found" }
$runId = [guid]::NewGuid().ToString()
$artifact = Join-Path 'backend/runtime/offertoday-research' $runId
python backend/scripts/offertoday_research_census.py freeze-candidate `
    --pilot-artifact $pilotArtifact.Path `
    --run-id $runId `
    --repo-root (Get-Location).Path `
    --artifact-root backend/runtime/offertoday-research
if ($LASTEXITCODE -ne 0) { throw "candidate freeze failed" }
python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
if ($LASTEXITCODE -ne 0) { throw "candidate artifact invalid" }
```

Expected: one verified `census-candidate` artifact with a deterministic candidate hash. Stop for candidate review before Task 13.

---

### Task 13: Run One Full Census to Confirmed Natural Exhaustion

**Files:**
- Modify: `backend/app/services/offertoday_research_live_service.py`
- Modify: `backend/scripts/offertoday_research_census.py`
- Modify: `backend/tests/test_offertoday_research_live_service.py`
- Modify: `backend/tests/test_offertoday_research_census_cli.py`
- Modify: `backend/tests/test_offertoday_research_conservation.py`

- [ ] **Step 1: Write failing full-census tests**

`run_census()` must pass all 31 frozen conditions to one shared runner with no unique cap, max pages 500, required empty confirmation, candidate retry/pacing controls, observation service, and reconciled staging sink. Assert the runner stops on the first incomplete condition and never labels `page_cap` complete.

- [ ] **Step 2: Add the `census` command**

Command:

```text
census
  --candidate-artifact PATH
  --baseline-artifact PATH  # exactly twice
  [--run-id UUID]
  [--artifact-root PATH]
  [--repo-root PATH]
```

The command rejects any mutable override for endpoint, `rcdType`, categories, pacing, retry, or cap. It loads the exact candidate hash from the artifact.

The safety budget is `listing_logical_max=15500`, `listing_attempt_max=46500`, and `detail=0` (31 conditions × 500 pages × 3 attempts). Natural exhaustion should consume far less; hitting either maximum is a failed `page_cap`, never success.

- [ ] **Step 3: Enforce full-run acceptance**

Require:

```text
31/31 condition outcomes present
31/31 naturally exhausted
gaps=0
identity_issues=0
identity_conflicts=0
conservation_difference=0
staging_amplification<=1.01
artifact_valid=true
```

Record per-condition and full-run ordered ID set hashes. Preserve partial evidence on all failures.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_census_cli.py backend/tests/test_offertoday_research_conservation.py
git add backend/app/services/offertoday_research_live_service.py backend/scripts/offertoday_research_census.py backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_conservation.py
git add -f backend/tests/test_offertoday_research_census_cli.py
git diff --cached --check
git commit -m "feat(offertoday): execute the full listing census"
```

- [ ] **Step 5: Execute census run 1 and stop for review**

Run only after candidate review:

```powershell
$candidateArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'census-candidate') {
                [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $candidateArtifact) { throw "reviewed census candidate not found" }
python backend/scripts/offertoday_research_census.py verify-run --artifact $candidateArtifact.Path
if ($LASTEXITCODE -ne 0) { throw "candidate artifact invalid" }

$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    $baselineA = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "census baseline A failed" }
    $baselineB = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "census baseline B failed" }
    if ($baselineA.data_hash -ne $baselineB.data_hash) { throw "census baseline snapshot drifted" }
    if ($baselineA.inventory_data_hash -ne $baselineB.inventory_data_hash) { throw "census baseline inventory drifted" }

    $runId = [guid]::NewGuid().ToString()
    $artifact = Join-Path 'backend/runtime/offertoday-research' $runId
    python backend/scripts/offertoday_research_census.py census `
        --candidate-artifact $candidateArtifact.Path `
        --baseline-artifact $baselineA.artifact `
        --baseline-artifact $baselineB.artifact `
        --run-id $runId `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research
    $stageExit = $LASTEXITCODE
} finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue } else { $env:DATABASE_URL = $previousDatabaseUrl }
}
python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
if ($LASTEXITCODE -ne 0) { throw "census run 1 artifact invalid" }
if ($stageExit -ne 0) { throw "census run 1 did not pass; do not schedule repeats" }
```

Expected: verified census artifact with 31 natural-exhaustion outcomes. Inspect database conservation and request-cost projection before scheduling repeats.

---

### Task 14: Compare Three Censuses and Separate Churn From Ranking Instability

**Files:**
- Create: `backend/app/sources/offertoday/research/stability.py`
- Create: `backend/tests/test_offertoday_research_stability.py`
- Modify: `backend/app/services/offertoday_research_live_service.py`
- Modify: `backend/tests/test_offertoday_research_live_service.py`
- Modify: `backend/scripts/offertoday_research_census.py`
- Modify: `backend/tests/test_offertoday_research_census_cli.py`

- [ ] **Step 1: Write failing set/statistic tests**

Implement and test:

```python
def canonical_id_set_hash(job_ids: Iterable[str]) -> str: ...

def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)

def coefficient_of_variation(values: Sequence[int]) -> float:
    if not values:
        raise ValueError("at least one value is required")
    mean = statistics.fmean(values)
    if mean == 0:
        return 0.0 if all(value == 0 for value in values) else math.inf
    return statistics.pstdev(values) / mean
```

Add exact added/removed cohorts, three pairwise Jaccards, fixed-cohort Jaccard, union hash, count CV, requests/new-ID, and seconds/new-ID tests.

- [ ] **Step 2: Add the offline `compare` command**

Command:

```text
compare
  --census-artifact PATH  # exactly three
  --fixed-repeat-artifact PATH  # exactly three
  [--run-id UUID]
  [--artifact-root PATH]
  [--repo-root PATH]
```

Require one candidate hash across every artifact, three distinct run IDs, at least two census time windows, verified manifests, and accepted run summaries.

Also add the command needed to produce the fixed-repeat inputs:

```text
repeat-fixed
  --candidate-artifact PATH
  --baseline-artifact PATH  # exactly twice
  --repeat-index {1,2,3}
  [--run-id UUID]
  [--artifact-root PATH]
  [--repo-root PATH]

```

`repeat-fixed` loads only candidate categories `(118000, 112000, 127000)`, runs them to confirmed natural exhaustion with the frozen candidate controls, and creates no detail requests. The Task 6 `verify-run` command continues to audit every generated artifact.

Each fixed repeat records `listing_logical_max=1500`, `listing_attempt_max=4500`, and `detail=0`; hitting a safety maximum fails the repeat.

- [ ] **Step 3: Implement the Plan 3 entry decision**

Accept only when:

```text
all three censuses accepted
fixed_cohort_jaccard >= 0.95
unique_count_cv <= 0.05
unresolved_gaps = 0
identity_conflicts = 0
conservation_difference = 0
unclassified_failures = 0
```

Output exact failing gates and cohorts when rejected.

- [ ] **Step 4: Run tests and commit**

```powershell
python -m pytest -q backend/tests/test_offertoday_research_stability.py backend/tests/test_offertoday_research_live_service.py backend/tests/test_offertoday_research_census_cli.py
git add backend/app/sources/offertoday/research/stability.py backend/app/services/offertoday_research_live_service.py backend/scripts/offertoday_research_census.py backend/tests/test_offertoday_research_live_service.py
git add -f backend/tests/test_offertoday_research_stability.py backend/tests/test_offertoday_research_census_cli.py
git diff --cached --check
git commit -m "feat(offertoday): compare repeated census evidence"
```

- [ ] **Step 5: Execute runs 2 and 3 across a second window**

Wait until the first accepted full-census artifact is at least six hours old. Do not implement this wait with a blocking sleep. When the second window opens, run this block; it recaptures matching baselines before each repeat and stops on the first failure:

```powershell
$candidateArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'census-candidate') {
                [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
$firstCensus = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'full-census') {
                [pscustomobject]@{ Path = $_.FullName; CapturedAt = [datetime]::Parse($manifest.provenance.captured_at) }
            }
        }
    } |
    Sort-Object CapturedAt |
    Select-Object -First 1
if ($null -eq $candidateArtifact -or $null -eq $firstCensus) { throw "candidate and census run 1 are required" }
if (((Get-Date).ToUniversalTime() - $firstCensus.CapturedAt.ToUniversalTime()).TotalHours -lt 6) {
    throw "second census window has not opened; wait without blocking this process"
}

function Invoke-CensusRepeat {
    param([int]$RepeatIndex)
    $baselineA = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "census repeat $RepeatIndex baseline A failed" }
    $baselineB = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "census repeat $RepeatIndex baseline B failed" }
    if ($baselineA.data_hash -ne $baselineB.data_hash) { throw "census repeat $RepeatIndex snapshot drifted" }
    if ($baselineA.inventory_data_hash -ne $baselineB.inventory_data_hash) { throw "census repeat $RepeatIndex inventory drifted" }
    $runId = [guid]::NewGuid().ToString()
    $artifact = Join-Path 'backend/runtime/offertoday-research' $runId
    python backend/scripts/offertoday_research_census.py census `
        --candidate-artifact $candidateArtifact.Path `
        --baseline-artifact $baselineA.artifact `
        --baseline-artifact $baselineB.artifact `
        --run-id $runId `
        --repo-root (Get-Location).Path `
        --artifact-root backend/runtime/offertoday-research
    if ($LASTEXITCODE -ne 0) { throw "census repeat $RepeatIndex failed" }
    python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
    if ($LASTEXITCODE -ne 0) { throw "census repeat $RepeatIndex artifact invalid" }
    return $artifact
}

$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    $census2 = Invoke-CensusRepeat -RepeatIndex 2
    $census3 = Invoke-CensusRepeat -RepeatIndex 3
} finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue } else { $env:DATABASE_URL = $previousDatabaseUrl }
}
```

Expected: two additional verified `full-census` artifacts with the identical candidate hash.

- [ ] **Step 6: Execute three fixed-condition repeats in one short window**

Run this block once after census run 3. Each repeat recaptures matching baselines and uses only candidate categories `(118000, 112000, 127000)`:

```powershell
$candidateArtifact = Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
    ForEach-Object {
        $manifestPath = Join-Path $_.FullName 'manifest.json'
        if (Test-Path -LiteralPath $manifestPath) {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.metadata.experiment -eq 'census-candidate') {
                [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
            }
        }
    } |
    Sort-Object CapturedAt -Descending |
    Select-Object -First 1
if ($null -eq $candidateArtifact) { throw "candidate artifact not found" }

$previousDatabaseUrl = $env:DATABASE_URL
try {
    $env:DATABASE_URL = 'postgresql://admin:dev_password@localhost:5433/jobsdb'
    foreach ($repeatIndex in 1..3) {
        $baselineA = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw "fixed repeat $repeatIndex baseline A failed" }
        $baselineB = (python backend/scripts/offertoday_research.py baseline --repo-root (Get-Location).Path --artifact-root backend/runtime/offertoday-research) | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw "fixed repeat $repeatIndex baseline B failed" }
        if ($baselineA.data_hash -ne $baselineB.data_hash) { throw "fixed repeat $repeatIndex snapshot drifted" }
        if ($baselineA.inventory_data_hash -ne $baselineB.inventory_data_hash) { throw "fixed repeat $repeatIndex inventory drifted" }
        $runId = [guid]::NewGuid().ToString()
        $artifact = Join-Path 'backend/runtime/offertoday-research' $runId
        python backend/scripts/offertoday_research_census.py repeat-fixed `
            --candidate-artifact $candidateArtifact.Path `
            --baseline-artifact $baselineA.artifact `
            --baseline-artifact $baselineB.artifact `
            --repeat-index $repeatIndex `
            --run-id $runId `
            --repo-root (Get-Location).Path `
            --artifact-root backend/runtime/offertoday-research
        if ($LASTEXITCODE -ne 0) { throw "fixed repeat $repeatIndex failed" }
        python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
        if ($LASTEXITCODE -ne 0) { throw "fixed repeat $repeatIndex artifact invalid" }
    }
} finally {
    if ($null -eq $previousDatabaseUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue } else { $env:DATABASE_URL = $previousDatabaseUrl }
}
```

- [ ] **Step 7: Produce and verify the comparison artifact**

```powershell
$censusArtifacts = @(
    Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
        ForEach-Object {
            $manifestPath = Join-Path $_.FullName 'manifest.json'
            if (Test-Path -LiteralPath $manifestPath) {
                $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
                if ($manifest.metadata.experiment -eq 'full-census') {
                    [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
                }
            }
        } |
        Sort-Object CapturedAt -Descending |
        Select-Object -First 3
)
$fixedArtifacts = @(
    Get-ChildItem 'backend/runtime/offertoday-research' -Directory |
        ForEach-Object {
            $manifestPath = Join-Path $_.FullName 'manifest.json'
            if (Test-Path -LiteralPath $manifestPath) {
                $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
                if ($manifest.metadata.experiment -eq 'fixed-condition-repeat') {
                    [pscustomobject]@{ Path = $_.FullName; CapturedAt = $manifest.provenance.captured_at }
                }
            }
        } |
        Sort-Object CapturedAt -Descending |
        Select-Object -First 3
)
if ($censusArtifacts.Count -ne 3 -or $fixedArtifacts.Count -ne 3) { throw "three census and three fixed-repeat artifacts are required" }
$runId = [guid]::NewGuid().ToString()
$artifact = Join-Path 'backend/runtime/offertoday-research' $runId
$arguments = @('backend/scripts/offertoday_research_census.py', 'compare', '--run-id', $runId, '--repo-root', (Get-Location).Path, '--artifact-root', 'backend/runtime/offertoday-research')
foreach ($item in $censusArtifacts) { $arguments += @('--census-artifact', $item.Path) }
foreach ($item in $fixedArtifacts) { $arguments += @('--fixed-repeat-artifact', $item.Path) }
python @arguments
if ($LASTEXITCODE -ne 0) { throw "Plan 2 comparison failed its entry gate" }
python backend/scripts/offertoday_research_census.py verify-run --artifact $artifact
if ($LASTEXITCODE -ne 0) { throw "comparison artifact invalid" }
```

Do not proceed to Plan 3 when any comparison gate fails.

---

### Task 15: Run the Plan 2 Verification and Handoff Gate

**Files:**
- Verification and decision-record files only.
- Create after live completion: `docs/superpowers/reports/2026-07-11-offertoday-plan2-census-decision.md`

- [ ] **Step 1: Run all Plan 2 deterministic tests**

```powershell
python -m pytest -q `
  backend/tests/test_offertoday_research_stage_gate.py `
  backend/tests/test_offertoday_research_smoke.py `
  backend/tests/test_offertoday_research_live_service.py `
  backend/tests/test_offertoday_research_census_cli.py `
  backend/tests/test_offertoday_research_calibration.py `
  backend/tests/test_offertoday_research_staging_service.py `
  backend/tests/test_offertoday_research_stability.py `
  backend/tests/test_offertoday_research_observation_service.py `
  backend/tests/test_offertoday_research_artifacts.py `
  backend/tests/test_offertoday_research_baseline.py `
  backend/tests/test_offertoday_research_conservation.py `
  backend/tests/test_offertoday_listing_runner.py `
  backend/tests/test_offertoday_browser_runtime.py `
  backend/tests/test_offertoday_canonical_and_identity.py
```

Expected: all pass.

- [ ] **Step 2: Run the complete backend suite**

```powershell
python -m pytest -q backend/tests
```

Expected: all collected backend tests pass. Record exact pre-existing unrelated failures without modifying unrelated code.

- [ ] **Step 3: Verify every accepted artifact**

Run `verify-artifact` for the two baseline artifacts, smoke, calibration, pilot, candidate, all census runs, all fixed-repeat runs, and the comparison artifact. Require `valid=true` for every path.

- [ ] **Step 4: Recompute acceptance metrics from JSONL**

Do not trust report prose. Re-run the offline compare command, confirm set hashes, Jaccard, CV, gaps, identity conflicts, conservation, staging amplification, and request cost from saved events.

- [ ] **Step 5: Verify scope and production defaults**

```powershell
git diff --name-only refs/codex/offertoday-plan2-base..HEAD -- backend/alembic backend/app/models docker-compose.yml docker-compose.dev.yml .env .env.example
python -m pytest -q backend/tests/test_offertoday_search_space.py::test_default_conditions_keep_stable_family_order_and_endpoint_semantics backend/tests/test_offertoday_standalone_crawl.py::test_run_listing_phase_preflights_once_and_uses_shared_default_it_policies backend/tests/test_offertoday_coverage_audit.py::test_target_threshold_is_diagnostic_only_and_never_caps_runner
git diff --check refs/codex/offertoday-plan2-base..HEAD
git status --short
```

Expected: no forbidden files, three default-policy tests pass, diff check is clean, and unrelated dirty work remains.

- [ ] **Step 6: Write the decision record**

The report must contain:

- immutable artifact paths/hashes and run timestamps;
- exact chosen/rejected endpoint and `rcdType` variants;
- smoke 20-detail classifications without claiming Plan 4 acceptance;
- per-category pilot and census counts;
- three-run and union set hashes;
- fixed-cohort Jaccard and count CV;
- gaps, identity, conservation, and amplification results;
- request/latency cost;
- every failing gate and exact cohort when not accepted; and
- a statement that production defaults remain unchanged.

- [ ] **Step 7: Run final spec and quality reviews**

Review the full Plan 2 range and the decision record. Fix and re-review every Critical/Important issue before declaring Plan 2 complete.

- [ ] **Step 8: Commit the decision record only after evidence is final**

```powershell
git add -f docs/superpowers/reports/2026-07-11-offertoday-plan2-census-decision.md
git diff --cached --check
git commit -m "docs(offertoday): record plan 2 census decision"
```

Do not commit runtime artifacts.

---

## Verification Matrix

| Claim | Required evidence |
|---|---|
| Offline Plan 1 CLI remains offline | Import-guard and subprocess tests |
| Live smoke is exactly bounded | One page attempt, at most 20 detail events, no retries |
| Twenty targets are canonical and distinct | Accepted-ID first-seen cohort fixture |
| Smoke uses one browser | Injected runtime fetcher and lifecycle test |
| Code 2520 is terminal but does not stop the cohort | Detail-loop fixture |
| Auth/WAF/IP/ID mismatch stops later targets | Batch-stop/unattempted fixtures |
| Unexpected exceptions are not mislabeled | Same-object propagation and type-only persistence tests |
| Smoke cannot write product data | No-op sink, run-start/end hashes, independent baselines |
| Bounded pilot is not called complete | Preserved `page_cap` and separate bounded acceptance |
| Endpoint/`rcdType` choice is evidence-backed | Calibration artifact and deterministic ranking |
| Every category is covered | Exact ordered 31-category fixtures |
| Full censuses naturally exhaust | 31 confirmed condition outcomes with empty confirmation |
| Repeated runs are stable | Jaccard >= 0.95 and CV <= 0.05 |
| Conservation remains exact | Per-run replay with zero difference |
| Production policy is unchanged | Default-policy tests and forbidden-range diff |

## Immediate Execution Stop

The original Task 8 attempt did not satisfy the operational smoke gate. Completion now requires the deterministic compatibility correction plus a separately authorized replacement smoke that passes and is reviewed. Tasks 9–15 remain the approved detailed Plan 2 path, but no later live stage begins without acceptance of that replacement Task 8 artifact.
