#!/usr/bin/env python3
"""Bounded, secret-safe CTGoodJobs transport viability research probe.

The probe is deliberately separate from the production crawl-mode contract. It
compares actual transports, validates returned HTML with the production parsers,
and writes only sanitized replayable evidence below ``backend/runtime``.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.scraper.access_block import classify_public_access_evidence  # noqa: E402
from app.scraper.ctgoodjobs.category_registry import (  # noqa: E402
    CTGoodJobsCategory,
    get_static_ctgoodjobs_categories,
)
from app.scraper.ctgoodjobs.html_fetcher import build_document_headers  # noqa: E402
from app.scraper.ctgoodjobs.page_state import (  # noqa: E402
    classify_ctgoodjobs_detail_page,
)
from app.sources.ctgoodjobs.parsers import (  # noqa: E402
    parse_category_page,
    parse_detail_page,
)


SCHEMA_VERSION = 1
DEFAULT_ARMS = (
    "plain-http",
    "fresh-headless",
    "stateful-headless",
    "headed-baseline",
)
APPROVED_HOSTS = frozenset({"jobs.ctgoodjobs.hk", "www.ctgoodjobs.hk"})
BROWSER_ARMS = frozenset(
    {"fresh-headless", "stateful-headless", "headed-baseline"}
)
CLASSIFICATIONS = frozenset(
    {
        "valid_content",
        "verification_block",
        "terminal_unavailable",
        "transport_failure",
        "structural_invalid",
    }
)
COMPLETION_STATES = frozenset({"completed", "partial", "hard_stop", "failed"})
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_REASON_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
_TITLE_PATTERN = re.compile(
    r"<title>\s*(?P<title>.*?)\s*</title>", re.IGNORECASE | re.DOTALL
)
_FORBIDDEN_KEY_PARTS = (
    "auth",
    "body",
    "cdp",
    "cookie",
    "credential",
    "exception",
    "header",
    "html",
    "password",
    "profile",
    "proxy",
    "response",
    "secret",
    "session_state",
    "storage",
    "token",
)
_OBSERVATION_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "ordinal",
        "captured_at",
        "arm",
        "phase",
        "session_label",
        "repetition",
        "sample_label",
        "source_url",
        "final_url",
        "status_code",
        "attempts",
        "elapsed_ms",
        "body_sha256",
        "classification",
        "failure_reason",
        "hard_stop",
        "parser_result",
    }
)

Arm = Literal[
    "plain-http", "fresh-headless", "stateful-headless", "headed-baseline"
]
Phase = Literal["listing", "detail"]


@dataclass(frozen=True, slots=True)
class ProbePlan:
    category_count: int = 3
    listing_repetitions: int = 3
    detail_count: int = 10
    detail_repetitions: int = 2
    browser_sessions: int = 2

    def __post_init__(self) -> None:
        for field_name, value in asdict(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.category_count > len(get_static_ctgoodjobs_categories()):
            raise ValueError("category_count exceeds the static public registry")


@dataclass(frozen=True, slots=True)
class ArtifactVerificationResult:
    valid: bool
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PageFetchResult:
    source_url: str
    final_url: str
    status_code: int | None
    title: str | None
    html: str
    attempts: int
    elapsed_ms: int
    waf_action: str | None = None


class ProbeHardStop(RuntimeError):
    """Stop later live requests after positive verification evidence."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _parse_aware_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _canonical_uuid(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = str(UUID(value))
    except ValueError:
        return None
    return parsed if parsed == value else None


def calculate_request_budget(
    plan: ProbePlan,
    *,
    selected_arms: Sequence[str] = DEFAULT_ARMS,
    max_attempts: int = 1,
) -> dict[str, int]:
    if type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    arm_count = len(tuple(selected_arms))
    listing_per_arm = plan.category_count * plan.listing_repetitions
    detail_per_arm = plan.detail_count * plan.detail_repetitions
    total_per_arm = listing_per_arm + detail_per_arm
    return {
        "arms": arm_count,
        "listing_per_arm": listing_per_arm,
        "detail_per_arm": detail_per_arm,
        "total_per_arm": total_per_arm,
        "total": arm_count * total_per_arm,
        "request_attempt_ceiling": arm_count * total_per_arm * max_attempts,
    }


