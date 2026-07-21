from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.job_intelligence.cutover import (
    ApplicationIdentity,
    BackupVerification,
    CutoverInventory,
    CutoverInventoryError,
    CutoverExecutionBlocked,
    CutoverExecutionResult,
    DatabaseIdentity,
    DatabaseSentinelEvidence,
    DatasetFingerprint,
    DryRunReport,
    CutoverPhaseCheckpoint,
    CutoverPhaseFailed,
    JobIntelligenceCutover,
    ManifestIntegrityError,
    PostgresCutoverEnvironment,
    RebuildIdentity,
    RevisionIdentity,
    SchemaIdentity,
    QuiescenceReport,
    WriterStateEvidence,
    ReleaseIdentity,
)
from app.job_intelligence.cutover.artifacts import content_hash
from app.job_intelligence.cutover.backup import PostgresBackupAdapter
from app.job_intelligence.cutover.constants import CUTOVER_PHASES, KNOWN_WRITERS
from app.job_intelligence.cutover.writer_probe import SystemWriterStateProvider
from app.models.job_embedding import EMBEDDING_DIMENSIONS
from app.services.embedding_document_builder import EmbeddingDocument
from app.services.embedding_indexer import EmbeddingIndexer


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def test_embedding_freshness_pins_document_model_version_and_dimensions() -> None:
    indexer = EmbeddingIndexer(
        embedding_model=object(),
        embedding_model_name="all-MiniLM-L6-v2",
        embedding_version=2,
    )
    document = EmbeddingDocument(
        document_text="Title: Platform Engineer",
        document_hash=SHA_A,
    )
    identity = {
        "document_hash": SHA_A,
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_version": 2,
        "embedding_dimensions": EMBEDDING_DIMENSIONS,
    }

    assert indexer.is_current(SimpleNamespace(**identity), document)
    for field, stale_value in (
        ("document_hash", SHA_B),
        ("embedding_model", "replacement-model"),
        ("embedding_version", 1),
        ("embedding_dimensions", EMBEDDING_DIMENSIONS - 1),
    ):
        stale = {**identity, field: stale_value}
        assert not indexer.is_current(SimpleNamespace(**stale), document)


def test_backup_adapter_keeps_credentials_out_of_commands_and_hashes_artifact(
    tmp_path: Path,
) -> None:
    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def command_runner(args: tuple[str, ...], *, env: dict[str, str]):
        calls.append((args, env))
        if args[:2] == ("pg_dump", "--version"):
            return SimpleNamespace(stdout="pg_dump (PostgreSQL) 15.8\n", stderr="")
        if args[:2] == ("pg_restore", "--version"):
            return SimpleNamespace(stdout="pg_restore (PostgreSQL) 15.8\n", stderr="")
        if args[0] == "pg_dump":
            output_path = Path(args[args.index("--file") + 1])
            output_path.write_bytes(b"fixture-custom-dump")
        return SimpleNamespace(stdout="", stderr="")

    artifact = PostgresBackupAdapter(command_runner=command_runner).create_and_restore(
        source_database_url=(
            "postgresql://operator:source-secret@postgres-db:5432/jobsdb"
        ),
        restore_database_url=(
            "postgresql://operator:restore-secret@postgres-db:5432/"
            "jobsdb_cutover_restore"
        ),
        backup_id="backup-20260720-0830",
        checkpoint_dir=tmp_path,
    )

    assert artifact.artifact_name == "backup-20260720-0830.dump"
    assert artifact.artifact_hash == hashlib.sha256(b"fixture-custom-dump").hexdigest()
    assert (tmp_path / artifact.artifact_name).read_bytes() == b"fixture-custom-dump"
    assert artifact.pg_dump_version == "pg_dump (PostgreSQL) 15.8"
    assert artifact.pg_restore_version == "pg_restore (PostgreSQL) 15.8"
    serialized_argv = " ".join(arg for args, _env in calls for arg in args)
    assert "source-secret" not in serialized_argv
    assert "restore-secret" not in serialized_argv
    dump_call = next(
        call for call in calls if call[0][0] == "pg_dump" and "--file" in call[0]
    )
    restore_call = next(
        call
        for call in calls
        if call[0][0] == "pg_restore" and "--version" not in call[0]
    )
    assert dump_call[1]["PGPASSWORD"] == "source-secret"
    assert restore_call[1]["PGPASSWORD"] == "restore-secret"
    assert "--dbname=jobsdb_cutover_restore" in restore_call[0]


