from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
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
    "passwd",
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
_REQUIRED_ARTIFACT_FILES = ("observations.jsonl", "working-tree.patch")
_ARTIFACT_DIRECTORY_FILES = ("manifest.json", *_REQUIRED_ARTIFACT_FILES)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MANIFEST_KEYS = {
    "artifact_version",
    "run_id",
    "metadata",
    "provenance",
    "files",
}
_PROVENANCE_KEYS = {
    "commit_sha",
    "source_hashes",
    "compose_file_hashes",
    "captured_at",
    "runtime_context",
    "untracked_file_hashes",
    "excluded_tracked_file_hashes",
    "excluded_untracked_file_hashes",
}
_PROVENANCE_SHA256_MAPPINGS = (
    "source_hashes",
    "compose_file_hashes",
    "untracked_file_hashes",
    "excluded_untracked_file_hashes",
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
_ASSIGNMENT_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_.])
    (?P<key>
        "(?:\\.|[^"\\\r\n])+"
        |
        '(?:\\.|[^'\\\r\n])+'
        |
        [A-Za-z_][A-Za-z0-9_.]*
        [ \t]*
        \[
            [ \t]*
            (?:
                "(?:\\.|[^"\\\r\n])+"
                |
                '(?:\\.|[^'\\\r\n])+'
            )
            [ \t]*
        \]
        |
        [A-Za-z_][A-Za-z0-9_. -]*?
    )
    [ \t]*
    (?:
        :[ \t]*[A-Za-z_][A-Za-z0-9_\[\], .|]*[ \t]*=
        |
        (?:(?:\*\*|//|<<|>>|[+\-*/%@&|^])?=|:=|:)
    )
    [ \t]*
    (?P<value>
        \$\{[A-Za-z_][A-Za-z0-9_]*\}
        |
        (?:[rubf]{0,2})?"(?:\\.|[^"\\\r\n])*"
        |
        (?:[rubf]{0,2})?'(?:\\.|[^'\\\r\n])*'
        |
        [^\s,;#}\]\r\n]+
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_ENV_REFERENCE_RE = re.compile(
    r"^\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})$"
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


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_hash_mapping(value: Any, *, allow_deleted: bool = False) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and (_is_sha256(item) or (allow_deleted and item == "deleted"))
        for key, item in value.items()
    )


def _is_aware_iso8601(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _is_valid_v1_manifest(manifest: Any, artifact_dir: Path) -> bool:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        return False
    if type(manifest["artifact_version"]) is not int:
        return False
    if manifest["artifact_version"] != 1:
        return False
    run_id = manifest["run_id"]
    if not isinstance(run_id, str):
        return False
    try:
        if str(UUID(run_id)) != run_id:
            return False
    except ValueError:
        return False
    if artifact_dir.name != run_id or not isinstance(manifest["metadata"], dict):
        return False

    provenance = manifest["provenance"]
    if not isinstance(provenance, dict) or set(provenance) != _PROVENANCE_KEYS:
        return False
    if not isinstance(provenance["commit_sha"], str):
        return False
    if not _is_aware_iso8601(provenance["captured_at"]):
        return False
    if not isinstance(provenance["runtime_context"], dict):
        return False
    if not all(
        _is_hash_mapping(provenance[name])
        for name in _PROVENANCE_SHA256_MAPPINGS
    ):
        return False
    if not _is_hash_mapping(
        provenance["excluded_tracked_file_hashes"],
        allow_deleted=True,
    ):
        return False

    files = manifest["files"]
    return (
        isinstance(files, dict)
        and set(files) == set(_REQUIRED_ARTIFACT_FILES)
        and all(_is_sha256(expected_hash) for expected_hash in files.values())
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_path_indirection(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return False
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    file_attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        file_attributes & reparse_attribute
    )


def _normalize_repo_relative_path(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
    ):
        raise ValueError(f"unsafe repository path: {relative_path!r}")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." or "\0" in part for part in parts):
        raise ValueError(f"unsafe repository path: {relative_path!r}")
    return "/".join(parts)


def _repo_candidate_path(repo_root: Path, relative_path: str) -> tuple[str, Path]:
    normalized = _normalize_repo_relative_path(relative_path)
    path = repo_root.joinpath(*normalized.split("/"))
    try:
        path.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"repository path escaped root: {relative_path!r}") from exc
    return normalized, path


def _indirection_component(repo_root: Path, path: Path) -> Path | None:
    relative = path.relative_to(repo_root)
    current = repo_root
    for part in relative.parts:
        current /= part
        if _is_path_indirection(current):
            return current
        if not os.path.lexists(current):
            return None
    return None


def _indirection_hash(relative_path: str) -> str:
    marker = f"filesystem-indirection:{relative_path}".encode("utf-8")
    return _sha256(marker)


def _read_regular_file(repo_root: Path, relative_path: str) -> bytes:
    normalized, path = _repo_candidate_path(repo_root, relative_path)
    indirection = _indirection_component(repo_root, path)
    if indirection is not None:
        raise ValueError(f"filesystem indirection is not allowed: {normalized}")
    if not os.path.lexists(path):
        raise FileNotFoundError(path)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"repository path escaped root: {normalized}") from exc

    flags = os.O_RDONLY
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(path, flags)
    try:
        opened_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise ValueError(f"repository candidate is not a regular file: {normalized}")
        path_stat = path.lstat()
        if _is_path_indirection(path):
            raise ValueError(f"filesystem indirection is not allowed: {normalized}")
        if (opened_stat.st_dev, opened_stat.st_ino) != (
            path_stat.st_dev,
            path_stat.st_ino,
        ):
            raise ValueError(f"repository candidate changed while reading: {normalized}")
        chunks: list[bytes] = []
        while chunk := os.read(file_descriptor, 1024 * 1024):
            chunks.append(chunk)
        if _indirection_component(repo_root, path) is not None:
            raise ValueError(f"filesystem indirection is not allowed: {normalized}")
        return b"".join(chunks)
    finally:
        os.close(file_descriptor)


def _write_atomic(path: Path, payload: bytes) -> None:
    if _is_path_indirection(path.parent):
        raise ValueError("artifact directory indirection is not allowed")
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        handle = os.fdopen(file_descriptor, "wb")
        file_descriptor = -1
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def export_research_artifact(
    *,
    root: Path,
    run_id: str,
    metadata: dict[str, Any],
    events: Sequence[dict[str, Any]],
    provenance: ResearchProvenance,
) -> Path:
    try:
        canonical_run_id = str(UUID(str(run_id)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("run_id must be a valid UUID") from exc

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    root_anchor = root.resolve(strict=True)
    if not root_anchor.is_dir():
        raise ValueError("artifact root must be a directory")
    artifact_dir = root_anchor / canonical_run_id
    try:
        artifact_dir.mkdir()
    except FileExistsError as exc:
        if _is_path_indirection(artifact_dir):
            raise ValueError("artifact directory indirection is not allowed") from exc
        raise FileExistsError(f"research artifact already exists: {canonical_run_id}") from exc
    if _is_path_indirection(artifact_dir):
        raise ValueError("artifact directory indirection is not allowed")
    resolved_artifact_dir = artifact_dir.resolve(strict=True)
    if resolved_artifact_dir.parent != root_anchor:
        raise ValueError("artifact directory escaped the artifact root")
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
        "run_id": canonical_run_id,
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
    """Verify local v1 structure and hashes, not artifact authenticity/signatures."""
    artifact_dir = Path(artifact_dir)
    if _is_path_indirection(artifact_dir):
        return ArtifactVerificationResult(
            valid=False,
            missing_files=(),
            mismatched_files=("manifest.json",),
        )
    manifest_path = artifact_dir / "manifest.json"
    required_paths = {
        relative_name: artifact_dir / relative_name
        for relative_name in _REQUIRED_ARTIFACT_FILES
    }
    symlinked = [
        relative_name
        for relative_name, path in required_paths.items()
        if path.is_symlink()
    ]
    manifest_is_symlink = manifest_path.is_symlink()
    try:
        actual_names = {entry.name for entry in os.scandir(artifact_dir)}
    except (FileNotFoundError, NotADirectoryError, OSError):
        return ArtifactVerificationResult(
            valid=False,
            missing_files=tuple(sorted(_ARTIFACT_DIRECTORY_FILES)),
            mismatched_files=(),
        )
    effective_names = set(actual_names)
    effective_names.update(symlinked)
    if manifest_is_symlink:
        effective_names.add("manifest.json")
    missing = [
        relative_name
        for relative_name, path in required_paths.items()
        if relative_name not in symlinked
        and (relative_name not in effective_names or not path.is_file())
    ]
    unexpected = sorted(actual_names - set(_ARTIFACT_DIRECTORY_FILES))
    if unexpected:
        return ArtifactVerificationResult(
            valid=False,
            missing_files=tuple(sorted(missing)),
            mismatched_files=tuple(sorted([*unexpected, *symlinked])),
        )
    if manifest_is_symlink:
        return ArtifactVerificationResult(
            valid=False,
            missing_files=tuple(sorted(missing)),
            mismatched_files=tuple(sorted(["manifest.json", *symlinked])),
        )
    if not manifest_path.is_file():
        return ArtifactVerificationResult(
            valid=False,
            missing_files=tuple(sorted(["manifest.json", *missing])),
            mismatched_files=tuple(sorted(symlinked)),
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return ArtifactVerificationResult(
            valid=False,
            missing_files=tuple(sorted(missing)),
            mismatched_files=tuple(sorted(["manifest.json", *symlinked])),
        )
    if not _is_valid_v1_manifest(manifest, artifact_dir):
        return ArtifactVerificationResult(
            valid=False,
            missing_files=tuple(sorted(missing)),
            mismatched_files=tuple(sorted(["manifest.json", *symlinked])),
        )

    mismatched = list(symlinked)
    files = manifest["files"]
    for relative_name in _REQUIRED_ARTIFACT_FILES:
        path = required_paths[relative_name]
        if relative_name in missing or relative_name in symlinked:
            continue
        if _sha256(path.read_bytes()) != files[relative_name]:
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


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
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
    for match in _ASSIGNMENT_RE.finditer(text):
        key = match.group("key").strip().strip("\"'").lower()
        compact_key = re.sub(r"[^a-z0-9]", "", key)
        if not any(
            part in key
            or re.sub(r"[^a-z0-9]", "", part) in compact_key
            for part in _SECRET_KEY_PARTS
        ):
            continue
        raw_value = match.group("value").strip()
        quoted_match = re.match(r"(?i)^[rubf]{0,2}([\"'])", raw_value)
        is_quoted = quoted_match is not None
        if is_quoted:
            quote_index = quoted_match.end() - 1
            value = raw_value[quote_index + 1 : -1]
        else:
            value = raw_value
        lowered = value.lower()
        if _ENV_REFERENCE_RE.fullmatch(value):
            continue
        if not is_quoted and lowered.startswith(
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


def _hash_or_deleted(repo_root: Path, relative_path: str) -> str:
    normalized, path = _repo_candidate_path(repo_root, relative_path)
    if not os.path.lexists(path):
        return "deleted"
    if _indirection_component(repo_root, path) is not None:
        return _indirection_hash(normalized)
    try:
        return _sha256(_read_regular_file(repo_root, normalized))
    except FileNotFoundError:
        return "deleted"
    except ValueError:
        return _indirection_hash(normalized)


def _git_blob_short_sha(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(  # noqa: S324 - Git patch object ID, not security.
        header + payload,
        usedforsecurity=False,
    ).hexdigest()[:7]


def _untracked_file_patch(
    relative_path: str,
    payload: bytes,
    text: str,
) -> str:
    normalized_path = relative_path.replace(os.sep, "/")
    patch = (
        f"diff --git a/{normalized_path} b/{normalized_path}\n"
        "new file mode 100644\n"
        f"index 0000000..{_git_blob_short_sha(payload)}\n"
    )
    if not payload:
        return patch
    patch += "".join(
        difflib.unified_diff(
            [],
            text.splitlines(keepends=True),
            fromfile="/dev/null",
            tofile=f"b/{normalized_path}",
        )
    )
    if not payload.endswith(b"\n"):
        patch += "\n\\ No newline at end of file\n"
    return patch


def _collect_relevant_source_paths(
    repo_root: Path,
    relative_path: str,
) -> list[str]:
    normalized, path = _repo_candidate_path(repo_root, relative_path)
    if not os.path.lexists(path):
        return []
    if _indirection_component(repo_root, path) is not None:
        raise ValueError(f"filesystem indirection is not allowed: {normalized}")
    path_stat = path.lstat()
    if stat.S_ISREG(path_stat.st_mode):
        return [normalized]
    if not stat.S_ISDIR(path_stat.st_mode):
        raise ValueError(f"relevant source is not a regular path: {normalized}")

    collected: list[str] = []
    pending = [(normalized, path)]
    while pending:
        directory_relative, directory = pending.pop()
        resolved_directory = directory.resolve(strict=True)
        try:
            resolved_directory.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(
                f"relevant source escaped repository root: {directory_relative}"
            ) from exc
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                child_relative = f"{directory_relative}/{entry.name}"
                child = Path(entry.path)
                if _is_path_indirection(child):
                    raise ValueError(
                        f"filesystem indirection is not allowed: {child_relative}"
                    )
                child_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(child_stat.st_mode):
                    pending.append((child_relative, child))
                elif stat.S_ISREG(child_stat.st_mode) and child.suffix == ".py":
                    collected.append(child_relative)
                elif child.suffix == ".py":
                    raise ValueError(
                        f"relevant source is not a regular file: {child_relative}"
                    )
    return sorted(collected)


def capture_research_provenance(
    *,
    repo_root: Path,
    runtime_context: dict[str, Any],
    captured_at: str,
    relevant_source_paths: Sequence[str] = DEFAULT_RELEVANT_SOURCE_PATHS,
) -> ResearchProvenance:
    repo_root = Path(repo_root).resolve(strict=True)
    if not repo_root.is_dir():
        raise ValueError("repository root must be a directory")
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
    for reported_path in tracked_paths:
        relative_path, path = _repo_candidate_path(repo_root, reported_path)
        if _indirection_component(repo_root, path) is not None:
            excluded_tracked_hashes[relative_path] = _indirection_hash(relative_path)
            continue
        if os.path.lexists(path):
            try:
                _read_regular_file(repo_root, relative_path)
            except (OSError, ValueError):
                excluded_tracked_hashes[relative_path] = _indirection_hash(
                    relative_path
                )
                continue
        if _is_sensitive_path(relative_path):
            excluded_tracked_hashes[relative_path] = _hash_or_deleted(
                repo_root,
                relative_path,
            )
            continue
        candidate_patch_bytes = _git_bytes(
            repo_root,
            "diff",
            "HEAD",
            "--binary",
            "--no-renames",
            "--",
            f":(literal){relative_path}",
        )
        if (
            b"GIT binary patch" in candidate_patch_bytes
            or b"Binary files " in candidate_patch_bytes
            or b"\0" in candidate_patch_bytes
        ):
            excluded_tracked_hashes[relative_path] = _hash_or_deleted(
                repo_root,
                relative_path,
            )
            continue
        try:
            candidate_patch = candidate_patch_bytes.decode("utf-8")
        except UnicodeDecodeError:
            excluded_tracked_hashes[relative_path] = _hash_or_deleted(
                repo_root,
                relative_path,
            )
            continue
        if _contains_sensitive_content(candidate_patch):
            excluded_tracked_hashes[relative_path] = _hash_or_deleted(
                repo_root,
                relative_path,
            )
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
    for reported_path in sorted(filter(None, untracked_output.split("\0"))):
        relative_path, path = _repo_candidate_path(repo_root, reported_path)
        if _indirection_component(repo_root, path) is not None:
            excluded_untracked_hashes[relative_path] = _indirection_hash(relative_path)
            continue
        if _is_sensitive_path(relative_path):
            try:
                excluded_untracked_hashes[relative_path] = _sha256(
                    _read_regular_file(repo_root, relative_path)
                )
            except (OSError, ValueError):
                excluded_untracked_hashes[relative_path] = _indirection_hash(
                    relative_path
                )
            continue
        if path.suffix.lower() not in _UNTRACKED_SUFFIXES:
            continue
        try:
            payload = _read_regular_file(repo_root, relative_path)
        except (OSError, ValueError):
            excluded_untracked_hashes[relative_path] = _indirection_hash(relative_path)
            continue
        payload_hash = _sha256(payload)
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
        untracked_patches.append(_untracked_file_patch(relative_path, payload, text))

    relevant_source_files: list[str] = []
    for relative_path in relevant_source_paths:
        relevant_source_files.extend(
            _collect_relevant_source_paths(repo_root, relative_path)
        )
    source_hashes = {
        relative_path: _sha256(_read_regular_file(repo_root, relative_path))
        for relative_path in sorted(set(relevant_source_files))
    }
    compose_hashes: dict[str, str] = {}
    for name in ("docker-compose.yml", "docker-compose.dev.yml"):
        _, path = _repo_candidate_path(repo_root, name)
        if not os.path.lexists(path):
            continue
        if _indirection_component(repo_root, path) is not None:
            raise ValueError(f"filesystem indirection is not allowed: {name}")
        compose_hashes[name] = _sha256(_read_regular_file(repo_root, name))
    combined_patch = tracked_patch + "".join(untracked_patches)
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
