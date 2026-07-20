from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicationIdentity(_FrozenContract):
    commit: str = Field(min_length=7)
    image: str = Field(min_length=1)
    configuration_hash: str = Field(pattern=SHA256_PATTERN)


class DatabaseIdentity(_FrozenContract):
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    database: str = Field(min_length=1)
    server_version: str = Field(min_length=1)


class SchemaIdentity(_FrozenContract):
    current_revision: str = Field(min_length=1)
    target_revision: str = Field(min_length=1)


class RevisionIdentity(_FrozenContract):
    revision_id: UUID
    release_key: str = Field(min_length=1)
    content_hash: str = Field(pattern=SHA256_PATTERN)


class ReleaseIdentity(_FrozenContract):
    release_key: str = Field(min_length=1)
    content_hash: str = Field(pattern=SHA256_PATTERN)


class DatasetFingerprint(_FrozenContract):
    count: int = Field(ge=0)
    content_hash: str = Field(pattern=SHA256_PATTERN)


class RebuildIdentity(_FrozenContract):
    source_attributes: str = Field(min_length=1)
    canonical_taxonomy: str = Field(min_length=1)
    company_industry: str = Field(min_length=1)
    skills: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_version: int = Field(ge=1)


class CutoverInventory(_FrozenContract):
    application: ApplicationIdentity
    database: DatabaseIdentity
    schema_identity: SchemaIdentity = Field(alias="schema")
    governed_revisions: dict[str, RevisionIdentity | None]
    target_revisions: dict[str, ReleaseIdentity]
    preserved_datasets: dict[str, DatasetFingerprint]
    legacy_projections: dict[str, DatasetFingerprint]
    writers: tuple[str, ...]
    rebuild: RebuildIdentity

    @field_validator("writers")
    @classmethod
    def validate_writers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if not normalized or any(not item for item in normalized):
            raise ValueError("Writer inventory must contain non-empty names")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Writer inventory cannot contain duplicates")
        return normalized


class CutoverManifest(_FrozenContract):
    schema_version: Literal[1] = 1
    created_at: datetime
    operator: Literal["local-operator"] = "local-operator"
    application: ApplicationIdentity
    database: DatabaseIdentity
    schema_identity: SchemaIdentity = Field(alias="schema")
    governed_revisions: dict[str, RevisionIdentity | None]
    target_revisions: dict[str, ReleaseIdentity]
    preserved_datasets: dict[str, DatasetFingerprint]
    legacy_projections: dict[str, DatasetFingerprint]
    writers: tuple[str, ...]
    rebuild: RebuildIdentity
    reset_allowlist: tuple[str, ...]

    @field_validator("created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Cutover manifest timestamp must include a timezone")
        return value


class CutoverManifestEnvelope(_FrozenContract):
    manifest: CutoverManifest
    manifest_hash: str = Field(pattern=SHA256_PATTERN)


class DryRunReport(_FrozenContract):
    schema_version: Literal[1] = 1
    mode: Literal["dry-run"] = "dry-run"
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    started_at: datetime
    completed_at: datetime
    mutation_detected: bool
    preserved_before: dict[str, DatasetFingerprint]
    preserved_after: dict[str, DatasetFingerprint]
    domain_inspections: dict[str, dict[str, object]]
    reset_allowlist: tuple[str, ...]

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_report_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Dry-run report timestamps must include a timezone")
        return value


class WriterStateEvidence(_FrozenContract):
    writer: str = Field(min_length=1)
    state: Literal["stopped", "running", "unknown"]
    evidence_kind: Literal["process", "container", "heartbeat"]
    evidence_ref: str = Field(min_length=1, max_length=512)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Writer evidence timestamp must include a timezone")
        return value


class DatabaseSentinelEvidence(_FrozenContract):
    observation_seconds: int = Field(ge=0)
    before_hash: str = Field(pattern=SHA256_PATTERN)
    after_hash: str = Field(pattern=SHA256_PATTERN)