def test_system_writer_probe_combines_container_and_process_evidence() -> None:
    def command_runner(args: tuple[str, ...], *, cwd: Path):
        assert cwd.name == "JOB_SCRAPER"
        if args == (
            "docker",
            "compose",
            "--profile",
            "*",
            "config",
            "--services",
        ):
            return SimpleNamespace(
                stdout=(
                    "backend-api\nscheduler-worker\ningest-worker\n"
                    "enrichment-worker\nembedding-worker\nscrapyd\n"
                )
            )
        if args == (
            "docker",
            "compose",
            "--profile",
            "*",
            "ps",
            "--all",
            "--format",
            "json",
        ):
            return SimpleNamespace(
                stdout=json.dumps(
                    [
                        {"Service": "backend-api", "State": "running"},
                        {"Service": "scheduler-worker", "State": "exited"},
                        {"Service": "ingest-worker", "State": "exited"},
                        {"Service": "enrichment-worker", "State": "exited"},
                        {"Service": "embedding-worker", "State": "exited"},
                        {"Service": "scrapyd", "State": "exited"},
                    ]
                )
            )
        if args == ("ps", "-eo", "pid=,args="):
            return SimpleNamespace(stdout="1 python -m unrelated.service\n")
        raise AssertionError(args)

    evidence = SystemWriterStateProvider(
        command_runner=command_runner,
        compose_directory=Path("/workspace/JOB_SCRAPER"),
    ).collect(
        writers=KNOWN_WRITERS,
        observed_at=datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc),
    )
    states = {item.writer: item.state for item in evidence}

    assert states == {
        "api": "running",
        "detail-worker": "stopped",
        "embedding-worker": "stopped",
        "enrichment-worker": "stopped",
        "ingest-worker": "stopped",
        "listing-worker": "stopped",
        "manual-action-helper": "stopped",
        "outbox-publisher": "running",
        "scheduler-worker": "stopped",
        "scrapyd": "stopped",
        "source-catalog-admin": "stopped",
    }


def test_system_writer_probe_returns_unknown_when_observation_fails() -> None:
    def failing_runner(_args: tuple[str, ...], *, cwd: Path):
        del cwd
        raise OSError("docker unavailable")

    evidence = SystemWriterStateProvider(
        command_runner=failing_runner,
        compose_directory=Path("/workspace/JOB_SCRAPER"),
    ).collect(
        writers=KNOWN_WRITERS,
        observed_at=datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc),
    )

    assert {item.state for item in evidence} == {"unknown"}
    assert all(
        item.evidence_ref == "writer-probe:observation-failed" for item in evidence
    )


def test_cutover_cli_execute_keeps_writer_reopen_as_separate_confirmation() -> None:
    from scripts import job_intelligence_cutover as cli

    common = [
        "execute",
        "--manifest",
        "manifest.json",
        "--checkpoint-dir",
        "checkpoints",
        "--backup-id",
        "backup-20260720-0830",
        "--restore-database-url",
        "postgresql://operator:secret@db/jobsdb_cutover_restore",
        "--confirm-manifest-hash",
        SHA_A,
        "--confirm-execute",
    ]

    prepare_args = cli._parser().parse_args(common)
    reopen_args = cli._parser().parse_args([*common, "--confirm-reopen-writers"])

    assert prepare_args.confirm_reopen_writers is False
    assert reopen_args.confirm_reopen_writers is True


