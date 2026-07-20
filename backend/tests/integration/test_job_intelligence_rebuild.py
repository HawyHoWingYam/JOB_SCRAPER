from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.job_intelligence.cutover import (
    ApplicationIdentity,
    CutoverPhaseCheckpoint,
    JobIntelligenceCutover,
    PostgresCutoverEnvironment,
    RebuildIdentity,
    WriterStateEvidence,
)
from app.job_intelligence.cutover.artifacts import content_hash
from app.job_intelligence.cutover.backup import PostgresBackupArtifact
from app.job_intelligence.source_attributes import SourceJobAttributes
from app.models.company import Company
from app.models.company_industry import (
    CompanyIndustryAssignment,
    CompanyIndustryReviewItem,
)
from app.models.canonical_job_taxonomy import (
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_embedding import EMBEDDING_DIMENSIONS, JobEmbedding
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedJobSkillMention,
    SkillCandidate,
)
from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogCandidate,
    SourceCatalogRevision,
)
from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    DiscoveredCatalog,
)


SHA_A = "a" * 64


class AllStoppedWriterStateProvider:
    def collect(
        self,
        *,
        writers: tuple[str, ...],
        observed_at: datetime,
    ) -> tuple[WriterStateEvidence, ...]:
        return tuple(
            WriterStateEvidence(
                writer=writer,
                state="stopped",
                evidence_kind="container",
                evidence_ref=f"integration-fixture:{writer}",
                observed_at=observed_at,
            )
            for writer in writers
        )


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.documents: list[str] = []

    def encode(self, document_text: str, *, normalize_embeddings: bool):
        assert normalize_embeddings is True
        self.documents.append(document_text)
        return [0.01] * EMBEDDING_DIMENSIONS


class FakeBackupAdapter:
    def create_and_restore(
        self,
        *,
        source_database_url: str,
        restore_database_url: str,
        backup_id: str,
        checkpoint_dir: Path,
    ) -> PostgresBackupArtifact:
        assert source_database_url.endswith("job_intelligence_product_surfaces_test")
        assert restore_database_url.endswith("job_intelligence_cutover_restore")
        payload = b"fixture-postgres-custom-dump"
        artifact_path = checkpoint_dir / f"{backup_id}.dump"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(payload)
        return PostgresBackupArtifact(
            artifact_name=artifact_path.name,
            artifact_hash=hashlib.sha256(payload).hexdigest(),
            pg_dump_version="pg_dump (PostgreSQL) 15.8",
            pg_restore_version="pg_restore (PostgreSQL) 15.8",
        )


class RecordingWriterControl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def reopen(
        self,
        *,
        writers: tuple[str, ...],
        observed_at: datetime,
    ) -> dict[str, object]:
        assert observed_at == datetime(2026, 7, 20, 8, 31, tzinfo=timezone.utc)
        self.calls.append(writers)
        return {
            "status": "reopened",
            "writer_states": {writer: "running" for writer in writers},
        }