class QuiescenceReport(_FrozenContract):
    observed_at: datetime
    writers: tuple[WriterStateEvidence, ...]
    database_sentinel: DatabaseSentinelEvidence
    pending_outbox: int = Field(ge=0)
    active_runs: dict[str, int]

    @field_validator("observed_at")
    @classmethod
    def require_aware_quiescence_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Quiescence timestamp must include a timezone")
        return value

    @field_validator("writers")
    @classmethod
    def require_unique_writer_evidence(
        cls,
        value: tuple[WriterStateEvidence, ...],
    ) -> tuple[WriterStateEvidence, ...]:
        names = [item.writer for item in value]
        if len(names) != len(set(names)):
            raise ValueError("Quiescence report contains duplicate writers")
        return value

    @field_validator("active_runs")
    @classmethod
    def require_nonnegative_active_runs(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("Active run counts cannot be negative")
        return value


class RuntimeSmokeChecks(_FrozenContract):
    backend_api: Literal[True]
    embedding: Literal[True]
    frontend: Literal[True]
    governance: Literal[True]
    search: Literal[True]


class RuntimeSmokeEvidence(_FrozenContract):
    schema_version: Literal[1] = 1
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    application: ApplicationIdentity
    status: Literal["passed"] = "passed"
    checks: RuntimeSmokeChecks
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Runtime smoke timestamp must include a timezone")
        return value


class BackupVerification(_FrozenContract):
    backup_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
    artifact_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$")
    artifact_hash: str = Field(pattern=SHA256_PATTERN)
    restore_database: str = Field(min_length=1)
    restored_fingerprints: dict[str, DatasetFingerprint]
    pg_dump_version: str = Field(min_length=1)
    pg_restore_version: str = Field(min_length=1)
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def require_aware_verification_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Backup verification timestamp must include a timezone")
        return value


class CutoverPhaseCheckpoint(_FrozenContract):
    schema_version: Literal[1] = 1
    ordinal: int = Field(ge=1, le=13)
    phase: str = Field(min_length=1)
    status: Literal["running", "completed", "failed"]
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    code_version: str = Field(min_length=7)
    input_hash: str = Field(pattern=SHA256_PATTERN)
    output_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    output: dict[str, object]
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = Field(default=None, max_length=512)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_checkpoint_timestamp(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Checkpoint timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_status_shape(self) -> CutoverPhaseCheckpoint:
        if self.status == "running":
            if self.completed_at is not None or self.output_hash is not None:
                raise ValueError("Running checkpoint cannot be completed")
        elif self.status == "completed":
            if self.completed_at is None or self.output_hash is None:
                raise ValueError("Completed checkpoint requires output and timestamp")
            if self.error_code is not None or self.error_message is not None:
                raise ValueError("Completed checkpoint cannot contain an error")
        elif self.completed_at is None or not self.error_code:
            raise ValueError("Failed checkpoint requires error and timestamp")
        return self


class CutoverExecutionResult(_FrozenContract):
    schema_version: Literal[1] = 1
    status: Literal["completed"] = "completed"
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    backup_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
    started_at: datetime
    completed_at: datetime
    phases: tuple[CutoverPhaseCheckpoint, ...]

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_aware_execution_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Execution timestamps must include a timezone")
        return value


class CutoverVerificationResult(_FrozenContract):
    schema_version: Literal[1] = 1
    status: Literal["verified"] = "verified"
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    verified_at: datetime
    checks: dict[str, object]

    @field_validator("verified_at")
    @classmethod
    def require_aware_verified_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Cutover verification timestamp must include a timezone")
        return value


class CutoverRollbackPlan(_FrozenContract):
    schema_version: Literal[1] = 1
    mode: Literal["rollback-plan"] = "rollback-plan"
    manifest_hash: str = Field(pattern=SHA256_PATTERN)
    generated_at: datetime
    application: ApplicationIdentity
    database: DatabaseIdentity
    schema_identity: SchemaIdentity = Field(alias="schema")
    backup: dict[str, object]
    steps: tuple[str, ...]

    @field_validator("generated_at")
    @classmethod
    def require_aware_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Rollback plan timestamp must include a timezone")
        return value