class FixedInventoryEnvironment:
    def __init__(
        self,
        *,
        writer_overrides: dict[str, str] | None = None,
        restored_fingerprint_overrides: dict[str, DatasetFingerprint] | None = None,
        fail_phase: str | None = None,
        pending_outbox: int = 0,
    ) -> None:
        self.writer_overrides = writer_overrides or {}
        self.restored_fingerprint_overrides = restored_fingerprint_overrides or {}
        self.fail_phase = fail_phase
        self.pending_outbox = pending_outbox
        self.phase_calls: list[str] = []

    def collect_inventory(self) -> CutoverInventory:
        return CutoverInventory(
            application=ApplicationIdentity(
                commit="0123456789abcdef",
                image="job-scraper@sha256:release-image",
                configuration_hash=SHA_A,
            ),
            database=DatabaseIdentity(
                host="postgres-db",
                port=5432,
                database="jobsdb",
                server_version="15.8",
            ),
            schema=SchemaIdentity(
                current_revision="20260719_160000",
                target_revision="20260719_160000",
            ),
            governed_revisions={
                "canonical-job-taxonomy": RevisionIdentity(
                    revision_id="11111111-1111-1111-1111-111111111111",
                    release_key="canonical-job-taxonomy-v1",
                    content_hash=SHA_B,
                ),
                "company-industry": None,
                "skill-taxonomy": RevisionIdentity(
                    revision_id="22222222-2222-2222-2222-222222222222",
                    release_key="skills-2026-07-19-v1",
                    content_hash=SHA_C,
                ),
            },
            target_revisions={
                "canonical-job-taxonomy": ReleaseIdentity(
                    release_key="canonical-job-taxonomy-v1",
                    content_hash=SHA_A,
                ),
                "canonical-job-taxonomy-mapping-seed": ReleaseIdentity(
                    release_key="source-to-canonical-job-mapping-v1",
                    content_hash=SHA_B,
                ),
                "company-industry": ReleaseIdentity(
                    release_key="hsic-v2.0-2026-07-19",
                    content_hash=SHA_C,
                ),
                "skill-taxonomy": ReleaseIdentity(
                    release_key="skills-2026-07-19-v1",
                    content_hash=SHA_A,
                ),
            },
            preserved_datasets={
                "jobs-core": DatasetFingerprint(count=17_596, content_hash=SHA_A),
                "companies-core": DatasetFingerprint(
                    count=4_657,
                    content_hash=SHA_B,
                ),
            },
            legacy_projections={
                "job-embeddings": DatasetFingerprint(
                    count=2_931,
                    content_hash=SHA_C,
                )
            },
            writers=(
                "api",
                "scheduler",
                "ingest-worker",
                "enrichment-worker",
                "embedding-worker",
                "outbox-publisher",
            ),
            rebuild=RebuildIdentity(
                source_attributes="v1",
                canonical_taxonomy="canonical-job-taxonomy-v1",
                company_industry="hsic-v2.0-2026-07-19",
                skills="skills-2026-07-19-v1",
                embedding_model="all-MiniLM-L6-v2",
                embedding_version=1,
            ),
        )

    def inspect_rebuild(self) -> dict[str, object]:
        return {
            "canonical_taxonomy": {
                "mode": "read-only",
                "jobs_inspected": 17_596,
                "unassigned": 13_758,
            },
            "company_industry": {
                "mode": "dry-run",
                "companies_inspected": 4_657,
                "review_required": 4_052,
            },
            "embeddings": {
                "mode": "read-only",
                "current": 2_931,
                "eligible": 17_596,
            },
            "skills": {
                "mode": "read-only",
                "jobs_inspected": 17_596,
                "pending_candidates": 5_456,
            },
            "source_attributes": {
                "mode": "read-only",
                "jobs_inspected": 17_596,
                "recoverable_jobs": 17_596,
            },
        }

    def collect_quiescence(self, *, observation_seconds: int) -> QuiescenceReport:
        observed_at = datetime(2026, 7, 20, 8, 31, tzinfo=timezone.utc)
        return QuiescenceReport(
            observed_at=observed_at,
            writers=tuple(
                WriterStateEvidence(
                    writer=writer,
                    state=self.writer_overrides.get(writer, "stopped"),
                    evidence_kind="container",
                    evidence_ref=f"docker-compose:{writer}",
                    observed_at=observed_at,
                )
                for writer in self.collect_inventory().writers
            ),
            database_sentinel=DatabaseSentinelEvidence(
                observation_seconds=observation_seconds,
                before_hash=SHA_A,
                after_hash=SHA_A,
            ),
            pending_outbox=self.pending_outbox,
            active_runs={
                "crawl_executions": 0,
                "enrichment_runs": 0,
                "scheduler_dispatches": 0,
            },
        )

    def create_and_verify_backup(
        self,
        *,
        backup_id: str,
        restore_database_url: str,
        checkpoint_dir: Path,
        expected_fingerprints: dict[str, DatasetFingerprint],
    ) -> BackupVerification:
        del restore_database_url, checkpoint_dir
        restored = {
            **expected_fingerprints,
            **self.restored_fingerprint_overrides,
        }
        return BackupVerification(
            backup_id=backup_id,
            artifact_name=f"{backup_id}.dump",
            artifact_hash=SHA_C,
            restore_database="jobsdb_cutover_restore",
            restored_fingerprints=restored,
            pg_dump_version="pg_dump (PostgreSQL) 15.8",
            pg_restore_version="pg_restore (PostgreSQL) 15.8",
            verified_at=datetime(2026, 7, 20, 8, 32, tzinfo=timezone.utc),
        )

    def run_cutover_phase(
        self,
        *,
        phase: str,
        manifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        del checkpoint_dir, manifest
        self.phase_calls.append(phase)
        if phase == self.fail_phase:
            raise RuntimeError(f"injected failure at {phase}")
        return {
            "phase": phase,
            "manifest_hash": manifest_hash,
            "processed": 3,
        }


def test_runtime_smoke_evidence_requires_post_embedding_timestamp(
    tmp_path: Path,
) -> None:
    fixed_environment = FixedInventoryEnvironment()
    manifest_path = tmp_path / "manifest.json"
    manifest = JobIntelligenceCutover(
        environment=fixed_environment,
        clock=lambda: datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
    ).inventory(output=manifest_path)
    manifest_hash = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "manifest_hash"
    ]
    environment = PostgresCutoverEnvironment(
        session_factory=lambda: SimpleNamespace(),
        database_url="postgresql://operator:secret@postgres-db:5432/jobsdb_test",
        application=manifest.application,
        target_schema_revision=manifest.schema_identity.target_revision,
        rebuild=manifest.rebuild,
    )

    def write_runtime_evidence(observed_at: str) -> None:
        environment.artifact_store.write(
            tmp_path / "runtime-smoke-evidence.json",
            {
                "schema_version": 1,
                "manifest_hash": manifest_hash,
                "application": manifest.application.model_dump(mode="json"),
                "status": "passed",
                "checks": {
                    "backend_api": True,
                    "embedding": True,
                    "frontend": True,
                    "governance": True,
                    "search": True,
                },
                "observed_at": observed_at,
            },
        )

    write_runtime_evidence("2026-07-20T08:31:00Z")
    with pytest.raises(CutoverInventoryError, match="embedding checkpoint"):
        environment._runtime_smoke_evidence(
            manifest=manifest,
            manifest_hash=manifest_hash,
            checkpoint_dir=tmp_path,
        )

    checkpoint_output = {"ready_jobs": 2}
    environment.artifact_store.write(
        tmp_path / "11-rebuild_embeddings.json",
        CutoverPhaseCheckpoint(
            ordinal=11,
            phase="rebuild_embeddings",
            status="completed",
            manifest_hash=manifest_hash,
            code_version=manifest.application.commit,
            input_hash=SHA_B,
            output_hash=content_hash(checkpoint_output),
            output=checkpoint_output,
            started_at=datetime(2026, 7, 20, 8, 29, tzinfo=timezone.utc),
            completed_at=datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
        ).model_dump(mode="json"),
    )

    write_runtime_evidence("2026-07-20T08:29:59Z")
    with pytest.raises(CutoverInventoryError, match="predates"):
        environment._runtime_smoke_evidence(
            manifest=manifest,
            manifest_hash=manifest_hash,
            checkpoint_dir=tmp_path,
        )

    write_runtime_evidence("2026-07-20T08:31:00")
    with pytest.raises(CutoverInventoryError, match="incomplete or invalid"):
        environment._runtime_smoke_evidence(
            manifest=manifest,
            manifest_hash=manifest_hash,
            checkpoint_dir=tmp_path,
        )

    write_runtime_evidence("2026-07-20T08:31:00Z")
    runtime = environment._runtime_smoke_evidence(
        manifest=manifest,
        manifest_hash=manifest_hash,
        checkpoint_dir=tmp_path,
    )

    assert runtime["observed_at"] == "2026-07-20T08:31:00Z"