def sanitize_url(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in APPROVED_HOSTS:
        raise ValueError("URL must use an approved CTGoodJobs host")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("URL authority must not contain credentials or custom ports")
    normalized_path = parsed.path or "/"
    return urlunsplit(("https", host, normalized_path, "", ""))


def _bounded_text_for_classification(html: str) -> str:
    if len(html) <= 65536:
        return html
    return html[:4096]


def _empty_parser_result(phase: str) -> dict[str, Any]:
    if phase == "listing":
        return {"job_id_count": 0, "parser_errors": []}
    return {
        "job_id_present": False,
        "title_present": False,
        "company_identity_present": False,
        "description_present": False,
        "field_coverage": {"required_present": 0, "required_total": 0},
        "parser_errors": [],
    }


def _detail_parser_result(parsed: Mapping[str, Any]) -> dict[str, Any]:
    coverage = parsed.get("field_coverage")
    if not isinstance(coverage, dict):
        coverage = {"required_present": 0, "required_total": 0}
    return {
        "job_id_present": bool(str(parsed.get("job_id") or "").strip()),
        "title_present": bool(str(parsed.get("title") or "").strip()),
        "company_identity_present": bool(
            str(parsed.get("company_id") or "").strip()
            or str(parsed.get("company_name") or "").strip()
        ),
        "description_present": bool(
            str(parsed.get("description_html") or "").strip()
            or str(parsed.get("description_text") or "").strip()
        ),
        "field_coverage": {
            "required_present": int(coverage.get("required_present") or 0),
            "required_total": int(coverage.get("required_total") or 0),
        },
        "parser_errors": [
            str(item)
            for item in parsed.get("errors", [])
            if isinstance(item, str)
        ],
    }


def classify_page_observation(
    *,
    run_id: str,
    ordinal: int,
    arm: str,
    phase: str,
    session_label: str,
    repetition: int,
    sample_label: str,
    source_url: str,
    final_url: str,
    status_code: int | None,
    title: str | None,
    html: str,
    attempts: int,
    elapsed_ms: int,
    captured_at: str,
    waf_action: str | None = None,
) -> dict[str, Any]:
    if arm not in DEFAULT_ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    if phase not in {"listing", "detail"}:
        raise ValueError(f"unsupported phase: {phase}")

    safe_source_url = sanitize_url(source_url)
    safe_final_url = sanitize_url(final_url or source_url)
    parser_result = _empty_parser_result(phase)
    classification = "structural_invalid"
    failure_reason: str | None = "missing_valid_content"
    hard_stop = False

    normalized_waf_action = str(waf_action or "").strip().lower()
    if normalized_waf_action == "captcha":
        classification = "verification_block"
        failure_reason = "aws_waf_captcha"
        hard_stop = True
    else:
        access_evidence = classify_public_access_evidence(
            status_code=status_code,
            final_url=final_url,
            title=title,
            text=_bounded_text_for_classification(html),
        )
        if access_evidence is not None:
            classification = "verification_block"
            failure_reason = access_evidence.reason
            hard_stop = True
        else:
            terminal = None
            if phase == "detail":
                terminal = classify_ctgoodjobs_detail_page(
                    status_code=status_code,
                    final_url=final_url,
                    title=title,
                    html=html,
                )
            if terminal is not None:
                classification = "terminal_unavailable"
                failure_reason = terminal.reason
            elif type(status_code) is int and not 200 <= status_code < 400:
                classification = "transport_failure"
                failure_reason = f"http_status_{status_code}"
            elif phase == "listing":
                parsed = parse_category_page(
                    html,
                    category_slug=sample_label,
                    source_classification_id=f"research:{sample_label}",
                    source_classification_name=sample_label,
                    page=1,
                    url=safe_source_url,
                )
                parser_errors = [
                    str(item)
                    for item in parsed.get("errors", [])
                    if isinstance(item, str)
                ]
                job_ids = [
                    str(item)
                    for item in parsed.get("job_ids", [])
                    if isinstance(item, str) and item
                ]
                parser_result = {
                    "job_id_count": len(job_ids),
                    "parser_errors": parser_errors,
                }
                if job_ids and "missing_item_list_json_ld" not in parser_errors:
                    classification = "valid_content"
                    failure_reason = None
                else:
                    failure_reason = "missing_valid_listing_ids"
            else:
                parsed = parse_detail_page(
                    html,
                    source_classification_id="research:detail",
                    source_classification_name="Research detail",
                    source_classification_slug="research-detail",
                    url=safe_source_url,
                )
                parser_result = _detail_parser_result(parsed)
                required_flags = (
                    parser_result["job_id_present"],
                    parser_result["title_present"],
                    parser_result["company_identity_present"],
                    parser_result["description_present"],
                )
                if all(required_flags):
                    classification = "valid_content"
                    failure_reason = None
                else:
                    failure_reason = "missing_valid_detail_fields"

    observation = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "ordinal": ordinal,
        "captured_at": captured_at,
        "arm": arm,
        "phase": phase,
        "session_label": str(session_label),
        "repetition": repetition,
        "sample_label": str(sample_label),
        "source_url": safe_source_url,
        "final_url": safe_final_url,
        "status_code": status_code if type(status_code) is int else None,
        "attempts": attempts,
        "elapsed_ms": elapsed_ms,
        "body_sha256": _sha256(html.encode("utf-8")),
        "classification": classification,
        "failure_reason": failure_reason,
        "hard_stop": hard_stop,
        "parser_result": parser_result,
    }
    issues = _observation_issues(observation)
    if issues:
        raise ValueError(f"invalid observation: {','.join(issues)}")
    return observation