def _publish_fixture_catalogs(db) -> None:
    mapping = json.loads(
        (
            Path(__file__).parents[2]
            / "app"
            / "data"
            / "job_source_taxonomy_mapping.json"
        ).read_text(encoding="utf-8")
    )
    entries_by_source: dict[str, list[dict[str, object]]] = {}
    for entry in mapping["entries"]:
        entries_by_source.setdefault(str(entry["source_site"]), []).append(entry)

    for source_site, entries in sorted(entries_by_source.items()):
        nodes = tuple(
            CatalogNodeSnapshot(
                node_key=str(entry["source_classification_id"]),
                source_site=source_site,
                classification_id=str(entry["source_classification_id"]),
                native_id=str(entry["source_classification_id"]).split(":", 1)[1],
                native_label=str(entry["source_label"]),
                parent_node_key=None,
                native_path=(str(entry["source_label"]),),
                depth=0,
                selectable=True,
                supports_exact=False,
                supports_subtree=False,
                queryable=False,
                alias_of_node_key=None,
                query_semantics_hash=None,
            )
            for entry in entries
        )
        catalog = DiscoveredCatalog(
            source_site=source_site,
            nodes=nodes,
            capabilities=CatalogScopeCapabilities(
                supports_all_scope=False,
                all_scope_root_node_keys=(),
            ),
            source_payload={"fixture_source": source_site},
            provenance={"fixture": True},
        )
        candidate = SourceCatalogCandidate(
            source_site=source_site,
            fingerprint=catalog.fingerprint,
            normalized_payload=catalog.normalized_payload(),
            source_payload=dict(catalog.source_payload),
            provenance=dict(catalog.provenance),
            diff={},
            validation_summary={"valid": True},
            state="published",
        )
        db.add(candidate)
        db.flush()
        revision = SourceCatalogRevision(
            source_site=source_site,
            sequence=1,
            fingerprint=catalog.fingerprint,
            normalized_payload=catalog.normalized_payload(),
            source_payload=dict(catalog.source_payload),
            provenance=dict(catalog.provenance),
            candidate_id=candidate.id,
            publication_metadata={"fixture": True},
            published_by="integration-fixture",
        )
        db.add(revision)
        db.flush()
        db.add(
            SourceCatalogActiveRevision(
                source_site=source_site,
                revision_id=revision.id,
                updated_by="integration-fixture",
            )
        )
    db.commit()