def test_inventory_writes_deterministic_secret_safe_manifest(tmp_path: Path) -> None:
    fixed_now = datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc)
    cutover = JobIntelligenceCutover(
        environment=FixedInventoryEnvironment(),
        clock=lambda: fixed_now,
    )
    first_path = tmp_path / "first-manifest.json"
    second_path = tmp_path / "second-manifest.json"

    first = cutover.inventory(output=first_path)
    second = cutover.inventory(output=second_path)

    assert first == second
    assert first_path.read_bytes() == second_path.read_bytes()
    assert first.operator == "local-operator"
    assert first.created_at == fixed_now
    assert first.reset_allowlist == (
        "company_industry_assignments",
        "company_industry_review_items",
        "governed_job_skill_mentions",
        "governed_job_skills",
        "job_embeddings",
        "job_employment_types",
        "job_source_attribute_projections",
        "job_source_classification_path_nodes",
        "job_source_classification_paths",
        "job_source_employment_labels",
        "job_taxonomy_assignments",
        "job_taxonomy_review_items",
        "skill_candidates",
    )

    envelope = json.loads(first_path.read_text(encoding="utf-8"))
    assert set(envelope) == {"manifest", "manifest_hash"}
    assert len(envelope["manifest_hash"]) == 64
    serialized = first_path.read_text(encoding="utf-8").lower()
    assert "password" not in serialized
    assert "dev_password" not in serialized
    assert "raw_data" not in serialized
    assert "description" not in serialized