def build_transport_failure_observation(
    *,
    run_id: str,
    ordinal: int,
    arm: str,
    phase: str,
    session_label: str,
    repetition: int,
    sample_label: str,
    source_url: str,
    attempts: int,
    elapsed_ms: int,
    captured_at: str,
) -> dict[str, Any]:
    observation = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "ordinal": ordinal,
        "captured_at": captured_at,
        "arm": arm,
        "phase": phase,
        "session_label": str(session_label),
        "repetition": repetition,
        "sample_label": str(sample_label),
        "source_url": sanitize_url(source_url),
        "final_url": sanitize_url(source_url),
        "status_code": None,
        "attempts": attempts,
        "elapsed_ms": elapsed_ms,
        "body_sha256": _sha256(b""),
        "classification": "transport_failure",
        "failure_reason": "bounded_transport_failure",
        "hard_stop": False,
        "parser_result": _empty_parser_result(phase),
    }
    issues = _observation_issues(observation)
    if issues:
        raise ValueError(f"invalid observation: {','.join(issues)}")
    return observation


def _metadata_has_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
                return True
            if _metadata_has_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(_metadata_has_forbidden_key(item) for item in value)
    return False


def _observation_issues(observation: Any) -> tuple[str, ...]:
    if not isinstance(observation, dict):
        return ("observation_not_object",)
    unexpected = set(observation) - _OBSERVATION_FIELDS
    missing = _OBSERVATION_FIELDS - set(observation)
    issues: list[str] = []
    if unexpected:
        issues.append("unexpected_observation_fields")
    if missing:
        issues.append("missing_observation_fields")
    if issues:
        return tuple(issues)
    if observation["schema_version"] != SCHEMA_VERSION:
        issues.append("unsupported_observation_version")
    if _canonical_uuid(observation["run_id"]) is None:
        issues.append("invalid_observation_run_id")
    if type(observation["ordinal"]) is not int or observation["ordinal"] < 1:
        issues.append("invalid_observation_ordinal")
    if not _parse_aware_timestamp(observation["captured_at"]):
        issues.append("invalid_observation_timestamp")
    if observation["arm"] not in DEFAULT_ARMS:
        issues.append("invalid_observation_arm")
    if observation["phase"] not in {"listing", "detail"}:
        issues.append("invalid_observation_phase")
    if not isinstance(observation["session_label"], str):
        issues.append("invalid_session_label")
    if type(observation["repetition"]) is not int or observation["repetition"] < 1:
        issues.append("invalid_repetition")
    if not isinstance(observation["sample_label"], str):
        issues.append("invalid_sample_label")
    for key in ("source_url", "final_url"):
        try:
            if sanitize_url(observation[key]) != observation[key]:
                issues.append(f"unsanitized_{key}")
        except (TypeError, ValueError):
            issues.append(f"invalid_{key}")
    if observation["status_code"] is not None and type(
        observation["status_code"]
    ) is not int:
        issues.append("invalid_status_code")
    if type(observation["attempts"]) is not int or observation["attempts"] < 1:
        issues.append("invalid_attempts")
    if type(observation["elapsed_ms"]) is not int or observation["elapsed_ms"] < 0:
        issues.append("invalid_elapsed_ms")
    if not isinstance(observation["body_sha256"], str) or not _SHA256_PATTERN.fullmatch(
        observation["body_sha256"]
    ):
        issues.append("invalid_body_sha256")
    if observation["classification"] not in CLASSIFICATIONS:
        issues.append("invalid_classification")
    failure_reason = observation["failure_reason"]
    if failure_reason is not None and (
        not isinstance(failure_reason, str)
        or _FAILURE_REASON_PATTERN.fullmatch(failure_reason) is None
    ):
        issues.append("invalid_failure_reason")
    if type(observation["hard_stop"]) is not bool:
        issues.append("invalid_hard_stop")
    if not isinstance(observation["parser_result"], dict):
        issues.append("invalid_parser_result")
    return tuple(issues)


def build_manifest_metadata(
    *,
    plan: ProbePlan,
    selected_arms: Sequence[str],
    cooldown_seconds: float,
    timeout_seconds: float,
    max_attempts: int = 1,
    browser_engine: str = "chromium",
    browser_channel: str | None = None,
) -> dict[str, Any]:
    arms = tuple(selected_arms)
    if not arms or any(arm not in DEFAULT_ARMS for arm in arms):
        raise ValueError("selected_arms contains an unsupported arm")
    return {
        "plan": asdict(plan),
        "selected_arms": list(arms),
        "budget": calculate_request_budget(
            plan,
            selected_arms=arms,
            max_attempts=max_attempts,
        ),
        "cooldown_seconds": float(cooldown_seconds),
        "timeout_seconds": float(timeout_seconds),
        "max_attempts": int(max_attempts),
        "browser_engine": browser_engine,
        "browser_channel": browser_channel,
    }


