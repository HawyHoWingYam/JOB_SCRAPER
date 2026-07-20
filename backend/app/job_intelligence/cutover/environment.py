from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Protocol, cast

from sqlalchemy import Select, Table, create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, joinedload, sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.job_intelligence.cutover.artifacts import (
    VerifiedArtifactStore,
    canonical_json_bytes,
    content_hash,
)
from app.job_intelligence.cutover.backup import PostgresBackupAdapter
from app.job_intelligence.cutover.constants import (
    CUTOVER_PHASES,
    KNOWN_WRITERS,
    RESET_ALLOWLIST,
)
from app.job_intelligence.cutover.contracts import (
    ApplicationIdentity,
    BackupVerification,
    CutoverPhaseCheckpoint,
    CutoverManifest,
    CutoverInventory,
    DatabaseSentinelEvidence,
    DatabaseIdentity,
    DatasetFingerprint,
    RebuildIdentity,
    QuiescenceReport,
    ReleaseIdentity,
    RevisionIdentity,
    RuntimeSmokeEvidence,
    SchemaIdentity,
    WriterStateEvidence,
)
from app.job_intelligence.cutover.writer_probe import SystemWriterStateProvider
from app.job_intelligence.canonical_taxonomy import (
    CanonicalJobTaxonomy,
    CanonicalTaxonomyPublisher,
    CanonicalTaxonomyRebuildInspector,
)
from app.job_intelligence.company_industry import (
    CompanyIndustry,
    CompanyIndustryPublisher,
    CompanyIndustryRebuildInspector,
)
from app.job_intelligence.skill_governance import (
    SkillExtractionContext,
    SkillGovernance,
    SkillGovernanceRebuildInspector,
    SkillTaxonomyPublisher,
)
from app.job_intelligence.skill_governance.contracts import SkillGovernanceReadError
from app.job_intelligence.source_attributes import (
    EMPLOYMENT_TYPE_SEEDS,
    SourceJobAttributeRebuildInspector,
    SourceJobAttributes,
    SourceJobAttributesView,
)
from app.job_intelligence.foundation import normalized_content_hash
from app.job_intelligence.skill_governance.seed import (
    load_skill_seed_bundle,
    skill_seed_content_hash,
)
from app.models.canonical_job_taxonomy import (
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.company import Company
from app.models.company_enrichment_run import CompanyEnrichmentRun
from app.models.company_industry import (
    CompanyIndustryActiveRevision,
    CompanyIndustryAssignment,
    CompanyIndustryReviewItem,
)
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_execution import CrawlJobExecution
from app.models.enrichment_run import EnrichmentRun
from app.models.event_outbox import EventOutbox
from app.models.governance import GovernanceRevision
from app.models.job import Job
from app.models.job_embedding import EMBEDDING_DIMENSIONS, JobEmbedding
from app.models.job_skill import JobSkill
from app.models.job_skill_mention import JobSkillMention
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedJobSkillMention,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
)
from app.models.schedule import SchedulerRuntimeHeartbeat
from app.models.source_job_attributes import (
    EmploymentType,
    JobEmploymentType,
    JobSourceAttributeProjection,
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
    JobSourceEmploymentLabel,
)
from app.services.embedding_indexer import EmbeddingIndexer
from app.services.governed_embedding_document_builder import (
    GovernedEmbeddingDocumentBuilder,
)


LEGACY_TABLES = (
    "job_categories",
    "job_domains",
    "job_skill_mentions",
    "job_skills",
    "job_subcategories",
    "skill_categories",
    "skill_review_candidates",
    "skill_technologies",
    "skills",
)

DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"


class CutoverInventoryError(RuntimeError):
    pass


class WriterStateProvider(Protocol):
    def collect(
        self,
        *,
        writers: tuple[str, ...],
        observed_at: datetime,
    ) -> tuple[WriterStateEvidence, ...]:
        ...


class FailClosedWriterStateProvider:
    def collect(
        self,
        *,
        writers: tuple[str, ...],
        observed_at: datetime,
    ) -> tuple[WriterStateEvidence, ...]:
        return tuple(
            WriterStateEvidence(
                writer=writer,
                state="unknown",
                evidence_kind="process",
                evidence_ref="writer-probe:not-configured",
                observed_at=observed_at,
            )
            for writer in writers
        )