def test_dry_run_rejects_tampered_manifest_before_writing_checkpoints(
    tmp_path: Path,
) -> None:
    cutover = JobIntelligenceCutover(
        environment=FixedInventoryEnvironment(),
        clock=lambda: datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    envelope["manifest"]["application"]["commit"] = "tampered-commit"
    manifest_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(
        ManifestIntegrityError,
        match="Cutover manifest content hash mismatch",
    ):
        cutover.dry_run(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
        )

    assert not checkpoint_dir.exists()


def test_dry_run_writes_complete_zero_mutation_report(tmp_path: Path) -> None:
    fixed_now = datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc)
    cutover = JobIntelligenceCutover(
        environment=FixedInventoryEnvironment(),
        clock=lambda: fixed_now,
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)

    report = cutover.dry_run(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
    )

    assert isinstance(report, DryRunReport)
    assert report.mode == "dry-run"
    assert report.mutation_detected is False
    assert report.preserved_before == report.preserved_after
    assert set(report.domain_inspections) == {
        "canonical_taxonomy",
        "company_industry",
        "embeddings",
        "skills",
        "source_attributes",
    }
    assert report.domain_inspections["canonical_taxonomy"]["unassigned"] == 13_758
    assert (
        report.reset_allowlist
        == cutover.inventory(
            output=tmp_path / "comparison-manifest.json"
        ).reset_allowlist
    )

    envelope = json.loads(
        (checkpoint_dir / "dry-run-report.json").read_text(encoding="utf-8")
    )
    assert set(envelope) == {"payload", "payload_hash"}
    assert envelope["payload"]["mode"] == "dry-run"
    assert len(envelope["payload_hash"]) == 64


