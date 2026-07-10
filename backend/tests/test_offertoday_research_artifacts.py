from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from uuid import UUID

import pytest

from app.sources.offertoday.research.artifacts import (
    DEFAULT_RELEVANT_SOURCE_PATHS,
    ResearchProvenance,
    capture_research_provenance,
    export_research_artifact,
    verify_research_artifact,
)


RUN_ID = "11111111-1111-1111-1111-111111111111"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def write_file(repo: Path, relative_path: str, payload: str | bytes) -> Path:
    path = repo / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initialize_git_fixture(
    tmp_path: Path,
    *,
    tracked_files: dict[str, str | bytes] | None = None,
) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "research-fixture@example.test")
    git(repo, "config", "user.name", "Research Fixture")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    write_file(
        repo,
        ".gitignore",
        "backend/tests/\nbackend/.host_browser_profiles/\n",
    )
    for relative_path, payload in (tracked_files or {}).items():
        write_file(repo, relative_path, payload)
    git(repo, "add", "-f", ".")
    git(repo, "commit", "-m", "fixture baseline")
    return repo


def fixture_provenance(**overrides) -> ResearchProvenance:
    values = {
        "commit_sha": "fixture-sha",
        "working_tree_patch": "diff --git a/safe.py b/safe.py\n",
        "source_hashes": {"backend/app/safe.py": "source-hash"},
        "compose_file_hashes": {"docker-compose.yml": "compose-hash"},
        "captured_at": "2026-07-10T00:00:00+00:00",
        "runtime_context": {"session_mode": "fixture"},
        "untracked_file_hashes": {},
        "excluded_tracked_file_hashes": {},
        "excluded_untracked_file_hashes": {},
    }
    values.update(overrides)
    return ResearchProvenance(**values)


def build_fixture_artifact(root: Path) -> Path:
    return export_research_artifact(
        root=root,
        run_id=RUN_ID,
        metadata={"experiment": "fixture"},
        events=[],
        provenance=fixture_provenance(),
    )