class PostgresCutoverEnvironment:
    """PostgreSQL-backed system boundary used by the cutover orchestrator."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        database_url: str,
        application: ApplicationIdentity,
        target_schema_revision: str,
        rebuild: RebuildIdentity,
        writers: tuple[str, ...] = KNOWN_WRITERS,
        writer_state_provider: WriterStateProvider | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
        artifact_store: VerifiedArtifactStore | None = None,
        embedding_model: Any | None = None,
        backup_adapter: Any | None = None,
        restore_engine_factory: Callable[[str], Any] = create_engine,
        writer_control: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.database_url = database_url
        self.application = application
        self.target_schema_revision = target_schema_revision
        self.rebuild = rebuild
        self.writers = writers
        self.writer_state_provider = (
            writer_state_provider or SystemWriterStateProvider()
        )
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.artifact_store = artifact_store or VerifiedArtifactStore()
        self.embedding_model = embedding_model
        self.embedding_document_builder = GovernedEmbeddingDocumentBuilder()
        self.backup_adapter = backup_adapter or PostgresBackupAdapter()
        self.restore_engine_factory = restore_engine_factory
        self.writer_control = writer_control

    def collect_inventory(self) -> CutoverInventory:
        db = self.session_factory()
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            database = self._database_identity(db)
            schema = SchemaIdentity(
                current_revision=self._current_alembic_revision(db),
                target_revision=self.target_schema_revision,
            )
            governed_revisions = self._governed_revisions(db)
            target_revisions = self._target_revisions()
            preserved = {
                "companies-core": self._fingerprint_statement(
                    db,
                    select(
                        Company.id,
                        Company.company_id,
                        Company.source_site,
                        Company.source_company_id,
                        Company.name,
                        Company.location,
                        Company.ai_description,
                        Company.extra_data,
                        Company.is_deleted,
                        Company.created_at,
                    ).order_by(Company.id),
                ),
                "crawl-raw-evidence": self._fingerprint_statement(
                    db,
                    select(
                        CrawlJobListing.id,
                        CrawlJobListing.crawl_job_id,
                        CrawlJobListing.source_site,
                        CrawlJobListing.source_job_id,
                        CrawlJobListing.source_url,
                        CrawlJobListing.source_classification_id,
                        CrawlJobListing.source_classification_name,
                        CrawlJobListing.listing_payload,
                        CrawlJobListing.detail_payload,
                        CrawlJobListing.created_at,
                    ).order_by(CrawlJobListing.id),
                ),
                "governance-history": self._combined_table_fingerprint(
                    db,
                    (
                        "governance_audit_events",
                        "governance_idempotency_records",
                        "governance_revisions",
                    ),
                ),
                "jobs-core": self._fingerprint_statement(
                    db,
                    select(
                        Job.id,
                        Job.job_id,
                        Job.source_site,
                        Job.source_job_id,
                        Job.company_id,
                        Job.title,
                        Job.description,
                        Job.ai_summary,
                        Job.ai_enriched_at,
                        Job.experience_min_years,
                        Job.experience_max_years,
                        Job.experience_level,
                        Job.experience_summary,
                        Job._experience_evidence,
                        Job.salary_range,
                        Job.salary_min,
                        Job.salary_max,
                        Job.salary_currency,
                        Job.location,
                        Job.raw_data,
                        Job.search_vector,
                        Job.posted_date,
                        Job.is_deleted,
                        Job.created_at,
                    ).order_by(Job.id),
                ),
                "source-catalog-governance": self._combined_table_fingerprint(
                    db,
                    tuple(
                        sorted(
                            name
                            for name in Base.metadata.tables
                            if name.startswith("source_catalog_")
                        )
                    ),
                ),
            }
            legacy = {
                "legacy-company-industry": self._fingerprint_statement(
                    db,
                    select(Company.id, Company.industry).order_by(Company.id),
                ),
                "legacy-job-fields": self._fingerprint_statement(
                    db,
                    select(
                        Job.id,
                        Job.subcategory_id,
                        Job.source_classification_id,
                        Job.source_classification_name,
                        Job.source_subclassification_id,
                        Job.source_subclassification_name,
                        Job.employment_type,
                    ).order_by(Job.id),
                ),
                "legacy-skill-and-taxonomy-tables": (
                    self._combined_table_fingerprint(db, LEGACY_TABLES)
                ),
            }
            legacy.update(
                {
                    f"reset:{table_name}": self._table_fingerprint(db, table_name)
                    for table_name in RESET_ALLOWLIST
                }
            )
            return CutoverInventory(
                application=self.application,
                database=database,
                schema=schema,
                governed_revisions=governed_revisions,
                target_revisions=target_revisions,
                preserved_datasets=preserved,
                legacy_projections=legacy,
                writers=self.writers,
                rebuild=self.rebuild,
            )
        finally:
            db.rollback()
            db.close()

    def inspect_rebuild(self) -> dict[str, object]:
        db = self.session_factory()
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            source_attributes = SourceJobAttributeRebuildInspector(db).inspect()
            canonical_taxonomy = CanonicalTaxonomyRebuildInspector(db).inspect()
            company_industry = CompanyIndustryRebuildInspector(db).inspect()
            try:
                skills: dict[str, object] = (
                    SkillGovernanceRebuildInspector(db).inspect().to_payload()
                )
                skills["available"] = True
            except SkillGovernanceReadError as exc:
                skills = {
                    "available": False,
                    "mode": "read-only",
                    "unavailable_code": exc.code,
                }

            eligible = int(
                db.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(Job.is_deleted.is_(False))
                )
                or 0
            )
            current = int(
                db.scalar(select(func.count()).select_from(JobEmbedding)) or 0
            )
            embeddings = {
                "mode": "read-only",
                "eligible": eligible,
                "current": current,
                "missing": max(eligible - current, 0),
                "coverage_ratio": current / eligible if eligible else 1.0,
            }
            return {
                "canonical_taxonomy": canonical_taxonomy.to_payload(),
                "company_industry": company_industry.to_payload(),
                "embeddings": embeddings,
                "skills": skills,
                "source_attributes": source_attributes.to_payload(),
            }
        finally:
            db.rollback()
            db.close()

    def collect_quiescence(self, *, observation_seconds: int) -> QuiescenceReport:
        observed_at = self.clock()
        writers = self.writer_state_provider.collect(
            writers=self.writers,
            observed_at=observed_at,
        )
        before_hash = self._mutation_sentinel_hash()
        self.sleeper(observation_seconds)
        after_hash = self._mutation_sentinel_hash()

        db = self.session_factory()
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            pending_outbox = int(
                db.scalar(
                    select(func.count())
                    .select_from(EventOutbox)
                    .where(EventOutbox.status != "published")
                )
                or 0
            )
            active_runs = {
                "company_enrichment_runs": self._status_count(
                    db,
                    CompanyEnrichmentRun,
                    ("pending", "running"),
                ),
                "crawl_executions": int(
                    db.scalar(
                        select(func.count())
                        .select_from(CrawlJobExecution)
                        .where(
                            CrawlJobExecution.status.notin_(
                                (
                                    "cancelled",
                                    "completed",
                                    "exited",
                                    "failed",
                                    "launch_failed",
                                )
                            )
                        )
                    )
                    or 0
                ),
                "crawl_jobs": int(
                    db.scalar(
                        select(func.count())
                        .select_from(CrawlJob)
                        .where(
                            CrawlJob.status.notin_(("cancelled", "completed", "failed"))
                        )
                    )
                    or 0
                ),
                "enrichment_runs": self._status_count(
                    db,
                    EnrichmentRun,
                    ("pending", "running", "stopping", "waiting"),
                ),
                "scheduler_dispatches": int(
                    db.scalar(
                        select(func.count())
                        .select_from(SchedulerRuntimeHeartbeat)
                        .where(SchedulerRuntimeHeartbeat.status != "stopped")
                    )
                    or 0
                ),
            }
        finally:
            db.rollback()
            db.close()

        return QuiescenceReport(
            observed_at=observed_at,
            writers=writers,
            database_sentinel=DatabaseSentinelEvidence(
                observation_seconds=observation_seconds,
                before_hash=before_hash,
                after_hash=after_hash,
            ),
            pending_outbox=pending_outbox,
            active_runs=active_runs,
        )

    def create_and_verify_backup(
        self,
        *,
        backup_id: str,
        restore_database_url: str,
        checkpoint_dir: Path,
        expected_fingerprints: dict[str, DatasetFingerprint],
    ) -> BackupVerification:
        source_database = make_url(self.database_url).database or ""
        restore_url = make_url(restore_database_url)
        restore_database = restore_url.database or ""
        if (
            not restore_database.endswith("_cutover_restore")
            or restore_database == source_database
        ):
            raise CutoverInventoryError(
                "Restore database must be a distinct *_cutover_restore database"
            )

        current = self.collect_inventory().preserved_datasets
        drift = sorted(
            name
            for name in set(expected_fingerprints) | set(current)
            if expected_fingerprints.get(name) != current.get(name)
        )
        if drift:
            raise CutoverInventoryError(
                "Current preserved fingerprints drifted before backup: "
                + ", ".join(drift)
            )

        artifact = self.backup_adapter.create_and_restore(
            source_database_url=self.database_url,
            restore_database_url=restore_database_url,
            backup_id=backup_id,
            checkpoint_dir=checkpoint_dir,
        )
        if Path(artifact.artifact_name).name != artifact.artifact_name:
            raise CutoverInventoryError(
                "Backup adapter returned an unsafe artifact name"
            )
        artifact_path = checkpoint_dir / artifact.artifact_name
        if (
            not artifact_path.is_file()
            or self._file_content_hash(artifact_path) != artifact.artifact_hash
        ):
            raise CutoverInventoryError(
                "Backup artifact checksum does not match the adapter result"
            )

        restore_engine = self.restore_engine_factory(restore_database_url)
        try:
            restore_session_factory = sessionmaker(
                bind=restore_engine,
                autoflush=False,
                expire_on_commit=False,
            )
            restored_environment = PostgresCutoverEnvironment(
                session_factory=restore_session_factory,
                database_url=restore_database_url,
                application=self.application,
                target_schema_revision=self.target_schema_revision,
                rebuild=self.rebuild,
                writers=self.writers,
                writer_state_provider=self.writer_state_provider,
                sleeper=self.sleeper,
                clock=self.clock,
                artifact_store=self.artifact_store,
                embedding_model=self.embedding_model,
                backup_adapter=self.backup_adapter,
                restore_engine_factory=self.restore_engine_factory,
                writer_control=self.writer_control,
            )
            restored_inventory = restored_environment.collect_inventory()
            restored_fingerprints = {
                name: restored_inventory.preserved_datasets[name]
                for name in sorted(expected_fingerprints)
                if name in restored_inventory.preserved_datasets
            }
        finally:
            restore_engine.dispose()

        return BackupVerification(
            backup_id=backup_id,
            artifact_name=artifact.artifact_name,
            artifact_hash=artifact.artifact_hash,
            restore_database=restore_database,
            restored_fingerprints=restored_fingerprints,
            pg_dump_version=artifact.pg_dump_version,
            pg_restore_version=artifact.pg_restore_version,
            verified_at=self.clock(),
        )

    def run_cutover_phase(
        self,
        *,
        phase: str,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        if phase == "legacy_audit_snapshot":
            return self._export_legacy_audit(
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "schema_expand_and_seed_revisions":
            return self._expand_and_seed_revisions(manifest)
        if phase == "rebuild_source_classification_paths":
            return self._rebuild_source_attributes(
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "rebuild_employment_types":
            return self._verify_employment_type_rebuild()
        if phase == "rebuild_canonical_job_taxonomy":
            return self._rebuild_canonical_taxonomy(
                manifest=manifest,
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "rebuild_company_industries":
            return self._rebuild_company_industries(
                manifest=manifest,
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "rebuild_skill_state":
            return self._rebuild_skill_state(
                manifest=manifest,
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "switch_authoritative_reads":
            return self._switch_authoritative_reads(
                manifest=manifest,
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "rebuild_embeddings":
            return self._rebuild_embeddings(
                manifest=manifest,
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "cross_layer_verify":
            return self._cross_layer_verify(
                manifest=manifest,
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        if phase == "reopen_writers":
            return self._reopen_writers(
                manifest=manifest,
                manifest_hash=manifest_hash,
                checkpoint_dir=checkpoint_dir,
            )
        raise CutoverInventoryError(f"Cutover phase is not implemented: {phase}")

    def _expand_and_seed_revisions(
        self,
        manifest: CutoverManifest,
    ) -> dict[str, object]:
        current_targets = self._target_revisions()
        if manifest.target_revisions != current_targets:
            raise CutoverInventoryError(
                "Committed governed seed content no longer matches the manifest"
            )
        taxonomy = json.loads(
            (DATA_DIRECTORY / "job_category_taxonomy.json").read_text(encoding="utf-8")
        )
        mapping = json.loads(
            (DATA_DIRECTORY / "job_source_taxonomy_mapping.json").read_text(
                encoding="utf-8"
            )
        )
        industry = json.loads(
            (DATA_DIRECTORY / "hsic_v2.json").read_text(encoding="utf-8")
        )
        skills = load_skill_seed_bundle()

        db = self.session_factory()
        try:
            canonical_publisher = CanonicalTaxonomyPublisher(db)
            canonical_revision = canonical_publisher.materialize(taxonomy)
            self._require_target_revision(
                canonical_revision.release_key,
                canonical_revision.content_hash,
                current_targets["canonical-job-taxonomy"],
            )
            canonical_active = db.get(
                CanonicalJobTaxonomyActiveRevision,
                "canonical-job-taxonomy",
            )
            canonical_publisher.activate(
                canonical_revision,
                expected_lock_version=(
                    cast(int, canonical_active.lock_version)
                    if canonical_active is not None
                    else 0
                ),
            )

            company_publisher = CompanyIndustryPublisher(db)
            company_revision = company_publisher.materialize(industry)
            self._require_target_revision(
                company_revision.release_key,
                company_revision.content_hash,
                current_targets["company-industry"],
            )
            company_active = db.get(
                CompanyIndustryActiveRevision,
                "company-industry",
            )
            if (
                company_active is None
                or company_active.revision_id != company_revision.revision_id
                or company_active.content_hash != company_revision.content_hash
            ):
                company_publisher.activate(
                    company_revision,
                    expected_lock_version=(
                        cast(int, company_active.lock_version)
                        if company_active is not None
                        else 0
                    ),
                )

            skill_publisher = SkillTaxonomyPublisher(db)
            skill_revision = skill_publisher.materialize(skills)
            self._require_target_revision(
                skill_revision.release_key,
                skill_revision.content_hash,
                current_targets["skill-taxonomy"],
            )
            skill_active = db.get(
                SkillTaxonomyActiveRevision,
                "skill-taxonomy",
            )
            skill_publisher.activate(
                skill_revision,
                expected_lock_version=(
                    cast(int, skill_active.lock_version)
                    if skill_active is not None
                    else 0
                ),
            )

            mapping_target = current_targets["canonical-job-taxonomy-mapping-seed"]
            if mapping_target.release_key != str(
                mapping["release_key"]
            ) or mapping_target.content_hash != normalized_content_hash(mapping):
                raise CutoverInventoryError(
                    "Canonical mapping seed no longer matches the manifest"
                )
            mapping_revision = canonical_publisher.materialize_mapping(
                taxonomy,
                mapping,
            )
            mapping_active = db.get(
                CanonicalJobTaxonomyActiveMappingRevision,
                "canonical-job-taxonomy-mapping",
            )
            canonical_publisher.activate_mapping(
                mapping_revision,
                expected_lock_version=(
                    cast(int, mapping_active.lock_version)
                    if mapping_active is not None
                    else 0
                ),
            )

            for code, label, sort_order in EMPLOYMENT_TYPE_SEEDS:
                employment_type = db.get(EmploymentType, code)
                if employment_type is None:
                    db.add(
                        EmploymentType(
                            code=code,
                            label=label,
                            sort_order=sort_order,
                        )
                    )
                elif (
                    employment_type.label != label
                    or employment_type.sort_order != sort_order
                ):
                    raise CutoverInventoryError(
                        f"Employment Type registry drift for {code}"
                    )
            db.commit()

            active_revisions = self._governed_revisions(db)
            if any(value is None for value in active_revisions.values()):
                raise CutoverInventoryError(
                    "All governed revisions must be active after seed expansion"
                )
            return {
                "active_revisions": {
                    domain: value.model_dump(mode="json")
                    for domain, value in sorted(active_revisions.items())
                    if value is not None
                },
                "mapping_seed_hash": mapping_target.content_hash,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _rebuild_source_attributes(
        self,
        *,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        progress_path = checkpoint_dir / "rebuild-source-attributes-progress.json"
        progress: dict[str, object]
        if progress_path.exists():
            progress = self.artifact_store.read(progress_path)
            if progress.get("manifest_hash") != manifest_hash:
                raise CutoverInventoryError(
                    "Source Attribute progress belongs to another manifest"
                )
            if progress.get("status") == "completed":
                output = progress.get("output")
                if not isinstance(output, dict):
                    raise CutoverInventoryError(
                        "Completed Source Attribute progress has no output"
                    )
                return output
        else:
            reset_db = self.session_factory()
            try:
                reset_db.execute(delete(JobEmploymentType))
                reset_db.execute(delete(JobSourceEmploymentLabel))
                reset_db.execute(delete(JobSourceClassificationPathNode))
                reset_db.execute(delete(JobSourceClassificationPath))
                reset_db.execute(delete(JobSourceAttributeProjection))
                reset_db.commit()
            except Exception:
                reset_db.rollback()
                raise
            finally:
                reset_db.close()
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": None,
                "output": {
                    "ambiguous_jobs": 0,
                    "changed_jobs": 0,
                    "classification_paths": 0,
                    "employment_type_assignments": 0,
                    "jobs_inspected": 0,
                    "projected_jobs": 0,
                    "provenance_limited_jobs": 0,
                    "unrecoverable_jobs": 0,
                },
            }
            self.artifact_store.write(progress_path, progress)

        recovery_db = self.session_factory()
        try:
            recovered = SourceJobAttributeRebuildInspector(recovery_db).recover()
        finally:
            recovery_db.rollback()
            recovery_db.close()

        last_cursor = progress.get("last_cursor")
        pending = tuple(
            item
            for item in recovered
            if last_cursor is None or item.cursor > str(last_cursor)
        )
        output_value = progress.get("output")
        if not isinstance(output_value, dict):
            raise CutoverInventoryError("Source Attribute progress output is invalid")
        counters: dict[str, int] = {
            str(key): int(value) for key, value in output_value.items()
        }

        batch_size = 100
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            batch_db = self.session_factory()
            batch_counts = {key: 0 for key in counters}
            try:
                for item in batch:
                    batch_counts["jobs_inspected"] += 1
                    if item.ambiguous:
                        batch_counts["ambiguous_jobs"] += 1
                        continue
                    if item.evidence is None:
                        batch_counts["unrecoverable_jobs"] += 1
                        continue
                    result = SourceJobAttributes(batch_db).project(
                        item.job_id,
                        item.evidence,
                    )
                    batch_counts["projected_jobs"] += 1
                    batch_counts["changed_jobs"] += int(result.changed)
                    batch_counts["classification_paths"] += len(
                        item.evidence.classification_paths
                    )
                    batch_counts["employment_type_assignments"] += len(
                        {
                            label.mapped_type_code
                            for label in item.evidence.employment_labels
                            if label.mapped_type_code is not None
                        }
                    )
                    batch_counts["provenance_limited_jobs"] += int(
                        any(
                            path.source_catalog_revision is None
                            for path in item.evidence.classification_paths
                        )
                    )
                batch_db.commit()
            except Exception:
                batch_db.rollback()
                raise
            finally:
                batch_db.close()

            for key, value in batch_counts.items():
                counters[key] += value
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": batch[-1].cursor,
                "output": counters,
            }
            self.artifact_store.write(progress_path, progress)

        completed = {
            "manifest_hash": manifest_hash,
            "status": "completed",
            "last_cursor": pending[-1].cursor if pending else last_cursor,
            "output": counters,
        }
        self.artifact_store.write(progress_path, completed)
        return cast(dict[str, object], counters)

    def _verify_employment_type_rebuild(self) -> dict[str, object]:
        db = self.session_factory()
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            return {
                "employment_type_assignments": int(
                    db.scalar(select(func.count()).select_from(JobEmploymentType)) or 0
                ),
                "jobs_with_projection": int(
                    db.scalar(
                        select(func.count()).select_from(JobSourceAttributeProjection)
                    )
                    or 0
                ),
                "mapped_labels": int(
                    db.scalar(
                        select(func.count())
                        .select_from(JobSourceEmploymentLabel)
                        .where(JobSourceEmploymentLabel.mapped_type_code.isnot(None))
                    )
                    or 0
                ),
                "source_labels": int(
                    db.scalar(
                        select(func.count()).select_from(JobSourceEmploymentLabel)
                    )
                    or 0
                ),
                "unknown_labels": int(
                    db.scalar(
                        select(func.count())
                        .select_from(JobSourceEmploymentLabel)
                        .where(JobSourceEmploymentLabel.mapped_type_code.is_(None))
                    )
                    or 0
                ),
            }
        finally:
            db.rollback()
            db.close()

    def _rebuild_canonical_taxonomy(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        progress_path = checkpoint_dir / "rebuild-canonical-taxonomy-progress.json"
        progress: dict[str, object]
        if progress_path.exists():
            progress = self.artifact_store.read(progress_path)
            if progress.get("manifest_hash") != manifest_hash:
                raise CutoverInventoryError(
                    "Canonical Taxonomy progress belongs to another manifest"
                )
            if progress.get("status") == "completed":
                output = progress.get("output")
                if not isinstance(output, dict):
                    raise CutoverInventoryError(
                        "Completed Canonical Taxonomy progress has no output"
                    )
                return output
        else:
            reset_db = self.session_factory()
            try:
                active = self._governed_revisions(reset_db)
                self._require_active_target(
                    active["canonical-job-taxonomy"],
                    manifest.target_revisions["canonical-job-taxonomy"],
                    domain="canonical-job-taxonomy",
                )
                active_taxonomy = reset_db.get(
                    CanonicalJobTaxonomyActiveRevision,
                    "canonical-job-taxonomy",
                )
                active_mapping = reset_db.get(
                    CanonicalJobTaxonomyActiveMappingRevision,
                    "canonical-job-taxonomy-mapping",
                )
                mapping_identity = active["canonical-job-taxonomy-mapping"]
                mapping_target = manifest.target_revisions[
                    "canonical-job-taxonomy-mapping-seed"
                ]
                if (
                    active_taxonomy is None
                    or active_mapping is None
                    or mapping_identity is None
                    or mapping_identity.release_key != mapping_target.release_key
                    or active_mapping.taxonomy_revision_id
                    != active_taxonomy.revision_id
                    or active_mapping.mapping_revision_id
                    != mapping_identity.revision_id
                    or active_mapping.content_hash != mapping_identity.content_hash
                ):
                    raise CutoverInventoryError(
                        "Active canonical-job-taxonomy-mapping release does not "
                        "match the manifest seed and active taxonomy"
                    )
                reset_db.execute(delete(JobTaxonomyReviewItem))
                reset_db.execute(delete(JobTaxonomyAssignment))
                reset_db.commit()
            except Exception:
                reset_db.rollback()
                raise
            finally:
                reset_db.close()
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": None,
                "output": {
                    "assigned_jobs": 0,
                    "jobs_inspected": 0,
                    "jobs_without_source_attributes": 0,
                    "review_jobs": 0,
                },
            }
            self.artifact_store.write(progress_path, progress)

        inventory_db = self.session_factory()
        try:
            job_ids = tuple(
                inventory_db.scalars(select(Job.id).order_by(Job.id.asc())).all()
            )
        finally:
            inventory_db.rollback()
            inventory_db.close()

        last_cursor = progress.get("last_cursor")
        pending = tuple(
            job_id
            for job_id in job_ids
            if last_cursor is None or str(job_id) > str(last_cursor)
        )
        output_value = progress.get("output")
        if not isinstance(output_value, dict):
            raise CutoverInventoryError("Canonical Taxonomy progress output is invalid")
        counters: dict[str, int] = {
            str(key): int(value) for key, value in output_value.items()
        }

        batch_size = 100
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            batch_db = self.session_factory()
            batch_counts = {key: 0 for key in counters}
            try:
                source_attributes = SourceJobAttributes(batch_db)
                canonical_taxonomy = CanonicalJobTaxonomy(batch_db)
                for job_id in batch:
                    batch_counts["jobs_inspected"] += 1
                    if batch_db.get(JobSourceAttributeProjection, job_id) is None:
                        batch_counts["jobs_without_source_attributes"] += 1
                        job = batch_db.get(Job, job_id)
                        if job is None:
                            raise CutoverInventoryError(
                                f"Canonical rebuild Job disappeared: {job_id}"
                            )
                        evidence = SourceJobAttributesView(
                            job_id=job_id,
                            source_site=job.source_site,
                            version=0,
                            evidence_hash=normalized_content_hash(
                                {
                                    "authority": "source-job-attributes",
                                    "job_id": str(job_id),
                                    "state": "unavailable",
                                }
                            ),
                            source_classification_paths=(),
                            employment_types=(),
                            source_employment_labels=(),
                        )
                    else:
                        evidence = source_attributes.get(job_id)
                    result = canonical_taxonomy.evaluate(job_id, evidence)
                    if result.state == "assigned":
                        batch_counts["assigned_jobs"] += 1
                    else:
                        batch_counts["review_jobs"] += 1
                batch_db.commit()
            except Exception:
                batch_db.rollback()
                raise
            finally:
                batch_db.close()

            for key, value in batch_counts.items():
                counters[key] += value
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": str(batch[-1]),
                "output": counters,
            }
            self.artifact_store.write(progress_path, progress)

        completed = {
            "manifest_hash": manifest_hash,
            "status": "completed",
            "last_cursor": str(pending[-1]) if pending else last_cursor,
            "output": counters,
        }
        self.artifact_store.write(progress_path, completed)
        return cast(dict[str, object], counters)

    def _rebuild_company_industries(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        progress_path = checkpoint_dir / "rebuild-company-industries-progress.json"
        progress: dict[str, object]
        if progress_path.exists():
            progress = self.artifact_store.read(progress_path)
            if progress.get("manifest_hash") != manifest_hash:
                raise CutoverInventoryError(
                    "Company Industry progress belongs to another manifest"
                )
            if progress.get("status") == "completed":
                output = progress.get("output")
                if not isinstance(output, dict):
                    raise CutoverInventoryError(
                        "Completed Company Industry progress has no output"
                    )
                return output
        else:
            reset_db = self.session_factory()
            try:
                active = self._governed_revisions(reset_db)
                self._require_active_target(
                    active["company-industry"],
                    manifest.target_revisions["company-industry"],
                    domain="company-industry",
                )
                reset_db.execute(delete(CompanyIndustryReviewItem))
                reset_db.execute(delete(CompanyIndustryAssignment))
                reset_db.commit()
            except Exception:
                reset_db.rollback()
                raise
            finally:
                reset_db.close()
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": None,
                "output": {
                    "assigned_companies": 0,
                    "companies_inspected": 0,
                    "no_evidence_companies": 0,
                    "review_companies": 0,
                },
            }
            self.artifact_store.write(progress_path, progress)

        recovery_db = self.session_factory()
        try:
            recovered = CompanyIndustryRebuildInspector(recovery_db).recover()
        finally:
            recovery_db.rollback()
            recovery_db.close()

        last_cursor = progress.get("last_cursor")
        pending = tuple(
            item
            for item in recovered
            if last_cursor is None or item.cursor > str(last_cursor)
        )
        output_value = progress.get("output")
        if not isinstance(output_value, dict):
            raise CutoverInventoryError("Company Industry progress output is invalid")
        counters: dict[str, int] = {
            str(key): int(value) for key, value in output_value.items()
        }

        batch_size = 100
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            batch_db = self.session_factory()
            batch_counts = {key: 0 for key in counters}
            try:
                company_industry = CompanyIndustry(batch_db)
                for item in batch:
                    batch_counts["companies_inspected"] += 1
                    if item.evidence is None:
                        batch_counts["no_evidence_companies"] += 1
                        continue
                    outcome = company_industry.ingest_evidence(
                        item.company_id,
                        item.evidence,
                    )
                    if outcome.state == "assigned":
                        batch_counts["assigned_companies"] += 1
                    else:
                        batch_counts["review_companies"] += 1
                batch_db.commit()
            except Exception:
                batch_db.rollback()
                raise
            finally:
                batch_db.close()

            for key, value in batch_counts.items():
                counters[key] += value
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": batch[-1].cursor,
                "output": counters,
            }
            self.artifact_store.write(progress_path, progress)

        completed = {
            "manifest_hash": manifest_hash,
            "status": "completed",
            "last_cursor": pending[-1].cursor if pending else last_cursor,
            "output": counters,
        }
        self.artifact_store.write(progress_path, completed)
        return cast(dict[str, object], counters)

    def _rebuild_skill_state(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        progress_path = checkpoint_dir / "rebuild-skill-state-progress.json"
        progress: dict[str, object]
        if progress_path.exists():
            progress = self.artifact_store.read(progress_path)
            if progress.get("manifest_hash") != manifest_hash:
                raise CutoverInventoryError(
                    "Skill rebuild progress belongs to another manifest"
                )
            if progress.get("status") == "completed":
                output = progress.get("output")
                if not isinstance(output, dict):
                    raise CutoverInventoryError(
                        "Completed Skill rebuild progress has no output"
                    )
                return output
        else:
            reset_db = self.session_factory()
            try:
                active = self._governed_revisions(reset_db)
                self._require_active_target(
                    active["skill-taxonomy"],
                    manifest.target_revisions["skill-taxonomy"],
                    domain="skill-taxonomy",
                )
                reset_db.execute(delete(GovernedJobSkill))
                reset_db.execute(delete(GovernedJobSkillMention))
                reset_db.execute(delete(SkillCandidate))
                reset_db.commit()
            except Exception:
                reset_db.rollback()
                raise
            finally:
                reset_db.close()
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": None,
                "output": {
                    "generic_tag_mentions": 0,
                    "jobs_inspected": 0,
                    "jobs_with_terms": 0,
                    "jobs_without_preserved_terms": 0,
                    "match_existing_mentions": 0,
                    "mentions": 0,
                    "rejected_mentions": 0,
                    "review_candidate_mentions": 0,
                },
            }
            self.artifact_store.write(progress_path, progress)

        recovery_db = self.session_factory()
        try:
            recovered = SkillGovernanceRebuildInspector(recovery_db).recover()
        finally:
            recovery_db.rollback()
            recovery_db.close()

        last_cursor = progress.get("last_cursor")
        pending = tuple(
            item
            for item in recovered
            if last_cursor is None or item.cursor > str(last_cursor)
        )
        output_value = progress.get("output")
        if not isinstance(output_value, dict):
            raise CutoverInventoryError("Skill rebuild progress output is invalid")
        counters: dict[str, int] = {
            str(key): int(value) for key, value in output_value.items()
        }

        batch_size = 100
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            batch_db = self.session_factory()
            batch_counts = {key: 0 for key in counters}
            try:
                skill_governance = SkillGovernance(batch_db)
                for item in batch:
                    batch_counts["jobs_inspected"] += 1
                    if not item.terms:
                        batch_counts["jobs_without_preserved_terms"] += 1
                        continue
                    batch_counts["jobs_with_terms"] += 1
                    result = skill_governance.extract(
                        item.job_id,
                        item.terms,
                        SkillExtractionContext(
                            source=item.extraction_source,
                            provenance={
                                "method": "preserved-skill-cutover-rebuild",
                                "evidence_source": item.evidence_source,
                                "evidence_hash": item.evidence_hash,
                            },
                        ),
                    )
                    batch_counts["mentions"] += len(result.mentions)
                    for mention in result.mentions:
                        counter = {
                            "generic_tag": "generic_tag_mentions",
                            "match_existing": "match_existing_mentions",
                            "rejected": "rejected_mentions",
                            "review_candidate": "review_candidate_mentions",
                        }[mention.resolution]
                        batch_counts[counter] += 1
                batch_db.commit()
            except Exception:
                batch_db.rollback()
                raise
            finally:
                batch_db.close()

            for key, value in batch_counts.items():
                counters[key] += value
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": batch[-1].cursor,
                "output": counters,
            }
            self.artifact_store.write(progress_path, progress)

        completed = {
            "manifest_hash": manifest_hash,
            "status": "completed",
            "last_cursor": pending[-1].cursor if pending else last_cursor,
            "output": counters,
        }
        self.artifact_store.write(progress_path, completed)
        return cast(dict[str, object], counters)

    def _rebuild_embeddings(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        progress_path = checkpoint_dir / "rebuild-embeddings-progress.json"
        progress: dict[str, object]
        if progress_path.exists():
            progress = self.artifact_store.read(progress_path)
            if progress.get("manifest_hash") != manifest_hash:
                raise CutoverInventoryError(
                    "Embedding rebuild progress belongs to another manifest"
                )
            if progress.get("status") == "completed":
                output = progress.get("output")
                if not isinstance(output, dict):
                    raise CutoverInventoryError(
                        "Completed Embedding rebuild progress has no output"
                    )
                return output
        else:
            if self.embedding_model is None:
                raise CutoverInventoryError(
                    "Embedding rebuild requires an explicit embedding model"
                )
            if manifest.rebuild != self.rebuild:
                raise CutoverInventoryError(
                    "Embedding rebuild configuration no longer matches the manifest"
                )
            reset_db = self.session_factory()
            try:
                active = self._governed_revisions(reset_db)
                self._require_active_target(
                    active["canonical-job-taxonomy"],
                    manifest.target_revisions["canonical-job-taxonomy"],
                    domain="canonical-job-taxonomy",
                )
                self._require_active_target(
                    active["skill-taxonomy"],
                    manifest.target_revisions["skill-taxonomy"],
                    domain="skill-taxonomy",
                )
                reset_db.execute(delete(JobEmbedding))
                reset_db.commit()
            except Exception:
                reset_db.rollback()
                raise
            finally:
                reset_db.close()

            inventory_db = self.session_factory()
            try:
                eligible_job_ids = tuple(
                    inventory_db.scalars(
                        select(Job.id)
                        .where(Job.is_deleted.is_(False))
                        .order_by(Job.id.asc())
                    ).all()
                )
            finally:
                inventory_db.rollback()
                inventory_db.close()
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": None,
                "output": {
                    "coverage_ratio": 1.0 if not eligible_job_ids else 0.0,
                    "eligible_jobs": len(eligible_job_ids),
                    "embedding_dimensions": EMBEDDING_DIMENSIONS,
                    "embedding_model": manifest.rebuild.embedding_model,
                    "embedding_version": manifest.rebuild.embedding_version,
                    "ready_jobs": 0,
                },
            }
            self.artifact_store.write(progress_path, progress)

        if self.embedding_model is None:
            raise CutoverInventoryError(
                "Embedding rebuild requires an explicit embedding model"
            )
        inventory_db = self.session_factory()
        try:
            eligible_job_ids = tuple(
                inventory_db.scalars(
                    select(Job.id)
                    .where(Job.is_deleted.is_(False))
                    .order_by(Job.id.asc())
                ).all()
            )
        finally:
            inventory_db.rollback()
            inventory_db.close()

        output_value = progress.get("output")
        if not isinstance(output_value, dict):
            raise CutoverInventoryError("Embedding rebuild progress output is invalid")
        if int(output_value.get("eligible_jobs", -1)) != len(eligible_job_ids):
            raise CutoverInventoryError(
                "Embedding rebuild eligible Job count changed during resume"
            )
        ready_jobs = int(output_value.get("ready_jobs", 0))
        last_cursor = progress.get("last_cursor")
        pending = tuple(
            job_id
            for job_id in eligible_job_ids
            if last_cursor is None or str(job_id) > str(last_cursor)
        )
        indexer = EmbeddingIndexer(
            embedding_model=self.embedding_model,
            embedding_model_name=manifest.rebuild.embedding_model,
            embedding_version=manifest.rebuild.embedding_version,
        )

        batch_size = 100
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            batch_db = self.session_factory()
            try:
                jobs: dict[Any, Job] = {
                    job.id: job
                    for job in (
                        batch_db.query(Job)
                        .options(joinedload(Job.company))
                        .filter(Job.id.in_(batch))
                        .all()
                    )
                }
                for job_id in batch:
                    job = jobs.get(job_id)
                    if job is None:
                        raise CutoverInventoryError(
                            f"Eligible embedding Job disappeared: {job_id}"
                        )
                    document = self.embedding_document_builder.build_for_job(
                        batch_db,
                        job,
                    )
                    indexer.index(
                        batch_db,
                        job_id=job_id,
                        document=document,
                        trigger_event_type="cutover.rebuild_embeddings",
                        source_service="job-intelligence-cutover",
                    )
                batch_db.commit()
            except Exception:
                batch_db.rollback()
                raise
            finally:
                batch_db.close()

            ready_jobs += len(batch)
            coverage_ratio = (
                ready_jobs / len(eligible_job_ids) if eligible_job_ids else 1.0
            )
            output = {
                "coverage_ratio": coverage_ratio,
                "eligible_jobs": len(eligible_job_ids),
                "embedding_dimensions": EMBEDDING_DIMENSIONS,
                "embedding_model": manifest.rebuild.embedding_model,
                "embedding_version": manifest.rebuild.embedding_version,
                "ready_jobs": ready_jobs,
            }
            progress = {
                "manifest_hash": manifest_hash,
                "status": "running",
                "last_cursor": str(batch[-1]),
                "output": output,
            }
            self.artifact_store.write(progress_path, progress)

        output = {
            "coverage_ratio": (
                ready_jobs / len(eligible_job_ids) if eligible_job_ids else 1.0
            ),
            "eligible_jobs": len(eligible_job_ids),
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
            "embedding_model": manifest.rebuild.embedding_model,
            "embedding_version": manifest.rebuild.embedding_version,
            "ready_jobs": ready_jobs,
        }
        completed = {
            "manifest_hash": manifest_hash,
            "status": "completed",
            "last_cursor": str(pending[-1]) if pending else last_cursor,
            "output": output,
        }
        self.artifact_store.write(progress_path, completed)
        return output

    def _switch_authoritative_reads(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        self._verify_authority_pins(manifest)
        output: dict[str, object] = {
            "authority": "governed-projections",
            "read_seams": [
                "canonical-job-taxonomy",
                "company-industry",
                "embedding-document",
                "job-search",
                "skill-governance",
            ],
            "switch_required": False,
        }
        self.artifact_store.write(
            checkpoint_dir / "authoritative-read-switch.json",
            {
                "manifest_hash": manifest_hash,
                **output,
            },
        )
        return output

    def _cross_layer_verify(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        self._verify_authority_pins(manifest)
        try:
            switch = self.artifact_store.read(
                checkpoint_dir / "authoritative-read-switch.json"
            )
        except FileNotFoundError as exc:
            raise CutoverInventoryError(
                "Authoritative read verification is required before cross-layer verify"
            ) from exc
        if (
            switch.get("manifest_hash") != manifest_hash
            or switch.get("authority") != "governed-projections"
        ):
            raise CutoverInventoryError(
                "Authoritative read verification does not match this manifest"
            )

        current_preserved = self.collect_inventory().preserved_datasets
        preserved_mismatches: list[str] = []
        for name in sorted(set(manifest.preserved_datasets) | set(current_preserved)):
            expected = manifest.preserved_datasets.get(name)
            current = current_preserved.get(name)
            if (
                name == "governance-history"
                and expected is not None
                and current is not None
            ):
                if current.count < expected.count or (
                    current.count == expected.count
                    and current.content_hash != expected.content_hash
                ):
                    preserved_mismatches.append(name)
            elif expected != current:
                preserved_mismatches.append(name)
        if preserved_mismatches:
            raise CutoverInventoryError(
                "Preserved dataset verification failed: "
                + ", ".join(preserved_mismatches)
            )

        db = self.session_factory()
        try:
            job_ids = set(db.scalars(select(Job.id)).all())
            assignment_job_ids = set(
                db.scalars(
                    select(JobTaxonomyAssignment.job_id).where(
                        JobTaxonomyAssignment.is_current.is_(True)
                    )
                ).all()
            )
            review_job_ids = set(
                db.scalars(
                    select(JobTaxonomyReviewItem.job_id).where(
                        JobTaxonomyReviewItem.status == "active"
                    )
                ).all()
            )
            canonical_state_job_ids = assignment_job_ids | review_job_ids
            missing_canonical_state = job_ids - canonical_state_job_ids
            if missing_canonical_state:
                raise CutoverInventoryError(
                    "Canonical rebuild left Jobs without assignment or review: "
                    f"{len(missing_canonical_state)}"
                )

            eligible_jobs = (
                db.query(Job)
                .options(joinedload(Job.company))
                .filter(Job.is_deleted.is_(False))
                .order_by(Job.id.asc())
                .all()
            )
            freshness = EmbeddingIndexer(
                embedding_model=object(),
                embedding_model_name=manifest.rebuild.embedding_model,
                embedding_version=manifest.rebuild.embedding_version,
            )
            fresh_embeddings = 0
            for job in eligible_jobs:
                document = self.embedding_document_builder.build_for_job(db, job)
                if freshness.is_current(db.get(JobEmbedding, job.id), document):
                    fresh_embeddings += 1
            if fresh_embeddings != len(eligible_jobs):
                raise CutoverInventoryError(
                    "Embedding coverage is stale or incomplete: "
                    f"{fresh_embeddings}/{len(eligible_jobs)}"
                )
        finally:
            db.rollback()
            db.close()

        runtime = self._runtime_smoke_evidence(
            manifest=manifest,
            manifest_hash=manifest_hash,
            checkpoint_dir=checkpoint_dir,
        )
        checks = runtime["checks"]
        assert isinstance(checks, dict)
        output: dict[str, object] = {
            "canonical_state_jobs": len(canonical_state_job_ids),
            "eligible_jobs": len(eligible_jobs),
            "fresh_embeddings": fresh_embeddings,
            "preserved_datasets_verified": len(manifest.preserved_datasets),
            "runtime_smoke_checks": len(checks),
            "status": "verified",
        }
        self.artifact_store.write(
            checkpoint_dir / "cross-layer-verification.json",
            {
                "manifest_hash": manifest_hash,
                **output,
            },
        )
        return output

    def _reopen_writers(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        try:
            verification = self.artifact_store.read(
                checkpoint_dir / "cross-layer-verification.json"
            )
        except FileNotFoundError as exc:
            raise CutoverInventoryError(
                "Cross-layer verification is required before writers reopen"
            ) from exc
        if (
            verification.get("manifest_hash") != manifest_hash
            or verification.get("status") != "verified"
        ):
            raise CutoverInventoryError(
                "Cross-layer verification does not authorize writer reopening"
            )
        if self.writer_control is None:
            raise CutoverInventoryError(
                "Writer reopening requires an explicit operator-controlled adapter"
            )
        result = self.writer_control.reopen(
            writers=manifest.writers,
            observed_at=self.clock(),
        )
        if not isinstance(result, dict) or result.get("status") != "reopened":
            raise CutoverInventoryError("Writer control did not confirm reopening")
        states = result.get("writer_states")
        if (
            not isinstance(states, dict)
            or set(states) != set(manifest.writers)
            or any(state not in {"running", "stopped"} for state in states.values())
        ):
            raise CutoverInventoryError(
                "Writer reopening returned incomplete or uncertain evidence"
            )
        return {
            "status": "reopened",
            "writer_states": {writer: states[writer] for writer in sorted(states)},
        }

    def _verify_authority_pins(self, manifest: CutoverManifest) -> None:
        db = self.session_factory()
        try:
            active = self._governed_revisions(db)
            for domain in (
                "canonical-job-taxonomy",
                "company-industry",
                "skill-taxonomy",
            ):
                self._require_active_target(
                    active[domain],
                    manifest.target_revisions[domain],
                    domain=domain,
                )
            active_taxonomy = db.get(
                CanonicalJobTaxonomyActiveRevision,
                "canonical-job-taxonomy",
            )
            active_mapping = db.get(
                CanonicalJobTaxonomyActiveMappingRevision,
                "canonical-job-taxonomy-mapping",
            )
            mapping_identity = active["canonical-job-taxonomy-mapping"]
            mapping_target = manifest.target_revisions[
                "canonical-job-taxonomy-mapping-seed"
            ]
            if (
                active_taxonomy is None
                or active_mapping is None
                or mapping_identity is None
                or mapping_identity.release_key != mapping_target.release_key
                or active_mapping.taxonomy_revision_id != active_taxonomy.revision_id
            ):
                raise CutoverInventoryError(
                    "Canonical mapping authority does not match the manifest target"
                )
        finally:
            db.rollback()
            db.close()

    def _runtime_smoke_evidence(
        self,
        *,
        manifest: CutoverManifest,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        try:
            runtime = RuntimeSmokeEvidence.model_validate(
                self.artifact_store.read(checkpoint_dir / "runtime-smoke-evidence.json")
            )
        except FileNotFoundError as exc:
            raise CutoverInventoryError(
                "Explicit runtime smoke evidence is required before verification"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise CutoverInventoryError(
                "Runtime smoke evidence is incomplete or invalid"
            ) from exc
        if (
            runtime.manifest_hash != manifest_hash
            or runtime.application != manifest.application
        ):
            raise CutoverInventoryError(
                "Runtime smoke evidence is incomplete or belongs to another release"
            )

        embedding_phase = "rebuild_embeddings"
        embedding_ordinal = CUTOVER_PHASES.index(embedding_phase) + 1
        try:
            checkpoint = CutoverPhaseCheckpoint.model_validate(
                self.artifact_store.read(
                    checkpoint_dir / f"{embedding_ordinal:02d}-{embedding_phase}.json"
                )
            )
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise CutoverInventoryError(
                "Completed embedding checkpoint is required before runtime smoke"
            ) from exc
        if (
            checkpoint.ordinal != embedding_ordinal
            or checkpoint.phase != embedding_phase
            or checkpoint.status != "completed"
            or checkpoint.manifest_hash != manifest_hash
            or checkpoint.code_version != manifest.application.commit
            or checkpoint.output_hash != content_hash(checkpoint.output)
            or checkpoint.completed_at is None
        ):
            raise CutoverInventoryError(
                "Embedding checkpoint does not authorize runtime smoke evidence"
            )
        if runtime.observed_at < checkpoint.completed_at:
            raise CutoverInventoryError(
                "Runtime smoke evidence predates the completed embedding phase"
            )
        return runtime.model_dump(mode="json")

    @staticmethod
    def _require_target_revision(
        release_key: str,
        revision_hash: str,
        target: ReleaseIdentity,
    ) -> None:
        if release_key != target.release_key or revision_hash != target.content_hash:
            raise CutoverInventoryError(
                f"Materialized release does not match target {target.release_key}"
            )

    @staticmethod
    def _require_active_target(
        active: RevisionIdentity | None,
        target: ReleaseIdentity,
        *,
        domain: str,
    ) -> None:
        if (
            active is None
            or active.release_key != target.release_key
            or active.content_hash != target.content_hash
        ):
            raise CutoverInventoryError(
                f"Active {domain} release does not match the manifest target"
            )

    def _export_legacy_audit(
        self,
        *,
        manifest_hash: str,
        checkpoint_dir: Path,
    ) -> dict[str, object]:
        db = self.session_factory()
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            records: list[dict[str, object]] = []
            counts = {
                "company_legacy_industry": 0,
                "job_embedding": 0,
                "job_legacy_fields": 0,
                "legacy_job_skill": 0,
                "legacy_skill_mention": 0,
            }
            companies = db.execute(
                select(
                    Company.id,
                    Company.source_site,
                    Company.source_company_id,
                    Company.industry,
                ).order_by(Company.id)
            ).all()
            for company_id, source_site, source_company_id, industry in companies:
                records.append(
                    {
                        "kind": "company_legacy_industry",
                        "company_id": str(company_id),
                        "source_site": source_site,
                        "source_company_id": source_company_id,
                        "legacy_industry": industry,
                    }
                )
                counts["company_legacy_industry"] += 1

            jobs = db.execute(
                select(
                    Job.id,
                    Job.source_site,
                    Job.source_job_id,
                    Job.subcategory_id,
                    Job.source_classification_id,
                    Job.source_classification_name,
                    Job.source_subclassification_id,
                    Job.source_subclassification_name,
                    Job.employment_type,
                    Job.raw_data,
                ).order_by(Job.id)
            ).all()
            for row in jobs:
                records.append(
                    {
                        "kind": "job_legacy_fields",
                        "job_id": str(row.id),
                        "source_site": row.source_site,
                        "source_job_id": row.source_job_id,
                        "legacy_subcategory_id": (
                            str(row.subcategory_id)
                            if row.subcategory_id is not None
                            else None
                        ),
                        "source_classification_id": row.source_classification_id,
                        "source_classification_name": row.source_classification_name,
                        "source_subclassification_id": row.source_subclassification_id,
                        "source_subclassification_name": (
                            row.source_subclassification_name
                        ),
                        "legacy_employment_type": row.employment_type,
                        "raw_evidence_hash": content_hash(row.raw_data),
                    }
                )
                counts["job_legacy_fields"] += 1

            embeddings = db.execute(
                select(
                    JobEmbedding.job_id,
                    JobEmbedding.embedding_model,
                    JobEmbedding.embedding_dimensions,
                    JobEmbedding.embedding_version,
                    JobEmbedding.document_hash,
                    JobEmbedding.updated_at,
                ).order_by(JobEmbedding.job_id)
            ).all()
            for row in embeddings:
                records.append(
                    {
                        "kind": "job_embedding",
                        "job_id": str(row.job_id),
                        "embedding_model": row.embedding_model,
                        "embedding_dimensions": row.embedding_dimensions,
                        "embedding_version": row.embedding_version,
                        "document_hash": row.document_hash,
                        "updated_at": row.updated_at,
                    }
                )
                counts["job_embedding"] += 1

            job_skills = db.execute(
                select(
                    JobSkill.job_id,
                    JobSkill.skill_id,
                    JobSkill.source,
                    JobSkill.confidence,
                    JobSkill.created_at,
                ).order_by(JobSkill.job_id, JobSkill.skill_id)
            ).all()
            for row in job_skills:
                records.append(
                    {
                        "kind": "legacy_job_skill",
                        "job_id": str(row.job_id),
                        "skill_id": str(row.skill_id),
                        "source": row.source,
                        "confidence": row.confidence,
                        "created_at": row.created_at,
                    }
                )
                counts["legacy_job_skill"] += 1

            mentions = db.execute(
                select(
                    JobSkillMention.id,
                    JobSkillMention.job_id,
                    JobSkillMention.raw_name,
                    JobSkillMention.normalized_name,
                    JobSkillMention.resolution,
                    JobSkillMention.skill_id,
                    JobSkillMention.review_candidate_id,
                    JobSkillMention.generic_tag,
                    JobSkillMention.source,
                    JobSkillMention.confidence,
                    JobSkillMention.created_at,
                ).order_by(JobSkillMention.id)
            ).all()
            for row in mentions:
                records.append(
                    {
                        "kind": "legacy_skill_mention",
                        "mention_id": str(row.id),
                        "job_id": str(row.job_id),
                        "raw_name": row.raw_name,
                        "normalized_name": row.normalized_name,
                        "resolution": row.resolution,
                        "skill_id": str(row.skill_id) if row.skill_id else None,
                        "review_candidate_id": (
                            str(row.review_candidate_id)
                            if row.review_candidate_id
                            else None
                        ),
                        "generic_tag": row.generic_tag,
                        "source": row.source,
                        "confidence": row.confidence,
                        "created_at": row.created_at,
                    }
                )
                counts["legacy_skill_mention"] += 1
        finally:
            db.rollback()
            db.close()

        records.sort(
            key=lambda record: (
                str(record["kind"]),
                str(
                    record.get("company_id")
                    or record.get("job_id")
                    or record.get("mention_id")
                    or ""
                ),
                str(record.get("skill_id") or ""),
            )
        )
        payload = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
        artifact_path = checkpoint_dir / "legacy-audit.jsonl"
        artifact_hash = self.artifact_store.write_bytes(artifact_path, payload)
        output: dict[str, object] = {
            "artifact_hash": artifact_hash,
            "artifact_name": artifact_path.name,
            "manifest_hash": manifest_hash,
            "record_counts": counts,
        }
        self.artifact_store.write(
            checkpoint_dir / "legacy-audit-manifest.json",
            output,
        )
        return output

    @staticmethod
    def _target_revisions() -> dict[str, ReleaseIdentity]:
        taxonomy = json.loads(
            (DATA_DIRECTORY / "job_category_taxonomy.json").read_text(encoding="utf-8")
        )
        mapping = json.loads(
            (DATA_DIRECTORY / "job_source_taxonomy_mapping.json").read_text(
                encoding="utf-8"
            )
        )
        industry = json.loads(
            (DATA_DIRECTORY / "hsic_v2.json").read_text(encoding="utf-8")
        )
        skills = load_skill_seed_bundle()
        return {
            "canonical-job-taxonomy": ReleaseIdentity(
                release_key=str(taxonomy["release_key"]),
                content_hash=normalized_content_hash(taxonomy),
            ),
            "canonical-job-taxonomy-mapping-seed": ReleaseIdentity(
                release_key=str(mapping["release_key"]),
                content_hash=normalized_content_hash(mapping),
            ),
            "company-industry": ReleaseIdentity(
                release_key=str(industry["release_key"]),
                content_hash=str(industry["content_hash"]),
            ),
            "skill-taxonomy": ReleaseIdentity(
                release_key=str(skills["taxonomy"]["release_key"]),
                content_hash=skill_seed_content_hash(skills),
            ),
        }

    def _mutation_sentinel_hash(self) -> str:
        sentinel_tables = tuple(
            sorted(
                {
                    *RESET_ALLOWLIST,
                    "canonical_job_taxonomy_active_mapping_revisions",
                    "canonical_job_taxonomy_active_revisions",
                    "company_industry_active_revisions",
                    "companies",
                    "company_enrichment_runs",
                    "crawl_job_executions",
                    "crawl_job_listings",
                    "crawl_jobs",
                    "enrichment_runs",
                    "event_outbox",
                    "jobs",
                    "scheduler_runtime_heartbeats",
                    "skill_taxonomy_active_revisions",
                }
            )
        )
        db = self.session_factory()
        try:
            db.execute(text("SET TRANSACTION READ ONLY"))
            return self._combined_table_fingerprint(
                db,
                sentinel_tables,
            ).content_hash
        finally:
            db.rollback()
            db.close()

    @staticmethod
    def _status_count(
        db: Session,
        model: Any,
        active_statuses: tuple[str, ...],
    ) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.status.in_(active_statuses))
            )
            or 0
        )

    def _database_identity(self, db: Session) -> DatabaseIdentity:
        url = make_url(self.database_url)
        server_version = str(db.execute(text("SHOW server_version")).scalar_one())
        return DatabaseIdentity(
            host=url.host or "local-socket",
            port=url.port or 5432,
            database=url.database or "",
            server_version=server_version,
        )

    @staticmethod
    def _current_alembic_revision(db: Session) -> str:
        exists = db.execute(
            text("SELECT to_regclass('public.alembic_version')")
        ).scalar_one()
        if exists is None:
            return "unversioned"
        revisions = tuple(
            sorted(
                str(row[0])
                for row in db.execute(
                    text("SELECT version_num FROM alembic_version")
                ).all()
            )
        )
        return ",".join(revisions) if revisions else "unversioned"

    @staticmethod
    def _governed_revisions(
        db: Session,
    ) -> dict[str, RevisionIdentity | None]:
        active_specs = (
            (
                "canonical-job-taxonomy",
                CanonicalJobTaxonomyActiveRevision,
                "canonical-job-taxonomy",
                "revision_id",
            ),
            (
                "canonical-job-taxonomy-mapping",
                CanonicalJobTaxonomyActiveMappingRevision,
                "canonical-job-taxonomy-mapping",
                "mapping_revision_id",
            ),
            (
                "company-industry",
                CompanyIndustryActiveRevision,
                "company-industry",
                "revision_id",
            ),
            (
                "skill-taxonomy",
                SkillTaxonomyActiveRevision,
                "skill-taxonomy",
                "revision_id",
            ),
        )
        result: dict[str, RevisionIdentity | None] = {}
        for domain, model, singleton, revision_attribute in active_specs:
            active = db.get(model, singleton)
            if active is None:
                result[domain] = None
                continue
            revision = db.get(
                GovernanceRevision,
                getattr(active, revision_attribute),
            )
            if revision is None or revision.domain != domain:
                raise CutoverInventoryError(
                    f"Active {domain} revision has no matching governance identity"
                )
            result[domain] = RevisionIdentity(
                revision_id=cast(Any, revision.id),
                release_key=cast(str, revision.release_key),
                content_hash=cast(str, revision.content_hash),
            )
        return result

    @classmethod
    def _combined_table_fingerprint(
        cls,
        db: Session,
        table_names: Iterable[str],
    ) -> DatasetFingerprint:
        fingerprints = {name: cls._table_fingerprint(db, name) for name in table_names}
        return DatasetFingerprint(
            count=sum(item.count for item in fingerprints.values()),
            content_hash=content_hash(
                {
                    name: item.model_dump(mode="json")
                    for name, item in sorted(fingerprints.items())
                }
            ),
        )

    @classmethod
    def _table_fingerprint(
        cls,
        db: Session,
        table_name: str,
    ) -> DatasetFingerprint:
        table = Base.metadata.tables.get(table_name)
        if not isinstance(table, Table):
            raise CutoverInventoryError(f"Required table is unknown: {table_name}")
        primary_key = tuple(table.primary_key.columns)
        order_columns = primary_key or tuple(table.columns)
        statement = select(*tuple(table.columns)).order_by(*order_columns)
        return cls._fingerprint_statement(db, statement)

    @staticmethod
    def _fingerprint_statement(
        db: Session,
        statement: Select[Any],
    ) -> DatasetFingerprint:
        digest = hashlib.sha256()
        count = 0
        for row in db.execute(statement):
            digest.update(canonical_json_bytes(tuple(row)))
            digest.update(b"\n")
            count += 1
        return DatasetFingerprint(count=count, content_hash=digest.hexdigest())

    @staticmethod
    def _file_content_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
