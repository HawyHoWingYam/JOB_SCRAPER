from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID


_SECRET_KEY_PARTS = (
    "api key",
    "api-key",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "csrf",
    "header",
    "password",
    "private-key",
    "private_key",
    "privatekey",
    "secret",
    "storage-state",
    "storage_state",
    "storagestate",
    "token",
)

DEFAULT_RELEVANT_SOURCE_PATHS = (
    "backend/app/sources/offertoday",
    "backend/app/scraper/offertoday_browser_runtime.py",
    "backend/app/scraper/offertoday_browser_detail_scraper.py",
    "backend/app/services/offertoday_detail_pipeline.py",
    "backend/app/services/crawl_job_runtime.py",
    "backend/scripts/offertoday_standalone_crawl.py",
    "backend/scripts/offertoday_coverage_audit.py",
    "backend/scripts/offertoday_research.py",
)

_UNTRACKED_ROOTS = (
    "backend/app",
    "backend/scripts",
    "backend/tests",
    "docs/superpowers",
)
_UNTRACKED_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".toml",
    ".yaml",
    ".yml",
}
_EXCLUDED_PATH_PARTS = {
    ".host_browser_profiles",
    ".ssh",
    "__pycache__",
    "auth",
    "credentials",
    "node_modules",
    "runtime",
    "secrets",
}
_SENSITIVE_FILE_MARKERS = (
    "auth_state",
    "cookie",
    "credential",
    "secret",
    "storage_state",
    "token",
)
_SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}
_SECRET_ASSIGNMENT_RE = re.compile(
    r"""
    (?P<key>
        authorization|cookie|csrf(?:[-_]?token)?|password|passwd|secret|
        storage_state|api[-_]?(?:key|token)|access[-_]?token|
        refresh[-_]?token|client[-_]?secret|private[-_]?key|token
    )
    \s*["']?\s*
    (?:
        :\s*[A-Za-z_][A-Za-z0-9_\[\], .|]*\s*=
        |
        [=:]
    )
    \s*
    (?P<value>
        (?:[rubf]{0,2})?["'][^"'\r\n]{4,}["']
        |
        [^\s,;#}\]\r\n]{8,}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_CREDENTIAL_URL_RE = re.compile(r"://[^\s/:]+:[^\s/@]+@")
_BEARER_TOKEN_RE = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}",
    re.IGNORECASE,
)
_PRIVATE_KEY_MARKER_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    commit_sha: str
    working_tree_patch: str
    source_hashes: dict[str, str]
    compose_file_hashes: dict[str, str]
    captured_at: str
    runtime_context: dict[str, Any]
    untracked_file_hashes: dict[str, str]
    excluded_tracked_file_hashes: dict[str, str]
    excluded_untracked_file_hashes: dict[str, str]


@dataclass(frozen=True, slots=True)
class ArtifactVerificationResult:
    valid: bool
    missing_files: tuple[str, ...]
    mismatched_files: tuple[str, ...]


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (StrEnum, UUID, Path)):
        return str(value)
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _redact(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in _SECRET_KEY_PARTS)
        }
    if isinstance(value, (tuple, list)):
        return [_redact(item) for item in value]
    if isinstance(value, (StrEnum, UUID, Path)):
        return str(value)
    return value


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            _to_jsonable(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def export_research_artifact(
    *,
    root: Path,
    run_id: str,
    metadata: dict[str, Any],
    events: Sequence[dict[str, Any]],
    provenance: ResearchProvenance,
) -> Path:
    artifact_dir = root / str(run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    observation_lines = [
        _canonical_json_bytes(_redact(event)).rstrip(b"\n") for event in events
    ]
    observations_payload = b"\n".join(observation_lines) + (
        b"\n" if observation_lines else b""
    )
    patch_payload = provenance.working_tree_patch.encode("utf-8")
    files = {
        "observations.jsonl": _sha256(observations_payload),
        "working-tree.patch": _sha256(patch_payload),
    }
    manifest = {
        "artifact_version": 1,
        "run_id": str(run_id),
        "metadata": _redact(metadata),
        "provenance": {
            "commit_sha": provenance.commit_sha,
            "source_hashes": dict(sorted(provenance.source_hashes.items())),
            "compose_file_hashes": dict(
                sorted(provenance.compose_file_hashes.items())
            ),
            "captured_at": provenance.captured_at,
            "runtime_context": _redact(provenance.runtime_context),
            "untracked_file_hashes": dict(
                sorted(provenance.untracked_file_hashes.items())
            ),
            "excluded_tracked_file_hashes": dict(
                sorted(provenance.excluded_tracked_file_hashes.items())
            ),
            "excluded_untracked_file_hashes": dict(
                sorted(provenance.excluded_untracked_file_hashes.items())
            ),
        },
        "files": files,
    }
    _write_atomic(artifact_dir / "observations.jsonl", observations_payload)
    _write_atomic(artifact_dir / "working-tree.patch", patch_payload)
    _write_atomic(artifact_dir / "manifest.json", _canonical_json_bytes(manifest))
    return artifact_dir


def verify_research_artifact(artifact_dir: Path) -> ArtifactVerificationResult:
    manifest_path = artifact_dir / "manifest.json"
    if not manifest_path.exists():
        return ArtifactVerificationResult(
            valid=False,
            missing_files=("manifest.json",),
            mismatched_files=(),
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing: list[str] = []
    mismatched: list[str] = []
    for relative_name, expected_hash in manifest.get("files", {}).items():
        path = artifact_dir / relative_name
        if not path.exists():
            missing.append(relative_name)
            continue
        if _sha256(path.read_bytes()) != expected_hash:
            mismatched.append(relative_name)
    return ArtifactVerificationResult(
        valid=not missing and not mismatched,
        missing_files=tuple(sorted(missing)),
        mismatched_files=tuple(sorted(mismatched)),
    )


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def _is_sensitive_path(relative_path: str) -> bool:
    path = Path(relative_path)
    lowered = relative_path.replace("\\", "/").lower()
    lowered_parts = {part.lower() for part in path.parts}
    return (
        path.name.lower().startswith(".env")
        or path.suffix.lower() in _SENSITIVE_SUFFIXES
        or bool(lowered_parts & _EXCLUDED_PATH_PARTS)
        or any(marker in lowered for marker in _SENSITIVE_FILE_MARKERS)
    )


def _contains_sensitive_content(text: str) -> bool:
    if (
        _CREDENTIAL_URL_RE.search(text)
        or _BEARER_TOKEN_RE.search(text)
        or _PRIVATE_KEY_MARKER_RE.search(text)
    ):
        return True
    for match in _SECRET_ASSIGNMENT_RE.finditer(text):
        value = match.group("value").strip().lstrip("rubfRUBF").strip("\"'")
        lowered = value.lower()
        if value.startswith("$") or lowered.startswith(
            (
                "env.",
                "environment.",
                "get_settings(",
                "getenv(",
                "os.getenv",
                "os.environ",
                "settings.",
            )
        ):
            continue
        if lowered in {"<redacted>", "redacted"}:
            continue
        return True
    return False


def _hash_or_deleted(path: Path) -> str:
    return _sha256(path.read_bytes()) if path.is_file() else "deleted"


def capture_research_provenance(
    *,
    repo_root: Path,
    runtime_context: dict[str, Any],
    captured_at: str,
    relevant_source_paths: Sequence[str] = DEFAULT_RELEVANT_SOURCE_PATHS,
) -> ResearchProvenance:
    commit_sha = _git(repo_root, "rev-parse", "HEAD").strip()
    tracked_output = _git(
        repo_root,
        "diff",
        "HEAD",
        "--name-only",
        "--no-renames",
        "-z",
        "--",
    )
    tracked_paths = sorted(filter(None, tracked_output.split("\0")))
    excluded_tracked_hashes: dict[str, str] = {}
    tracked_patches: list[str] = []
    for relative_path in tracked_paths:
        path = repo_root / relative_path
        if _is_sensitive_path(relative_path):
            excluded_tracked_hashes[relative_path] = _hash_or_deleted(path)
            continue
        candidate_patch = _git(
            repo_root,
            "diff",
            "HEAD",
            "--binary",
            "--no-renames",
            "--",
            f":(literal){relative_path}",
        )
        if (
            "GIT binary patch" in candidate_patch
            or "Binary files " in candidate_patch
            or _contains_sensitive_content(candidate_patch)
        ):
            excluded_tracked_hashes[relative_path] = _hash_or_deleted(path)
            continue
        tracked_patches.append(candidate_patch)
    tracked_patch = "".join(tracked_patches)

    untracked_output = _git(
        repo_root,
        "ls-files",
        "--others",
        "-z",
        "--",
        *_UNTRACKED_ROOTS,
    )
    untracked_hashes: dict[str, str] = {}
    excluded_untracked_hashes: dict[str, str] = {}
    untracked_patches: list[str] = []
    for relative_path in sorted(filter(None, untracked_output.split("\0"))):
        path = repo_root / relative_path
        if path.suffix.lower() not in _UNTRACKED_SUFFIXES:
            continue
        payload = path.read_bytes()
        payload_hash = _sha256(payload)
        if _is_sensitive_path(relative_path):
            excluded_untracked_hashes[relative_path] = payload_hash
            continue
        if b"\0" in payload:
            excluded_untracked_hashes[relative_path] = payload_hash
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            excluded_untracked_hashes[relative_path] = payload_hash
            continue
        if _contains_sensitive_content(text):
            excluded_untracked_hashes[relative_path] = payload_hash
            continue
        untracked_hashes[relative_path] = payload_hash
        untracked_patches.append(
            "".join(
                difflib.unified_diff(
                    [],
                    text.splitlines(keepends=True),
                    fromfile="/dev/null",
                    tofile=f"b/{relative_path.replace(os.sep, '/')}",
                )
            )
        )

    relevant_source_files: list[Path] = []
    for relative_path in relevant_source_paths:
        path = repo_root / relative_path
        if path.is_file():
            relevant_source_files.append(path)
        elif path.is_dir():
            relevant_source_files.extend(path.rglob("*.py"))
    source_hashes = {
        path.relative_to(repo_root).as_posix(): _sha256(path.read_bytes())
        for path in sorted(set(relevant_source_files))
    }
    compose_hashes = {
        name: _sha256((repo_root / name).read_bytes())
        for name in ("docker-compose.yml", "docker-compose.dev.yml")
        if (repo_root / name).exists()
    }
    combined_patch = tracked_patch
    if untracked_patches:
        combined_patch += "\n" + "\n".join(untracked_patches)
    return ResearchProvenance(
        commit_sha=commit_sha,
        working_tree_patch=combined_patch,
        source_hashes=source_hashes,
        compose_file_hashes=compose_hashes,
        captured_at=captured_at,
        runtime_context=_redact(runtime_context),
        untracked_file_hashes=untracked_hashes,
        excluded_tracked_file_hashes=excluded_tracked_hashes,
        excluded_untracked_file_hashes=excluded_untracked_hashes,
    )