def test_export_is_atomic_canonical_hashed_and_recursively_redacted(tmp_path) -> None:
    secret_values = {
        "authorization": "authorization-value",
        "CookieJar": "cookie-value",
        "credential_path": "credential-value",
        "csrf-token": "csrf-value",
        "RequestHeaders": "header-value",
        "password": "password-value",
        "private-key": "private-key-value",
        "secret_note": "secret-value",
        "storage-state": "storage-value",
        "refreshToken": "token-value",
        "X-API-Key": "api-key-value",
    }
    provenance = fixture_provenance(
        runtime_context={
            "session_mode": "fixture",
            "nested": {
                "client_secret": "runtime-secret-value",
                "safe": "runtime-safe",
            },
        },
    )

    artifact_dir = export_research_artifact(
        root=tmp_path,
        run_id=RUN_ID,
        metadata={
            "experiment": "fixture",
            "nested": {**secret_values, "safe": "metadata-safe"},
            "uuid": UUID(RUN_ID),
        },
        events=[
            {
                "sequence_no": 1,
                "event_type": "research.page_attempt",
                "payload": {
                    "page": 1,
                    "headers": {"csrf-token": "event-secret-value"},
                    "nested": {"safe": "event-safe", "api_token": "event-token"},
                    "id_pairs": [
                        {"job_id": "j-1", "encrypted_job_id": "enc-1"}
                    ],
                    "unicode": "Hong Kong \u9999\u6e2f",
                },
            }
        ],
        provenance=provenance,
    )

    assert artifact_dir == tmp_path / RUN_ID
    assert sorted(path.name for path in artifact_dir.iterdir()) == [
        "manifest.json",
        "observations.jsonl",
        "working-tree.patch",
    ]
    assert not list(artifact_dir.glob("*.tmp"))

    observations_payload = (artifact_dir / "observations.jsonl").read_bytes()
    assert observations_payload.endswith(b"\n")
    assert b"headers" not in observations_payload
    assert b"event-secret-value" not in observations_payload
    assert b"event-token" not in observations_payload
    assert b"\\u9999\\u6e2f" in observations_payload
    observation = json.loads(observations_payload)
    assert observation["payload"] == {
        "id_pairs": [{"encrypted_job_id": "enc-1", "job_id": "j-1"}],
        "nested": {"safe": "event-safe"},
        "page": 1,
        "unicode": "Hong Kong \u9999\u6e2f",
    }

    manifest_path = artifact_dir / "manifest.json"
    manifest_payload = manifest_path.read_bytes()
    assert manifest_payload.endswith(b"\n")
    manifest = json.loads(manifest_payload)
    assert manifest["artifact_version"] == 1
    assert manifest["run_id"] == RUN_ID
    assert manifest["metadata"] == {
        "experiment": "fixture",
        "nested": {"safe": "metadata-safe"},
        "uuid": RUN_ID,
    }
    assert manifest["provenance"]["runtime_context"] == {
        "nested": {"safe": "runtime-safe"},
        "session_mode": "fixture",
    }
    assert manifest_payload == (
        json.dumps(
            manifest,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    assert manifest["files"] == {
        "observations.jsonl": hashlib.sha256(observations_payload).hexdigest(),
        "working-tree.patch": file_sha256(artifact_dir / "working-tree.patch"),
    }
    serialized_payloads = manifest_payload + observations_payload
    for secret_value in (*secret_values.values(), "runtime-secret-value"):
        assert secret_value.encode() not in serialized_payloads
    assert verify_research_artifact(artifact_dir).valid is True


def test_redaction_does_not_remove_excluded_sensitive_path_hash_keys(tmp_path) -> None:
    excluded_tracked = {
        ".env.local": "env-hash",
        "backend/app/token_cache.py": "token-hash",
        "backend/runtime/manual_actions/storage_state.json": "deleted",
    }
    excluded_untracked = {
        "backend/tests/cookie_fixture.json": "cookie-hash",
        "backend/tests/test_secret_probe.py": "secret-hash",
    }

    artifact_dir = export_research_artifact(
        root=tmp_path,
        run_id=RUN_ID,
        metadata={"api_key": "remove-me", "safe": "keep-me"},
        events=[],
        provenance=fixture_provenance(
            excluded_tracked_file_hashes=excluded_tracked,
            excluded_untracked_file_hashes=excluded_untracked,
        ),
    )

    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["metadata"] == {"safe": "keep-me"}
    assert manifest["provenance"]["excluded_tracked_file_hashes"] == (
        excluded_tracked
    )
    assert manifest["provenance"]["excluded_untracked_file_hashes"] == (
        excluded_untracked
    )


def test_verifier_rejects_tampered_observations(tmp_path) -> None:
    artifact_dir = build_fixture_artifact(tmp_path)
    (artifact_dir / "observations.jsonl").write_text("changed\n", encoding="utf-8")

    result = verify_research_artifact(artifact_dir)

    assert result.valid is False
    assert result.missing_files == ()
    assert result.mismatched_files == ("observations.jsonl",)


def test_verifier_reports_missing_files_deterministically(tmp_path) -> None:
    artifact_dir = build_fixture_artifact(tmp_path)
    (artifact_dir / "working-tree.patch").unlink()
    (artifact_dir / "observations.jsonl").unlink()

    result = verify_research_artifact(artifact_dir)

    assert result.valid is False
    assert result.missing_files == (
        "observations.jsonl",
        "working-tree.patch",
    )
    assert result.mismatched_files == ()

    (artifact_dir / "manifest.json").unlink()
    no_manifest = verify_research_artifact(artifact_dir)
    assert no_manifest.valid is False
    assert no_manifest.missing_files == (
        "manifest.json",
        "observations.jsonl",
        "working-tree.patch",
    )
    assert no_manifest.mismatched_files == ()


@pytest.mark.parametrize(
    "invalid_files",
    (
        {},
        [],
        None,
        {
            "observations.jsonl": 123,
            "working-tree.patch": "0" * 64,
        },
        {
            "observations.jsonl": "not-a-sha256",
            "working-tree.patch": "0" * 64,
        },
        {"observations.jsonl": "0" * 64},
    ),
    ids=(
        "empty-map",
        "list",
        "null",
        "wrong-hash-type",
        "malformed-hash",
        "missing-required-name",
    ),
)
def test_verifier_rejects_malformed_fixed_file_maps(tmp_path, invalid_files) -> None:
    artifact_dir = build_fixture_artifact(tmp_path)
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = invalid_files
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_research_artifact(artifact_dir)

    assert result.valid is False
    assert result.missing_files == ()
    assert result.mismatched_files == ("manifest.json",)


@pytest.mark.parametrize("extra_kind", ("ordinary", "parent", "absolute"))
def test_verifier_rejects_extra_and_outside_file_names(tmp_path, extra_kind) -> None:
    artifact_dir = build_fixture_artifact(tmp_path)
    outside = write_file(tmp_path, "outside.txt", "outside evidence\n")
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if extra_kind == "ordinary":
        extra_name = "extra.txt"
    elif extra_kind == "parent":
        extra_name = "../outside.txt"
    else:
        extra_name = str(outside.resolve())
    manifest["files"][extra_name] = file_sha256(outside)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_research_artifact(artifact_dir)

    assert result.valid is False
    assert result.missing_files == ()
    assert result.mismatched_files == ("manifest.json",)


@pytest.mark.parametrize(
    "manifest_text",
    (
        "{not-json",
        "[]",
        '"not-an-object"',
    ),
    ids=("invalid-json", "array", "scalar"),
)
def test_verifier_rejects_malformed_manifest_shapes(tmp_path, manifest_text) -> None:
    artifact_dir = build_fixture_artifact(tmp_path)
    (artifact_dir / "manifest.json").write_text(manifest_text, encoding="utf-8")

    result = verify_research_artifact(artifact_dir)

    assert result.valid is False
    assert result.missing_files == ()
    assert result.mismatched_files == ("manifest.json",)


def test_invalid_manifest_still_reports_missing_required_artifacts(tmp_path) -> None:
    artifact_dir = build_fixture_artifact(tmp_path)
    (artifact_dir / "observations.jsonl").unlink()
    manifest_path = artifact_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = {}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_research_artifact(artifact_dir)

    assert result.valid is False
    assert result.missing_files == ("observations.jsonl",)
    assert result.mismatched_files == ("manifest.json",)


@pytest.mark.parametrize(
    "fixed_name",
    ("manifest.json", "observations.jsonl", "working-tree.patch"),
)
@pytest.mark.parametrize("broken", (False, True), ids=("existing", "broken"))
def test_verifier_rejects_fixed_name_symlinks_without_following(
    tmp_path,
    monkeypatch,
    fixed_name,
    broken,
) -> None:
    artifact_dir = build_fixture_artifact(tmp_path)
    unsafe_path = artifact_dir / fixed_name
    if broken:
        unsafe_path.unlink()

    original_is_symlink = Path.is_symlink
    original_is_file = Path.is_file
    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def fake_is_symlink(path):
        if path == unsafe_path:
            return True
        return original_is_symlink(path)

    def guarded_is_file(path):
        if path == unsafe_path:
            raise AssertionError(f"unsafe is_file call for {fixed_name}")
        return original_is_file(path)

    def guarded_read_text(path, *args, **kwargs):
        if path == unsafe_path:
            raise AssertionError(f"unsafe read_text call for {fixed_name}")
        return original_read_text(path, *args, **kwargs)

    def guarded_read_bytes(path):
        if path == unsafe_path:
            raise AssertionError(f"unsafe read_bytes call for {fixed_name}")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "is_symlink", fake_is_symlink)
    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    result = verify_research_artifact(artifact_dir)

    assert result.valid is False
    assert result.missing_files == ()
    assert result.mismatched_files == (fixed_name,)


def test_provenance_captures_staged_unstaged_and_ignored_safe_files(tmp_path) -> None:
    repo = initialize_git_fixture(
        tmp_path,
        tracked_files={
            "backend/app/staged.py": "VALUE = 1\n",
            "backend/app/unstaged.py": "VALUE = 1\n",
            "backend/app/config.py": "FEATURE_ENABLED = False\n",
        },
    )
    staged = write_file(repo, "backend/app/staged.py", "VALUE = 2\n")
    git(repo, "add", "backend/app/staged.py")
    unstaged = write_file(repo, "backend/app/unstaged.py", "VALUE = 3\n")
    ordinary_config = write_file(
        repo,
        "backend/app/config.py",
        "FEATURE_ENABLED = True\n",
    )
    ignored_test = write_file(
        repo,
        "backend/tests/test_new.py",
        "def test_new():\n    assert True\n",
    )
    script = write_file(
        repo,
        "backend/scripts/new_probe.py",
        "RESULT = 'safe'\n",
    )

    provenance = capture_research_provenance(
        repo_root=repo,
        runtime_context={"session_mode": "fixture"},
        captured_at="2026-07-10T00:00:00+00:00",
    )

    assert provenance.commit_sha == git(repo, "rev-parse", "HEAD").strip()
    assert "+VALUE = 2" in provenance.working_tree_patch
    assert "+VALUE = 3" in provenance.working_tree_patch
    assert "+FEATURE_ENABLED = True" in provenance.working_tree_patch
    assert "--- /dev/null" in provenance.working_tree_patch
    assert "+++ b/backend/tests/test_new.py" in provenance.working_tree_patch
    assert "+++ b/backend/scripts/new_probe.py" in provenance.working_tree_patch
    assert provenance.working_tree_patch.index("backend/app/config.py") < (
        provenance.working_tree_patch.index("backend/app/staged.py")
    )
    assert provenance.working_tree_patch.index("backend/app/staged.py") < (
        provenance.working_tree_patch.index("backend/app/unstaged.py")
    )
    assert provenance.untracked_file_hashes == {
        "backend/scripts/new_probe.py": file_sha256(script),
        "backend/tests/test_new.py": file_sha256(ignored_test),
    }
    assert provenance.excluded_tracked_file_hashes == {}
    assert provenance.excluded_untracked_file_hashes == {}
    assert file_sha256(staged) != file_sha256(unstaged)
    assert file_sha256(ordinary_config)


def test_provenance_fails_closed_for_sensitive_and_binary_candidates(tmp_path) -> None:
    sensitive_tracked_paths = (
        ".env.production",
        "backend/.host_browser_profiles/profile.json",
        "backend/app/.ssh/identity.json",
        "backend/app/__pycache__/cache.py",
        "backend/app/auth/state.py",
        "backend/app/credentials/state.py",
        "backend/app/node_modules/state.py",
        "backend/app/runtime/state.py",
        "backend/app/secrets/state.py",
        "backend/app/auth_state.py",
        "backend/app/cookie_cache.py",
        "backend/app/credential_bundle.py",
        "backend/app/secret_notes.py",
        "backend/app/storage_state.py",
        "backend/app/token_cache.py",
        "backend/app/client.key",
        "backend/app/client.p12",
        "backend/app/client.pem",
        "backend/app/client.pfx",
    )
    tracked_files: dict[str, str | bytes] = {
        path: "VALUE = 'before'\n" for path in sensitive_tracked_paths
    }
    tracked_files.update(
        {
            "backend/runtime/manual_actions/storage_state.json": "{}\n",
            "backend/app/binary.py": b"before\x00payload\n",
            "backend/app/config.py": "FEATURE_ENABLED = False\n",
            "backend/app/deleted_probe.py": 'API_TOKEN = "baseline-secret"\n',
            "backend/app/safe_settings.py": "FEATURE_ENABLED = False\n",
        }
    )
    repo = initialize_git_fixture(tmp_path, tracked_files=tracked_files)

    for relative_path in sensitive_tracked_paths:
        write_file(repo, relative_path, "VALUE = 'after'\n")
    deleted_sensitive_path = repo / "backend/runtime/manual_actions/storage_state.json"
    deleted_sensitive_path.unlink()
    binary_path = write_file(repo, "backend/app/binary.py", b"after\x00payload\n")
    config_path = write_file(
        repo,
        "backend/app/config.py",
        'API_TOKEN = "tracked-hard-coded-secret"\n',
    )
    (repo / "backend/app/deleted_probe.py").unlink()
    write_file(
        repo,
        "backend/app/safe_settings.py",
        "FEATURE_ENABLED = True\n",
    )

    excluded_untracked_payloads: dict[str, str | bytes] = {
        "backend/app/runtime/profile.json": '{"safe":"path-sensitive"}\n',
        "backend/tests/client.pem": "sensitive-suffix-candidate\n",
        "backend/tests/cookie_fixture.json": '{"safe":"path-sensitive"}\n',
        "backend/tests/test_probe.py": 'API_TOKEN = "untracked-hard-coded"\n',
        "backend/tests/test_bearer.py": "VALUE = 'Bearer abcdefghijklmnop'\n",
        "backend/tests/test_private_marker.py": (
            "VALUE = '-----BEGIN PRIVATE KEY-----'\n"
        ),
        "backend/tests/test_url.py": (
            "VALUE = 'https://username:password@example.test/path'\n"
        ),
        "backend/tests/test_binary.py": b"not-utf8-\xff\xfe\n",
        "backend/tests/test_nul_binary.py": b"utf8-decodable\x00binary\n",
    }
    untracked_paths = {
        relative_path: write_file(repo, relative_path, payload)
        for relative_path, payload in excluded_untracked_payloads.items()
    }
    safe_reference = write_file(
        repo,
        "backend/tests/test_safe_reference.py",
        "import os\nAPI_TOKEN = os.getenv('API_TOKEN')\n"
        "CLIENT_SECRET = settings.client_secret\n"
        "MASKED_TOKEN = '<redacted>'\n",
    )

    provenance = capture_research_provenance(
        repo_root=repo,
        runtime_context={"session_mode": "fixture"},
        captured_at="2026-07-10T00:00:00+00:00",
    )

    expected_tracked = {
        path: file_sha256(repo / path) for path in sensitive_tracked_paths
    }
    expected_tracked.update(
        {
            "backend/runtime/manual_actions/storage_state.json": "deleted",
            "backend/app/binary.py": file_sha256(binary_path),
            "backend/app/config.py": file_sha256(config_path),
            "backend/app/deleted_probe.py": "deleted",
        }
    )
    assert provenance.excluded_tracked_file_hashes == dict(
        sorted(expected_tracked.items())
    )
    assert provenance.excluded_untracked_file_hashes == {
        relative_path: file_sha256(path)
        for relative_path, path in sorted(untracked_paths.items())
    }
    assert provenance.untracked_file_hashes == {
        "backend/tests/test_safe_reference.py": file_sha256(safe_reference)
    }
    assert "+FEATURE_ENABLED = True" in provenance.working_tree_patch
    assert "backend/tests/test_safe_reference.py" in provenance.working_tree_patch
    for relative_path in (*expected_tracked, *untracked_paths):
        assert relative_path not in provenance.working_tree_patch
    for sensitive_value in (
        "tracked-hard-coded-secret",
        "untracked-hard-coded",
        "Bearer abcdefghijklmnop",
        "BEGIN PRIVATE KEY",
        "username:password@",
    ):
        assert sensitive_value not in provenance.working_tree_patch


@pytest.mark.parametrize(
    "assignment_key",
    (
        "SECRET_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "CREDENTIAL",
        "REQUEST_HEADERS",
    ),
)
def test_provenance_excludes_complete_marker_bearing_assignment_keys(
    tmp_path,
    assignment_key,
) -> None:
    repo = initialize_git_fixture(
        tmp_path,
        tracked_files={"backend/app/tracked_probe.py": "SAFE_VALUE = 1\n"},
    )
    tracked = write_file(
        repo,
        "backend/app/tracked_probe.py",
        f'{assignment_key} = "tracked-hard-coded-value"\n',
    )
    untracked = write_file(
        repo,
        "backend/tests/assignment_probe.py",
        f'{assignment_key} = "untracked-hard-coded-value"\n',
    )

    provenance = capture_research_provenance(
        repo_root=repo,
        runtime_context={"session_mode": "fixture"},
        captured_at="2026-07-10T00:00:00+00:00",
    )

    assert provenance.excluded_tracked_file_hashes == {
        "backend/app/tracked_probe.py": file_sha256(tracked)
    }
    assert provenance.excluded_untracked_file_hashes == {
        "backend/tests/assignment_probe.py": file_sha256(untracked)
    }
    assert "tracked-hard-coded-value" not in provenance.working_tree_patch
    assert "untracked-hard-coded-value" not in provenance.working_tree_patch
    assert provenance.untracked_file_hashes == {}


def test_provenance_hash_excludes_tracked_non_utf8_text_diff(tmp_path) -> None:
    repo = initialize_git_fixture(
        tmp_path,
        tracked_files={"backend/app/opaque.py": "VALUE = 'before'\n"},
    )
    opaque = write_file(
        repo,
        "backend/app/opaque.py",
        b"VALUE = 'after-\xff\xfe'\n",
    )

    provenance = capture_research_provenance(
        repo_root=repo,
        runtime_context={"session_mode": "fixture"},
        captured_at="2026-07-10T00:00:00+00:00",
    )

    assert provenance.working_tree_patch == ""
    assert provenance.excluded_tracked_file_hashes == {
        "backend/app/opaque.py": file_sha256(opaque)
    }


def test_provenance_emits_empty_and_no_final_newline_file_patches(tmp_path) -> None:
    repo = initialize_git_fixture(tmp_path)
    no_final_newline = write_file(
        repo,
        "backend/tests/a_no_final_newline.py",
        "VALUE = 1",
    )
    following = write_file(
        repo,
        "backend/tests/b_following.py",
        "VALUE = 2\n",
    )
    empty = write_file(repo, "backend/tests/c_empty.py", b"")

    provenance = capture_research_provenance(
        repo_root=repo,
        runtime_context={"session_mode": "fixture"},
        captured_at="2026-07-10T00:00:00+00:00",
    )

    assert provenance.untracked_file_hashes == {
        "backend/tests/a_no_final_newline.py": file_sha256(no_final_newline),
        "backend/tests/b_following.py": file_sha256(following),
        "backend/tests/c_empty.py": file_sha256(empty),
    }
    assert (
        "--- /dev/null\n"
        "+++ b/backend/tests/a_no_final_newline.py\n"
        "@@ -0,0 +1 @@\n"
        "+VALUE = 1\n"
        "\\ No newline at end of file\n"
        "diff --git a/backend/tests/b_following.py "
        "b/backend/tests/b_following.py\n"
    ) in provenance.working_tree_patch
    empty_record = provenance.working_tree_patch.split(
        "diff --git a/backend/tests/c_empty.py b/backend/tests/c_empty.py\n"
    )[-1]
    empty_lines = empty_record.splitlines()
    assert empty_lines[:1] == ["new file mode 100644"]
    assert len(empty_lines) == 2
    assert empty_lines[1].startswith("index 0000000..")
    assert len(empty_lines[1].removeprefix("index 0000000..")) == 7


def test_provenance_hashes_default_sources_compose_and_redacts_runtime(tmp_path) -> None:
    source_payloads = {
        "backend/app/sources/offertoday/root.py": "ROOT = 1\n",
        "backend/app/sources/offertoday/nested/child.py": "CHILD = 1\n",
        "backend/app/sources/offertoday/README.md": "not a Python source\n",
        "backend/app/scraper/offertoday_browser_runtime.py": "RUNTIME = 1\n",
        "backend/app/scraper/offertoday_browser_detail_scraper.py": "DETAIL = 1\n",
        "backend/app/services/offertoday_detail_pipeline.py": "PIPELINE = 1\n",
        "backend/app/services/crawl_job_runtime.py": "CRAWL = 1\n",
        "backend/scripts/offertoday_standalone_crawl.py": "STANDALONE = 1\n",
        "backend/scripts/offertoday_coverage_audit.py": "AUDIT = 1\n",
        "backend/scripts/offertoday_research.py": "RESEARCH = 1\n",
        "docker-compose.yml": "services: {}\n",
        "docker-compose.dev.yml": "services: {}\n",
    }
    repo = initialize_git_fixture(tmp_path, tracked_files=source_payloads)

    provenance = capture_research_provenance(
        repo_root=repo,
        runtime_context={
            "session_mode": "saved-responses",
            "nested": {
                "Authorization": "runtime-token",
                "safe": "runtime-safe",
            },
        },
        captured_at="2026-07-10T12:34:56+00:00",
    )

    expected_source_paths = {
        path
        for path in source_payloads
        if path.endswith(".py")
    }
    assert tuple(DEFAULT_RELEVANT_SOURCE_PATHS) == (
        "backend/app/sources/offertoday",
        "backend/app/scraper/offertoday_browser_runtime.py",
        "backend/app/scraper/offertoday_browser_detail_scraper.py",
        "backend/app/services/offertoday_detail_pipeline.py",
        "backend/app/services/crawl_job_runtime.py",
        "backend/scripts/offertoday_standalone_crawl.py",
        "backend/scripts/offertoday_coverage_audit.py",
        "backend/scripts/offertoday_research.py",
    )
    assert provenance.source_hashes == {
        path: file_sha256(repo / path) for path in sorted(expected_source_paths)
    }
    assert provenance.compose_file_hashes == {
        "docker-compose.dev.yml": file_sha256(repo / "docker-compose.dev.yml"),
        "docker-compose.yml": file_sha256(repo / "docker-compose.yml"),
    }
    assert provenance.captured_at == "2026-07-10T12:34:56+00:00"
    assert provenance.runtime_context == {
        "session_mode": "saved-responses",
        "nested": {"safe": "runtime-safe"},
    }
    assert "runtime-token" not in json.dumps(provenance.runtime_context)