def test_execute_requires_successful_dry_run_for_same_manifest(
    tmp_path: Path,
) -> None:
    cutover = JobIntelligenceCutover(
        environment=FixedInventoryEnvironment(),
        clock=lambda: datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)
    manifest_hash = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "manifest_hash"
    ]

    with pytest.raises(CutoverExecutionBlocked) as exc_info:
        cutover.execute(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            backup_id="backup-20260720-0830",
            restore_database_url=(
                "postgresql://operator:secret@postgres-db:5432/"
                "jobsdb_cutover_restore"
            ),
            confirm_execute=True,
            confirm_manifest_hash=manifest_hash,
        )

    assert exc_info.value.code == "CUTOVER_DRY_RUN_REQUIRED"
    assert not checkpoint_dir.exists()


def test_verify_and_rollback_plan_are_explicit_read_only_commands(
    tmp_path: Path,
) -> None:
    environment = FixedInventoryEnvironment()
    cutover = JobIntelligenceCutover(
        environment=environment,
        clock=lambda: datetime(2026, 7, 20, 9, 15, tzinfo=timezone.utc),
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    cutover.artifact_store.write(
        checkpoint_dir / "backup-verification.json",
        BackupVerification(
            backup_id="backup-20260720-0830",
            artifact_name="backup-20260720-0830.dump",
            artifact_hash=SHA_C,
            restore_database="jobsdb_cutover_restore",
            restored_fingerprints=environment.collect_inventory().preserved_datasets,
            pg_dump_version="pg_dump (PostgreSQL) 15.8",
            pg_restore_version="pg_restore (PostgreSQL) 15.8",
            verified_at=datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc),
        ).model_dump(mode="json"),
    )

    verification = cutover.verify(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
    )
    rollback = cutover.rollback_plan(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
    )

    assert verification.status == "verified"
    assert verification.manifest_hash == envelope["manifest_hash"]
    assert verification.checks["phase"] == "cross_layer_verify"
    assert environment.phase_calls == ["cross_layer_verify"]
    assert rollback.mode == "rollback-plan"
    assert rollback.manifest_hash == envelope["manifest_hash"]
    assert rollback.backup["backup_id"] == "backup-20260720-0830"
    assert rollback.steps[0] == "stop_all_services"
    assert rollback.steps[-1] == "reopen_previous_writers"


def test_execute_fails_closed_when_any_writer_state_is_unknown(
    tmp_path: Path,
) -> None:
    environment = FixedInventoryEnvironment(
        writer_overrides={"embedding-worker": "unknown"}
    )
    cutover = JobIntelligenceCutover(
        environment=environment,
        clock=lambda: datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)
    cutover.dry_run(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
    )
    manifest_hash = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "manifest_hash"
    ]

    with pytest.raises(CutoverExecutionBlocked) as exc_info:
        cutover.execute(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            backup_id="backup-20260720-0830",
            restore_database_url=(
                "postgresql://operator:secret@postgres-db:5432/"
                "jobsdb_cutover_restore"
            ),
            confirm_execute=True,
            confirm_manifest_hash=manifest_hash,
        )

    assert exc_info.value.code == "CUTOVER_WRITERS_NOT_QUIESCENT"
    assert "embedding-worker" in str(exc_info.value)
    assert not (checkpoint_dir / "execute-state.json").exists()


def test_execute_rejects_backup_restore_with_preserved_hash_mismatch(
    tmp_path: Path,
) -> None:
    environment = FixedInventoryEnvironment(
        restored_fingerprint_overrides={
            "jobs-core": DatasetFingerprint(count=17_596, content_hash=SHA_C)
        }
    )
    cutover = JobIntelligenceCutover(
        environment=environment,
        clock=lambda: datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)
    cutover.dry_run(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
    )
    manifest_hash = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "manifest_hash"
    ]

    with pytest.raises(CutoverExecutionBlocked) as exc_info:
        cutover.execute(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            backup_id="backup-20260720-0830",
            restore_database_url=(
                "postgresql://operator:secret@postgres-db:5432/"
                "jobsdb_cutover_restore"
            ),
            confirm_execute=True,
            confirm_manifest_hash=manifest_hash,
        )

    assert exc_info.value.code == "CUTOVER_BACKUP_RESTORE_MISMATCH"
    assert "jobs-core" in str(exc_info.value)
    assert not (checkpoint_dir / "execute-state.json").exists()