def _write_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def export_probe_artifact(
    *,
    root: Path,
    run_id: str,
    metadata: dict[str, Any],
    observations: Sequence[dict[str, Any]],
    completion_state: str,
    failure_reason: str | None,
    captured_at: str,
) -> Path:
    canonical_run_id = _canonical_uuid(run_id)
    if canonical_run_id is None:
        raise ValueError("run_id must be a canonical UUID")
    if completion_state not in COMPLETION_STATES:
        raise ValueError("unsupported completion_state")
    if failure_reason is not None and (
        not isinstance(failure_reason, str)
        or _FAILURE_REASON_PATTERN.fullmatch(failure_reason) is None
    ):
        raise ValueError("failure_reason must be bounded and enumerated")
    if not _parse_aware_timestamp(captured_at):
        raise ValueError("captured_at must be timezone-aware ISO-8601")
    if _metadata_has_forbidden_key(metadata):
        raise ValueError("metadata contains a forbidden sensitive key")

    normalized_observations = list(observations)
    for index, observation in enumerate(normalized_observations, start=1):
        unexpected = set(observation) - _OBSERVATION_FIELDS
        if unexpected:
            raise ValueError(
                "unexpected observation fields: " + ",".join(sorted(unexpected))
            )
        issues = _observation_issues(observation)
        if issues:
            raise ValueError(f"invalid observation: {','.join(issues)}")
        if observation["run_id"] != canonical_run_id:
            raise ValueError("observation run_id mismatch")
        if observation["ordinal"] != index:
            raise ValueError("observation ordinals must be contiguous")

    observation_lines = [
        _canonical_json_bytes(observation).rstrip(b"\n")
        for observation in normalized_observations
    ]
    observation_payload = b"\n".join(observation_lines)
    if observation_lines:
        observation_payload += b"\n"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": canonical_run_id,
        "captured_at": captured_at,
        "completion_state": completion_state,
        "failure_reason": failure_reason,
        "metadata": metadata,
        "files": {"observations.jsonl": _sha256(observation_payload)},
    }

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    root_anchor = root.resolve(strict=True)
    artifact_dir = root_anchor / canonical_run_id
    artifact_dir.mkdir()
    if artifact_dir.is_symlink() or artifact_dir.resolve(strict=True).parent != root_anchor:
        raise ValueError("artifact directory escaped the artifact root")
    _write_atomic(artifact_dir / "observations.jsonl", observation_payload)
    _write_atomic(artifact_dir / "manifest.json", _canonical_json_bytes(manifest))
    return artifact_dir


