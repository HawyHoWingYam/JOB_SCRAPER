from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Protocol

from sqlalchemy.engine import make_url

from app.job_intelligence.cutover.artifacts import (
    CutoverManifestStore,
    VerifiedArtifactStore,
    content_hash,
)
from app.job_intelligence.cutover.contracts import (
    BackupVerification,
    CutoverExecutionResult,
    CutoverInventory,
    CutoverManifest,
    CutoverPhaseCheckpoint,
    CutoverRollbackPlan,
    CutoverVerificationResult,
    DatasetFingerprint,
    DryRunReport,
    QuiescenceReport,
)
from app.job_intelligence.cutover.constants import CUTOVER_PHASES, RESET_ALLOWLIST


class CutoverInventoryEnvironment(Protocol):
    def collect_inventory(self) -> CutoverInventory:
        ...

    def inspect_rebuild(self) -> dict[str, object]:
        ...

    def collect_quiescence(
        self,
        *,
        observation_seconds: int,
    ) -> QuiescenceReport:
        ...

    def create_and_verify_backup(
        self,
        *,
        backup_id: str,
        restore_database_url: str,
        checkpoint_dir: Path,
        expected_fingerprints: dict[str, DatasetFingerprint],
    ) -> BackupVerification:
        ...

    def run_cutover_phase(
        self,
        *,
        phase: str,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        ...


class CutoverDriftError(RuntimeError):
    pass


class DryRunMutationError(RuntimeError):
    pass


class CutoverExecutionBlocked(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CutoverPhaseFailed(RuntimeError):
    def __init__(self, phase: str, cause: Exception) -> None:
        super().__init__(f"Cutover phase {phase} failed: {cause}")
        self.phase = phase
        self.cause = cause


class JobIntelligenceCutover:
    """Public orchestration seam for controlled Job Intelligence cutover."""

    def __init__(
        self,
        *,
        environment: CutoverInventoryEnvironment,
        clock: Callable[[], datetime] | None = None,
        manifest_store: CutoverManifestStore | None = None,
        artifact_store: VerifiedArtifactStore | None = None,
    ) -> None:
        self.environment = environment
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.manifest_store = manifest_store or CutoverManifestStore()
        self.artifact_store = artifact_store or VerifiedArtifactStore()

    def inventory(self, *, output: Path) -> CutoverManifest:
        inventory = self.environment.collect_inventory()
        manifest = self._manifest_from_inventory(
            inventory,
            created_at=self.clock(),
        )
        self.manifest_store.write(output, manifest)
        return manifest

    def dry_run(
        self,
        *,
        manifest_path: Path,
        checkpoint_dir: Path,
    ) -> DryRunReport:
        envelope = self.manifest_store.read(manifest_path)
        started_at = self.clock()
        before = self.environment.collect_inventory()
        current_manifest = self._manifest_from_inventory(
            before,
            created_at=envelope.manifest.created_at,
        )
        if current_manifest != envelope.manifest:
            raise CutoverDriftError(
                "Current inventory no longer matches the cutover manifest"
            )

        inspections = self.environment.inspect_rebuild()
        required_domains = {
            "canonical_taxonomy",
            "company_industry",
            "embeddings",
            "skills",
            "source_attributes",
        }
        if set(inspections) != required_domains or any(
            not isinstance(payload, dict) for payload in inspections.values()
        ):
            raise ValueError(
                "Dry-run inspection must report Source Attributes, Canonical "
                "Taxonomy, Company Industry, Skills, and embeddings"
            )

        after = self.environment.collect_inventory()
        mutation_detected = before != after
        report = DryRunReport(
            manifest_hash=envelope.manifest_hash,
            started_at=started_at,
            completed_at=self.clock(),
            mutation_detected=mutation_detected,
            preserved_before=dict(sorted(before.preserved_datasets.items())),
            preserved_after=dict(sorted(after.preserved_datasets.items())),
            domain_inspections={
                key: value
                for key, value in sorted(inspections.items())
                if isinstance(value, dict)
            },
            reset_allowlist=RESET_ALLOWLIST,
        )
        report_path = checkpoint_dir / "dry-run-report.json"
        self.artifact_store.write(
            report_path,
            report.model_dump(mode="json"),
        )
        if mutation_detected:
            raise DryRunMutationError(
                f"Dry-run changed inventory; inspect {report_path}"
            )
        return report

    def execute(
        self,
        *,
        manifest_path: Path,
        checkpoint_dir: Path,
        backup_id: str,
        restore_database_url: str,
        confirm_execute: bool,
        confirm_manifest_hash: str,
    ) -> CutoverExecutionResult:
        execution_started_at = self.clock()
        envelope = self.manifest_store.read(manifest_path)
        if not confirm_execute:
            raise CutoverExecutionBlocked(
                "CUTOVER_EXECUTION_UNCONFIRMED",
                "Cutover execute requires explicit confirmation",
            )
        if confirm_manifest_hash != envelope.manifest_hash:
            raise CutoverExecutionBlocked(
                "CUTOVER_MANIFEST_CONFIRMATION_MISMATCH",
                "Confirmed manifest hash does not match the verified manifest",
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}", backup_id):
            raise CutoverExecutionBlocked(
                "CUTOVER_BACKUP_ID_INVALID",
                "Backup ID must be a bounded filesystem-safe identifier",
            )
        if not restore_database_url.strip():
            raise CutoverExecutionBlocked(
                "CUTOVER_RESTORE_DATABASE_REQUIRED",
                "A disposable restore database URL is required",
            )
        try:
            restore_database = make_url(restore_database_url).database or ""
        except Exception as exc:
            raise CutoverExecutionBlocked(
                "CUTOVER_RESTORE_DATABASE_INVALID",
                "Restore database URL is invalid",
            ) from exc
        if (
            not restore_database.endswith("_cutover_restore")
            or restore_database == envelope.manifest.database.database
        ):
            raise CutoverExecutionBlocked(
                "CUTOVER_RESTORE_DATABASE_UNSAFE",
                "Restore database must be a distinct *_cutover_restore database",
            )

        report_path = checkpoint_dir / "dry-run-report.json"
        try:
            report = self.artifact_store.read(report_path)
        except FileNotFoundError as exc:
            raise CutoverExecutionBlocked(
                "CUTOVER_DRY_RUN_REQUIRED",
                "A successful dry-run report is required before execute",
            ) from exc
        if (
            report.get("manifest_hash") != envelope.manifest_hash
            or report.get("mode") != "dry-run"
            or report.get("mutation_detected") is not False
        ):
            raise CutoverExecutionBlocked(
                "CUTOVER_DRY_RUN_INVALID",
                "Dry-run report does not prove a zero-mutation run for this manifest",
            )

        quiescence = self.environment.collect_quiescence(observation_seconds=30)
        self.artifact_store.write(
            checkpoint_dir / "quiescence-report.json",
            quiescence.model_dump(mode="json"),
        )
        expected_writers = set(envelope.manifest.writers)
        reported_writers = {item.writer for item in quiescence.writers}
        non_stopped = sorted(
            item.writer for item in quiescence.writers if item.state != "stopped"
        )
        missing_writers = sorted(expected_writers - reported_writers)
        unexpected_writers = sorted(reported_writers - expected_writers)
        if non_stopped or missing_writers or unexpected_writers:
            details = ", ".join(
                (
                    *(f"not-stopped:{item}" for item in non_stopped),
                    *(f"missing:{item}" for item in missing_writers),
                    *(f"unexpected:{item}" for item in unexpected_writers),
                )
            )
            raise CutoverExecutionBlocked(
                "CUTOVER_WRITERS_NOT_QUIESCENT",
                f"Writer quiescence is incomplete: {details}",
            )
        sentinel = quiescence.database_sentinel
        if (
            sentinel.observation_seconds < 30
            or sentinel.before_hash != sentinel.after_hash
        ):
            raise CutoverExecutionBlocked(
                "CUTOVER_DATABASE_NOT_QUIESCENT",
                "Database write sentinel changed or used an insufficient window",
            )
        if quiescence.pending_outbox:
            raise CutoverExecutionBlocked(
                "CUTOVER_OUTBOX_NOT_DRAINED",
                "Relevant outbox events must be drained before execute",
            )
        active_runs = sorted(
            name for name, count in quiescence.active_runs.items() if count
        )
        if active_runs:
            raise CutoverExecutionBlocked(
                "CUTOVER_ACTIVE_RUNS_PRESENT",
                f"Active runtime state remains: {', '.join(active_runs)}",
            )

        first_checkpoint = self._complete_gate_checkpoint(
            ordinal=1,
            phase=CUTOVER_PHASES[0],
            manifest_hash=envelope.manifest_hash,
            code_version=envelope.manifest.application.commit,
            input_hash=envelope.manifest_hash,
            output={"quiescence": quiescence.model_dump(mode="json")},
            checkpoint_dir=checkpoint_dir,
        )
        second_input_hash = first_checkpoint.output_hash
        if second_input_hash is None:
            raise AssertionError("Completed quiescence checkpoint has no output hash")
        existing_backup_checkpoint = self._load_checkpoint(
            ordinal=2,
            phase=CUTOVER_PHASES[1],
            manifest_hash=envelope.manifest_hash,
            code_version=envelope.manifest.application.commit,
            input_hash=second_input_hash,
            checkpoint_dir=checkpoint_dir,
        )
        if (
            existing_backup_checkpoint is not None
            and existing_backup_checkpoint.status == "completed"
        ):
            backup = BackupVerification.model_validate(
                existing_backup_checkpoint.output.get("backup")
            )
        else:
            backup = self.environment.create_and_verify_backup(
                backup_id=backup_id,
                restore_database_url=restore_database_url,
                checkpoint_dir=checkpoint_dir,
                expected_fingerprints=dict(envelope.manifest.preserved_datasets),
            )
            self.artifact_store.write(
                checkpoint_dir / "backup-verification.json",
                backup.model_dump(mode="json"),
            )
        expected_fingerprints = envelope.manifest.preserved_datasets
        mismatches = sorted(
            name
            for name in set(expected_fingerprints) | set(backup.restored_fingerprints)
            if expected_fingerprints.get(name) != backup.restored_fingerprints.get(name)
        )
        if (
            backup.backup_id != backup_id
            or backup.restore_database != restore_database
            or mismatches
        ):
            details = ", ".join(mismatches) or "backup identity"
            raise CutoverExecutionBlocked(
                "CUTOVER_BACKUP_RESTORE_MISMATCH",
                f"Backup restore does not preserve: {details}",
            )

        second_checkpoint = self._complete_gate_checkpoint(
            ordinal=2,
            phase=CUTOVER_PHASES[1],
            manifest_hash=envelope.manifest_hash,
            code_version=envelope.manifest.application.commit,
            input_hash=second_input_hash,
            output={"backup": backup.model_dump(mode="json")},
            checkpoint_dir=checkpoint_dir,
        )
        checkpoints = [first_checkpoint, second_checkpoint]
        previous_output_hash = second_checkpoint.output_hash
        if previous_output_hash is None:
            raise AssertionError("Completed backup checkpoint has no output hash")

        for ordinal, phase in enumerate(CUTOVER_PHASES[2:], start=3):
            checkpoint = self._load_checkpoint(
                ordinal=ordinal,
                phase=phase,
                manifest_hash=envelope.manifest_hash,
                code_version=envelope.manifest.application.commit,
                input_hash=previous_output_hash,
                checkpoint_dir=checkpoint_dir,
            )
            if checkpoint is not None and checkpoint.status == "completed":
                checkpoints.append(checkpoint)
                if checkpoint.output_hash is None:
                    raise AssertionError("Completed checkpoint has no output hash")
                previous_output_hash = checkpoint.output_hash
                continue

            started_at = self.clock()
            running = CutoverPhaseCheckpoint(
                ordinal=ordinal,
                phase=phase,
                status="running",
                manifest_hash=envelope.manifest_hash,
                code_version=envelope.manifest.application.commit,
                input_hash=previous_output_hash,
                output={},
                started_at=started_at,
            )
            self._write_checkpoint(running, checkpoint_dir)
            try:
                output = self.environment.run_cutover_phase(
                    phase=phase,
                    manifest=envelope.manifest,
                    manifest_hash=envelope.manifest_hash,
                    checkpoint_dir=checkpoint_dir,
                )
                if not isinstance(output, dict):
                    raise TypeError("Cutover phase output must be a JSON object")
            except Exception as exc:
                failed = CutoverPhaseCheckpoint(
                    ordinal=ordinal,
                    phase=phase,
                    status="failed",
                    manifest_hash=envelope.manifest_hash,
                    code_version=envelope.manifest.application.commit,
                    input_hash=previous_output_hash,
                    output={},
                    started_at=started_at,
                    completed_at=self.clock(),
                    error_code=type(exc).__name__,
                    error_message=str(exc)[:512],
                )
                self._write_checkpoint(failed, checkpoint_dir)
                raise CutoverPhaseFailed(phase, exc) from exc

            completed = CutoverPhaseCheckpoint(
                ordinal=ordinal,
                phase=phase,
                status="completed",
                manifest_hash=envelope.manifest_hash,
                code_version=envelope.manifest.application.commit,
                input_hash=previous_output_hash,
                output_hash=content_hash(output),
                output=output,
                started_at=started_at,
                completed_at=self.clock(),
            )
            self._write_checkpoint(completed, checkpoint_dir)
            checkpoints.append(completed)
            if completed.output_hash is None:
                raise AssertionError("Completed checkpoint has no output hash")
            previous_output_hash = completed.output_hash

        result = CutoverExecutionResult(
            manifest_hash=envelope.manifest_hash,
            backup_id=backup_id,
            started_at=execution_started_at,
            completed_at=self.clock(),
            phases=tuple(checkpoints),
        )
        self.artifact_store.write(
            checkpoint_dir / "execute-state.json",
            result.model_dump(mode="json"),
        )
        return result

    def verify(
        self,
        *,
        manifest_path: Path,
        checkpoint_dir: Path,
    ) -> CutoverVerificationResult:
        envelope = self.manifest_store.read(manifest_path)
        checks = self.environment.run_cutover_phase(
            phase="cross_layer_verify",
            manifest=envelope.manifest,
            manifest_hash=envelope.manifest_hash,
            checkpoint_dir=checkpoint_dir,
        )
        if not isinstance(checks, dict):
            raise TypeError("Cutover verification output must be a JSON object")
        result = CutoverVerificationResult(
            manifest_hash=envelope.manifest_hash,
            verified_at=self.clock(),
            checks=checks,
        )
        self.artifact_store.write(
            checkpoint_dir / "verify-report.json",
            result.model_dump(mode="json"),
        )
        return result

    def rollback_plan(
        self,
        *,
        manifest_path: Path,
        checkpoint_dir: Path,
    ) -> CutoverRollbackPlan:
        envelope = self.manifest_store.read(manifest_path)
        try:
            backup = BackupVerification.model_validate(
                self.artifact_store.read(checkpoint_dir / "backup-verification.json")
            )
        except FileNotFoundError as exc:
            raise CutoverExecutionBlocked(
                "CUTOVER_BACKUP_VERIFICATION_REQUIRED",
                "Rollback planning requires the verified backup artifact",
            ) from exc
        plan = CutoverRollbackPlan(
            manifest_hash=envelope.manifest_hash,
            generated_at=self.clock(),
            application=envelope.manifest.application,
            database=envelope.manifest.database,
            schema=envelope.manifest.schema_identity,
            backup=backup.model_dump(mode="json"),
            steps=(
                "stop_all_services",
                "restore_verified_database_backup",
                "deploy_previous_application_image_and_configuration",
                "validate_legacy_health_and_preserved_fingerprints",
                "reopen_previous_writers",
            ),
        )
        self.artifact_store.write(
            checkpoint_dir / "rollback-plan.json",
            plan.model_dump(mode="json"),
        )
        return plan

    def _complete_gate_checkpoint(
        self,
        *,
        ordinal: int,
        phase: str,
        manifest_hash: str,
        code_version: str,
        input_hash: str,
        output: dict[str, object],
        checkpoint_dir: Path,
    ) -> CutoverPhaseCheckpoint:
        existing = self._load_checkpoint(
            ordinal=ordinal,
            phase=phase,
            manifest_hash=manifest_hash,
            code_version=code_version,
            input_hash=input_hash,
            checkpoint_dir=checkpoint_dir,
        )
        if existing is not None and existing.status == "completed":
            return existing
        now = self.clock()
        completed = CutoverPhaseCheckpoint(
            ordinal=ordinal,
            phase=phase,
            status="completed",
            manifest_hash=manifest_hash,
            code_version=code_version,
            input_hash=input_hash,
            output_hash=content_hash(output),
            output=output,
            started_at=now,
            completed_at=now,
        )
        self._write_checkpoint(completed, checkpoint_dir)
        return completed

    def _load_checkpoint(
        self,
        *,
        ordinal: int,
        phase: str,
        manifest_hash: str,
        code_version: str,
        input_hash: str,
        checkpoint_dir: Path,
    ) -> CutoverPhaseCheckpoint | None:
        path = self._checkpoint_path(checkpoint_dir, ordinal, phase)
        if not path.exists():
            return None
        checkpoint = CutoverPhaseCheckpoint.model_validate(
            self.artifact_store.read(path)
        )
        if (
            checkpoint.ordinal != ordinal
            or checkpoint.phase != phase
            or checkpoint.manifest_hash != manifest_hash
            or checkpoint.code_version != code_version
            or checkpoint.input_hash != input_hash
        ):
            raise CutoverExecutionBlocked(
                "CUTOVER_CHECKPOINT_MISMATCH",
                f"Checkpoint identity mismatch for {phase}",
            )
        if checkpoint.status == "completed" and checkpoint.output_hash != content_hash(
            checkpoint.output
        ):
            raise CutoverExecutionBlocked(
                "CUTOVER_CHECKPOINT_MISMATCH",
                f"Checkpoint output hash mismatch for {phase}",
            )
        return checkpoint

    def _write_checkpoint(
        self,
        checkpoint: CutoverPhaseCheckpoint,
        checkpoint_dir: Path,
    ) -> None:
        self.artifact_store.write(
            self._checkpoint_path(
                checkpoint_dir,
                checkpoint.ordinal,
                checkpoint.phase,
            ),
            checkpoint.model_dump(mode="json"),
        )

    @staticmethod
    def _checkpoint_path(
        checkpoint_dir: Path,
        ordinal: int,
        phase: str,
    ) -> Path:
        return checkpoint_dir / f"{ordinal:02d}-{phase}.json"

    @staticmethod
    def _manifest_from_inventory(
        inventory: CutoverInventory,
        *,
        created_at: datetime,
    ) -> CutoverManifest:
        return CutoverManifest(
            created_at=created_at,
            application=inventory.application,
            database=inventory.database,
            schema=inventory.schema_identity,
            governed_revisions=dict(sorted(inventory.governed_revisions.items())),
            target_revisions=dict(sorted(inventory.target_revisions.items())),
            preserved_datasets=dict(sorted(inventory.preserved_datasets.items())),
            legacy_projections=dict(sorted(inventory.legacy_projections.items())),
            writers=tuple(sorted(inventory.writers)),
            rebuild=inventory.rebuild,
            reset_allowlist=RESET_ALLOWLIST,
        )