def test_execute_resumes_from_failed_phase_without_replaying_completed_phases(
    tmp_path: Path,
) -> None:
    environment = FixedInventoryEnvironment(fail_phase="rebuild_company_industries")
    cutover = JobIntelligenceCutover(
        environment=environment,
        clock=lambda: datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)
    cutover.dry_run(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
    )
    manifest_hash = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "manifest_hash"
    ]
    execute_kwargs = {
        "manifest_path": manifest_path,
        "checkpoint_dir": checkpoint_dir,
        "backup_id": "backup-20260720-0830",
        "restore_database_url": (
            "postgresql://operator:secret@postgres-db:5432/" "jobsdb_cutover_restore"
        ),
        "confirm_execute": True,
        "confirm_manifest_hash": manifest_hash,
    }

    with pytest.raises(CutoverPhaseFailed) as exc_info:
        cutover.execute(**execute_kwargs)

    assert exc_info.value.phase == "rebuild_company_industries"
    assert environment.phase_calls == [
        "legacy_audit_snapshot",
        "schema_expand_and_seed_revisions",
        "rebuild_source_classification_paths",
        "rebuild_employment_types",
        "rebuild_canonical_job_taxonomy",
        "rebuild_company_industries",
    ]
    assert (checkpoint_dir / "07-rebuild_canonical_job_taxonomy.json").is_file()
    failed_checkpoint = json.loads(
        (checkpoint_dir / "08-rebuild_company_industries.json").read_text(
            encoding="utf-8"
        )
    )["payload"]
    assert failed_checkpoint["status"] == "failed"
    assert not (checkpoint_dir / "09-rebuild_skill_state.json").exists()

    environment.fail_phase = None
    environment.pending_outbox = 64_142
    environment.phase_calls.clear()
    result = cutover.execute(**execute_kwargs)

    assert isinstance(result, CutoverExecutionResult)
    assert result.status == "completed"
    assert environment.phase_calls == [
        "rebuild_company_industries",
        "rebuild_skill_state",
        "switch_authoritative_reads",
        "rebuild_embeddings",
        "cross_layer_verify",
        "reopen_writers",
    ]
    assert len(result.phases) == 13


@pytest.mark.parametrize("fail_phase", CUTOVER_PHASES[2:])
def test_execute_resumes_at_every_mutating_or_verification_checkpoint(
    tmp_path: Path,
    fail_phase: str,
) -> None:
    environment = FixedInventoryEnvironment(fail_phase=fail_phase)
    cutover = JobIntelligenceCutover(
        environment=environment,
        clock=lambda: datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
    )
    manifest_path = tmp_path / "manifest.json"
    checkpoint_dir = tmp_path / "checkpoints"
    cutover.inventory(output=manifest_path)
    cutover.dry_run(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
    )
    manifest_hash = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "manifest_hash"
    ]
    execute_kwargs = {
        "manifest_path": manifest_path,
        "checkpoint_dir": checkpoint_dir,
        "backup_id": "backup-20260720-0830",
        "restore_database_url": (
            "postgresql://operator:secret@postgres-db:5432/" "jobsdb_cutover_restore"
        ),
        "confirm_execute": True,
        "confirm_manifest_hash": manifest_hash,
    }
    expected_first_calls = list(
        CUTOVER_PHASES[2 : CUTOVER_PHASES.index(fail_phase) + 1]
    )

    with pytest.raises(CutoverPhaseFailed) as exc_info:
        cutover.execute(**execute_kwargs)

    assert exc_info.value.phase == fail_phase
    assert environment.phase_calls == expected_first_calls
    environment.fail_phase = None
    environment.phase_calls.clear()

    result = cutover.execute(**execute_kwargs)

    assert environment.phase_calls == list(
        CUTOVER_PHASES[CUTOVER_PHASES.index(fail_phase) :]
    )
    assert len(result.phases) == len(CUTOVER_PHASES)