def verify_probe_artifact(artifact_dir: Path) -> ArtifactVerificationResult:
    artifact_dir = Path(artifact_dir)
    issues: list[str] = []
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        return ArtifactVerificationResult(False, ("artifact_directory_invalid",))
    try:
        actual_names = {entry.name for entry in os.scandir(artifact_dir)}
    except OSError:
        return ArtifactVerificationResult(False, ("artifact_directory_invalid",))
    expected_names = {"manifest.json", "observations.jsonl"}
    if actual_names != expected_names:
        issues.append("artifact_file_set_mismatch")
    manifest_path = artifact_dir / "manifest.json"
    observations_path = artifact_dir / "observations.jsonl"
    if manifest_path.is_symlink() or observations_path.is_symlink():
        issues.append("artifact_file_indirection")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ArtifactVerificationResult(False, tuple(sorted({*issues, "manifest_invalid"})))
    expected_manifest_fields = {
        "schema_version",
        "run_id",
        "captured_at",
        "completion_state",
        "failure_reason",
        "metadata",
        "files",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_manifest_fields:
        issues.append("manifest_shape_invalid")
        return ArtifactVerificationResult(False, tuple(sorted(set(issues))))
    if manifest["schema_version"] != SCHEMA_VERSION:
        issues.append("unsupported_schema_version")
    run_id = _canonical_uuid(manifest["run_id"])
    if run_id is None or artifact_dir.name != run_id:
        issues.append("manifest_run_id_invalid")
    if not _parse_aware_timestamp(manifest["captured_at"]):
        issues.append("manifest_timestamp_invalid")
    if manifest["completion_state"] not in COMPLETION_STATES:
        issues.append("completion_state_invalid")
    failure_reason = manifest["failure_reason"]
    if failure_reason is not None and (
        not isinstance(failure_reason, str)
        or _FAILURE_REASON_PATTERN.fullmatch(failure_reason) is None
    ):
        issues.append("manifest_failure_reason_invalid")
    if not isinstance(manifest["metadata"], dict) or _metadata_has_forbidden_key(
        manifest["metadata"]
    ):
        issues.append("manifest_metadata_invalid")
    files = manifest["files"]
    if not isinstance(files, dict) or set(files) != {"observations.jsonl"}:
        issues.append("manifest_files_invalid")

    try:
        observations_payload = observations_path.read_bytes()
    except OSError:
        issues.append("observations_missing")
        return ArtifactVerificationResult(False, tuple(sorted(set(issues))))
    if isinstance(files, dict) and files.get("observations.jsonl") != _sha256(
        observations_payload
    ):
        issues.append("observations_hash_mismatch")

    observations: list[Any] = []
    try:
        for raw_line in observations_payload.decode("utf-8").splitlines():
            if not raw_line.strip():
                issues.append("observations_blank_line")
                continue
            observations.append(json.loads(raw_line))
    except (UnicodeDecodeError, json.JSONDecodeError):
        issues.append("observations_invalid_json")
        observations = []
    for index, observation in enumerate(observations, start=1):
        observation_issues = _observation_issues(observation)
        issues.extend(observation_issues)
        if isinstance(observation, dict):
            if observation.get("run_id") != run_id:
                issues.append("observation_run_id_mismatch")
            if observation.get("ordinal") != index:
                issues.append("observation_ordinal_mismatch")
    return ArtifactVerificationResult(not issues, tuple(sorted(set(issues))))


def assess_operational_viability(
    observations: Sequence[Mapping[str, Any]],
    *,
    arm: str,
) -> dict[str, Any]:
    if arm not in DEFAULT_ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    arm_observations = [item for item in observations if item.get("arm") == arm]
    listing_counts: dict[str, Counter[int]] = defaultdict(Counter)
    detail_counts: dict[str, Counter[int]] = defaultdict(Counter)
    valid_sessions: set[str] = set()
    classifications: Counter[str] = Counter()
    for item in arm_observations:
        classification = str(item.get("classification") or "")
        classifications[classification] += 1
        if classification != "valid_content":
            continue
        sample_label = str(item.get("sample_label") or "")
        repetition = item.get("repetition")
        if type(repetition) is not int:
            continue
        valid_sessions.add(str(item.get("session_label") or ""))
        if item.get("phase") == "listing":
            listing_counts[sample_label][repetition] += 1
        elif item.get("phase") == "detail":
            detail_counts[sample_label][repetition] += 1

    listing_passing = sum(
        1
        for repetitions in listing_counts.values()
        if all(repetitions[index] >= 1 for index in range(1, 4))
    )
    detail_passing = sum(
        1
        for repetitions in detail_counts.values()
        if all(repetitions[index] >= 1 for index in range(1, 3))
    )
    session_requirement_met = arm == "plain-http" or len(valid_sessions) >= 2
    failure_count = sum(
        classifications[name]
        for name in (
            "verification_block",
            "transport_failure",
            "structural_invalid",
        )
    )
    viable = (
        listing_passing >= 3
        and detail_passing >= 10
        and session_requirement_met
        and failure_count == 0
    )
    total = len(arm_observations)
    classified_transport_success = (
        classifications["valid_content"] + classifications["terminal_unavailable"]
    )
    return {
        "arm": arm,
        "verdict": "operationally_viable" if viable else "conditional",
        "listing_categories_passing": listing_passing,
        "detail_samples_passing": detail_passing,
        "browser_sessions_observed": len(valid_sessions) if arm != "plain-http" else 0,
        "session_requirement_met": session_requirement_met,
        "transport_classification_success": classified_transport_success,
        "valid_content": classifications["valid_content"],
        "terminal_unavailable": classifications["terminal_unavailable"],
        "verification_blocks": classifications["verification_block"],
        "transport_failures": classifications["transport_failure"],
        "structural_invalid": classifications["structural_invalid"],
        "observations": total,
    }


def resolve_probe_exit_code(
    *,
    completion_state: str,
    verification_valid: bool,
    decisions: Mapping[str, Mapping[str, Any]],
) -> int:
    if not verification_valid or completion_state == "failed":
        return 5
    if completion_state == "hard_stop":
        return 4
    if completion_state != "completed" or any(
        decision.get("verdict") != "operationally_viable"
        for decision in decisions.values()
    ):
        return 3
    return 0


class _BrowserTransport:
    def __init__(
        self,
        *,
        arm: str,
        session_count: int,
        timeout_seconds: float,
        browser_channel: str | None,
    ) -> None:
        self.arm = arm
        self.session_count = session_count
        self.timeout_ms = int(timeout_seconds * 1000)
        self.browser_channel = browser_channel
        self._playwright = None
        self._contexts: list[Any] = []
        self._temporary_profiles: list[tempfile.TemporaryDirectory[str]] = []

    async def __aenter__(self) -> "_BrowserTransport":
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        if self.arm in {"stateful-headless", "headed-baseline"}:
            for _index in range(self.session_count):
                temporary = tempfile.TemporaryDirectory(
                    prefix="ctgoodjobs-headless-research-"
                )
                self._temporary_profiles.append(temporary)
                launch_kwargs: dict[str, Any] = {
                    "user_data_dir": temporary.name,
                    "headless": self.arm != "headed-baseline",
                }
                if self.browser_channel:
                    launch_kwargs["channel"] = self.browser_channel
                context = await self._playwright.chromium.launch_persistent_context(
                    **launch_kwargs
                )
                context.set_default_navigation_timeout(self.timeout_ms)
                self._contexts.append(context)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        for context in reversed(self._contexts):
            await context.close()
        self._contexts.clear()
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
        for temporary in reversed(self._temporary_profiles):
            temporary.cleanup()
        self._temporary_profiles.clear()

    async def fetch(self, url: str, session_index: int) -> PageFetchResult:
        if self._playwright is None:
            raise RuntimeError("browser transport is not started")
        started = time.monotonic()
        browser = None
        context = None
        if self.arm == "fresh-headless":
            launch_kwargs: dict[str, Any] = {"headless": True}
            if self.browser_channel:
                launch_kwargs["channel"] = self.browser_channel
            browser = await self._playwright.chromium.launch(**launch_kwargs)
            context = await browser.new_context()
            context.set_default_navigation_timeout(self.timeout_ms)
        else:
            context = self._contexts[session_index % len(self._contexts)]
        page = await context.new_page()
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            status_code = response.status if response is not None else None
            headers = await response.all_headers() if response is not None else {}
            html = await page.content()
            title = await page.title()
            return PageFetchResult(
                source_url=url,
                final_url=page.url or url,
                status_code=status_code,
                title=title,
                html=html,
                attempts=1,
                elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                waf_action=headers.get("x-amzn-waf-action"),
            )
        finally:
            await page.close()
            if browser is not None:
                await browser.close()


async def _fetch_plain_http(url: str, timeout_seconds: float) -> PageFetchResult:
    import httpx

    started = time.monotonic()
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        response = await client.get(url, headers=build_document_headers())
    html = response.text
    match = _TITLE_PATTERN.search(html)
    title = match.group("title").strip() if match else None
    return PageFetchResult(
        source_url=url,
        final_url=str(response.url),
        status_code=response.status_code,
        title=title,
        html=html,
        attempts=1,
        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
        waf_action=response.headers.get("x-amzn-waf-action"),
    )


async def _fetch_with_attempts(
    *,
    arm: str,
    url: str,
    session_index: int,
    timeout_seconds: float,
    cooldown_seconds: float,
    max_attempts: int,
    browser_transport: _BrowserTransport | None,
) -> tuple[PageFetchResult | None, int, int]:
    started = time.monotonic()
    for attempt in range(1, max_attempts + 1):
        try:
            if arm == "plain-http":
                result = await _fetch_plain_http(url, timeout_seconds)
            else:
                if browser_transport is None:
                    raise RuntimeError("browser transport missing")
                result = await browser_transport.fetch(url, session_index)
            return (
                PageFetchResult(
                    source_url=result.source_url,
                    final_url=result.final_url,
                    status_code=result.status_code,
                    title=result.title,
                    html=result.html,
                    attempts=attempt,
                    elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                    waf_action=result.waf_action,
                ),
                attempt,
                max(0, int((time.monotonic() - started) * 1000)),
            )
        except Exception:
            if attempt < max_attempts:
                await asyncio.sleep(cooldown_seconds)
    return None, max_attempts, max(0, int((time.monotonic() - started) * 1000))


def _session_label(arm: str, work_index: int, browser_sessions: int) -> str:
    if arm == "plain-http":
        return "stateless-http"
    if arm == "fresh-headless":
        return f"fresh-session-{work_index + 1}"
    return f"persistent-session-{(work_index % browser_sessions) + 1}"


def _listing_candidates(html: str, category: CTGoodJobsCategory) -> list[str]:
    parsed = parse_category_page(
        html,
        category_slug=category.slug,
        source_classification_id=category.source_classification_id,
        source_classification_name=category.name,
        page=1,
        url=category.url,
    )
    candidates: list[str] = []
    for value in parsed.get("job_urls", []):
        if not isinstance(value, str):
            continue
        try:
            candidates.append(sanitize_url(value))
        except ValueError:
            continue
    return candidates


async def _run_live_probe(
    *,
    plan: ProbePlan,
    selected_arms: tuple[str, ...],
    cooldown_seconds: float,
    timeout_seconds: float,
    max_attempts: int,
    browser_channel: str | None,
    output_root: Path,
    supplied_detail_urls: Sequence[str],
) -> tuple[int, Path]:
    run_id = str(uuid4())
    captured_at = _utc_now()
    observations: list[dict[str, Any]] = []
    detail_candidates: list[str] = []
    completion_state = "completed"
    failure_reason: str | None = None
    categories = get_static_ctgoodjobs_categories()[: plan.category_count]
    ordered_arms = list(selected_arms)
    if not supplied_detail_urls and "headed-baseline" in ordered_arms:
        ordered_arms.remove("headed-baseline")
        ordered_arms.insert(0, "headed-baseline")

    async def observe(
        *,
        arm: str,
        phase: str,
        session_label: str,
        session_index: int,
        repetition: int,
        sample_label: str,
        url: str,
        browser_transport: _BrowserTransport | None,
    ) -> tuple[dict[str, Any], PageFetchResult | None]:
        fetch_result, attempts, elapsed_ms = await _fetch_with_attempts(
            arm=arm,
            url=url,
            session_index=session_index,
            timeout_seconds=timeout_seconds,
            cooldown_seconds=cooldown_seconds,
            max_attempts=max_attempts,
            browser_transport=browser_transport,
        )
        ordinal = len(observations) + 1
        if fetch_result is None:
            observation = build_transport_failure_observation(
                run_id=run_id,
                ordinal=ordinal,
                arm=arm,
                phase=phase,
                session_label=session_label,
                repetition=repetition,
                sample_label=sample_label,
                source_url=url,
                attempts=attempts,
                elapsed_ms=elapsed_ms,
                captured_at=_utc_now(),
            )
        else:
            observation = classify_page_observation(
                run_id=run_id,
                ordinal=ordinal,
                arm=arm,
                phase=phase,
                session_label=session_label,
                repetition=repetition,
                sample_label=sample_label,
                source_url=url,
                final_url=fetch_result.final_url,
                status_code=fetch_result.status_code,
                title=fetch_result.title,
                html=fetch_result.html,
                attempts=fetch_result.attempts,
                elapsed_ms=fetch_result.elapsed_ms,
                captured_at=_utc_now(),
                waf_action=fetch_result.waf_action,
            )
        observations.append(observation)
        print(
            json.dumps(
                {
                    "ordinal": observation["ordinal"],
                    "arm": arm,
                    "phase": phase,
                    "sample": sample_label,
                    "classification": observation["classification"],
                },
                sort_keys=True,
            )
        )
        if observation["hard_stop"]:
            raise ProbeHardStop("verification_block")
        await asyncio.sleep(cooldown_seconds)
        return observation, fetch_result

    try:
        for arm in ordered_arms:
            browser_transport = None
            if arm in BROWSER_ARMS:
                browser_transport = _BrowserTransport(
                    arm=arm,
                    session_count=plan.browser_sessions,
                    timeout_seconds=timeout_seconds,
                    browser_channel=browser_channel,
                )
            context_manager = (
                browser_transport if browser_transport is not None else _NullAsyncContext()
            )
            async with context_manager:
                work_index = 0
                for category in categories:
                    for repetition in range(1, plan.listing_repetitions + 1):
                        session_label = _session_label(
                            arm, work_index, plan.browser_sessions
                        )
                        _observation, result = await observe(
                            arm=arm,
                            phase="listing",
                            session_label=session_label,
                            session_index=work_index % plan.browser_sessions,
                            repetition=repetition,
                            sample_label=category.slug,
                            url=category.url,
                            browser_transport=browser_transport,
                        )
                        if (
                            arm == "headed-baseline"
                            and repetition == 1
                            and result is not None
                        ):
                            for candidate in _listing_candidates(result.html, category):
                                if candidate not in detail_candidates:
                                    detail_candidates.append(candidate)
                        work_index += 1

        if supplied_detail_urls:
            detail_candidates = [sanitize_url(url) for url in supplied_detail_urls]
        detail_candidates = detail_candidates[: plan.detail_count]
        if len(detail_candidates) < plan.detail_count:
            completion_state = "partial"
            failure_reason = "insufficient_detail_samples"

        for arm in ordered_arms:
            browser_transport = None
            if arm in BROWSER_ARMS:
                browser_transport = _BrowserTransport(
                    arm=arm,
                    session_count=plan.browser_sessions,
                    timeout_seconds=timeout_seconds,
                    browser_channel=browser_channel,
                )
            context_manager = (
                browser_transport if browser_transport is not None else _NullAsyncContext()
            )
            async with context_manager:
                work_index = 0
                for detail_index, detail_url in enumerate(detail_candidates, start=1):
                    for repetition in range(1, plan.detail_repetitions + 1):
                        await observe(
                            arm=arm,
                            phase="detail",
                            session_label=_session_label(
                                arm, work_index, plan.browser_sessions
                            ),
                            session_index=work_index % plan.browser_sessions,
                            repetition=repetition,
                            sample_label=f"detail-{detail_index}",
                            url=detail_url,
                            browser_transport=browser_transport,
                        )
                        work_index += 1
    except ProbeHardStop:
        completion_state = "hard_stop"
        failure_reason = "verification_block"
    except Exception:
        completion_state = "failed"
        failure_reason = "unexpected_failure"

    decisions = {
        arm: assess_operational_viability(observations, arm=arm)
        for arm in selected_arms
    }
    metadata = build_manifest_metadata(
        plan=plan,
        selected_arms=selected_arms,
        cooldown_seconds=cooldown_seconds,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        browser_channel=browser_channel,
    )
    metadata.update(
        {
            "category_labels": [category.slug for category in categories],
            "detail_sample_count": len(detail_candidates),
            "decisions": decisions,
        }
    )
    artifact_dir = export_probe_artifact(
        root=output_root,
        run_id=run_id,
        metadata=metadata,
        observations=observations,
        completion_state=completion_state,
        failure_reason=failure_reason,
        captured_at=captured_at,
    )
    verification = verify_probe_artifact(artifact_dir)
    return (
        resolve_probe_exit_code(
            completion_state=completion_state,
            verification_valid=verification.valid,
            decisions=decisions,
        ),
        artifact_dir,
    )


class _NullAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _selected_arms(raw_arms: Sequence[str] | None) -> tuple[str, ...]:
    values = list(raw_arms or ["all"])
    if "all" in values:
        if len(values) != 1:
            raise ValueError("--arm all cannot be combined with another arm")
        return DEFAULT_ARMS
    deduped = tuple(dict.fromkeys(values))
    if not deduped or any(value not in DEFAULT_ARMS for value in deduped):
        raise ValueError("unsupported arm")
    return deduped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("run", "verify"), default="run")
    parser.add_argument("--plan", action="store_true", help="print budget only")
    parser.add_argument(
        "--confirm-live-research",
        action="store_true",
        help="required before any network or browser dependency is created",
    )
    parser.add_argument(
        "--arm",
        action="append",
        choices=("all", *DEFAULT_ARMS),
        help="repeat to select arms; defaults to all",
    )
    parser.add_argument("--category-count", type=int, default=3)
    parser.add_argument("--listing-repetitions", type=int, default=3)
    parser.add_argument("--detail-count", type=int, default=10)
    parser.add_argument("--detail-repetitions", type=int, default=2)
    parser.add_argument("--browser-sessions", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--cooldown-seconds", type=float, default=1.0)
    parser.add_argument("--max-attempts", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--browser-channel")
    parser.add_argument(
        "--detail-url",
        action="append",
        default=[],
        help="optional explicit public detail URL; repeat up to detail-count",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=BACKEND_ROOT / "runtime" / "ctgoodjobs-headless-research",
    )
    parser.add_argument("--artifact", type=Path, help="artifact directory for verify")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "verify":
        if args.artifact is None:
            parser.error("verify requires --artifact")
        result = verify_probe_artifact(args.artifact)
        print(json.dumps({"valid": result.valid, "issues": result.issues}, indent=2))
        return 0 if result.valid else 5

    try:
        plan = ProbePlan(
            category_count=args.category_count,
            listing_repetitions=args.listing_repetitions,
            detail_count=args.detail_count,
            detail_repetitions=args.detail_repetitions,
            browser_sessions=args.browser_sessions,
        )
        selected_arms = _selected_arms(args.arm)
    except ValueError as exc:
        parser.error(str(exc))
    if args.timeout_seconds <= 0 or args.cooldown_seconds < 0:
        parser.error("timeout must be positive and cooldown must be nonnegative")
    if len(args.detail_url) > plan.detail_count:
        parser.error("too many --detail-url values")

    plan_payload = {
        "plan": asdict(plan),
        "selected_arms": selected_arms,
        "budget": calculate_request_budget(
            plan,
            selected_arms=selected_arms,
            max_attempts=args.max_attempts,
        ),
        "timeout_seconds": args.timeout_seconds,
        "cooldown_seconds": args.cooldown_seconds,
        "max_attempts": args.max_attempts,
        "output_root": str(args.output_root),
        "visible_browser": "headed-baseline" in selected_arms,
    }
    if args.plan:
        print(json.dumps(plan_payload, indent=2, sort_keys=True))
        return 0
    if not args.confirm_live_research:
        parser.error("live execution requires --confirm-live-research")
    for detail_url in args.detail_url:
        try:
            sanitize_url(detail_url)
        except ValueError as exc:
            parser.error(str(exc))
    print(json.dumps(plan_payload, indent=2, sort_keys=True))
    try:
        exit_code, artifact_dir = asyncio.run(
            _run_live_probe(
                plan=plan,
                selected_arms=selected_arms,
                cooldown_seconds=args.cooldown_seconds,
                timeout_seconds=args.timeout_seconds,
                max_attempts=args.max_attempts,
                browser_channel=args.browser_channel,
                output_root=args.output_root,
                supplied_detail_urls=args.detail_url,
            )
        )
    except Exception:
        print(json.dumps({"failure_reason": "unexpected_failure", "exit_code": 5}))
        return 5
    print(json.dumps({"artifact": str(artifact_dir), "exit_code": exit_code}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