def test_postgres_inventory_separates_preserved_core_from_legacy_projection(
    tmp_path: Path,
) -> None:
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("Cutover integration tests require a dedicated *_test database")

    engine = create_engine(database_url)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.drop_all(engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    db = session_factory()
    try:
        fixture = json.loads(
            (
                Path(__file__).parents[1]
                / "fixtures"
                / "job_intelligence_cutover_legacy.json"
            ).read_text(encoding="utf-8")
        )
        assert fixture["schema_version"] == 1
        assert fixture["anonymized"] is True
        company = Company(**fixture["company"])
        db.add(company)
        db.flush()
        job_payload, unsupported_payload = fixture["jobs"]
        posted_date = datetime(2026, 7, 18, tzinfo=timezone.utc)
        job = Job(company_id=company.id, posted_date=posted_date, **job_payload)
        unsupported_job = Job(
            company_id=company.id,
            posted_date=posted_date,
            **unsupported_payload,
        )
        db.add_all([job, unsupported_job])
        db.commit()
        _publish_fixture_catalogs(db)

        embedding_model = FakeEmbeddingModel()
        writer_control = RecordingWriterControl()
        environment = PostgresCutoverEnvironment(
            session_factory=session_factory,
            database_url=database_url,
            application=ApplicationIdentity(
                commit="0123456789abcdef",
                image="job-scraper@sha256:test-image",
                configuration_hash=SHA_A,
            ),
            target_schema_revision="20260719_160000",
            rebuild=RebuildIdentity(
                source_attributes="v1",
                canonical_taxonomy="canonical-job-taxonomy-v1",
                company_industry="hsic-v2.0-2026-07-19",
                skills="skills-2026-07-19-v1",
                embedding_model="all-MiniLM-L6-v2",
                embedding_version=1,
            ),
            writer_state_provider=AllStoppedWriterStateProvider(),
            embedding_model=embedding_model,
            backup_adapter=FakeBackupAdapter(),
            restore_engine_factory=lambda _database_url: engine,
            writer_control=writer_control,
            sleeper=lambda _seconds: None,
            clock=lambda: datetime(2026, 7, 20, 8, 31, tzinfo=timezone.utc),
        )

        first = environment.collect_inventory()
        assert first.database.database.endswith("_test")
        assert first.schema_identity.current_revision == "unversioned"
        assert first.preserved_datasets["jobs-core"].count == 2
        assert first.preserved_datasets["companies-core"].count == 1
        assert first.governed_revisions == {
            "canonical-job-taxonomy": None,
            "canonical-job-taxonomy-mapping": None,
            "company-industry": None,
            "skill-taxonomy": None,
        }
        backup = environment.create_and_verify_backup(
            backup_id="backup-20260720-0830",
            restore_database_url=(
                "postgresql://admin:dev_password@postgres-db:5432/"
                "job_intelligence_cutover_restore"
            ),
            checkpoint_dir=tmp_path / "backup",
            expected_fingerprints=dict(first.preserved_datasets),
        )
        assert backup.backup_id == "backup-20260720-0830"
        assert backup.restore_database == "job_intelligence_cutover_restore"
        assert backup.restored_fingerprints == first.preserved_datasets
        assert backup.artifact_name == "backup-20260720-0830.dump"
        inspections = environment.inspect_rebuild()
        after_inspection = environment.collect_inventory()
        assert after_inspection == first
        assert inspections["source_attributes"]["jobs_inspected"] == 2
        assert inspections["canonical_taxonomy"]["jobs_inspected"] == 2
        assert inspections["company_industry"]["companies_inspected"] == 1
        assert inspections["skills"] == {
            "available": False,
            "mode": "read-only",
            "unavailable_code": "SKILL_TAXONOMY_NOT_ACTIVE",
        }
        assert inspections["embeddings"] == {
            "coverage_ratio": 0.0,
            "current": 0,
            "eligible": 2,
            "missing": 2,
            "mode": "read-only",
        }
        manifest = JobIntelligenceCutover(
            environment=environment,
            clock=lambda: datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
        ).inventory(output=tmp_path / "manifest.json")
        audit_output = environment.run_cutover_phase(
            phase="legacy_audit_snapshot",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert audit_output["record_counts"] == {
            "company_legacy_industry": 1,
            "job_embedding": 0,
            "job_legacy_fields": 2,
            "legacy_job_skill": 0,
            "legacy_skill_mention": 0,
        }
        audit_path = tmp_path / "legacy-audit.jsonl"
        assert audit_output["artifact_name"] == audit_path.name
        assert len(audit_output["artifact_hash"]) == 64
        records = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
        ]
        assert [record["kind"] for record in records] == [
            "company_legacy_industry",
            "job_legacy_fields",
            "job_legacy_fields",
        ]
        serialized_audit = audit_path.read_text(encoding="utf-8").lower()
        assert "preserved description" not in serialized_audit
        assert "raw_data" not in serialized_audit
        assert "classifications" not in serialized_audit
        seed_output = environment.run_cutover_phase(
            phase="schema_expand_and_seed_revisions",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        replay_output = environment.run_cutover_phase(
            phase="schema_expand_and_seed_revisions",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert replay_output == seed_output
        assert set(seed_output["active_revisions"]) == {
            "canonical-job-taxonomy",
            "canonical-job-taxonomy-mapping",
            "company-industry",
            "skill-taxonomy",
        }
        current_after_seed = environment.collect_inventory()
        assert all(
            current_after_seed.governed_revisions[domain] is not None
            for domain in (
                "canonical-job-taxonomy",
                "canonical-job-taxonomy-mapping",
                "company-industry",
                "skill-taxonomy",
            )
        )
        source_output = environment.run_cutover_phase(
            phase="rebuild_source_classification_paths",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        source_replay = environment.run_cutover_phase(
            phase="rebuild_source_classification_paths",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert source_replay == source_output
        assert source_output == {
            "ambiguous_jobs": 0,
            "changed_jobs": 1,
            "classification_paths": 1,
            "employment_type_assignments": 1,
            "jobs_inspected": 2,
            "projected_jobs": 1,
            "provenance_limited_jobs": 1,
            "unrecoverable_jobs": 1,
        }
        employment_output = environment.run_cutover_phase(
            phase="rebuild_employment_types",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert employment_output == {
            "employment_type_assignments": 1,
            "jobs_with_projection": 1,
            "mapped_labels": 1,
            "source_labels": 1,
            "unknown_labels": 0,
        }
        canonical_output = environment.run_cutover_phase(
            phase="rebuild_canonical_job_taxonomy",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        canonical_replay = environment.run_cutover_phase(
            phase="rebuild_canonical_job_taxonomy",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert canonical_replay == canonical_output
        assert canonical_output == {
            "assigned_jobs": 0,
            "jobs_inspected": 2,
            "jobs_without_source_attributes": 1,
            "review_jobs": 2,
        }
        reviews = db.query(JobTaxonomyReviewItem).all()
        assert {review.job_id: review.reasons for review in reviews} == {
            job.id: ["source_catalog_provenance_missing"],
            unsupported_job.id: ["source_classification_paths_missing"],
        }
        assert {review.status for review in reviews} == {"active"}
        assert db.query(JobTaxonomyAssignment).count() == 0
        assert (
            db.query(EventOutbox)
            .filter(EventOutbox.event_type == "job.canonical_taxonomy_changed")
            .count()
            == 2
        )
        industry_output = environment.run_cutover_phase(
            phase="rebuild_company_industries",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        industry_replay = environment.run_cutover_phase(
            phase="rebuild_company_industries",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert industry_replay == industry_output
        assert industry_output == {
            "assigned_companies": 0,
            "companies_inspected": 1,
            "no_evidence_companies": 0,
            "review_companies": 1,
        }
        industry_review = db.query(CompanyIndustryReviewItem).one()
        assert industry_review.company_id == company.id
        assert industry_review.reason == "manual_evidence"
        assert industry_review.provenance["method"] == (
            "legacy-company-industry-cutover"
        )
        assert db.query(CompanyIndustryAssignment).count() == 0
        assert (
            db.query(EventOutbox)
            .filter(EventOutbox.event_type == "company.industry_review_changed")
            .count()
            == 1
        )
        skill_output = environment.run_cutover_phase(
            phase="rebuild_skill_state",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        skill_replay = environment.run_cutover_phase(
            phase="rebuild_skill_state",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert skill_replay == skill_output
        assert skill_output == {
            "generic_tag_mentions": 0,
            "jobs_inspected": 2,
            "jobs_with_terms": 1,
            "jobs_without_preserved_terms": 1,
            "match_existing_mentions": 1,
            "mentions": 2,
            "rejected_mentions": 0,
            "review_candidate_mentions": 1,
        }
        mentions = (
            db.query(GovernedJobSkillMention)
            .order_by(GovernedJobSkillMention.normalized_key)
            .all()
        )
        assert [(item.raw_name, item.resolution) for item in mentions] == [
            ("Novel Stack", "review_candidate"),
            ("Python", "match_existing"),
        ]
        assert db.query(GovernedJobSkill).count() == 1
        candidate = db.query(SkillCandidate).one()
        assert candidate.canonical_raw_name == "Novel Stack"
        assert candidate.status == "pending"
        assert (
            db.query(EventOutbox)
            .filter(EventOutbox.event_type == "job.skill_projection_changed")
            .count()
            == 1
        )
        embedding_output = environment.run_cutover_phase(
            phase="rebuild_embeddings",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        embedding_replay = environment.run_cutover_phase(
            phase="rebuild_embeddings",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert embedding_replay == embedding_output
        assert embedding_output == {
            "coverage_ratio": 1.0,
            "eligible_jobs": 2,
            "embedding_dimensions": EMBEDDING_DIMENSIONS,
            "embedding_model": "all-MiniLM-L6-v2",
            "embedding_version": 1,
            "ready_jobs": 2,
        }
        embedding = db.get(JobEmbedding, job.id)
        assert embedding is not None
        assert embedding.embedding_model == "all-MiniLM-L6-v2"
        assert embedding.embedding_version == 1
        assert embedding.embedding_dimensions == EMBEDDING_DIMENSIONS
        assert "Skills: Python" in embedding.document_text
        assert "Novel Stack" not in embedding.document_text
        assert len(embedding_model.documents) == 2
        assert embedding.document_text in embedding_model.documents
        assert (
            db.query(EventOutbox)
            .filter(EventOutbox.event_type == "job.embedded")
            .count()
            == 2
        )
        switch_output = environment.run_cutover_phase(
            phase="switch_authoritative_reads",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert switch_output == {
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
        embedding_checkpoint_output = {"embedding": embedding_output}
        environment.artifact_store.write(
            tmp_path / "11-rebuild_embeddings.json",
            CutoverPhaseCheckpoint(
                ordinal=11,
                phase="rebuild_embeddings",
                status="completed",
                manifest_hash=SHA_A,
                code_version=manifest.application.commit,
                input_hash="b" * 64,
                output_hash=content_hash(embedding_checkpoint_output),
                output=embedding_checkpoint_output,
                started_at=datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc),
                completed_at=datetime(2026, 7, 20, 8, 31, tzinfo=timezone.utc),
            ).model_dump(mode="json"),
        )
        environment.artifact_store.write(
            tmp_path / "runtime-smoke-evidence.json",
            {
                "schema_version": 1,
                "manifest_hash": SHA_A,
                "application": manifest.application.model_dump(mode="json"),
                "status": "passed",
                "checks": {
                    "backend_api": True,
                    "embedding": True,
                    "frontend": True,
                    "governance": True,
                    "search": True,
                },
                "observed_at": "2026-07-20T08:31:00Z",
            },
        )
        verify_output = environment.run_cutover_phase(
            phase="cross_layer_verify",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert verify_output == {
            "canonical_state_jobs": 2,
            "eligible_jobs": 2,
            "fresh_embeddings": 2,
            "preserved_datasets_verified": len(first.preserved_datasets),
            "runtime_smoke_checks": 5,
            "status": "verified",
        }
        reopen_output = environment.run_cutover_phase(
            phase="reopen_writers",
            manifest=manifest,
            manifest_hash=SHA_A,
            checkpoint_dir=tmp_path,
        )
        assert reopen_output["status"] == "reopened"
        assert set(reopen_output["writer_states"]) == set(manifest.writers)
        assert writer_control.calls == [manifest.writers]
        projection_db = session_factory()
        try:
            source_view = SourceJobAttributes(projection_db).get(job.id)
            assert [
                node.source_classification_id
                for path in source_view.source_classification_paths
                for node in path.nodes
            ] == ["jobsdb:6281"]
            assert [item.code for item in source_view.employment_types] == ["full_time"]
            assert source_view.source_classification_paths[0].provenance_limited
        finally:
            projection_db.close()

        job.description = "Changed preserved description"
        db.commit()
        second = environment.collect_inventory()
        assert (
            second.preserved_datasets["jobs-core"].content_hash
            != first.preserved_datasets["jobs-core"].content_hash
        )

        preserved_hash = second.preserved_datasets["jobs-core"].content_hash
        legacy_hash = second.legacy_projections["legacy-job-fields"].content_hash
        job.employment_type = "Contract"
        db.commit()
        third = environment.collect_inventory()
        assert third.preserved_datasets["jobs-core"].content_hash == preserved_hash
        assert third.legacy_projections["legacy-job-fields"].content_hash != legacy_hash

        quiescence = environment.collect_quiescence(observation_seconds=0)
        assert quiescence.database_sentinel.before_hash == (
            quiescence.database_sentinel.after_hash
        )
        # The first projection emits one event; checkpoint replay must not
        # duplicate it. Writer reopening remains blocked until it is drained.
        assert quiescence.pending_outbox == 7
        assert quiescence.active_runs == {
            "company_enrichment_runs": 0,
            "crawl_executions": 0,
            "crawl_jobs": 0,
            "enrichment_runs": 0,
            "scheduler_dispatches": 0,
        }
        assert {item.state for item in quiescence.writers} == {"stopped"}
    finally:
        db.close()
        Base.metadata.drop_all(engine, checkfirst=True)
        engine.dispose()
