#!/usr/bin/env python3
"""Stage-gated live OfferToday Plan 2 research commands."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

BACKEND = str(Path(__file__).resolve().parents[1])
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.database import SessionLocal  # noqa: E402
from app.repositories.offertoday_research_repository import (  # noqa: E402
    OfferTodayResearchRepository,
)
from app.scraper.offertoday_browser_runtime import (  # noqa: E402
    OfferTodayBrowserRuntime,
)
from app.services.crawl_job_runtime import CrawlJobRuntime  # noqa: E402
from app.services.offertoday_research_live_service import (  # noqa: E402
    OfferTodayResearchLiveService,
)
from app.services.offertoday_research_observation_service import (  # noqa: E402
    OfferTodayResearchObservationService,
)
from app.services.offertoday_research_staging_service import (  # noqa: E402
    OfferTodayReconciledListingStagingSink,
    ResearchNoopListingStagingSink,
)
from app.sources.offertoday.listing_runner import (  # noqa: E402
    listing_observation_to_payload,
)
from app.sources.offertoday.research.artifacts import (  # noqa: E402
    capture_research_provenance,
    export_research_artifact,
    verify_research_artifact,
)
from app.sources.offertoday.research.baseline import (  # noqa: E402
    build_baseline_snapshot,
    build_run_start_inventory,
)
from app.sources.offertoday.research.calibration import (  # noqa: E402
    CalibrationVariantSummary,
    build_calibration_conditions,
    build_census_candidate,
    build_pilot_conditions,
    select_calibration_variants,
    summarize_calibration_variants,
)
from app.sources.offertoday.research.conservation import (  # noqa: E402
    build_listing_conservation_report,
)
from app.sources.offertoday.research.contracts import ResearchMetadata  # noqa: E402
from app.sources.offertoday.research.live_contracts import (  # noqa: E402
    CensusCandidate,
    DiscoveryCandidateV2,
    DiscoveryPolicyCandidateV2,
)
from app.sources.offertoday.research.phase_d import (  # noqa: E402
    DISCOVERY_POLICY_CANDIDATE_EXPERIMENT,
    PHASE_D_CENSUS_EXPERIMENT,
    PHASE_D_FIXED_REPEAT_EXPERIMENT,
    PhaseDProductEvidence,
    PhaseDStagingEvidence,
    build_discovery_policy_candidate_v2,
    build_phase_d_run_evidence,
    discovery_policy_candidate_artifact_payload,
    phase_d_run_artifact_payload,
    validate_discovery_policy_candidate_artifact_payload,
)
from app.sources.offertoday.research.phase_d_stage_gate import (  # noqa: E402
    build_phase_d_comparison_artifact_payload,
    phase_d_artifact_events,
    phase_d_artifact_reference,
    phase_d_metadata,
)
from app.sources.offertoday.research.pagination_bakeoff import (  # noqa: E402
    BAKEOFF_CATEGORY_IDS,
    BAKEOFF_ENDPOINT,
    BAKEOFF_MAX_ATTEMPTS_PER_PAGE,
    BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION,
    BAKEOFF_PAGE_DELAY_RANGE_SECONDS,
    BAKEOFF_RCD_TYPE,
    BAKEOFF_REQUIRE_EMPTY_CONFIRMATION,
    BAKEOFF_RETRY_DELAYS_SECONDS,
    BAKEOFF_SESSION_MODE,
    BAKEOFF_TERMINAL_POLICY,
    BAKEOFF_VARIANTS,
    canonical_bakeoff_payload_hash,
    compare_bakeoff_payloads,
    pagination_bakeoff_controls_payload,
    pagination_bakeoff_thresholds_payload,
    pagination_bakeoff_to_payload,
    validate_bakeoff_payload,
)
from app.sources.offertoday.research.pagination_stage_gate import (  # noqa: E402
    PAGINATION_BAKEOFF_REQUEST_BUDGET,
    validate_pagination_comparison_parents,
)
from app.sources.offertoday.research.partition_research import (  # noqa: E402
    ENDPOINT_PROBE_EXPERIMENT,
    OFFERTODAY_PARTITION_CATALOG,
    PARTITION_PROBE_EXPERIMENT,
    EndpointProbePlan,
    PhaseCProbeExecution,
    build_partition_probe_plan,
    canonical_phase_c_hash,
)
from app.sources.offertoday.research.partition_stage_gate import (  # noqa: E402
    PhaseCArtifactReference,
    PhaseCBaselineReference,
    PhaseCNoWriteEvidence,
    build_partition_comparison_artifact_payload,
    build_partition_probe_parent_projection,
    build_phase_c_probe_artifact_payload,
    phase_c_artifact_events,
    phase_c_artifact_reference,
    phase_c_comparison_metadata,
    phase_c_comparison_summary,
    phase_c_probe_metadata,
    phase_c_probe_summary,
    validate_partition_comparison_artifact_payload,
    validate_phase_c_probe_artifact_payload,
)
from app.sources.offertoday.research.smoke import (  # noqa: E402
    runtime_smoke_request_budget,
)
from app.sources.offertoday.research.stability import (  # noqa: E402
    StabilityRun,
    compare_stability,
)
from app.sources.offertoday.research.stage_gate import (  # noqa: E402
    MatchingBaselineGate,
    require_matching_baselines,
    verify_live_research_run,
)
from app.utils.time import utc_now  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INCOMPLETE = 3
EXIT_HARD_STOP = 4
EXIT_EVIDENCE_FAILURE = 5

_HARD_STOP_REASONS = {
    "auth_expired",
    "waf_challenge",
    "ip_blocked",
    "id_mismatch",
    "listing_auth_expired",
    "listing_waf_challenge",
    "listing_ip_blocked",
    "listing_id_mismatch",
}
_CALIBRATION_REQUEST_BUDGET = {
    "listing_logical": 24,
    "listing_attempt_max": 72,
    "detail": 0,
}
_PILOT_REQUEST_BUDGET = {
    "listing_logical": 93,
    "listing_attempt_max": 279,
    "detail": 0,
}
_CENSUS_REQUEST_BUDGET = {
    "listing_logical": 15_500,
    "listing_attempt_max": 46_500,
    "detail": 0,
}
_FIXED_REPEAT_REQUEST_BUDGET = {
    "listing_logical": 1_500,
    "listing_attempt_max": 4_500,
    "detail": 0,
}
_MIN_CENSUS_WINDOW_SECONDS = 6 * 60 * 60
_PLAYWRIGHT_STORAGE_STATE_FIELDS = {"cookies", "origins"}
_PLAYWRIGHT_COOKIE_STRING_FIELDS = ("name", "value", "domain", "path")


@dataclass(frozen=True, slots=True)
class PilotVariantEvidence:
    endpoint: str
    rcd_type: int | None
    variant_rank: int
    parent_artifact_hash: str
    calibration_run_id: str


@dataclass(frozen=True, slots=True)
class CensusCandidateEvidence:
    candidate: CensusCandidate
    candidate_hash: str
    parent_artifact_hash: str
    candidate_run_id: str


@dataclass(frozen=True, slots=True)
class PhaseDPolicyEvidence:
    candidate: DiscoveryPolicyCandidateV2
    candidate_hash: str
    manifest_hash: str
    run_id: str


@dataclass(frozen=True, slots=True)
class SavedSessionState:
    path: Path
    sha256: str


@dataclass(frozen=True, slots=True)
class StabilityArtifactEvidence:
    artifact_dir: Path
    manifest_hash: str
    experiment: str
    candidate_hash: str
    captured_at: datetime
    run: StabilityRun
    listing_logical_count: int
    retry_count: int
    stop_reason: str | None
    repeat_index: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifact": str(self.artifact_dir),
            "manifest_hash": self.manifest_hash,
            "experiment": self.experiment,
            "candidate_hash": self.candidate_hash,
            "captured_at": self.captured_at.isoformat(),
            "listing_logical_count": self.listing_logical_count,
            "retry_count": self.retry_count,
            "stop_reason": self.stop_reason,
            "repeat_index": self.repeat_index,
            **self.run.to_payload(),
        }


@dataclass(frozen=True, slots=True)
class StabilityInputs:
    census_runs: tuple[StabilityArtifactEvidence, ...]
    fixed_repeat_runs: tuple[StabilityArtifactEvidence, ...]
    candidate_hash: str
    census_window_span_seconds: float
    fixed_window_span_seconds: float


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
    calibrate = commands.add_parser("calibrate")
    calibrate.add_argument("--smoke-artifact", type=Path, required=True)
    calibrate.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    calibrate.add_argument("--run-id", default=None)
    calibrate.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    calibrate.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    pilot = commands.add_parser("pilot")
    pilot.add_argument("--calibration-artifact", type=Path, required=True)
    pilot.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    pilot.add_argument("--variant-rank", type=int, default=1)
    pilot.add_argument("--run-id", default=None)
    pilot.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    pilot.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    census = commands.add_parser("census")
    census.add_argument("--candidate-artifact", type=Path, required=True)
    census.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    census.add_argument("--run-id", default=None)
    census.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    census.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    repeat_fixed = commands.add_parser("repeat-fixed")
    repeat_fixed.add_argument("--candidate-artifact", type=Path, required=True)
    repeat_fixed.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    repeat_fixed.add_argument(
        "--repeat-index",
        type=int,
        choices=(1, 2, 3),
        required=True,
    )
    repeat_fixed.add_argument("--run-id", default=None)
    repeat_fixed.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    repeat_fixed.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    compare = commands.add_parser("compare")
    compare.add_argument(
        "--census-artifact",
        action="append",
        type=Path,
        required=True,
    )
    compare.add_argument(
        "--fixed-repeat-artifact",
        action="append",
        type=Path,
        required=True,
    )
    compare.add_argument("--run-id", default=None)
    compare.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    compare.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    freeze = commands.add_parser("freeze-candidate")
    freeze.add_argument("--pilot-artifact", type=Path, required=True)
    freeze.add_argument("--run-id", default=None)
    freeze.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    freeze.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    pagination_bakeoff = commands.add_parser("pagination-bakeoff")
    pagination_bakeoff.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    pagination_bakeoff.add_argument(
        "--repeat-index",
        type=int,
        choices=(1, 2),
        required=True,
    )
    pagination_bakeoff.add_argument("--order-seed", type=int, required=True)
    pagination_bakeoff.add_argument("--run-id", default=None)
    pagination_bakeoff.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    pagination_bakeoff.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    compare_pagination = commands.add_parser("compare-pagination")
    compare_pagination.add_argument(
        "--bakeoff-artifact",
        action="append",
        type=Path,
        required=True,
    )
    compare_pagination.add_argument("--run-id", default=None)
    compare_pagination.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    compare_pagination.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    freeze_discovery = commands.add_parser("freeze-discovery-candidate")
    freeze_discovery.add_argument(
        "--comparison-artifact",
        type=Path,
        required=True,
    )
    freeze_discovery.add_argument("--run-id", default=None)
    freeze_discovery.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    freeze_discovery.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    probe_endpoints = commands.add_parser("probe-endpoints")
    probe_endpoints.add_argument(
        "--phase-b-comparison-artifact",
        type=Path,
        required=True,
    )
    probe_endpoints.add_argument(
        "--endpoint-contract-id",
        action="append",
        required=True,
    )
    probe_endpoints.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    probe_endpoints.add_argument(
        "--confirm-live-research",
        action="store_true",
        required=True,
    )
    probe_endpoints.add_argument("--auth-state", type=Path, required=True)
    probe_endpoints.add_argument("--run-id", default=None)
    probe_endpoints.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    probe_endpoints.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    probe_partitions = commands.add_parser("probe-partitions")
    probe_partitions.add_argument(
        "--endpoint-probe-artifact",
        type=Path,
        required=True,
    )
    probe_partitions.add_argument(
        "--endpoint-contract-id",
        required=True,
    )
    probe_partitions.add_argument(
        "--partition-id",
        action="append",
        required=True,
    )
    probe_partitions.add_argument(
        "--max-pages-per-condition",
        type=int,
        choices=range(1, 11),
        required=True,
    )
    probe_partitions.add_argument(
        "--baseline-artifact",
        action="append",
        type=Path,
        required=True,
    )
    probe_partitions.add_argument(
        "--confirm-live-research",
        action="store_true",
        required=True,
    )
    probe_partitions.add_argument("--auth-state", type=Path, required=True)
    probe_partitions.add_argument("--run-id", default=None)
    probe_partitions.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    probe_partitions.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    compare_partitions = commands.add_parser("compare-partitions")
    compare_partitions.add_argument(
        "--partition-probe-artifact",
        action="append",
        type=Path,
        required=True,
    )
    compare_partitions.add_argument("--run-id", default=None)
    compare_partitions.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    compare_partitions.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    freeze_policy = commands.add_parser("freeze-discovery-policy")
    freeze_policy.add_argument(
        "--phase-b-comparison-artifact",
        type=Path,
        required=True,
    )
    freeze_policy.add_argument(
        "--endpoint-probe-artifact",
        type=Path,
        required=True,
    )
    freeze_policy.add_argument(
        "--partition-probe-artifact",
        action="append",
        type=Path,
        required=True,
    )
    freeze_policy.add_argument(
        "--partition-comparison-artifact",
        type=Path,
        required=True,
    )
    freeze_policy.add_argument("--run-id", default=None)
    freeze_policy.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    freeze_policy.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    for command_name in ("census-v2", "repeat-fixed-v2"):
        phase_d_live = commands.add_parser(command_name)
        phase_d_live.add_argument("--candidate-artifact", type=Path, required=True)
        phase_d_live.add_argument(
            "--baseline-artifact",
            action="append",
            type=Path,
            required=True,
        )
        phase_d_live.add_argument(
            "--run-index",
            type=int,
            choices=(1, 2, 3),
            required=True,
        )
        phase_d_live.add_argument("--window-id", required=True)
        phase_d_live.add_argument(
            "--staging-mode",
            choices=("noop", "reconciled"),
            required=True,
        )
        phase_d_live.add_argument(
            "--confirm-live-research",
            action="store_true",
            required=True,
        )
        phase_d_live.add_argument("--auth-state", type=Path, required=True)
        phase_d_live.add_argument(
            "--confirm-staging-writes",
            action="store_true",
        )
        phase_d_live.add_argument("--run-id", default=None)
        phase_d_live.add_argument(
            "--artifact-root",
            type=Path,
            default=Path("backend/runtime/offertoday-research"),
        )
        phase_d_live.add_argument(
            "--repo-root",
            type=Path,
            default=Path(__file__).resolve().parents[2],
        )
    compare_phase_d = commands.add_parser("compare-stability-v2")
    compare_phase_d.add_argument(
        "--census-artifact",
        action="append",
        type=Path,
        required=True,
    )
    compare_phase_d.add_argument(
        "--fixed-repeat-artifact",
        action="append",
        type=Path,
        required=True,
    )
    compare_phase_d.add_argument(
        "--active-holdout-id",
        action="append",
        default=[],
    )
    compare_phase_d.add_argument("--run-id", default=None)
    compare_phase_d.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("backend/runtime/offertoday-research"),
    )
    compare_phase_d.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    verify = commands.add_parser("verify-run")
    verify.add_argument("--artifact", type=Path, required=True)
    return parser


def _print_json(value: dict[str, Any], *, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=True, sort_keys=True), file=stream)


def _is_playwright_storage_state(payload: Any) -> bool:
    if not isinstance(payload, dict) or set(payload) != _PLAYWRIGHT_STORAGE_STATE_FIELDS:
        return False
    cookies = payload["cookies"]
    origins = payload["origins"]
    if not isinstance(cookies, list) or not isinstance(origins, list):
        return False
    for cookie in cookies:
        if not isinstance(cookie, dict) or any(
            not isinstance(cookie.get(field_name), str)
            for field_name in _PLAYWRIGHT_COOKIE_STRING_FIELDS
        ):
            return False
        expires = cookie.get("expires")
        if (
            isinstance(expires, bool)
            or not isinstance(expires, (int, float))
            or not isinstance(cookie.get("httpOnly"), bool)
            or not isinstance(cookie.get("secure"), bool)
            or cookie.get("sameSite") not in {"Strict", "Lax", "None"}
        ):
            return False
    for origin in origins:
        if (
            not isinstance(origin, dict)
            or not isinstance(origin.get("origin"), str)
            or not origin["origin"].strip()
            or not isinstance(origin.get("localStorage"), list)
        ):
            return False
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not isinstance(item.get("value"), str)
            for item in origin["localStorage"]
        ):
            return False
    return True


def _require_saved_session_state(path: Path) -> SavedSessionState:
    try:
        resolved_path = Path(path).expanduser().resolve(strict=True)
        if not resolved_path.is_file():
            raise ValueError
        payload_bytes = resolved_path.read_bytes()
        payload = json.loads(payload_bytes)
    except (OSError, RuntimeError, TypeError, UnicodeDecodeError, ValueError):
        raise ValueError(
            "auth state must be a readable valid Playwright storage-state JSON file"
        ) from None
    if not _is_playwright_storage_state(payload):
        raise ValueError(
            "auth state must be a readable valid Playwright storage-state JSON file"
        )
    return SavedSessionState(
        path=resolved_path,
        sha256=hashlib.sha256(payload_bytes).hexdigest(),
    )


def _bind_saved_session_runtime_factory(runtime_factory, state: SavedSessionState):
    def saved_session_runtime_factory(*args, **kwargs):
        try:
            current_hash = hashlib.sha256(state.path.read_bytes()).hexdigest()
        except OSError:
            raise ValueError("auth state became unreadable after validation") from None
        if current_hash != state.sha256:
            raise ValueError("auth state changed after validation")
        if "auth_state_path" in kwargs:
            raise ValueError("runtime auth state must be bound by the live command")
        return runtime_factory(
            *args,
            auth_state_path=str(state.path),
            **kwargs,
        )

    return saved_session_runtime_factory


def _require_accepted_smoke_artifact(artifact_dir: Path) -> dict[str, Any]:
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError("smoke artifact failed strict verification")
    manifest_path = Path(artifact_dir) / "manifest.json"
    observations_path = Path(artifact_dir) / "observations.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    summaries = [
        event.get("payload")
        for line in observations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        and (event := json.loads(line)).get("event_type") == "research.run_summary"
    ]
    expected_budget = runtime_smoke_request_budget()
    metadata = manifest.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("smoke_passed") is not True
        or metadata.get("request_budget") != expected_budget
        or len(summaries) != 1
        or not isinstance(summaries[0], dict)
        or summaries[0].get("smoke_passed") is not True
        or summaries[0].get("request_budget") != expected_budget
    ):
        raise ValueError("smoke artifact is not an accepted 2/20 predecessor")
    return manifest


def _require_accepted_calibration_variant(
    artifact_dir: Path,
    *,
    variant_rank: int,
) -> PilotVariantEvidence:
    if type(variant_rank) is not int or variant_rank < 1:
        raise ValueError("selected variant rank must be a positive exact integer")
    artifact_dir = Path(artifact_dir)
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError("calibration artifact failed strict verification")
    manifest_bytes = (artifact_dir / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    observations = [
        json.loads(line)
        for line in (artifact_dir / "observations.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    metadata = manifest.get("metadata")
    summaries = [
        event.get("payload")
        for event in observations
        if isinstance(event, dict) and event.get("event_type") == "research.run_summary"
    ]
    if (
        not isinstance(metadata, dict)
        or metadata.get("experiment") != "listing-calibration"
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("calibration_passed") is not True
        or len(summaries) != 1
        or not isinstance(summaries[0], dict)
        or summaries[0].get("calibration_passed") is not True
    ):
        raise ValueError("calibration artifact is not an accepted predecessor")
    selection = summaries[0].get("selection")
    selected_variants = (
        selection.get("selected_variants") if isinstance(selection, dict) else None
    )
    if not isinstance(selected_variants, list) or variant_rank > len(selected_variants):
        raise ValueError("selected variant rank is not present in calibration artifact")
    selected = selected_variants[variant_rank - 1]
    if not isinstance(selected, dict) or selected.get("accepted") is not True:
        raise ValueError("selected variant rank is not accepted")
    endpoint = selected.get("endpoint")
    rcd_type = selected.get("rcd_type")
    if not isinstance(endpoint, str) or (
        rcd_type is not None and type(rcd_type) is not int
    ):
        raise ValueError("selected calibration variant controls are invalid")
    build_pilot_conditions(endpoint, rcd_type)
    calibration_run_id = manifest.get("run_id")
    if not isinstance(calibration_run_id, str):
        raise ValueError("calibration artifact is missing run_id")
    return PilotVariantEvidence(
        endpoint=endpoint,
        rcd_type=rcd_type,
        variant_rank=variant_rank,
        parent_artifact_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        calibration_run_id=calibration_run_id,
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _require_accepted_pilot_artifact(
    artifact_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact_dir = Path(artifact_dir)
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError("pilot artifact failed strict verification")
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    summaries = [
        event.get("payload")
        for event in _read_jsonl(artifact_dir / "observations.jsonl")
        if event.get("event_type") == "research.run_summary"
    ]
    metadata = manifest.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("experiment") != "category-pilot"
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("pilot_passed") is not True
        or len(summaries) != 1
        or not isinstance(summaries[0], dict)
        or summaries[0].get("pilot_passed") is not True
        or summaries[0].get("condition_count") != 31
        or summaries[0].get("accepted_condition_count") != 31
    ):
        raise ValueError("pilot artifact is not an accepted 31-category predecessor")
    return manifest, summaries[0]


def _require_census_candidate_artifact(
    artifact_dir: Path,
) -> CensusCandidateEvidence:
    artifact_dir = Path(artifact_dir).resolve(strict=True)
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError("candidate artifact failed strict verification")
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = manifest.get("metadata")
    candidate = CensusCandidate.from_payload(
        json.loads((artifact_dir / "candidate.json").read_text(encoding="utf-8"))
    )
    run_id = manifest.get("run_id")
    if (
        not isinstance(metadata, dict)
        or metadata.get("experiment") != "census-candidate"
        or metadata.get("crawl_job_status") != "completed"
        or metadata.get("candidate_frozen") is not True
        or metadata.get("candidate_hash") != candidate.candidate_hash
        or not isinstance(run_id, str)
        or metadata.get("crawl_job_id") != run_id
    ):
        raise ValueError("candidate artifact is not a frozen census predecessor")
    return CensusCandidateEvidence(
        candidate=candidate,
        candidate_hash=candidate.candidate_hash,
        parent_artifact_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        candidate_run_id=run_id,
    )


def _find_parent_calibration_artifact(
    pilot_artifact: Path,
    pilot_manifest: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    metadata = pilot_manifest.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    expected_hash = metadata.get("parent_artifact_hash")
    expected_run_id = metadata.get("calibration_run_id")
    if not isinstance(expected_hash, str) or not isinstance(expected_run_id, str):
        raise ValueError("pilot artifact is missing calibration lineage")

    matches: dict[Path, dict[str, Any]] = {}
    search_roots = (pilot_artifact.parent, pilot_artifact.parent.parent)
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for manifest_path in search_root.rglob("manifest.json"):
            if manifest_path == pilot_artifact / "manifest.json":
                continue
            try:
                if (
                    hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    != expected_hash
                ):
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                continue
            if (
                manifest.get("run_id") == expected_run_id
                and isinstance(manifest.get("metadata"), dict)
                and manifest["metadata"].get("experiment") == "listing-calibration"
            ):
                matches[manifest_path.parent.resolve()] = manifest
        if matches:
            break
    if len(matches) != 1:
        raise ValueError("exactly one referenced calibration artifact is required")
    artifact_dir, manifest = next(iter(matches.items()))
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError("referenced calibration artifact failed strict verification")
    return artifact_dir, manifest


def _calibration_ranked_variants(
    artifact_dir: Path,
) -> tuple[CalibrationVariantSummary, ...]:
    summaries = [
        event.get("payload")
        for event in _read_jsonl(artifact_dir / "observations.jsonl")
        if event.get("event_type") == "research.run_summary"
    ]
    selection = summaries[0].get("selection") if len(summaries) == 1 else None
    ranked_payloads = (
        selection.get("ranked_variants") if isinstance(selection, dict) else None
    )
    if not isinstance(ranked_payloads, list) or not ranked_payloads:
        raise ValueError("calibration artifact is missing ranked variant evidence")
    variants: list[CalibrationVariantSummary] = []
    expected_keys = set(CalibrationVariantSummary.__dataclass_fields__)
    for payload in ranked_payloads:
        if not isinstance(payload, dict) or set(payload) != expected_keys:
            raise ValueError("calibration ranked variant evidence is invalid")
        variants.append(
            CalibrationVariantSummary(
                **{
                    **payload,
                    "job_ids": tuple(payload["job_ids"]),
                    "unique_ids": tuple(payload["unique_ids"]),
                }
            )
        )
    return tuple(variants)


def _freeze_candidate_command(
    args,
    *,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    try:
        pilot_artifact = args.pilot_artifact.resolve(strict=True)
        pilot_manifest, pilot_summary = _require_accepted_pilot_artifact(pilot_artifact)
        calibration_artifact, calibration_manifest = _find_parent_calibration_artifact(
            pilot_artifact, pilot_manifest
        )
        endpoint = pilot_summary.get("endpoint")
        rcd_type = pilot_summary.get("rcd_type")
        candidate = build_census_candidate(
            selected_endpoint=endpoint,
            selected_rcd_type=rcd_type,
            ranked_variants=_calibration_ranked_variants(calibration_artifact),
            source_artifact_hash=hashlib.sha256(
                (pilot_artifact / "manifest.json").read_bytes()
            ).hexdigest(),
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "freeze-candidate",
                "session_mode": "offline",
                "crawl_job_status": "completed",
            },
            captured_at=utc_now().isoformat(),
        )
        payload = candidate.to_payload()
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata={
                "experiment": "census-candidate",
                "crawl_job_id": run_id,
                "crawl_job_status": "completed",
                "candidate_frozen": True,
                "candidate_hash": candidate.candidate_hash,
                "endpoint": candidate.endpoint,
                "rcd_type": candidate.rcd_type,
                "parent_artifact_hash": candidate.source_artifact_hash,
                "source_pilot_run_id": pilot_manifest.get("run_id"),
                "calibration_artifact_hash": hashlib.sha256(
                    (calibration_artifact / "manifest.json").read_bytes()
                ).hexdigest(),
                "calibration_run_id": calibration_manifest.get("run_id"),
                "planner_version": planner_version,
            },
            events=[
                {
                    "sequence_no": 1,
                    "event_type": "research.candidate_frozen",
                    "payload": payload,
                    "emitted_by": "offertoday-research",
                    "created_at": utc_now().isoformat(),
                }
            ],
            provenance=provenance,
            json_files={"candidate.json": payload},
        )
        artifact_check = artifact_verifier(artifact_dir)
        live_check = verify_live_research_run(artifact_dir)
        if not artifact_check.valid or not live_check.valid:
            return EXIT_EVIDENCE_FAILURE
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    _print_json(
        {
            "artifact": str(artifact_dir),
            "candidate_hash": candidate.candidate_hash,
            "endpoint": candidate.endpoint,
            "rcd_type": candidate.rcd_type,
            "run_id": run_id,
        }
    )
    return EXIT_OK


def _parse_aware_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed


def _accepted_stability_artifact(
    artifact_dir: Path,
    *,
    expected_experiment: str,
) -> StabilityArtifactEvidence:
    artifact_dir = Path(artifact_dir).resolve(strict=True)
    verification = verify_live_research_run(artifact_dir)
    if not verification.valid:
        raise ValueError(f"{expected_experiment} artifact failed strict verification")
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = manifest.get("metadata")
    provenance = manifest.get("provenance")
    events = _read_jsonl(artifact_dir / "observations.jsonl")
    summaries = [
        event.get("payload")
        for event in events
        if event.get("event_type") == "research.run_summary"
    ]
    if (
        not isinstance(metadata, dict)
        or not isinstance(provenance, dict)
        or metadata.get("experiment") != expected_experiment
        or metadata.get("crawl_job_status") != "completed"
        or len(summaries) != 1
        or not isinstance(summaries[0], dict)
    ):
        raise ValueError(f"{expected_experiment} artifact is not accepted")
    summary = summaries[0]
    passed_field = (
        "fixed_repeat_passed"
        if expected_experiment == "fixed-condition-repeat"
        else "census_passed"
    )
    if metadata.get(passed_field) is not True or summary.get(passed_field) is not True:
        raise ValueError(f"{expected_experiment} artifact is not accepted")

    run_id = manifest.get("run_id")
    candidate_hash = metadata.get("candidate_hash")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("stability artifact run ID is invalid")
    if (
        not isinstance(candidate_hash, str)
        or len(candidate_hash) != 64
        or any(character not in "0123456789abcdef" for character in candidate_hash)
    ):
        raise ValueError("stability artifact candidate hash is invalid")

    ordered_job_ids: list[str] = []
    seen_job_ids: set[str] = set()
    for event in events:
        if event.get("event_type") != "research.page_attempt":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        for pair in payload.get("id_pairs", ()):
            job_id = pair.get("job_id") if isinstance(pair, dict) else None
            if isinstance(job_id, str) and job_id and job_id not in seen_job_ids:
                seen_job_ids.add(job_id)
                ordered_job_ids.append(job_id)
    if summary.get("unique_job_count") != len(seen_job_ids):
        raise ValueError("stability artifact unique job count is inconsistent")

    listing_requests = summary.get("listing_attempt_count")
    if type(listing_requests) is not int or listing_requests < 0:
        raise ValueError("stability artifact listing request count is invalid")
    listing_logical_count = summary.get("listing_logical_count")
    if (
        type(listing_logical_count) is not int
        or listing_logical_count < 0
        or listing_logical_count > listing_requests
    ):
        raise ValueError("stability artifact logical request count is invalid")
    stop_reason = summary.get("stop_reason")
    if stop_reason is not None and (
        not isinstance(stop_reason, str) or not stop_reason.strip()
    ):
        raise ValueError("stability artifact stop reason is invalid")
    start_events = [
        event for event in events if event.get("event_type") == "research.run_started"
    ]
    summary_events = [
        event for event in events if event.get("event_type") == "research.run_summary"
    ]
    if len(start_events) != 1 or len(summary_events) != 1:
        raise ValueError("stability artifact lifecycle timestamps are incomplete")
    started_at = _parse_aware_timestamp(
        start_events[0].get("created_at"),
        "stability run start",
    )
    completed_at = _parse_aware_timestamp(
        summary_events[0].get("created_at"),
        "stability run summary",
    )
    duration_seconds = (completed_at - started_at).total_seconds()
    if duration_seconds < 0:
        raise ValueError("stability artifact duration is negative")

    def nonnegative_summary_count(field_name: str) -> int:
        value = summary.get(field_name, 0)
        if type(value) is not int or value < 0:
            raise ValueError(f"stability artifact {field_name} is invalid")
        return value

    repeat_index = metadata.get("repeat_index")
    if expected_experiment == "fixed-condition-repeat":
        if type(repeat_index) is not int or repeat_index not in {1, 2, 3}:
            raise ValueError("fixed repeat index must be 1, 2, or 3")
    else:
        repeat_index = None
    return StabilityArtifactEvidence(
        artifact_dir=artifact_dir,
        manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        experiment=expected_experiment,
        candidate_hash=candidate_hash,
        captured_at=_parse_aware_timestamp(
            provenance.get("captured_at"),
            "stability artifact captured_at",
        ),
        run=StabilityRun(
            run_id=run_id,
            job_ids=frozenset(ordered_job_ids),
            listing_requests=listing_requests,
            duration_seconds=duration_seconds,
            accepted=True,
            unresolved_gaps=nonnegative_summary_count("unresolved_gaps"),
            identity_conflicts=nonnegative_summary_count("identity_conflict_count"),
            conservation_difference=nonnegative_summary_count(
                "conservation_difference"
            ),
            unclassified_failures=nonnegative_summary_count("unclassified_failures"),
        ),
        listing_logical_count=listing_logical_count,
        retry_count=listing_requests - listing_logical_count,
        stop_reason=stop_reason,
        repeat_index=repeat_index,
    )


def _load_stability_inputs(
    census_artifacts,
    fixed_repeat_artifacts,
) -> StabilityInputs:
    if len(census_artifacts) != 3 or len(fixed_repeat_artifacts) != 3:
        raise ValueError("compare requires exactly three census and fixed artifacts")
    census_runs = tuple(
        sorted(
            (
                _accepted_stability_artifact(
                    path,
                    expected_experiment="full-census",
                )
                for path in census_artifacts
            ),
            key=lambda item: (item.captured_at, item.run.run_id),
        )
    )
    fixed_repeat_runs = tuple(
        sorted(
            (
                _accepted_stability_artifact(
                    path,
                    expected_experiment="fixed-condition-repeat",
                )
                for path in fixed_repeat_artifacts
            ),
            key=lambda item: (item.repeat_index, item.run.run_id),
        )
    )
    run_ids = [item.run.run_id for item in (*census_runs, *fixed_repeat_runs)]
    if len(set(run_ids)) != 6:
        raise ValueError("compare requires six distinct run IDs")
    candidate_hashes = {
        item.candidate_hash for item in (*census_runs, *fixed_repeat_runs)
    }
    if len(candidate_hashes) != 1:
        raise ValueError("compare requires one candidate hash across all artifacts")
    if tuple(item.repeat_index for item in fixed_repeat_runs) != (1, 2, 3):
        raise ValueError("compare requires fixed repeat indexes 1, 2, and 3")
    census_window_span_seconds = (
        census_runs[-1].captured_at - census_runs[0].captured_at
    ).total_seconds()
    if census_window_span_seconds < _MIN_CENSUS_WINDOW_SECONDS:
        raise ValueError("census artifacts must span at least six hours")
    return StabilityInputs(
        census_runs=census_runs,
        fixed_repeat_runs=fixed_repeat_runs,
        candidate_hash=next(iter(candidate_hashes)),
        census_window_span_seconds=census_window_span_seconds,
        fixed_window_span_seconds=(
            max(item.captured_at for item in fixed_repeat_runs)
            - min(item.captured_at for item in fixed_repeat_runs)
        ).total_seconds(),
    )


def _comparison_run_reference(item: StabilityArtifactEvidence) -> dict[str, Any]:
    return {
        "artifact": str(item.artifact_dir),
        "run_id": item.run.run_id,
        "manifest_hash": item.manifest_hash,
        "captured_at": item.captured_at.isoformat(),
        "repeat_index": item.repeat_index,
    }


def _compare_command(
    args,
    *,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    try:
        inputs = _load_stability_inputs(
            args.census_artifact,
            args.fixed_repeat_artifact,
        )
        comparison = compare_stability(
            tuple(item.run for item in inputs.census_runs),
            tuple(item.run for item in inputs.fixed_repeat_runs),
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
        census_payloads = [item.to_payload() for item in inputs.census_runs]
        fixed_payloads = [item.to_payload() for item in inputs.fixed_repeat_runs]
        comparison_payload = comparison.to_payload()
        summary = {
            "status": "completed",
            "comparison_completed": True,
            "candidate_hash": inputs.candidate_hash,
            "minimum_census_window_seconds": _MIN_CENSUS_WINDOW_SECONDS,
            "census_window_span_seconds": inputs.census_window_span_seconds,
            "fixed_window_span_seconds": inputs.fixed_window_span_seconds,
            "census_runs": census_payloads,
            "fixed_repeat_runs": fixed_payloads,
            **comparison_payload,
            "plan3_entry_accepted": comparison.decision.accepted,
            "failing_gates": list(comparison.decision.failing_gates),
        }
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "compare",
                "session_mode": "offline",
                "crawl_job_status": "completed",
            },
            captured_at=utc_now().isoformat(),
        )
        parent_artifact_hash = inputs.fixed_repeat_runs[-1].manifest_hash
        started_payload = {
            "experiment": "census-stability-comparison",
            "candidate_hash": inputs.candidate_hash,
            "parent_artifact_hash": parent_artifact_hash,
            "minimum_census_window_seconds": _MIN_CENSUS_WINDOW_SECONDS,
            "census_runs": [
                _comparison_run_reference(item) for item in inputs.census_runs
            ],
            "fixed_repeat_runs": [
                _comparison_run_reference(item) for item in inputs.fixed_repeat_runs
            ],
        }
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata={
                "experiment": "census-stability-comparison",
                "crawl_job_id": run_id,
                "crawl_job_status": "completed",
                "parent_artifact_hash": parent_artifact_hash,
                "candidate_hash": inputs.candidate_hash,
                "plan3_entry_accepted": comparison.decision.accepted,
                "planner_version": planner_version,
                "census_run_ids": [item.run.run_id for item in inputs.census_runs],
                "fixed_repeat_run_ids": [
                    item.run.run_id for item in inputs.fixed_repeat_runs
                ],
            },
            events=[
                {
                    "sequence_no": 1,
                    "event_type": "research.comparison_started",
                    "payload": started_payload,
                    "emitted_by": "offertoday-research",
                    "created_at": utc_now().isoformat(),
                },
                {
                    "sequence_no": 2,
                    "event_type": "research.run_summary",
                    "payload": summary,
                    "emitted_by": "offertoday-research",
                    "created_at": utc_now().isoformat(),
                },
            ],
            provenance=provenance,
        )
        artifact_check = artifact_verifier(artifact_dir)
        live_check = verify_live_research_run(artifact_dir)
        if not artifact_check.valid or not live_check.valid:
            return EXIT_EVIDENCE_FAILURE
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "plan3_entry_accepted": comparison.decision.accepted,
            "failing_gates": list(comparison.decision.failing_gates),
            "fixed_cohort_jaccard": comparison.fixed_cohort_jaccard,
            "unique_count_cv": comparison.unique_count_cv,
            "union_hash": comparison.union_hash,
            "census_pairwise": [
                item.to_payload() for item in comparison.census_pairwise
            ],
            "fixed_pairwise": [item.to_payload() for item in comparison.fixed_pairwise],
        }
    )
    return EXIT_OK if comparison.decision.accepted else EXIT_INCOMPLETE


def _event_dict(event: Any) -> dict[str, Any]:
    created_at = event.created_at
    return {
        "sequence_no": int(event.sequence_no),
        "event_type": str(event.event_type),
        "payload": listing_observation_to_payload(event.payload or {}),
        "emitted_by": event.emitted_by,
        "created_at": (
            created_at.isoformat()
            if hasattr(created_at, "isoformat")
            else str(created_at)
        ),
    }


def _ordered_events(events: list[Any]) -> list[dict[str, Any]]:
    return [
        _event_dict(event)
        for event in sorted(events, key=lambda item: int(item.sequence_no))
    ]


def _capture_snapshot(repository, db):
    listings = repository.list_staged_snapshots(db)
    jobs = repository.list_published_snapshots(db)
    product_data = repository.capture_product_data_snapshot(db)
    return (
        build_baseline_snapshot(
            listings=listings,
            jobs=jobs,
            product_data=product_data,
        ),
        build_run_start_inventory(listings=listings, jobs=jobs),
    )


def _snapshot_counts(snapshot) -> tuple[tuple[str, int], ...]:
    payload = asdict(snapshot)
    return tuple(
        (key, payload[key])
        for key in (
            "staged_rows",
            "distinct_staged_ids",
            "published_jobs",
            "distinct_staged_unpublished_ids",
            "pending_rows",
            "duplicate_staging_rows",
            "missing_encrypted_job_id_rows",
            "observed_encrypted_job_id_rows",
            "job_id_fallback_rows",
            "unusable_identity_rows",
        )
    )


def _require_current_baseline(
    baseline_gate: MatchingBaselineGate,
    snapshot,
    inventory,
) -> None:
    if snapshot.data_hash != baseline_gate.second.snapshot_hash:
        raise ValueError("run-start snapshot differs from the verified baselines")
    if inventory.data_hash != baseline_gate.second.inventory_hash:
        raise ValueError("run-start inventory differs from the verified baselines")
    if _snapshot_counts(snapshot) != baseline_gate.second.counts:
        raise ValueError("run-start counts differ from the verified baselines")


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


async def _execute_smoke_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_smoke(
            runtime=active_runtime,
            observation_service=observation_service,
        )


async def _execute_calibration_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_bounded_conditions(
            runtime=active_runtime,
            observation_service=observation_service,
            conditions=build_calibration_conditions(),
        )


async def _execute_pilot_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
    conditions,
    staging_sink,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_bounded_conditions(
            runtime=active_runtime,
            observation_service=observation_service,
            conditions=conditions,
            staging_sink=staging_sink,
        )


async def _execute_census_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
    candidate,
    staging_sink,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_census(
            runtime=active_runtime,
            observation_service=observation_service,
            candidate=candidate,
            staging_sink=staging_sink,
        )


async def _execute_fixed_repeat_with_runtime(
    *,
    runtime_factory,
    service,
    observation_service,
    candidate,
    staging_sink,
):
    runtime = runtime_factory(headed=False)
    async with runtime as active_runtime:
        return await service.run_fixed_repeat(
            runtime=active_runtime,
            observation_service=observation_service,
            candidate=candidate,
            staging_sink=staging_sink,
        )


def _event_counts(events: list[dict[str, Any]]) -> tuple[int, int, int]:
    listing_attempts = sum(
        event.get("event_type") == "research.page_attempt" for event in events
    )
    detail_attempts = sum(
        event.get("event_type") == "research.detail_attempt" for event in events
    )
    frozen_counts = [
        event.get("payload", {}).get("count")
        for event in events
        if event.get("event_type") == "research.detail_cohort_frozen"
        and isinstance(event.get("payload"), dict)
    ]
    frozen_count = frozen_counts[-1] if frozen_counts else 0
    if type(frozen_count) is not int or frozen_count < 0:
        frozen_count = 0
    return listing_attempts, detail_attempts, frozen_count


def _listing_identity_counts(
    *,
    execution,
    events_before_summary: list[dict[str, Any]],
) -> tuple[int, int]:
    if execution is not None:
        page_payloads = [
            listing_observation_to_payload(observation)
            for observation in execution.listing_result.observations
        ]
    else:
        page_payloads = [
            event["payload"]
            for event in events_before_summary
            if event.get("event_type") == "research.page_attempt"
            and isinstance(event.get("payload"), dict)
        ]

    def total(field_name: str) -> int:
        values = [payload.get(field_name, 0) for payload in page_payloads]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError(
                f"research page {field_name} must be a non-negative exact integer"
            )
        return sum(values)

    return (
        total("missing_encrypted_job_id_count"),
        total("job_id_fallback_count"),
    )


def _build_summary(
    *,
    status: str,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    execution,
    events_before_summary: list[dict[str, Any]],
    failure_reason: str | None,
    request_budget: dict[str, int],
) -> dict[str, Any]:
    listing_attempts, detail_attempts, event_frozen_count = _event_counts(
        events_before_summary
    )
    missing_encrypted_job_id_count, job_id_fallback_count = _listing_identity_counts(
        execution=execution,
        events_before_summary=events_before_summary,
    )
    product_data_unchanged = (
        start_snapshot.data_hash == end_snapshot.data_hash
        and start_inventory.data_hash == end_inventory.data_hash
    )
    if execution is None:
        smoke_passed = False
        listing_complete = False
        expected_truncation = False
        frozen_count = event_frozen_count
        success_count = sum(
            event.get("payload", {}).get("classification") == "success"
            for event in events_before_summary
            if event.get("event_type") == "research.detail_attempt"
            and isinstance(event.get("payload"), dict)
        )
        terminal_count = sum(
            event.get("payload", {}).get("classification") == "terminal_unavailable"
            for event in events_before_summary
            if event.get("event_type") == "research.detail_attempt"
            and isinstance(event.get("payload"), dict)
        )
        unattempted_count = max(0, frozen_count - detail_attempts)
        listing_stop_reason = failure_reason
        would_stage_rows = 0
        stage_calls = 0
    else:
        decision = execution.decision
        smoke_passed = decision.smoke_passed and product_data_unchanged
        listing_complete = execution.listing_result.is_complete
        expected_truncation = decision.expected_truncation
        frozen_count = decision.frozen_count
        success_count = decision.success_count
        terminal_count = decision.terminal_count
        unattempted_count = decision.unattempted_count
        listing_stop_reason = execution.listing_result.stop_reason
        failure_reason = failure_reason or decision.stop_reason
        would_stage_rows = execution.would_stage_rows
        stage_calls = execution.stage_calls
    return {
        "status": status,
        "smoke_passed": smoke_passed,
        "listing_complete": listing_complete,
        "expected_truncation": expected_truncation,
        "frozen_count": frozen_count,
        "attempted_count": detail_attempts,
        "success_count": success_count,
        "terminal_count": terminal_count,
        "unattempted_count": unattempted_count,
        "missing_encrypted_job_id_count": missing_encrypted_job_id_count,
        "job_id_fallback_count": job_id_fallback_count,
        "listing_attempt_count": listing_attempts,
        "listing_stop_reason": listing_stop_reason,
        "stop_reason": failure_reason,
        "request_budget": dict(request_budget),
        "would_stage_rows": would_stage_rows,
        "stage_calls": stage_calls,
        "product_data_unchanged": product_data_unchanged,
        "run_start_snapshot_hash": start_snapshot.data_hash,
        "run_end_snapshot_hash": end_snapshot.data_hash,
        "run_start_product_data_hash": start_snapshot.product_data_hash,
        "run_end_product_data_hash": end_snapshot.product_data_hash,
        "run_start_inventory_hash": start_inventory.data_hash,
        "run_end_inventory_hash": end_inventory.data_hash,
    }


def _calibration_page_counts(
    *,
    results,
    events_before_summary: list[dict[str, Any]],
) -> tuple[int, int]:
    if results is not None:
        page_payloads = [
            listing_observation_to_payload(observation)
            for result in results
            for observation in result.listing_result.observations
        ]
    else:
        page_payloads = [
            event["payload"]
            for event in events_before_summary
            if event.get("event_type") == "research.page_attempt"
            and isinstance(event.get("payload"), dict)
        ]
    logical_pages = {
        (payload.get("condition_id"), payload.get("page"))
        for payload in page_payloads
        if isinstance(payload.get("condition_id"), str)
        and type(payload.get("page")) is int
        and payload.get("page") > 0
    }
    return len(logical_pages), len(page_payloads)


def _calibration_analysis(results) -> tuple[bool, str | None, list[dict], dict | None]:
    locked_conditions = build_calibration_conditions()
    variant_summaries = summarize_calibration_variants(results or ())
    variant_payloads = [asdict(item) for item in variant_summaries]
    selection_payload = None
    try:
        selection_payload = asdict(
            select_calibration_variants(variant_summaries, limit=2)
        )
    except ValueError:
        pass

    exact_matrix = (
        results is not None
        and tuple(item.condition for item in results) == locked_conditions
    )
    all_accepted = bool(results) and all(item.accepted for item in results)
    calibration_passed = exact_matrix and all_accepted and selection_payload is not None
    if calibration_passed:
        failure_reason = None
    else:
        rejected = next(
            (
                item.rejection_reason
                for item in (results or ())
                if not item.accepted and item.rejection_reason
            ),
            None,
        )
        failure_reason = rejected or "calibration_incomplete"
        if failure_reason.startswith("batch_stop:"):
            failure_reason = failure_reason.split(":", 1)[1]
    return (
        calibration_passed,
        failure_reason,
        variant_payloads,
        selection_payload,
    )


def _build_calibration_summary(
    *,
    status: str,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    results,
    events_before_summary: list[dict[str, Any]],
    failure_reason: str | None,
    request_budget: dict[str, int],
) -> dict[str, Any]:
    logical_count, attempt_count = _calibration_page_counts(
        results=results,
        events_before_summary=events_before_summary,
    )
    detail_attempt_count = sum(
        event.get("event_type") == "research.detail_attempt"
        for event in events_before_summary
    )
    (
        calibration_passed,
        analysis_failure_reason,
        variant_summaries,
        selection,
    ) = _calibration_analysis(results)
    product_data_unchanged = (
        start_snapshot.data_hash == end_snapshot.data_hash
        and start_inventory.data_hash == end_inventory.data_hash
    )
    calibration_passed = (
        calibration_passed
        and status == "completed"
        and failure_reason is None
        and product_data_unchanged
        and detail_attempt_count == 0
    )
    condition_count = (
        len(results)
        if results is not None
        else sum(
            event.get("event_type")
            in {"research.condition_completed", "research.condition_incomplete"}
            for event in events_before_summary
        )
    )
    accepted_condition_count = sum(item.accepted for item in (results or ()))
    return {
        "status": status,
        "calibration_passed": calibration_passed,
        "condition_count": condition_count,
        "accepted_condition_count": accepted_condition_count,
        "listing_logical_count": logical_count,
        "listing_attempt_count": attempt_count,
        "detail_attempt_count": detail_attempt_count,
        "stop_reason": failure_reason or analysis_failure_reason,
        "request_budget": dict(request_budget),
        "variant_summaries": variant_summaries,
        "selection": selection,
        "product_data_unchanged": product_data_unchanged,
        "run_start_snapshot_hash": start_snapshot.data_hash,
        "run_end_snapshot_hash": end_snapshot.data_hash,
        "run_start_product_data_hash": start_snapshot.product_data_hash,
        "run_end_product_data_hash": end_snapshot.product_data_hash,
        "run_start_inventory_hash": start_inventory.data_hash,
        "run_end_inventory_hash": end_inventory.data_hash,
    }


def _pilot_analysis(
    *,
    results,
    conditions,
    reconciliation,
) -> tuple[bool, str | None]:
    if results is None:
        return False, "pilot_condition_matrix_mismatch"
    result_conditions = tuple(item.condition for item in results)
    if result_conditions != tuple(conditions[: len(result_conditions)]):
        return False, "pilot_condition_matrix_mismatch"
    rejected = next((item for item in results if not item.accepted), None)
    if rejected is not None:
        reason = rejected.rejection_reason or "pilot_condition_rejected"
        if reason.startswith("batch_stop:"):
            reason = reason.split(":", 1)[1]
        return False, reason
    if len(results) != len(conditions):
        return False, "pilot_condition_matrix_mismatch"
    if reconciliation.deferred_identity_conflict_ids:
        return False, "deferred_identity_conflict"
    if not reconciliation.staging_amplification_within_limit:
        return False, "staging_amplification"
    return True, None


def _build_pilot_summary(
    *,
    status: str,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    results,
    conditions,
    events_before_summary: list[dict[str, Any]],
    failure_reason: str | None,
    request_budget: dict[str, int],
    variant: PilotVariantEvidence,
    reconciliation,
) -> dict[str, Any]:
    logical_count, attempt_count = _calibration_page_counts(
        results=results,
        events_before_summary=events_before_summary,
    )
    detail_attempt_count = sum(
        event.get("event_type") == "research.detail_attempt"
        for event in events_before_summary
    )
    condition_count = (
        len(results)
        if results is not None
        else sum(
            event.get("event_type")
            in {"research.condition_completed", "research.condition_incomplete"}
            for event in events_before_summary
        )
    )
    accepted_condition_count = sum(item.accepted for item in (results or ()))
    pilot_accepted, analysis_failure_reason = _pilot_analysis(
        results=results,
        conditions=conditions,
        reconciliation=reconciliation,
    )
    staged_rows_delta = end_snapshot.staged_rows - start_snapshot.staged_rows
    conservation_difference = staged_rows_delta - reconciliation.rows_created
    published_jobs_unchanged = (
        start_snapshot.published_jobs == end_snapshot.published_jobs
        and start_snapshot.published_jobs_hash == end_snapshot.published_jobs_hash
    )
    companies_unchanged = start_snapshot.companies_hash == end_snapshot.companies_hash
    pilot_passed = (
        pilot_accepted
        and status == "completed"
        and failure_reason is None
        and detail_attempt_count == 0
        and conservation_difference == 0
        and published_jobs_unchanged
        and companies_unchanged
    )
    return {
        "status": status,
        "pilot_passed": pilot_passed,
        "planned_condition_count": len(conditions),
        "condition_count": condition_count,
        "accepted_condition_count": accepted_condition_count,
        "planned_listing_logical_count": request_budget["listing_logical"],
        "listing_logical_count": logical_count,
        "listing_attempt_count": attempt_count,
        "detail_attempt_count": detail_attempt_count,
        "variant_rank": variant.variant_rank,
        "endpoint": variant.endpoint,
        "rcd_type": variant.rcd_type,
        "calibration_run_id": variant.calibration_run_id,
        "stop_reason": failure_reason or analysis_failure_reason,
        "request_budget": dict(request_budget),
        "reconciliation": reconciliation.to_payload(),
        "staged_rows_delta": staged_rows_delta,
        "conservation_difference": conservation_difference,
        "published_jobs_unchanged": published_jobs_unchanged,
        "companies_unchanged": companies_unchanged,
        "run_start_snapshot_hash": start_snapshot.data_hash,
        "run_end_snapshot_hash": end_snapshot.data_hash,
        "run_start_product_data_hash": start_snapshot.product_data_hash,
        "run_end_product_data_hash": end_snapshot.product_data_hash,
        "run_start_inventory_hash": start_inventory.data_hash,
        "run_end_inventory_hash": end_inventory.data_hash,
    }


def _ordered_id_hash(values) -> str:
    canonical = json.dumps(
        list(dict.fromkeys(str(value) for value in values)),
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _census_page_payloads(
    *,
    result,
    events_before_summary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if result is not None:
        return [
            listing_observation_to_payload(observation)
            for observation in result.observations
        ]
    return [
        event["payload"]
        for event in events_before_summary
        if event.get("event_type") == "research.page_attempt"
        and isinstance(event.get("payload"), dict)
    ]


def _census_condition_summaries(
    *,
    result,
    conditions,
    events_before_summary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    accepted_ids = set(result.accepted_job_ids) if result is not None else None
    ids_by_condition: dict[str, list[str]] = {}
    for payload in _census_page_payloads(
        result=result,
        events_before_summary=events_before_summary,
    ):
        condition_id = payload.get("condition_id")
        if not isinstance(condition_id, str):
            continue
        condition_ids = ids_by_condition.setdefault(condition_id, [])
        seen = set(condition_ids)
        for pair in payload.get("id_pairs", ()):
            if not isinstance(pair, dict):
                continue
            job_id = str(pair.get("job_id") or "")
            if (
                job_id
                and (accepted_ids is None or job_id in accepted_ids)
                and job_id not in seen
            ):
                condition_ids.append(job_id)
                seen.add(job_id)
    if result is not None:
        outcome_evidence = tuple(
            (
                outcome.condition,
                outcome.pages_observed,
                outcome.stop_reason,
                outcome.is_complete,
            )
            for outcome in result.condition_outcomes
        )
    else:
        outcome_evidence = tuple(
            (
                conditions[index],
                payload.get("pages_observed"),
                payload.get("stop_reason"),
                payload.get("is_complete"),
            )
            for index, event in enumerate(
                event
                for event in events_before_summary
                if event.get("event_type")
                in {"research.condition_completed", "research.condition_incomplete"}
            )
            if index < len(conditions)
            and isinstance((payload := event.get("payload")), dict)
        )
    return [
        {
            "condition_id": condition.condition_id,
            "category_id": condition.category_id,
            "endpoint": condition.endpoint,
            "rcd_type": condition.rcd_type,
            "pages_observed": pages_observed,
            "stop_reason": stop_reason,
            "is_complete": is_complete,
            "ordered_job_count": len(ids_by_condition.get(condition.condition_id, ())),
            "ordered_job_id_hash": _ordered_id_hash(
                ids_by_condition.get(condition.condition_id, ())
            ),
        }
        for condition, pages_observed, stop_reason, is_complete in outcome_evidence
    ]


def _census_conservation_report(
    *,
    result,
    events_before_summary: list[dict[str, Any]],
    reconciliation,
):
    page_payloads = _census_page_payloads(
        result=result,
        events_before_summary=events_before_summary,
    )
    if result is not None:
        valid_ids = set(result.accepted_job_ids)
        unresolved_gaps = len(result.gaps)
    else:
        valid_ids = {
            str(pair.get("job_id") or pair.get("source_job_id"))
            for payload in page_payloads
            for pair in payload.get("id_pairs", ())
            if isinstance(pair, dict)
            and str(pair.get("job_id") or pair.get("source_job_id") or "")
        }
        unresolved_gaps = sum(
            event.get("event_type") == "research.condition_incomplete"
            for event in events_before_summary
        )
    raw_listing_rows = sum(
        payload.get("row_count", 0)
        for payload in page_payloads
        if type(payload.get("row_count", 0)) is int and payload.get("row_count", 0) >= 0
    )
    rows_missing_job_id = sum(
        payload.get("missing_job_id_count", 0)
        for payload in page_payloads
        if type(payload.get("missing_job_id_count", 0)) is int
        and payload.get("missing_job_id_count", 0) >= 0
    )
    return build_listing_conservation_report(
        raw_listing_rows=raw_listing_rows,
        rows_missing_job_id=rows_missing_job_id,
        rows_containing_job_id=max(raw_listing_rows - rows_missing_job_id, 0),
        valid_distinct_job_ids=valid_ids,
        already_published_ids=set(reconciliation.published_source_job_ids),
        preexisting_staged_unpublished_ids=set(
            reconciliation.preexisting_staged_source_job_ids
        ),
        newly_staged_ids=set(reconciliation.created_source_job_ids),
        deferred_identity_conflict_ids=set(
            reconciliation.deferred_identity_conflict_ids
        ),
        newly_created_staging_rows=reconciliation.rows_created,
        unresolved_gaps=unresolved_gaps,
    )


def _census_conservation_difference(report) -> int:
    return (
        abs(report.raw_rows.difference)
        + abs(report.distinct_ids.difference)
        + len(report.partition_overlap_ids)
        + len(report.unexplained_ids)
        + report.unresolved_gaps
        + len(report.identity_pair_mismatch_page_keys)
        + int(report.staging_amplification_violation)
    )


def _analyze_census(
    *,
    result,
    conditions,
    events_before_summary: list[dict[str, Any]],
    reconciliation,
    request_budget: dict[str, int] | None = None,
) -> dict[str, Any]:
    active_request_budget = request_budget or _CENSUS_REQUEST_BUDGET
    page_payloads = _census_page_payloads(
        result=result,
        events_before_summary=events_before_summary,
    )
    logical_pages = {
        (payload.get("condition_id"), payload.get("page"))
        for payload in page_payloads
        if isinstance(payload.get("condition_id"), str)
        and type(payload.get("page")) is int
        and payload.get("page") > 0
    }
    detail_attempt_count = sum(
        event.get("event_type") == "research.detail_attempt"
        for event in events_before_summary
    )
    report = _census_conservation_report(
        result=result,
        events_before_summary=events_before_summary,
        reconciliation=reconciliation,
    )
    conservation_difference = _census_conservation_difference(report)
    expected_conditions = tuple(conditions)
    condition_event_payloads = [
        event.get("payload")
        for event in events_before_summary
        if event.get("event_type")
        in {"research.condition_completed", "research.condition_incomplete"}
        and isinstance(event.get("payload"), dict)
    ]
    if result is not None:
        outcomes = tuple(result.condition_outcomes)
        actual_conditions = tuple(outcome.condition for outcome in outcomes)
        condition_prefix_matches = (
            actual_conditions == expected_conditions[: len(actual_conditions)]
        )
        incomplete_reason = next(
            (
                outcome.stop_reason or "condition_incomplete"
                for outcome in outcomes
                if not outcome.is_complete
            ),
            None,
        )
        natural_exhaustion_count = sum(
            outcome.is_complete and outcome.stop_reason == "natural_exhaustion"
            for outcome in outcomes
        )
        condition_count = len(outcomes)
        identity_issue_count = len(result.identity_issues)
        identity_conflict_count = len(result.identity_conflicts)
        ordered_job_ids = tuple(result.accepted_job_ids)
    else:
        actual_condition_payloads = tuple(
            payload.get("condition") for payload in condition_event_payloads
        )
        expected_condition_payloads = tuple(
            listing_observation_to_payload(condition)
            for condition in expected_conditions[: len(actual_condition_payloads)]
        )
        condition_prefix_matches = (
            actual_condition_payloads == expected_condition_payloads
        )
        incomplete_reason = next(
            (
                payload.get("stop_reason") or "condition_incomplete"
                for payload in condition_event_payloads
                if payload.get("is_complete") is False
            ),
            None,
        )
        natural_exhaustion_count = sum(
            payload.get("is_complete") is True
            and payload.get("stop_reason") == "natural_exhaustion"
            for payload in condition_event_payloads
        )
        condition_count = len(condition_event_payloads)
        identity_issue_count = sum(
            len(payload.get("identity_issues", ()))
            for payload in page_payloads
            if isinstance(payload.get("identity_issues", ()), list)
        )
        identity_conflict_count = sum(
            len(payload.get("identity_conflicts", ()))
            for payload in page_payloads
            if isinstance(payload.get("identity_conflicts", ()), list)
        )
        ordered_job_ids_list: list[str] = []
        seen_job_ids: set[str] = set()
        for payload in page_payloads:
            for pair in payload.get("id_pairs", ()):
                job_id = pair.get("job_id") if isinstance(pair, dict) else None
                if isinstance(job_id, str) and job_id and job_id not in seen_job_ids:
                    seen_job_ids.add(job_id)
                    ordered_job_ids_list.append(job_id)
        ordered_job_ids = tuple(ordered_job_ids_list)
    unresolved_gaps = len(result.gaps) if result is not None else report.unresolved_gaps
    if result is None:
        failure_reason = "census_execution_missing"
    elif not condition_prefix_matches:
        failure_reason = "census_condition_matrix_mismatch"
    elif incomplete_reason is not None:
        failure_reason = incomplete_reason
    elif condition_count != len(expected_conditions):
        failure_reason = "census_condition_matrix_mismatch"
    elif natural_exhaustion_count != len(expected_conditions):
        failure_reason = "census_natural_exhaustion_mismatch"
    elif not result.is_complete or result.stop_reason != "natural_exhaustion":
        failure_reason = result.stop_reason or "census_incomplete"
    elif len(logical_pages) >= active_request_budget["listing_logical"]:
        failure_reason = "listing_logical_budget_exceeded"
    elif len(page_payloads) >= active_request_budget["listing_attempt_max"]:
        failure_reason = "listing_attempt_budget_exceeded"
    elif detail_attempt_count:
        failure_reason = "census_detail_request_observed"
    elif unresolved_gaps:
        failure_reason = "unresolved_gaps"
    elif identity_issue_count:
        failure_reason = "identity_issue"
    elif identity_conflict_count or reconciliation.deferred_identity_conflict_ids:
        failure_reason = "identity_conflict"
    elif not reconciliation.staging_amplification_within_limit:
        failure_reason = "staging_amplification"
    elif conservation_difference:
        failure_reason = "conservation_difference"
    else:
        failure_reason = None
    return {
        "accepted": failure_reason is None,
        "failure_reason": failure_reason,
        "listing_logical_count": len(logical_pages),
        "listing_attempt_count": len(page_payloads),
        "detail_attempt_count": detail_attempt_count,
        "condition_count": condition_count,
        "natural_exhaustion_count": natural_exhaustion_count,
        "unresolved_gaps": unresolved_gaps,
        "identity_issue_count": identity_issue_count,
        "identity_conflict_count": identity_conflict_count,
        "conservation_difference": conservation_difference,
        "conservation_report": report,
        "condition_outcomes": _census_condition_summaries(
            result=result,
            conditions=expected_conditions,
            events_before_summary=events_before_summary,
        ),
        "ordered_job_ids": tuple(ordered_job_ids),
        "ordered_job_id_hash": _ordered_id_hash(ordered_job_ids),
        "unique_job_count": len(set(ordered_job_ids)),
    }


def _build_census_summary(
    *,
    status: str,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    result,
    conditions,
    events_before_summary: list[dict[str, Any]],
    failure_reason: str | None,
    request_budget: dict[str, int],
    candidate_evidence: CensusCandidateEvidence,
    reconciliation,
) -> dict[str, Any]:
    analysis = _analyze_census(
        result=result,
        conditions=conditions,
        events_before_summary=events_before_summary,
        reconciliation=reconciliation,
        request_budget=request_budget,
    )
    report = analysis.pop("conservation_report")
    staged_rows_delta = end_snapshot.staged_rows - start_snapshot.staged_rows
    database_conservation_difference = staged_rows_delta - reconciliation.rows_created
    published_jobs_unchanged = (
        start_snapshot.published_jobs == end_snapshot.published_jobs
        and start_snapshot.published_jobs_hash == end_snapshot.published_jobs_hash
    )
    companies_unchanged = start_snapshot.companies_hash == end_snapshot.companies_hash
    total_conservation_difference = analysis["conservation_difference"] + abs(
        database_conservation_difference
    )
    census_passed = (
        analysis["accepted"]
        and status == "completed"
        and failure_reason is None
        and total_conservation_difference == 0
        and published_jobs_unchanged
        and companies_unchanged
    )
    return {
        "status": status,
        "census_passed": census_passed,
        "candidate_hash": candidate_evidence.candidate_hash,
        "candidate_run_id": candidate_evidence.candidate_run_id,
        "planned_condition_count": len(conditions),
        "condition_count": analysis["condition_count"],
        "natural_exhaustion_count": analysis["natural_exhaustion_count"],
        "listing_logical_count": analysis["listing_logical_count"],
        "listing_attempt_count": analysis["listing_attempt_count"],
        "detail_attempt_count": analysis["detail_attempt_count"],
        "unresolved_gaps": analysis["unresolved_gaps"],
        "identity_issue_count": analysis["identity_issue_count"],
        "identity_conflict_count": analysis["identity_conflict_count"],
        "conservation_difference": total_conservation_difference,
        "listing_conservation_difference": analysis["conservation_difference"],
        "database_conservation_difference": database_conservation_difference,
        "conservation": {
            "raw_rows_difference": report.raw_rows.difference,
            "distinct_ids_difference": report.distinct_ids.difference,
            "partition_overlap_ids": list(report.partition_overlap_ids),
            "unexplained_ids": list(report.unexplained_ids),
            "identity_pair_mismatch_page_keys": list(
                report.identity_pair_mismatch_page_keys
            ),
        },
        "staging_amplification_ratio": (reconciliation.staging_amplification_ratio),
        "staging_amplification_within_limit": (
            reconciliation.staging_amplification_within_limit
        ),
        "reconciliation": reconciliation.to_payload(),
        "staged_rows_delta": staged_rows_delta,
        "published_jobs_unchanged": published_jobs_unchanged,
        "companies_unchanged": companies_unchanged,
        "ordered_job_id_hash": analysis["ordered_job_id_hash"],
        "unique_job_count": analysis["unique_job_count"],
        "condition_outcomes": analysis["condition_outcomes"],
        "stop_reason": failure_reason or analysis["failure_reason"],
        "request_budget": dict(request_budget),
        "run_start_snapshot_hash": start_snapshot.data_hash,
        "run_end_snapshot_hash": end_snapshot.data_hash,
        "run_start_product_data_hash": start_snapshot.product_data_hash,
        "run_end_product_data_hash": end_snapshot.product_data_hash,
        "run_start_inventory_hash": start_inventory.data_hash,
        "run_end_inventory_hash": end_inventory.data_hash,
    }


def _build_fixed_repeat_summary(
    *,
    repeat_index: int,
    **kwargs,
) -> dict[str, Any]:
    summary = _build_census_summary(**kwargs)
    summary["fixed_repeat_passed"] = summary.pop("census_passed")
    summary["repeat_index"] = repeat_index
    return summary


def _unexpected_error_message(
    error: BaseException,
    *,
    experiment: str = "runtime-smoke",
) -> str:
    prefix = (
        "unexpected_listing_calibration_error"
        if experiment == "listing-calibration"
        else (
            "unexpected_category_pilot_error"
            if experiment == "category-pilot"
            else (
                (
                    "unexpected_fixed_condition_repeat_error"
                    if experiment == "fixed-condition-repeat"
                    else "unexpected_full_census_error"
                )
                if experiment in {"full-census", "fixed-condition-repeat"}
                else "unexpected_live_smoke_error"
            )
        )
    )
    return f"{prefix}:{type(error).__name__}"


def _summary_event(
    events_before_summary: list[dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "sequence_no": len(events_before_summary) + 1,
        "event_type": "research.run_summary",
        "payload": listing_observation_to_payload(summary),
        "emitted_by": "offertoday-research",
        "created_at": utc_now().isoformat(),
    }


def _best_effort_finalize_unexpected_failure(
    *,
    db,
    repository,
    observation_service,
    run_id: str,
    error: BaseException,
    start_snapshot,
    start_inventory,
    end_snapshot,
    end_inventory,
    fallback_events: list[dict[str, Any]],
    request_budget: dict[str, int],
    experiment: str = "runtime-smoke",
    pilot_variant: PilotVariantEvidence | None = None,
    pilot_conditions=(),
    pilot_reconciliation=None,
    census_candidate_evidence: CensusCandidateEvidence | None = None,
    census_conditions=(),
    census_reconciliation=None,
    fixed_repeat_index: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    error_message = _unexpected_error_message(error, experiment=experiment)
    product_data_evidence_complete = (
        end_snapshot is not None and end_inventory is not None
    )
    if not product_data_evidence_complete:
        try:
            end_snapshot, end_inventory = _capture_snapshot(repository, db)
            product_data_evidence_complete = True
        except BaseException as snapshot_error:
            error.add_note(
                "run-end evidence capture also failed: "
                f"{type(snapshot_error).__name__}"
            )
            end_snapshot = start_snapshot
            end_inventory = start_inventory

    try:
        current_events = _ordered_events(
            repository.list_research_events(db, UUID(run_id))
        )
    except BaseException as event_error:
        error.add_note(
            "partial event loading also failed: " f"{type(event_error).__name__}"
        )
        current_events = list(fallback_events)

    has_terminal_summary = any(
        event.get("event_type") == "research.run_summary" for event in current_events
    )
    if not has_terminal_summary:
        try:
            observation_service.record_event(
                "research.run_stopped",
                {"reason": error_message},
            )
            current_events = _ordered_events(
                repository.list_research_events(db, UUID(run_id))
            )
        except BaseException as stop_error:
            error.add_note(
                "failure stop event persistence also failed: "
                f"{type(stop_error).__name__}"
            )

    if (
        experiment in {"full-census", "fixed-condition-repeat"}
        and census_candidate_evidence is not None
        and census_reconciliation is not None
    ):
        summary_builder = (
            _build_fixed_repeat_summary
            if experiment == "fixed-condition-repeat"
            else _build_census_summary
        )
        summary = summary_builder(
            **(
                {"repeat_index": fixed_repeat_index}
                if experiment == "fixed-condition-repeat"
                else {}
            ),
            status="failed",
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            result=None,
            conditions=census_conditions,
            events_before_summary=current_events,
            failure_reason=error_message,
            request_budget=request_budget,
            candidate_evidence=census_candidate_evidence,
            reconciliation=census_reconciliation,
        )
    elif (
        experiment == "category-pilot"
        and pilot_variant is not None
        and pilot_reconciliation is not None
    ):
        summary = _build_pilot_summary(
            status="failed",
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            results=None,
            conditions=pilot_conditions,
            events_before_summary=current_events,
            failure_reason=error_message,
            request_budget=request_budget,
            variant=pilot_variant,
            reconciliation=pilot_reconciliation,
        )
    elif experiment == "listing-calibration":
        summary = _build_calibration_summary(
            status="failed",
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            results=None,
            events_before_summary=current_events,
            failure_reason=error_message,
            request_budget=request_budget,
        )
    else:
        summary = _build_summary(
            status="failed",
            start_snapshot=start_snapshot,
            start_inventory=start_inventory,
            end_snapshot=end_snapshot,
            end_inventory=end_inventory,
            execution=None,
            events_before_summary=current_events,
            failure_reason=error_message,
            request_budget=request_budget,
        )
    if not product_data_evidence_complete:
        summary["product_data_unchanged"] = False

    if not has_terminal_summary:
        try:
            observation_service.finish_run(
                status="failed",
                summary=summary,
                error_message=error_message,
            )
            current_events = [*current_events, _summary_event(current_events, summary)]
        except BaseException as finish_error:
            error.add_note(
                "type-only failure finalization also failed: "
                f"{type(finish_error).__name__}"
            )
            try:
                current_events = _ordered_events(
                    repository.list_research_events(db, UUID(run_id))
                )
            except BaseException as reload_error:
                error.add_note(
                    "failure event reload also failed: "
                    f"{type(reload_error).__name__}"
                )
    return summary, current_events


def _pagination_input_set_hash(inputs: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        inputs,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _require_pagination_bakeoff_artifact(artifact_dir: Path):
    artifact_dir = Path(artifact_dir).resolve(strict=True)
    verification = verify_live_research_run(artifact_dir)
    if (
        not verification.valid
        or verification.experiment != "cursor-pagination-bakeoff-v2"
    ):
        raise ValueError("pagination bake-off artifact failed strict verification")
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = json.loads(
        (artifact_dir / "bakeoff.json").read_text(encoding="utf-8")
    )
    validate_bakeoff_payload(payload)
    metadata = manifest["metadata"]
    return {
        "artifact": str(artifact_dir),
        "manifest_hash": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "run_id": manifest["run_id"],
        "repeat_index": payload["repeat_index"],
        "parent_artifact_hash": metadata["parent_artifact_hash"],
        "baseline_artifact_hashes": metadata["baseline_artifact_hashes"],
        "baseline_snapshot_hash": metadata["baseline_snapshot_hash"],
        "baseline_inventory_hash": metadata["baseline_inventory_hash"],
        "bakeoff_payload_hash": canonical_bakeoff_payload_hash(payload),
    }, payload


def _compare_pagination_command(
    args,
    *,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    if len(args.bakeoff_artifact) != 2:
        _print_json(
            {"error": "compare-pagination requires exactly two bake-off artifacts"},
            stream=sys.stderr,
        )
        return EXIT_USAGE
    try:
        evidence = [
            _require_pagination_bakeoff_artifact(path)
            for path in args.bakeoff_artifact
        ]
        evidence.sort(key=lambda item: item[0]["repeat_index"])
        inputs = [item[0] for item in evidence]
        payloads = [item[1] for item in evidence]
        validate_pagination_comparison_parents(inputs)
        decision = compare_bakeoff_payloads(payloads[0], payloads[1])
        input_set_hash = _pagination_input_set_hash(inputs)
        comparison_payload = {
            "schema_version": 2,
            "input_set_hash": input_set_hash,
            "inputs": inputs,
            "thresholds": pagination_bakeoff_thresholds_payload(),
            "decision": decision.to_payload(),
        }
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
        captured_at = utc_now().isoformat()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "compare-pagination",
                "session_mode": "offline",
                "crawl_job_status": "completed",
            },
            captured_at=captured_at,
        )
        events = [
            {
                "sequence_no": 1,
                "event_type": "research.run_started",
                "payload": {
                    "experiment": "cursor-pagination-comparison-v2",
                    "input_set_hash": input_set_hash,
                },
                "emitted_by": "offertoday-research",
                "created_at": captured_at,
            },
            {
                "sequence_no": 2,
                "event_type": "research.pagination_comparison",
                "payload": decision.to_payload(),
                "emitted_by": "offertoday-research",
                "created_at": utc_now().isoformat(),
            },
            {
                "sequence_no": 3,
                "event_type": "research.run_summary",
                "payload": {
                    "input_set_hash": input_set_hash,
                    "decision": decision.to_payload(),
                },
                "emitted_by": "offertoday-research",
                "created_at": utc_now().isoformat(),
            },
        ]
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata={
                "experiment": "cursor-pagination-comparison-v2",
                "crawl_job_id": run_id,
                "crawl_job_status": "completed",
                "parent_artifact_hash": input_set_hash,
                "pagination_passed": decision.accepted,
                "selected_variant_id": decision.selected_variant_id,
                "planner_version": planner_version,
            },
            events=events,
            provenance=provenance,
            json_files={"comparison.json": comparison_payload},
        )
        if (
            not artifact_verifier(artifact_dir).valid
            or not verify_live_research_run(artifact_dir).valid
        ):
            return EXIT_EVIDENCE_FAILURE
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    exit_code = EXIT_OK if decision.accepted else EXIT_INCOMPLETE
    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "pagination_passed": decision.accepted,
            "selected_variant_id": decision.selected_variant_id,
            "exit_code": exit_code,
        }
    )
    return exit_code


def _freeze_discovery_candidate_command(
    args,
    *,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    try:
        comparison_dir = args.comparison_artifact.resolve(strict=True)
        comparison_check = verify_live_research_run(comparison_dir)
        if (
            not comparison_check.valid
            or comparison_check.experiment
            != "cursor-pagination-comparison-v2"
        ):
            raise ValueError("comparison artifact failed strict verification")
        comparison_payload = json.loads(
            (comparison_dir / "comparison.json").read_text(encoding="utf-8")
        )
        decision = comparison_payload.get("decision")
        if not isinstance(decision, dict) or decision.get("accepted") is not True:
            raise ValueError("pagination comparison did not accept a candidate")
        selected_variant_id = decision.get("selected_variant_id")
        selected_variant = next(
            item
            for item in BAKEOFF_VARIANTS
            if item.variant_id == selected_variant_id
        )
        if selected_variant.pagination_mode != "response-cursor":
            raise ValueError("selected discovery candidate must be cursor based")
        comparison_manifest_hash = hashlib.sha256(
            (comparison_dir / "manifest.json").read_bytes()
        ).hexdigest()
        candidate = DiscoveryCandidateV2(
            candidate_version=2,
            endpoint=BAKEOFF_ENDPOINT,
            rcd_type=BAKEOFF_RCD_TYPE,
            category_ids=BAKEOFF_CATEGORY_IDS,
            pagination_mode=selected_variant.pagination_mode,
            requested_page_size=selected_variant.requested_page_size,
            browser_lifecycle=selected_variant.browser_lifecycle,
            terminal_policy=BAKEOFF_TERMINAL_POLICY,
            max_pages_per_condition=BAKEOFF_MAX_LOGICAL_PAGES_PER_CONDITION,
            require_empty_confirmation=BAKEOFF_REQUIRE_EMPTY_CONFIRMATION,
            max_attempts_per_page=BAKEOFF_MAX_ATTEMPTS_PER_PAGE,
            retry_delays_seconds=BAKEOFF_RETRY_DELAYS_SECONDS,
            page_delay_range_seconds=BAKEOFF_PAGE_DELAY_RANGE_SECONDS,
            session_mode=BAKEOFF_SESSION_MODE,
            fixed_repeat_category_ids=BAKEOFF_CATEGORY_IDS,
            source_artifact_hash=comparison_payload["input_set_hash"],
            comparison_artifact_hash=comparison_manifest_hash,
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
        captured_at = utc_now().isoformat()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "freeze-discovery-candidate",
                "session_mode": "offline",
                "crawl_job_status": "completed",
            },
            captured_at=captured_at,
        )
        candidate_payload = candidate.to_payload()
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata={
                "experiment": "discovery-candidate-v2",
                "crawl_job_id": run_id,
                "crawl_job_status": "completed",
                "candidate_frozen": True,
                "candidate_hash": candidate.candidate_hash,
                "parent_artifact_hash": comparison_manifest_hash,
                "comparison_artifact": str(comparison_dir),
                "selected_variant_id": selected_variant_id,
                "planner_version": planner_version,
            },
            events=[
                {
                    "sequence_no": 1,
                    "event_type": "research.candidate_frozen",
                    "payload": candidate_payload,
                    "emitted_by": "offertoday-research",
                    "created_at": captured_at,
                }
            ],
            provenance=provenance,
            json_files={"candidate.json": candidate_payload},
        )
        if (
            not artifact_verifier(artifact_dir).valid
            or not verify_live_research_run(artifact_dir).valid
        ):
            return EXIT_EVIDENCE_FAILURE
    except (
        OSError,
        ValueError,
        StopIteration,
        subprocess.SubprocessError,
    ) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "candidate_hash": candidate.candidate_hash,
            "selected_variant_id": selected_variant_id,
        }
    )
    return EXIT_OK


def _pagination_bakeoff_command(
    args,
    *,
    session_factory,
    repository,
    runtime_factory,
    service_factory,
    observation_service_factory,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    if len(args.baseline_artifact) != 2:
        _print_json(
            {"error": "pagination-bakeoff requires exactly two baseline artifacts"},
            stream=sys.stderr,
        )
        return EXIT_USAGE
    try:
        baseline_gate = require_matching_baselines(
            args.baseline_artifact[0],
            args.baseline_artifact[1],
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    research_repository = repository or OfferTodayResearchRepository()
    db = None
    artifact_dir = None
    try:
        db = session_factory()
        start_snapshot, start_inventory = _capture_snapshot(
            research_repository,
            db,
        )
        _require_current_baseline(baseline_gate, start_snapshot, start_inventory)
        observation_service = observation_service_factory(db)
        observation_service.create_run(
            ResearchMetadata(
                run_id=run_id,
                experiment="cursor-pagination-bakeoff-v2",
                variant="frozen-five-variant-three-category-v2",
                planner_version=planner_version,
                plan=3,
                parent_artifact_hash=baseline_gate.parent_artifact_hash,
                request_budget=dict(PAGINATION_BAKEOFF_REQUEST_BUDGET),
            ),
            run_start_inventory=start_inventory,
        )
        observation_service.record_event(
            "research.run_started",
            {
                "experiment": "cursor-pagination-bakeoff-v2",
                "repeat_index": args.repeat_index,
                "order_seed": args.order_seed,
                "condition_count": 15,
                "request_budget": dict(PAGINATION_BAKEOFF_REQUEST_BUDGET),
                "endpoint": BAKEOFF_ENDPOINT,
                "rcd_type": BAKEOFF_RCD_TYPE,
                "category_ids": list(BAKEOFF_CATEGORY_IDS),
                "controls": pagination_bakeoff_controls_payload(),
                "thresholds": pagination_bakeoff_thresholds_payload(),
            },
        )
        staging_sink = ResearchNoopListingStagingSink()
        execution = asyncio.run(
            service_factory().run_pagination_bakeoff(
                runtime_factory=runtime_factory,
                observation_service=observation_service,
                repeat_index=args.repeat_index,
                order_seed=args.order_seed,
                staging_sink=staging_sink,
            )
        )
        end_snapshot, end_inventory = _capture_snapshot(
            research_repository,
            db,
        )
        product_data_unchanged = (
            start_snapshot.data_hash == end_snapshot.data_hash
            and start_inventory.data_hash == end_inventory.data_hash
        )
        bakeoff_payload = pagination_bakeoff_to_payload(execution)
        page_evidence = [
            observation.cursor_evidence
            for item in execution.executions
            for observation in item.result.observations
            if observation.cursor_evidence is not None
        ]
        logical_count = len({item.logical_request_id for item in page_evidence})
        physical_count = len(page_evidence)
        bakeoff_completed = (
            execution.failure_reason is None
            and len(execution.executions) == 15
            and logical_count <= PAGINATION_BAKEOFF_REQUEST_BUDGET["listing_logical"]
            and physical_count
            <= PAGINATION_BAKEOFF_REQUEST_BUDGET["listing_attempt_max"]
            and product_data_unchanged
        )
        summary = {
            "bakeoff_completed": bakeoff_completed,
            "failure_reason": execution.failure_reason,
            "repeat_index": args.repeat_index,
            "order_seed": args.order_seed,
            "request_budget": dict(PAGINATION_BAKEOFF_REQUEST_BUDGET),
            "logical_listing_requests": logical_count,
            "physical_listing_attempts": physical_count,
            "detail_attempts": 0,
            "product_writes": 0,
            "product_data_unchanged": product_data_unchanged,
            "run_start_snapshot_hash": start_snapshot.data_hash,
            "run_end_snapshot_hash": end_snapshot.data_hash,
            "run_start_product_data_hash": start_snapshot.product_data_hash,
            "run_end_product_data_hash": end_snapshot.product_data_hash,
            "run_start_inventory_hash": start_inventory.data_hash,
            "run_end_inventory_hash": end_inventory.data_hash,
            "would_stage_rows": staging_sink.would_stage_rows,
            "stage_calls": staging_sink.stage_calls,
            "variant_summaries": bakeoff_payload["variant_summaries"],
            "bakeoff_payload_hash": canonical_bakeoff_payload_hash(
                bakeoff_payload
            ),
        }
        terminal_status = "completed" if bakeoff_completed else "failed"
        observation_service.finish_run(
            status=terminal_status,
            summary=summary,
            error_message=(None if bakeoff_completed else "pagination_bakeoff_failed"),
        )
        events = _ordered_events(
            research_repository.list_research_events(db, UUID(run_id))
        )
        captured_at = utc_now().isoformat()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "pagination-bakeoff",
                "repeat_index": args.repeat_index,
                "order_seed": args.order_seed,
                "session_mode": BAKEOFF_SESSION_MODE,
                "crawl_job_status": terminal_status,
            },
            captured_at=captured_at,
        )
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata={
                "experiment": "cursor-pagination-bakeoff-v2",
                "crawl_job_id": run_id,
                "crawl_job_status": terminal_status,
                "parent_artifact_hash": baseline_gate.parent_artifact_hash,
                "baseline_artifact_hash": baseline_gate.parent_artifact_hash,
                "baseline_artifact_hashes": [
                    baseline_gate.first.manifest_hash,
                    baseline_gate.second.manifest_hash,
                ],
                "baseline_run_ids": [
                    baseline_gate.first.run_id,
                    baseline_gate.second.run_id,
                ],
                "baseline_snapshot_hash": baseline_gate.first.snapshot_hash,
                "baseline_inventory_hash": baseline_gate.first.inventory_hash,
                "repeat_index": args.repeat_index,
                "order_seed": args.order_seed,
                "request_budget": dict(PAGINATION_BAKEOFF_REQUEST_BUDGET),
                "product_data_unchanged": product_data_unchanged,
                "planner_version": planner_version,
            },
            events=events,
            provenance=provenance,
            json_files={"bakeoff.json": bakeoff_payload},
        )
        generic_check = artifact_verifier(artifact_dir)
        strict_check = verify_live_research_run(artifact_dir)
        if not generic_check.valid or not strict_check.valid:
            _print_json(
                {
                    "error": "pagination bake-off artifact verification failed",
                    "strict_issues": list(strict_check.issues),
                },
                stream=sys.stderr,
            )
            return EXIT_EVIDENCE_FAILURE
    except (OSError, SQLAlchemyError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    finally:
        if db is not None:
            db.close()
    exit_code = EXIT_OK if bakeoff_completed else EXIT_HARD_STOP
    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "repeat_index": args.repeat_index,
            "bakeoff_completed": bakeoff_completed,
            "failure_reason": execution.failure_reason,
            "logical_listing_requests": logical_count,
            "physical_listing_attempts": physical_count,
            "exit_code": exit_code,
        }
    )
    return exit_code


def _phase_b_comparison_reference(artifact_dir: Path) -> PhaseCArtifactReference:
    artifact_dir = Path(artifact_dir).resolve(strict=True)
    verification = verify_live_research_run(artifact_dir)
    if (
        not verification.valid
        or verification.experiment != "cursor-pagination-comparison-v2"
        or verification.run_id is None
    ):
        raise ValueError("Phase B comparison artifact failed strict verification")
    manifest_path = artifact_dir / "manifest.json"
    comparison_payload = json.loads(
        (artifact_dir / "comparison.json").read_text(encoding="utf-8")
    )
    decision = comparison_payload.get("decision")
    accepted = decision.get("accepted") if isinstance(decision, dict) else None
    if type(accepted) is not bool:
        raise ValueError("Phase B comparison decision is invalid")
    return PhaseCArtifactReference(
        experiment=verification.experiment,
        run_id=verification.run_id,
        manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        payload_hash=canonical_phase_c_hash(comparison_payload),
        accepted=accepted,
    )


def _phase_c_baseline_reference(
    gate: MatchingBaselineGate,
) -> PhaseCBaselineReference:
    return PhaseCBaselineReference(
        artifact_hashes=(gate.first.manifest_hash, gate.second.manifest_hash),
        run_ids=(gate.first.run_id, gate.second.run_id),
        snapshot_hash=gate.first.snapshot_hash,
        inventory_hash=gate.first.inventory_hash,
    )


def _phase_c_probe_plan(args):
    if args.command == "probe-endpoints":
        return EndpointProbePlan(contract_ids=tuple(args.endpoint_contract_id))
    return build_partition_probe_plan(
        endpoint_contract_id=args.endpoint_contract_id,
        partition_ids=tuple(args.partition_id),
        max_pages_per_condition=args.max_pages_per_condition,
    )


def _phase_c_probe_parent(args) -> PhaseCArtifactReference:
    if args.command == "probe-endpoints":
        return _phase_b_comparison_reference(args.phase_b_comparison_artifact)
    parent = phase_c_artifact_reference(args.endpoint_probe_artifact)
    if parent.experiment != ENDPOINT_PROBE_EXPERIMENT:
        raise ValueError("probe-partitions requires an endpoint probe parent")
    return parent


def _phase_c_probe_command(
    args,
    *,
    session_factory,
    repository,
    runtime_factory,
    service_factory,
    observation_service_factory,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    if len(args.baseline_artifact) != 2:
        _print_json(
            {"error": f"{args.command} requires exactly two baseline artifacts"},
            stream=sys.stderr,
        )
        return EXIT_USAGE
    try:
        plan = _phase_c_probe_plan(args)
    except (KeyError, TypeError, ValueError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_USAGE
    try:
        saved_session = _require_saved_session_state(args.auth_state)
        saved_session_runtime_factory = _bind_saved_session_runtime_factory(
            runtime_factory,
            saved_session,
        )
        parent = _phase_c_probe_parent(args)
        baseline_gate = require_matching_baselines(
            args.baseline_artifact[0],
            args.baseline_artifact[1],
        )
        baseline = _phase_c_baseline_reference(baseline_gate)
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    research_repository = repository or OfferTodayResearchRepository()
    db = None
    artifact_dir = None
    try:
        db = session_factory()
        start_snapshot, start_inventory = _capture_snapshot(
            research_repository,
            db,
        )
        _require_current_baseline(baseline_gate, start_snapshot, start_inventory)
        observation_service = observation_service_factory(db)
        observation_service.create_run(
            ResearchMetadata(
                run_id=run_id,
                experiment=(
                    ENDPOINT_PROBE_EXPERIMENT
                    if args.command == "probe-endpoints"
                    else PARTITION_PROBE_EXPERIMENT
                ),
                variant="phase-c-research-only-v1",
                planner_version=planner_version,
                plan=3,
                parent_artifact_hash=parent.manifest_hash,
                request_budget=plan.budget.to_payload(),
            ),
            run_start_inventory=start_inventory,
        )
        staging_sink = ResearchNoopListingStagingSink()
        service = service_factory()
        if args.command == "probe-endpoints":
            execution: PhaseCProbeExecution = asyncio.run(
                service.run_endpoint_probe(
                    runtime_factory=saved_session_runtime_factory,
                    observation_service=observation_service,
                    plan=plan,
                    staging_sink=staging_sink,
                )
            )
            file_name = "endpoint-probe.json"
        else:
            execution = asyncio.run(
                service.run_partition_probe(
                    runtime_factory=saved_session_runtime_factory,
                    observation_service=observation_service,
                    plan=plan,
                    staging_sink=staging_sink,
                )
            )
            file_name = "partition-probe.json"
        end_snapshot, end_inventory = _capture_snapshot(
            research_repository,
            db,
        )
        no_write = PhaseCNoWriteEvidence(
            start_snapshot_hash=start_snapshot.data_hash,
            end_snapshot_hash=end_snapshot.data_hash,
            start_product_data_hash=start_snapshot.product_data_hash,
            end_product_data_hash=end_snapshot.product_data_hash,
            start_inventory_hash=start_inventory.data_hash,
            end_inventory_hash=end_inventory.data_hash,
            stage_calls=staging_sink.stage_calls,
            would_stage_rows=staging_sink.would_stage_rows,
        )
        payload = build_phase_c_probe_artifact_payload(
            execution=execution,
            parent=parent,
            baseline=baseline,
            no_write=no_write,
        )
        summary = phase_c_probe_summary(payload)
        terminal_status = summary["status"]
        observation_service.finish_run(
            status=terminal_status,
            summary=summary,
            error_message=(
                None
                if execution.failure_reason is None
                else "phase_c_probe_stopped"
            ),
        )
        captured_at = utc_now().isoformat()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": args.command,
                "session_mode": plan.to_payload()["session_mode"],
                "session_state_sha256": saved_session.sha256,
                "crawl_job_status": terminal_status,
            },
            captured_at=captured_at,
        )
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata=phase_c_probe_metadata(
                payload,
                run_id=run_id,
                planner_version=planner_version,
            ),
            events=phase_c_artifact_events(payload, created_at=captured_at),
            provenance=provenance,
            json_files={file_name: payload},
        )
        generic_check = artifact_verifier(artifact_dir)
        strict_check = verify_live_research_run(artifact_dir)
        if not generic_check.valid or not strict_check.valid:
            _print_json(
                {
                    "error": "Phase C probe artifact verification failed",
                    "strict_issues": list(strict_check.issues),
                },
                stream=sys.stderr,
            )
            return EXIT_EVIDENCE_FAILURE
    except (OSError, SQLAlchemyError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    finally:
        if db is not None:
            db.close()

    exit_code = (
        EXIT_HARD_STOP
        if execution.failure_reason is not None
        else (EXIT_OK if execution.accepted else EXIT_INCOMPLETE)
    )
    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "experiment": execution.experiment,
            "accepted": execution.accepted,
            "failure_reason": execution.failure_reason,
            "logical_listing_requests": execution.logical_requests,
            "physical_listing_attempts": execution.physical_attempts,
            "candidate_frozen": False,
            "exit_code": exit_code,
        }
    )
    return exit_code


def _compare_partitions_command(
    args,
    *,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    try:
        parent_inputs = []
        for artifact_path in args.partition_probe_artifact:
            artifact_dir = Path(artifact_path).resolve(strict=True)
            reference = phase_c_artifact_reference(artifact_dir)
            if reference.experiment != PARTITION_PROBE_EXPERIMENT:
                raise ValueError(
                    "compare-partitions requires partition probe artifacts"
                )
            probe_payload = json.loads(
                (artifact_dir / "partition-probe.json").read_text(encoding="utf-8")
            )
            parent_inputs.append(
                build_partition_probe_parent_projection(
                    reference=reference,
                    probe_payload=probe_payload,
                )
            )
        partition_order = {
            partition.partition_id: index
            for index, partition in enumerate(OFFERTODAY_PARTITION_CATALOG)
        }
        parent_inputs.sort(
            key=lambda item: partition_order[item[1].conditions[0].partition_id]
        )
        payload = build_partition_comparison_artifact_payload(parent_inputs)
        summary = phase_c_comparison_summary(payload)
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
        captured_at = utc_now().isoformat()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "compare-partitions",
                "session_mode": "offline",
                "crawl_job_status": "completed",
            },
            captured_at=captured_at,
        )
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata=phase_c_comparison_metadata(
                payload,
                run_id=run_id,
                planner_version=planner_version,
            ),
            events=phase_c_artifact_events(payload, created_at=captured_at),
            provenance=provenance,
            json_files={"partition-comparison.json": payload},
        )
        generic_check = artifact_verifier(artifact_dir)
        strict_check = verify_live_research_run(artifact_dir)
        if not generic_check.valid or not strict_check.valid:
            _print_json(
                {
                    "error": "partition comparison artifact verification failed",
                    "strict_issues": list(strict_check.issues),
                },
                stream=sys.stderr,
            )
            return EXIT_EVIDENCE_FAILURE
    except (
        IndexError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    exit_code = EXIT_OK if summary["accepted"] else EXIT_INCOMPLETE
    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "accepted": summary["accepted"],
            "retained_partition_ids": summary["retained_partition_ids"],
            "rejected_partition_ids": summary["rejected_partition_ids"],
            "candidate_frozen": False,
            "exit_code": exit_code,
        }
    )
    return exit_code


def _phase_c_endpoint_condition_satisfies_policy_freeze(condition) -> bool:
    contract_evidence_is_clean = (
        condition.contract_verified
        and bool(condition.pages)
        and all(page.contract_error is None for page in condition.pages)
        and condition.gap_count == 0
        and condition.identity_conflict_count == 0
        and condition.identity_issue_count == 0
        and condition.conservation_difference == 0
    )
    bounded_contract_observation = (
        condition.stop_reason == "page_cap"
        and not condition.is_complete
        and not condition.terminal_confirmed
        and not condition.empty_confirmation
    )
    exhausted_contract_observation = (
        condition.stop_reason == "natural_exhaustion"
        and condition.is_complete
        and condition.terminal_confirmed
        and condition.empty_confirmation
    )
    return contract_evidence_is_clean and (
        bounded_contract_observation or exhausted_contract_observation
    )


def _freeze_discovery_policy_command(
    args,
    *,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    try:
        phase_b = _phase_b_comparison_reference(
            args.phase_b_comparison_artifact
        )
        if phase_b.accepted is not False:
            raise ValueError(
                "Phase D policy freeze requires the valid-rejected Phase B lineage"
            )

        endpoint_dir = Path(args.endpoint_probe_artifact).resolve(strict=True)
        endpoint_reference = phase_c_artifact_reference(endpoint_dir)
        if endpoint_reference.experiment != ENDPOINT_PROBE_EXPERIMENT:
            raise ValueError("policy freeze requires an endpoint probe artifact")
        endpoint_payload = json.loads(
            (endpoint_dir / "endpoint-probe.json").read_text(encoding="utf-8")
        )
        endpoint_execution, endpoint_parent, _, _ = (
            validate_phase_c_probe_artifact_payload(endpoint_payload)
        )
        if endpoint_parent != phase_b:
            raise ValueError("endpoint probe does not descend from the supplied Phase B comparison")
        if endpoint_execution.failure_reason is not None:
            raise ValueError("endpoint probe ended with a hard stop")

        comparison_dir = Path(args.partition_comparison_artifact).resolve(
            strict=True
        )
        comparison_reference = phase_c_artifact_reference(comparison_dir)
        if comparison_reference.experiment != "partition-comparison-v1":
            raise ValueError(
                "policy freeze requires a partition comparison artifact"
            )
        comparison_payload = json.loads(
            (comparison_dir / "partition-comparison.json").read_text(
                encoding="utf-8"
            )
        )
        comparison_decision, _ = (
            validate_partition_comparison_artifact_payload(comparison_payload)
        )
        if (
            comparison_reference.accepted is not True
            or comparison_decision.accepted is not True
        ):
            raise ValueError("partition comparison did not retain a discovery policy")

        endpoint_contract_id = comparison_payload["endpoint_contract_id"]
        endpoint_conditions = tuple(
            condition
            for condition in endpoint_execution.conditions
            if condition.endpoint_contract_id == endpoint_contract_id
        )
        if len(endpoint_conditions) != 1 or not (
            _phase_c_endpoint_condition_satisfies_policy_freeze(
                endpoint_conditions[0]
            )
        ):
            raise ValueError(
                "selected endpoint lacks verified cursor-contract probe evidence"
            )

        supplied_projections = []
        for artifact_path in args.partition_probe_artifact:
            probe_dir = Path(artifact_path).resolve(strict=True)
            probe_reference = phase_c_artifact_reference(probe_dir)
            if probe_reference.experiment != PARTITION_PROBE_EXPERIMENT:
                raise ValueError("policy freeze requires partition probe artifacts")
            probe_payload = json.loads(
                (probe_dir / "partition-probe.json").read_text(encoding="utf-8")
            )
            probe_execution, probe_parent, _, _ = (
                validate_phase_c_probe_artifact_payload(probe_payload)
            )
            if probe_parent != endpoint_reference:
                raise ValueError(
                    "partition probe does not descend from the supplied endpoint probe"
                )
            if probe_execution.plan.endpoint_contract_id != endpoint_contract_id:
                raise ValueError(
                    "partition probe endpoint does not match the comparison policy"
                )
            projection, _ = build_partition_probe_parent_projection(
                reference=probe_reference,
                probe_payload=probe_payload,
            )
            supplied_projections.append(projection.to_payload())

        expected_projections = comparison_payload["parents"]
        supplied_hashes = tuple(
            sorted(canonical_phase_c_hash(item) for item in supplied_projections)
        )
        expected_hashes = tuple(
            sorted(canonical_phase_c_hash(item) for item in expected_projections)
        )
        if (
            len(supplied_projections) != len(expected_projections)
            or len(set(supplied_hashes)) != len(supplied_hashes)
            or supplied_hashes != expected_hashes
        ):
            raise ValueError(
                "supplied partition probes do not exactly match comparison parents"
            )

        candidate = build_discovery_policy_candidate_v2(
            comparison_payload=comparison_payload["comparison"],
            endpoint_contract_id=endpoint_contract_id,
            phase_b_comparison_artifact_hash=phase_b.manifest_hash,
            phase_c_comparison_artifact_hash=comparison_reference.manifest_hash,
        )
        payload = discovery_policy_candidate_artifact_payload(candidate)
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
        captured_at = utc_now().isoformat()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "freeze-discovery-policy",
                "session_mode": "offline",
                "crawl_job_status": "completed",
            },
            captured_at=captured_at,
        )
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata=phase_d_metadata(
                payload,
                run_id=run_id,
                planner_version=planner_version,
            ),
            events=phase_d_artifact_events(payload, created_at=captured_at),
            provenance=provenance,
            json_files={"discovery-policy.json": payload},
        )
        generic_check = artifact_verifier(artifact_dir)
        strict_check = verify_live_research_run(artifact_dir)
        if not generic_check.valid or not strict_check.valid:
            return EXIT_EVIDENCE_FAILURE
    except (
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "candidate_hash": candidate.candidate_hash,
            "endpoint_contract_id": candidate.endpoint_contract_id,
            "retained_partition_ids": list(candidate.retained_partition_ids),
            "deferred_issue_ids": list(candidate.deferred_issue_ids),
            "exit_code": EXIT_OK,
        }
    )
    return EXIT_OK


def _require_phase_d_policy_artifact(
    artifact_dir: Path,
) -> PhaseDPolicyEvidence:
    artifact_dir = Path(artifact_dir).resolve(strict=True)
    strict_check = verify_live_research_run(artifact_dir)
    if (
        not strict_check.valid
        or strict_check.experiment != DISCOVERY_POLICY_CANDIDATE_EXPERIMENT
        or strict_check.run_id is None
    ):
        raise ValueError(
            "Phase D requires a strict discovery-policy-candidate-v2 artifact"
        )
    manifest_path = artifact_dir / "manifest.json"
    payload = json.loads(
        (artifact_dir / "discovery-policy.json").read_text(encoding="utf-8")
    )
    candidate = validate_discovery_policy_candidate_artifact_payload(payload)
    return PhaseDPolicyEvidence(
        candidate=candidate,
        candidate_hash=candidate.candidate_hash,
        manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        run_id=strict_check.run_id,
    )


def _phase_d_request_budget(
    candidate: DiscoveryPolicyCandidateV2,
    *,
    experiment: str,
) -> dict[str, int]:
    condition_count = (
        len(candidate.phase_d_partitions)
        if experiment == PHASE_D_CENSUS_EXPERIMENT
        else len(candidate.fixed_repeat_category_ids)
    )
    logical = condition_count * candidate.max_pages_per_condition
    return {
        "listing_logical": logical,
        "listing_attempt_max": logical * candidate.max_attempts_per_page,
        "detail": 0,
        "product_writes": 0,
    }


def _phase_d_staging_evidence(staging_sink) -> PhaseDStagingEvidence:
    if isinstance(staging_sink, ResearchNoopListingStagingSink):
        deferred_ids = tuple(
            sorted(
                {
                    job_id
                    for conflict in staging_sink.deferred_conflicts
                    for job_id in conflict.job_ids
                }
            )
        )
        return PhaseDStagingEvidence(
            staging_mode="noop",
            rows_seen=0,
            rows_created=0,
            published_source_job_ids=(),
            preexisting_staged_source_job_ids=(),
            created_source_job_ids=(),
            deferred_identity_conflict_ids=deferred_ids,
            would_stage_rows=staging_sink.would_stage_rows,
            stage_calls=staging_sink.stage_calls,
        )
    if isinstance(staging_sink, OfferTodayReconciledListingStagingSink):
        reconciliation = staging_sink.reconciliation

        def canonical(values) -> tuple[str, ...]:
            return tuple(sorted(set(values)))

        return PhaseDStagingEvidence(
            staging_mode="reconciled",
            rows_seen=reconciliation.rows_seen,
            rows_created=reconciliation.rows_created,
            published_source_job_ids=canonical(
                reconciliation.published_source_job_ids
            ),
            preexisting_staged_source_job_ids=canonical(
                reconciliation.preexisting_staged_source_job_ids
            ),
            created_source_job_ids=canonical(
                reconciliation.created_source_job_ids
            ),
            deferred_identity_conflict_ids=canonical(
                reconciliation.deferred_identity_conflict_ids
            ),
            would_stage_rows=0,
            stage_calls=staging_sink.stage_calls,
        )
    raise ValueError("unsupported Phase D staging sink")


def _phase_d_condition_conservation_difference(result) -> int:
    observed_ids = {
        job_id
        for observation in result.observations
        if observation.cursor_evidence is not None
        for job_id in (
            *observation.cursor_evidence.result_job_ids,
            *observation.cursor_evidence.supplemental_job_ids,
        )
    }
    return len(observed_ids.symmetric_difference(result.accepted_job_ids))


def _phase_d_staging_conservation_difference(
    *,
    results,
    staging: PhaseDStagingEvidence,
    start_snapshot,
    end_snapshot,
) -> int:
    if end_snapshot is None:
        return 1
    staged_rows_delta = end_snapshot.staged_rows - start_snapshot.staged_rows
    if staging.staging_mode == "noop":
        return abs(staged_rows_delta)

    discovered_ids = {
        job_id for result in results for job_id in result.accepted_job_ids
    }
    cohorts = (
        set(staging.published_source_job_ids),
        set(staging.preexisting_staged_source_job_ids),
        set(staging.created_source_job_ids),
        set(staging.deferred_identity_conflict_ids),
    )
    reconciled_ids = set().union(*cohorts)
    overlap_count = sum(
        max(sum(job_id in cohort for cohort in cohorts) - 1, 0)
        for job_id in reconciled_ids
    )
    return (
        len(discovered_ids.symmetric_difference(reconciled_ids))
        + overlap_count
        + abs(staged_rows_delta - staging.rows_created)
    )


def _phase_d_product_evidence(
    *,
    start_snapshot,
    end_snapshot,
    start_inventory,
    end_inventory,
    staging: PhaseDStagingEvidence,
    detail_attempts: int,
    product_writes: int,
    activity_evidence_captured: bool = True,
) -> PhaseDProductEvidence:
    return PhaseDProductEvidence(
        start_snapshot_hash=start_snapshot.data_hash,
        end_snapshot_hash=(end_snapshot.data_hash if end_snapshot else None),
        start_inventory_hash=start_inventory.data_hash,
        end_inventory_hash=(end_inventory.data_hash if end_inventory else None),
        start_staged_rows_hash=start_snapshot.staged_rows_hash,
        end_staged_rows_hash=(
            end_snapshot.staged_rows_hash if end_snapshot else None
        ),
        start_published_jobs_hash=start_snapshot.published_jobs_hash,
        end_published_jobs_hash=(
            end_snapshot.published_jobs_hash if end_snapshot else None
        ),
        start_companies_hash=start_snapshot.companies_hash,
        end_companies_hash=(end_snapshot.companies_hash if end_snapshot else None),
        start_product_data_hash=start_snapshot.product_data_hash,
        end_product_data_hash=(
            end_snapshot.product_data_hash if end_snapshot else None
        ),
        detail_attempts=detail_attempts,
        product_writes=product_writes,
        staging=staging,
        activity_evidence_captured=activity_evidence_captured,
    )


def _phase_d_live_command(
    args,
    *,
    session_factory,
    repository,
    runtime_factory,
    service_factory,
    observation_service_factory,
    crawl_runtime_factory,
    staging_sink_factory,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    if len(args.baseline_artifact) != 2:
        _print_json(
            {"error": f"{args.command} requires exactly two baseline artifacts"},
            stream=sys.stderr,
        )
        return EXIT_USAGE
    if args.staging_mode == "reconciled" and not args.confirm_staging_writes:
        _print_json(
            {"error": "reconciled staging requires --confirm-staging-writes"},
            stream=sys.stderr,
        )
        return EXIT_USAGE
    if args.staging_mode == "noop" and args.confirm_staging_writes:
        _print_json(
            {"error": "--confirm-staging-writes requires reconciled staging"},
            stream=sys.stderr,
        )
        return EXIT_USAGE

    try:
        saved_session = _require_saved_session_state(args.auth_state)
        saved_session_runtime_factory = _bind_saved_session_runtime_factory(
            runtime_factory,
            saved_session,
        )
        candidate_evidence = _require_phase_d_policy_artifact(
            args.candidate_artifact
        )
        baseline_gate = require_matching_baselines(
            args.baseline_artifact[0],
            args.baseline_artifact[1],
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    experiment = (
        PHASE_D_CENSUS_EXPERIMENT
        if args.command == "census-v2"
        else PHASE_D_FIXED_REPEAT_EXPERIMENT
    )
    candidate = candidate_evidence.candidate
    request_budget = _phase_d_request_budget(
        candidate,
        experiment=experiment,
    )
    research_repository = repository or OfferTodayResearchRepository()
    db = None
    artifact_dir = None
    try:
        db = session_factory()
        start_snapshot, start_inventory = _capture_snapshot(
            research_repository,
            db,
        )
        _require_current_baseline(
            baseline_gate,
            start_snapshot,
            start_inventory,
        )

        observation_service = observation_service_factory(db)
        observation_service.create_run(
            ResearchMetadata(
                run_id=run_id,
                experiment=experiment,
                variant=f"phase-c:{candidate.endpoint_contract_id}",
                planner_version=planner_version,
                plan=3,
                parent_artifact_hash=candidate_evidence.manifest_hash,
                request_budget=request_budget,
            ),
            run_start_inventory=start_inventory,
        )
        staging_sink = (
            ResearchNoopListingStagingSink()
            if args.staging_mode == "noop"
            else staging_sink_factory(
                crawl_runtime=crawl_runtime_factory(),
                crawl_job_id=run_id,
                skip_existing=True,
            )
        )
        service = service_factory()
        started_at = time.perf_counter()
        execution = asyncio.run(
            (
                service.run_census_v2
                if experiment == PHASE_D_CENSUS_EXPERIMENT
                else service.run_fixed_repeat_v2
            )(
                runtime_factory=saved_session_runtime_factory,
                observation_service=observation_service,
                candidate=candidate,
                staging_sink=staging_sink,
            )
        )
        duration_seconds = max(0.0, time.perf_counter() - started_at)
        evidence_failure = False
        failure_reason = execution.failure_reason
        end_snapshot = None
        end_inventory = None
        try:
            end_snapshot, end_inventory = _capture_snapshot(
                research_repository,
                db,
            )
        except Exception as exc:
            evidence_failure = True
            failure_reason = (
                "unexpected_phase_d_census_error:"
                f"{type(exc).__name__}"
            )
        activity_evidence_captured = True
        try:
            recorded_events = _ordered_events(
                research_repository.list_research_events(db, UUID(run_id))
            )
        except Exception as exc:
            recorded_events = []
            activity_evidence_captured = False
            evidence_failure = True
            failure_reason = (
                "unexpected_phase_d_census_error:"
                f"{type(exc).__name__}"
            )
        detail_attempts = sum(
            event.get("event_type") == "research.detail_attempt"
            for event in recorded_events
        )
        product_writes = sum(
            event.get("event_type") == "research.product_write"
            for event in recorded_events
        )
        staging = _phase_d_staging_evidence(staging_sink)
        product = _phase_d_product_evidence(
            start_snapshot=start_snapshot,
            end_snapshot=end_snapshot,
            start_inventory=start_inventory,
            end_inventory=end_inventory,
            staging=staging,
            detail_attempts=detail_attempts,
            product_writes=product_writes,
            activity_evidence_captured=activity_evidence_captured,
        )
        captured_at = utc_now().isoformat()
        condition_differences = tuple(
            _phase_d_condition_conservation_difference(result)
            for result in execution.results
        )
        staging_difference = _phase_d_staging_conservation_difference(
            results=execution.results,
            staging=staging,
            start_snapshot=start_snapshot,
            end_snapshot=end_snapshot,
        )
        baseline = _phase_c_baseline_reference(baseline_gate)

        def build_run_payload(active_failure_reason):
            active_run = build_phase_d_run_evidence(
                experiment=experiment,
                run_id=run_id,
                run_index=args.run_index,
                window_id=args.window_id,
                captured_at=captured_at,
                candidate=candidate,
                candidate_artifact_hash=candidate_evidence.manifest_hash,
                duration_seconds=duration_seconds,
                results=execution.results,
                product=product,
                failure_reason=active_failure_reason,
                condition_conservation_differences=condition_differences,
                staging_conservation_difference=staging_difference,
            )
            active_payload = phase_d_run_artifact_payload(
                run=active_run,
                candidate=candidate,
                baseline=baseline,
                product=product,
            )
            return active_run, active_payload

        run, payload = build_run_payload(failure_reason)

        def build_summary() -> dict[str, Any]:
            return {
                "experiment": experiment,
                "accepted": payload["accepted"],
                "candidate_hash": candidate.candidate_hash,
                "run_index": run.run_index,
                "window_id": run.window_id,
                "completed_condition_count": len(run.conditions),
                "logical_listing_requests": run.logical_requests,
                "physical_listing_attempts": run.physical_attempts,
                "failure_reason": failure_reason,
                "staging_mode": staging.staging_mode,
                "detail_attempts": product.detail_attempts,
                "product_writes": product.product_writes,
                "end_snapshot_captured": product.end_snapshot_captured,
                "activity_evidence_captured": (
                    product.activity_evidence_captured
                ),
            }

        summary = build_summary()
        try:
            observation_service.finish_run(
                status="completed" if payload["accepted"] else "failed",
                summary=summary,
                error_message=(
                    None if failure_reason is None else "phase_d_live_stopped"
                ),
            )
        except Exception as exc:
            evidence_failure = True
            failure_reason = (
                "unexpected_phase_d_census_error:"
                f"{type(exc).__name__}"
            )
            run, payload = build_run_payload(failure_reason)
            summary = build_summary()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": args.command,
                "session_mode": candidate.session_mode,
                "session_state_sha256": saved_session.sha256,
                "crawl_job_status": (
                    "completed" if payload["accepted"] else "failed"
                ),
                "staging_mode": staging.staging_mode,
            },
            captured_at=captured_at,
        )
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata=phase_d_metadata(
                payload,
                run_id=run_id,
                planner_version=planner_version,
            ),
            events=phase_d_artifact_events(payload, created_at=captured_at),
            provenance=provenance,
            json_files={"phase-d-run.json": payload},
        )
        generic_check = artifact_verifier(artifact_dir)
        strict_check = verify_live_research_run(artifact_dir)
        if not generic_check.valid or not strict_check.valid:
            return EXIT_EVIDENCE_FAILURE
    except (
        AttributeError,
        OSError,
        SQLAlchemyError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    finally:
        if db is not None:
            db.close()

    exit_code = (
        EXIT_EVIDENCE_FAILURE
        if evidence_failure or not product.accepted
        else (
            EXIT_HARD_STOP
            if failure_reason is not None
            else (EXIT_OK if payload["accepted"] else EXIT_INCOMPLETE)
        )
    )
    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "experiment": experiment,
            "candidate_hash": candidate.candidate_hash,
            "run_index": run.run_index,
            "window_id": run.window_id,
            "accepted": payload["accepted"],
            "failure_reason": failure_reason,
            "completed_condition_count": len(run.conditions),
            "logical_listing_requests": run.logical_requests,
            "physical_listing_attempts": run.physical_attempts,
            "staging_mode": staging.staging_mode,
            "exit_code": exit_code,
        }
    )
    return exit_code


def _compare_phase_d_command(
    args,
    *,
    provenance_provider,
    artifact_exporter,
    artifact_verifier,
) -> int:
    if len(args.census_artifact) != 3 or len(args.fixed_repeat_artifact) != 3:
        _print_json(
            {
                "error": (
                    "compare-stability-v2 requires exactly three census and "
                    "three fixed-repeat artifacts"
                )
            },
            stream=sys.stderr,
        )
        return EXIT_USAGE
    try:
        census_parents = []
        for artifact_path in args.census_artifact:
            artifact_dir = Path(artifact_path).resolve(strict=True)
            reference = phase_d_artifact_reference(artifact_dir)
            if reference.experiment != PHASE_D_CENSUS_EXPERIMENT:
                raise ValueError(
                    "compare-stability-v2 census parent version does not match"
                )
            if reference.accepted is not True:
                raise ValueError(
                    "compare-stability-v2 requires accepted census parents"
                )
            payload = json.loads(
                (artifact_dir / "phase-d-run.json").read_text(encoding="utf-8")
            )
            census_parents.append((reference, payload))
        fixed_parents = []
        for artifact_path in args.fixed_repeat_artifact:
            artifact_dir = Path(artifact_path).resolve(strict=True)
            reference = phase_d_artifact_reference(artifact_dir)
            if reference.experiment != PHASE_D_FIXED_REPEAT_EXPERIMENT:
                raise ValueError(
                    "compare-stability-v2 fixed parent version does not match"
                )
            if reference.accepted is not True:
                raise ValueError(
                    "compare-stability-v2 requires accepted fixed-repeat parents"
                )
            payload = json.loads(
                (artifact_dir / "phase-d-run.json").read_text(encoding="utf-8")
            )
            fixed_parents.append((reference, payload))
        census_parents.sort(key=lambda item: item[1]["run"]["run_index"])
        fixed_parents.sort(key=lambda item: item[1]["run"]["run_index"])
        payload = build_phase_d_comparison_artifact_payload(
            (*census_parents, *fixed_parents),
            active_holdout_ids=tuple(args.active_holdout_id),
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
        captured_at = utc_now().isoformat()
        provenance = provenance_provider(
            repo_root=repo_root,
            runtime_context={
                "command": "compare-stability-v2",
                "session_mode": "offline",
                "crawl_job_status": "completed",
            },
            captured_at=captured_at,
        )
        artifact_dir = artifact_exporter(
            root=args.artifact_root,
            run_id=run_id,
            metadata=phase_d_metadata(
                payload,
                run_id=run_id,
                planner_version=planner_version,
            ),
            events=phase_d_artifact_events(payload, created_at=captured_at),
            provenance=provenance,
            json_files={"phase-d-comparison.json": payload},
        )
        generic_check = artifact_verifier(artifact_dir)
        strict_check = verify_live_research_run(artifact_dir)
        if not generic_check.valid or not strict_check.valid:
            return EXIT_EVIDENCE_FAILURE
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    accepted = bool(payload["comparison"]["comparison"]["decision"]["accepted"])
    exit_code = EXIT_OK if accepted else EXIT_INCOMPLETE
    comparison = payload["comparison"]["comparison"]
    _print_json(
        {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "accepted": accepted,
            "candidate_hash": comparison["candidate_hash"],
            "fixed_cohort_jaccard": comparison["fixed_cohort_jaccard"],
            "unique_count_cv": comparison["unique_count_cv"],
            "stable_reference_count": len(comparison["stable_reference_ids"]),
            "stable_reference_hash": comparison["stable_reference_hash"],
            "exit_code": exit_code,
        }
    )
    return exit_code


def main(
    argv: list[str] | None = None,
    *,
    session_factory=SessionLocal,
    repository: OfferTodayResearchRepository | None = None,
    runtime_factory=OfferTodayBrowserRuntime,
    service_factory=OfferTodayResearchLiveService,
    observation_service_factory=OfferTodayResearchObservationService,
    crawl_runtime_factory=CrawlJobRuntime,
    staging_sink_factory=OfferTodayReconciledListingStagingSink,
    provenance_provider=capture_research_provenance,
    artifact_exporter=export_research_artifact,
    artifact_verifier=verify_research_artifact,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "verify-run":
        result = verify_live_research_run(args.artifact)
        _print_json(result.to_payload())
        return EXIT_OK if result.valid else EXIT_EVIDENCE_FAILURE
    if args.command in {"probe-endpoints", "probe-partitions"}:
        return _phase_c_probe_command(
            args,
            session_factory=session_factory,
            repository=repository,
            runtime_factory=runtime_factory,
            service_factory=service_factory,
            observation_service_factory=observation_service_factory,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "compare-partitions":
        return _compare_partitions_command(
            args,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "freeze-discovery-policy":
        return _freeze_discovery_policy_command(
            args,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command in {"census-v2", "repeat-fixed-v2"}:
        return _phase_d_live_command(
            args,
            session_factory=session_factory,
            repository=repository,
            runtime_factory=runtime_factory,
            service_factory=service_factory,
            observation_service_factory=observation_service_factory,
            crawl_runtime_factory=crawl_runtime_factory,
            staging_sink_factory=staging_sink_factory,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "compare-stability-v2":
        return _compare_phase_d_command(
            args,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "pagination-bakeoff":
        return _pagination_bakeoff_command(
            args,
            session_factory=session_factory,
            repository=repository,
            runtime_factory=runtime_factory,
            service_factory=service_factory,
            observation_service_factory=observation_service_factory,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "compare-pagination":
        return _compare_pagination_command(
            args,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "freeze-discovery-candidate":
        return _freeze_discovery_candidate_command(
            args,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "freeze-candidate":
        return _freeze_candidate_command(
            args,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )
    if args.command == "compare":
        return _compare_command(
            args,
            provenance_provider=provenance_provider,
            artifact_exporter=artifact_exporter,
            artifact_verifier=artifact_verifier,
        )

    request_budget = (
        dict(_CALIBRATION_REQUEST_BUDGET)
        if args.command == "calibrate"
        else (
            dict(_PILOT_REQUEST_BUDGET)
            if args.command == "pilot"
            else (
                dict(_FIXED_REPEAT_REQUEST_BUDGET)
                if args.command == "repeat-fixed"
                else (
                    dict(_CENSUS_REQUEST_BUDGET)
                    if args.command == "census"
                    else runtime_smoke_request_budget()
                )
            )
        )
    )
    if len(args.baseline_artifact) != 2:
        _print_json(
            {"error": (f"{args.command} requires exactly two baseline artifacts")},
            stream=sys.stderr,
        )
        return EXIT_USAGE

    try:
        smoke_artifact_hash = None
        pilot_variant = None
        candidate_evidence = None
        if args.command == "calibrate":
            _require_accepted_smoke_artifact(args.smoke_artifact)
            smoke_artifact_hash = hashlib.sha256(
                (Path(args.smoke_artifact) / "manifest.json").read_bytes()
            ).hexdigest()
        elif args.command == "pilot":
            pilot_variant = _require_accepted_calibration_variant(
                args.calibration_artifact,
                variant_rank=args.variant_rank,
            )
        elif args.command in {"census", "repeat-fixed"}:
            candidate_evidence = _require_census_candidate_artifact(
                args.candidate_artifact
            )
        baseline_gate = require_matching_baselines(
            args.baseline_artifact[0],
            args.baseline_artifact[1],
        )
        run_id = str(UUID(args.run_id)) if args.run_id else str(uuid4())
        repo_root = args.repo_root.resolve(strict=True)
        planner_version = _git_head(repo_root)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        _print_json({"error": str(exc)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE

    research_repository = repository or OfferTodayResearchRepository()
    db = None
    observation_service = None
    start_snapshot = None
    start_inventory = None
    end_snapshot = None
    end_inventory = None
    execution = None
    events: list[dict[str, Any]] = []
    events_before_summary: list[dict[str, Any]] = []
    terminal_status = "failed"
    summary: dict[str, Any] = {}
    exit_code = EXIT_EVIDENCE_FAILURE
    original_error: BaseException | None = None
    pre_run_error: BaseException | None = None
    finalization_error: BaseException | None = None
    artifact_dir: Path | None = None
    is_calibration = args.command == "calibrate"
    is_pilot = args.command == "pilot"
    is_census = args.command == "census"
    is_fixed_repeat = args.command == "repeat-fixed"
    is_census_family = is_census or is_fixed_repeat
    experiment = (
        "listing-calibration"
        if is_calibration
        else (
            "category-pilot"
            if is_pilot
            else (
                "fixed-condition-repeat"
                if is_fixed_repeat
                else "full-census" if is_census else "runtime-smoke"
            )
        )
    )
    variant = (
        "locked-2x2x2-fresh-headless"
        if is_calibration
        else (
            (
                f"{pilot_variant.endpoint}-rcdtype-"
                f"{pilot_variant.rcd_type if pilot_variant.rcd_type is not None else 'omitted'}"
                "-31-category-pilot"
            )
            if is_pilot and pilot_variant is not None
            else (
                (
                    f"{candidate_evidence.candidate.endpoint}-rcdtype-"
                    f"{candidate_evidence.candidate.rcd_type if candidate_evidence.candidate.rcd_type is not None else 'omitted'}"
                    f"{'-3-category-fixed-repeat' if is_fixed_repeat else '-31-category-full-census'}"
                )
                if is_census_family and candidate_evidence is not None
                else "search-rcdtype-7-fresh-headless"
            )
        )
    )
    parent_artifact_hash = (
        smoke_artifact_hash
        if is_calibration and smoke_artifact_hash is not None
        else (
            pilot_variant.parent_artifact_hash
            if is_pilot and pilot_variant is not None
            else (
                candidate_evidence.parent_artifact_hash
                if is_census_family and candidate_evidence is not None
                else baseline_gate.parent_artifact_hash
            )
        )
    )
    calibration_results = None
    pilot_results = None
    pilot_conditions = (
        build_pilot_conditions(pilot_variant.endpoint, pilot_variant.rcd_type)
        if is_pilot and pilot_variant is not None
        else ()
    )
    pilot_staging_sink = None
    census_result = None
    census_conditions = ()
    if is_census_family and candidate_evidence is not None:
        all_candidate_conditions = build_pilot_conditions(
            candidate_evidence.candidate.endpoint,
            candidate_evidence.candidate.rcd_type,
        )
        if is_fixed_repeat:
            conditions_by_category = {
                condition.category_id: condition
                for condition in all_candidate_conditions
            }
            census_conditions = tuple(
                conditions_by_category[category_id]
                for category_id in candidate_evidence.candidate.fixed_repeat_category_ids
            )
        else:
            census_conditions = all_candidate_conditions
    census_staging_sink = None

    try:
        db = session_factory()
        start_snapshot, start_inventory = _capture_snapshot(research_repository, db)
        _require_current_baseline(baseline_gate, start_snapshot, start_inventory)
        observation_service = observation_service_factory(db)
        observation_service.create_run(
            ResearchMetadata(
                run_id=run_id,
                experiment=experiment,
                variant=variant,
                planner_version=planner_version,
                plan=2,
                parent_artifact_hash=parent_artifact_hash,
                request_budget=dict(request_budget),
            ),
            run_start_inventory=start_inventory,
        )
        observation_service.record_event(
            "research.run_started",
            {
                "experiment": experiment,
                "parent_artifact_hash": parent_artifact_hash,
                "baseline_artifact_hash": baseline_gate.parent_artifact_hash,
                "request_budget": dict(request_budget),
                "session_mode": "fresh-headless",
                **(
                    {"condition_count": len(build_calibration_conditions())}
                    if is_calibration
                    else (
                        {
                            "condition_count": len(pilot_conditions),
                            "variant_rank": pilot_variant.variant_rank,
                            "endpoint": pilot_variant.endpoint,
                            "rcd_type": pilot_variant.rcd_type,
                            "calibration_run_id": pilot_variant.calibration_run_id,
                        }
                        if is_pilot and pilot_variant is not None
                        else (
                            {
                                "condition_count": len(census_conditions),
                                "candidate_hash": candidate_evidence.candidate_hash,
                                "candidate_run_id": candidate_evidence.candidate_run_id,
                                "endpoint": candidate_evidence.candidate.endpoint,
                                "rcd_type": candidate_evidence.candidate.rcd_type,
                                "max_pages_per_condition": (
                                    candidate_evidence.candidate.max_pages_per_condition
                                ),
                                "require_empty_confirmation": (
                                    candidate_evidence.candidate.require_empty_confirmation
                                ),
                                "max_attempts_per_page": (
                                    candidate_evidence.candidate.max_attempts_per_page
                                ),
                                "retry_delays_seconds": list(
                                    candidate_evidence.candidate.retry_delays_seconds
                                ),
                                "page_delay_range_seconds": list(
                                    candidate_evidence.candidate.page_delay_range_seconds
                                ),
                                **(
                                    {"repeat_index": args.repeat_index}
                                    if is_fixed_repeat
                                    else {}
                                ),
                            }
                            if is_census_family and candidate_evidence is not None
                            else {}
                        )
                    )
                ),
            },
        )

        try:
            if is_calibration:
                calibration_results = asyncio.run(
                    _execute_calibration_with_runtime(
                        runtime_factory=runtime_factory,
                        service=service_factory(),
                        observation_service=observation_service,
                    )
                )
            elif is_census_family and candidate_evidence is not None:
                census_staging_sink = staging_sink_factory(
                    crawl_runtime=crawl_runtime_factory(),
                    crawl_job_id=run_id,
                    skip_existing=True,
                )
                census_result = asyncio.run(
                    (
                        _execute_fixed_repeat_with_runtime
                        if is_fixed_repeat
                        else _execute_census_with_runtime
                    )(
                        runtime_factory=runtime_factory,
                        service=service_factory(),
                        observation_service=observation_service,
                        candidate=candidate_evidence.candidate,
                        staging_sink=census_staging_sink,
                    )
                )
            elif is_pilot:
                pilot_staging_sink = staging_sink_factory(
                    crawl_runtime=crawl_runtime_factory(),
                    crawl_job_id=run_id,
                    skip_existing=True,
                )
                pilot_results = asyncio.run(
                    _execute_pilot_with_runtime(
                        runtime_factory=runtime_factory,
                        service=service_factory(),
                        observation_service=observation_service,
                        conditions=pilot_conditions,
                        staging_sink=pilot_staging_sink,
                    )
                )
            else:
                execution = asyncio.run(
                    _execute_smoke_with_runtime(
                        runtime_factory=runtime_factory,
                        service=service_factory(),
                        observation_service=observation_service,
                    )
                )
        except BaseException as exc:
            original_error = exc

        end_snapshot, end_inventory = _capture_snapshot(research_repository, db)
        product_data_unchanged = (
            start_snapshot.data_hash == end_snapshot.data_hash
            and start_inventory.data_hash == end_inventory.data_hash
        )
        if original_error is not None:
            failure_reason = _unexpected_error_message(
                original_error,
                experiment=experiment,
            )
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
            )
        elif (
            is_census_family
            and candidate_evidence is not None
            and census_staging_sink is not None
        ):
            census_events = _ordered_events(
                research_repository.list_research_events(db, UUID(run_id))
            )
            census_analysis = _analyze_census(
                result=census_result,
                conditions=census_conditions,
                events_before_summary=census_events,
                reconciliation=census_staging_sink.reconciliation,
                request_budget=request_budget,
            )
            database_conservation_difference = (
                end_snapshot.staged_rows
                - start_snapshot.staged_rows
                - census_staging_sink.reconciliation.rows_created
            )
            published_jobs_unchanged = (
                start_snapshot.published_jobs == end_snapshot.published_jobs
                and start_snapshot.published_jobs_hash
                == end_snapshot.published_jobs_hash
            )
            companies_unchanged = (
                start_snapshot.companies_hash == end_snapshot.companies_hash
            )
            failure_reason = census_analysis["failure_reason"]
            if failure_reason is None and database_conservation_difference != 0:
                failure_reason = "conservation_difference"
            if failure_reason is None and not published_jobs_unchanged:
                failure_reason = "published_jobs_changed"
            if failure_reason is None and not companies_unchanged:
                failure_reason = "companies_changed"
            if failure_reason is None:
                terminal_status = "completed"
                exit_code = EXIT_OK
            else:
                observation_service.record_event(
                    "research.run_stopped",
                    {"reason": failure_reason},
                )
                if failure_reason in _HARD_STOP_REASONS:
                    exit_code = EXIT_HARD_STOP
                elif failure_reason in {
                    "page_cap",
                    "condition_incomplete",
                    "census_condition_matrix_mismatch",
                    "census_natural_exhaustion_mismatch",
                    "census_incomplete",
                }:
                    exit_code = EXIT_INCOMPLETE
                else:
                    exit_code = EXIT_EVIDENCE_FAILURE
        elif is_pilot and pilot_staging_sink is not None:
            pilot_accepted, failure_reason = _pilot_analysis(
                results=pilot_results,
                conditions=pilot_conditions,
                reconciliation=pilot_staging_sink.reconciliation,
            )
            conservation_difference = (
                end_snapshot.staged_rows
                - start_snapshot.staged_rows
                - pilot_staging_sink.reconciliation.rows_created
            )
            published_jobs_unchanged = (
                start_snapshot.published_jobs == end_snapshot.published_jobs
                and start_snapshot.published_jobs_hash
                == end_snapshot.published_jobs_hash
            )
            companies_unchanged = (
                start_snapshot.companies_hash == end_snapshot.companies_hash
            )
            if (
                pilot_accepted
                and conservation_difference == 0
                and published_jobs_unchanged
                and companies_unchanged
            ):
                failure_reason = None
                terminal_status = "completed"
                exit_code = EXIT_OK
            else:
                if failure_reason is None:
                    if conservation_difference != 0:
                        failure_reason = "conservation_difference"
                    elif not published_jobs_unchanged:
                        failure_reason = "published_jobs_changed"
                    else:
                        failure_reason = "companies_changed"
                observation_service.record_event(
                    "research.run_stopped",
                    {"reason": failure_reason},
                )
                exit_code = (
                    EXIT_EVIDENCE_FAILURE
                    if failure_reason
                    in {
                        "staging_amplification",
                        "conservation_difference",
                        "published_jobs_changed",
                        "companies_changed",
                    }
                    else (
                        EXIT_HARD_STOP
                        if failure_reason in _HARD_STOP_REASONS
                        else EXIT_INCOMPLETE
                    )
                )
        elif not product_data_unchanged:
            failure_reason = "product_data_changed"
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
            )
        elif is_calibration:
            (
                calibration_passed,
                failure_reason,
                variant_summaries,
                selection,
            ) = _calibration_analysis(calibration_results)
            observation_service.record_event(
                "research.calibration_selection",
                {
                    "variant_summaries": variant_summaries,
                    "selection": selection,
                },
            )
            if calibration_passed:
                terminal_status = "completed"
                exit_code = EXIT_OK
            else:
                observation_service.record_event(
                    "research.run_stopped",
                    {"reason": failure_reason},
                )
                exit_code = (
                    EXIT_HARD_STOP
                    if failure_reason in _HARD_STOP_REASONS
                    else EXIT_INCOMPLETE
                )
        elif execution is not None and execution.decision.smoke_passed:
            failure_reason = None
            terminal_status = "completed"
            exit_code = EXIT_OK
        else:
            failure_reason = (
                execution.decision.stop_reason
                if execution is not None
                else "smoke_execution_missing"
            )
            observation_service.record_event(
                "research.run_stopped",
                {"reason": failure_reason},
            )
            exit_code = (
                EXIT_HARD_STOP
                if failure_reason in _HARD_STOP_REASONS
                else EXIT_INCOMPLETE
            )

        events_before_summary = _ordered_events(
            research_repository.list_research_events(db, UUID(run_id))
        )
        if (
            is_census_family
            and candidate_evidence is not None
            and census_staging_sink is not None
        ):
            summary_builder = (
                _build_fixed_repeat_summary
                if is_fixed_repeat
                else _build_census_summary
            )
            summary = summary_builder(
                **({"repeat_index": args.repeat_index} if is_fixed_repeat else {}),
                status=terminal_status,
                start_snapshot=start_snapshot,
                start_inventory=start_inventory,
                end_snapshot=end_snapshot,
                end_inventory=end_inventory,
                result=census_result,
                conditions=census_conditions,
                events_before_summary=events_before_summary,
                failure_reason=failure_reason,
                request_budget=request_budget,
                candidate_evidence=candidate_evidence,
                reconciliation=census_staging_sink.reconciliation,
            )
        elif is_pilot and pilot_variant is not None and pilot_staging_sink is not None:
            summary = _build_pilot_summary(
                status=terminal_status,
                start_snapshot=start_snapshot,
                start_inventory=start_inventory,
                end_snapshot=end_snapshot,
                end_inventory=end_inventory,
                results=pilot_results,
                conditions=pilot_conditions,
                events_before_summary=events_before_summary,
                failure_reason=failure_reason,
                request_budget=request_budget,
                variant=pilot_variant,
                reconciliation=pilot_staging_sink.reconciliation,
            )
        elif is_calibration:
            summary = _build_calibration_summary(
                status=terminal_status,
                start_snapshot=start_snapshot,
                start_inventory=start_inventory,
                end_snapshot=end_snapshot,
                end_inventory=end_inventory,
                results=calibration_results,
                events_before_summary=events_before_summary,
                failure_reason=failure_reason,
                request_budget=request_budget,
            )
        else:
            summary = _build_summary(
                status=terminal_status,
                start_snapshot=start_snapshot,
                start_inventory=start_inventory,
                end_snapshot=end_snapshot,
                end_inventory=end_inventory,
                execution=execution,
                events_before_summary=events_before_summary,
                failure_reason=failure_reason,
                request_budget=request_budget,
            )
        if not is_pilot and not is_census_family and not product_data_unchanged:
            exit_code = EXIT_EVIDENCE_FAILURE
        observation_service.finish_run(
            status=terminal_status,
            summary=summary,
            error_message=(
                _unexpected_error_message(original_error, experiment=experiment)
                if original_error is not None
                else None
            ),
        )
        events = [
            *events_before_summary,
            _summary_event(events_before_summary, summary),
        ]
    except BaseException as exc:
        if observation_service is None and isinstance(
            exc,
            (OSError, SQLAlchemyError, ValueError),
        ):
            pre_run_error = exc
        else:
            if original_error is None:
                original_error = exc
            if (
                observation_service is not None
                and start_snapshot is not None
                and start_inventory is not None
                and db is not None
            ):
                try:
                    summary, events = _best_effort_finalize_unexpected_failure(
                        db=db,
                        repository=research_repository,
                        observation_service=observation_service,
                        run_id=run_id,
                        error=original_error,
                        start_snapshot=start_snapshot,
                        start_inventory=start_inventory,
                        end_snapshot=end_snapshot,
                        end_inventory=end_inventory,
                        fallback_events=events_before_summary,
                        request_budget=request_budget,
                        experiment=experiment,
                        pilot_variant=pilot_variant,
                        pilot_conditions=pilot_conditions,
                        pilot_reconciliation=(
                            pilot_staging_sink.reconciliation
                            if pilot_staging_sink is not None
                            else None
                        ),
                        census_candidate_evidence=candidate_evidence,
                        census_conditions=census_conditions,
                        census_reconciliation=(
                            census_staging_sink.reconciliation
                            if census_staging_sink is not None
                            else None
                        ),
                        fixed_repeat_index=(
                            args.repeat_index if is_fixed_repeat else None
                        ),
                    )
                    terminal_status = "failed"
                    exit_code = EXIT_EVIDENCE_FAILURE
                except BaseException as finalization_exc:
                    original_error.add_note(
                        "best-effort failure finalization also failed: "
                        f"{type(finalization_exc).__name__}"
                    )
    finally:
        if db is not None:
            try:
                db.close()
            except BaseException as exc:
                if original_error is None:
                    original_error = exc
                else:
                    original_error.add_note(
                        f"database cleanup also failed: {type(exc).__name__}"
                    )

        if observation_service is not None:
            try:
                provenance = provenance_provider(
                    repo_root=repo_root,
                    runtime_context={
                        "command": args.command,
                        "session_mode": "fresh-headless",
                        "crawl_job_status": terminal_status,
                    },
                    captured_at=utc_now().isoformat(),
                )
                artifact_dir = artifact_exporter(
                    root=args.artifact_root,
                    run_id=run_id,
                    metadata={
                        "experiment": experiment,
                        "crawl_job_id": run_id,
                        "crawl_job_status": terminal_status,
                        "parent_artifact_hash": parent_artifact_hash,
                        "baseline_artifact_hash": baseline_gate.parent_artifact_hash,
                        "request_budget": dict(request_budget),
                        **(
                            {
                                "pilot_passed": bool(summary.get("pilot_passed")),
                                "variant_rank": pilot_variant.variant_rank,
                                "endpoint": pilot_variant.endpoint,
                                "rcd_type": pilot_variant.rcd_type,
                                "calibration_run_id": (
                                    pilot_variant.calibration_run_id
                                ),
                            }
                            if is_pilot and pilot_variant is not None
                            else (
                                {
                                    "calibration_passed": bool(
                                        summary.get("calibration_passed")
                                    )
                                }
                                if is_calibration
                                else (
                                    {
                                        **(
                                            {
                                                "fixed_repeat_passed": bool(
                                                    summary.get("fixed_repeat_passed")
                                                ),
                                                "repeat_index": args.repeat_index,
                                            }
                                            if is_fixed_repeat
                                            else {
                                                "census_passed": bool(
                                                    summary.get("census_passed")
                                                )
                                            }
                                        ),
                                        "candidate_hash": (
                                            candidate_evidence.candidate_hash
                                        ),
                                        "candidate_run_id": (
                                            candidate_evidence.candidate_run_id
                                        ),
                                        "endpoint": (
                                            candidate_evidence.candidate.endpoint
                                        ),
                                        "rcd_type": (
                                            candidate_evidence.candidate.rcd_type
                                        ),
                                    }
                                    if is_census_family
                                    and candidate_evidence is not None
                                    else {
                                        "smoke_passed": bool(
                                            summary.get("smoke_passed")
                                        )
                                    }
                                )
                            )
                        ),
                    },
                    events=events,
                    provenance=provenance,
                )
                artifact_check = artifact_verifier(artifact_dir)
                live_check = verify_live_research_run(artifact_dir)
                if not artifact_check.valid or not live_check.valid:
                    exit_code = EXIT_EVIDENCE_FAILURE
            except BaseException as exc:
                finalization_error = exc
                exit_code = EXIT_EVIDENCE_FAILURE

    if pre_run_error is not None and original_error is None:
        _print_json({"error": str(pre_run_error)}, stream=sys.stderr)
        return EXIT_EVIDENCE_FAILURE
    if original_error is not None:
        if finalization_error is not None:
            original_error.add_note(
                "artifact finalization also failed: "
                f"{type(finalization_error).__name__}"
            )
        raise original_error
    if finalization_error is not None:
        _print_json(
            {
                "error": f"artifact finalization failed:{type(finalization_error).__name__}"
            },
            stream=sys.stderr,
        )
        return EXIT_EVIDENCE_FAILURE

    if is_census_family:
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            **(
                {
                    "fixed_repeat_passed": bool(summary.get("fixed_repeat_passed")),
                    "repeat_index": args.repeat_index,
                }
                if is_fixed_repeat
                else {"census_passed": bool(summary.get("census_passed"))}
            ),
            "request_budget": dict(request_budget),
            "condition_count": int(summary.get("condition_count", 0)),
            "natural_exhaustion_count": int(summary.get("natural_exhaustion_count", 0)),
            "listing_logical_count": int(summary.get("listing_logical_count", 0)),
            "listing_attempt_count": int(summary.get("listing_attempt_count", 0)),
            "detail_attempt_count": int(summary.get("detail_attempt_count", 0)),
            "unique_job_count": int(summary.get("unique_job_count", 0)),
            "conservation_difference": int(summary.get("conservation_difference", 0)),
        }
    elif is_pilot:
        reconciliation = summary.get("reconciliation")
        reconciliation = reconciliation if isinstance(reconciliation, dict) else {}
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            "pilot_passed": bool(summary.get("pilot_passed")),
            "request_budget": dict(request_budget),
            "condition_count": int(summary.get("condition_count", 0)),
            "listing_logical_count": int(summary.get("listing_logical_count", 0)),
            "listing_attempt_count": int(summary.get("listing_attempt_count", 0)),
            "detail_attempt_count": int(summary.get("detail_attempt_count", 0)),
            "rows_created": int(reconciliation.get("rows_created", 0)),
            "conservation_difference": int(summary.get("conservation_difference", 0)),
        }
    elif is_calibration:
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            "calibration_passed": bool(summary.get("calibration_passed")),
            "request_budget": dict(request_budget),
            "condition_count": int(summary.get("condition_count", 0)),
            "listing_logical_count": int(summary.get("listing_logical_count", 0)),
            "listing_attempt_count": int(summary.get("listing_attempt_count", 0)),
            "detail_attempt_count": int(summary.get("detail_attempt_count", 0)),
        }
    else:
        output = {
            "artifact": str(artifact_dir),
            "run_id": run_id,
            "exit_code": exit_code,
            "smoke_passed": bool(summary.get("smoke_passed")),
            "request_budget": dict(request_budget),
            "missing_encrypted_job_id_count": int(
                summary.get("missing_encrypted_job_id_count", 0)
            ),
            "job_id_fallback_count": int(summary.get("job_id_fallback_count", 0)),
        }
    _print_json(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
