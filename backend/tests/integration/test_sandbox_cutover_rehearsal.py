from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

import pytest
import redis
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import Base
import app.models  # noqa: F401
from app.job_intelligence.sandbox_cutover import (
    RedisRuntimeStateCleaner,
    SandboxCutover,
    clear_database,
    verify_target_state,
)
from app.job_intelligence.source_attributes import EMPLOYMENT_TYPE_SEEDS
from app.messaging.topics import (
    STREAM_JOB_INGEST,
    STREAM_JOB_INGEST_DEAD_LETTER,
)
from app.models.company import Company
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentSourceTaxonomyMapping,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.models.governance import GovernanceAuditEvent, GovernanceIdempotencyRecord
from app.models.job import Job
from app.models.job_embedding import JobEmbedding
from app.models.source_classification import SourceClassification
from app.models.source_job_attributes import (
    JobEmploymentType,
    JobSourceAttributeProjection,
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
    JobSourceEmploymentLabel,
)
from scripts.bootstrap_db import bootstrap_database


def _test_resources():
    database_url = os.getenv("SANDBOX_CUTOVER_TEST_DATABASE_URL", "").strip()
    redis_url = os.getenv("SANDBOX_CUTOVER_TEST_REDIS_URL", "").strip()
    if not database_url or not redis_url:
        pytest.skip("sandbox cutover disposable PostgreSQL/Redis URLs are not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        raise RuntimeError("SANDBOX_CUTOVER_TEST_DATABASE_URL must end in _test")
    redis_database = make_url(redis_url).database
    if redis_database in (None, "", "0"):
        raise RuntimeError("SANDBOX_CUTOVER_TEST_REDIS_URL must use a non-zero database")
    return create_engine(database_url), redis.Redis.from_url(redis_url, decode_responses=True)


def _seed_retained_and_runtime_cycle(engine) -> dict[str, str]:
    now = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
    with Session(engine) as db:
        company = Company(
            company_id="offertoday:company-1",
            source_site="offertoday",
            source_company_id="company-1",
            name="Retained Company",
            ai_description="Retained company enrichment",
        )
        job = Job(
            job_id="offertoday:job-1",
            source_site="offertoday",
            source_job_id="job-1",
            company=company,
            title="Retained Engineer",
            description="Retained detail",
            ai_summary="Retained AI enrichment",
            ai_enriched_at=now,
        )
        db.add_all((company, job))
        db.flush()
        source_root = SourceClassification(
            source_site="offertoday",
            classification_id="offertoday:100",
            native_id="100",
            label="Technology",
            depth=0,
            is_top_level=True,
            is_active=True,
            query_metadata={"query_code": 100},
            first_observed_at=now,
            last_observed_at=now,
        )
        db.add(source_root)
        db.add_all(
            (
                CurrentTaxonomyNodeRecord(
                    taxonomy="company_industry", code="technology", parent_code=None,
                    level="section", labels={"en": "Technology"}, sort_order=1,
                    is_assignable=True, is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="skill", code="python", parent_code=None,
                    level="skill", labels={"en": "Python"}, sort_order=1,
                    is_assignable=True, is_active=True,
                ),
            )
        )
        db.flush()
        candidate_id = uuid4()
        mention_id = uuid4()
        audit_id = uuid4()
        db.add_all(
            (
                CurrentTaxonomyAliasRecord(
                    taxonomy="skill", node_code="python", alias="Py",
                    normalized_alias="py",
                ),
                CurrentCompanyIndustryAssignment(
                    company_id=company.id, taxonomy="company_industry",
                    taxonomy_code="technology", method="source", provenance={},
                    evidence_hash="b" * 64,
                    breadcrumb={"section": {"code": "technology", "label": "Technology"}},
                    is_primary=True, primary_basis="source", captured_at=now,
                ),
                CurrentJobSkillAssignment(
                    job_id=job.id, skill_code="python", taxonomy="skill",
                    source="ai", confidence=0.9, provenance={}, mention_count=1,
                    updated_at=now,
                ),
                CurrentSkillCandidate(
                    id=candidate_id, taxonomy="skill", normalized_key="new tool",
                    canonical_raw_name="New Tool", raw_variants=["New Tool"],
                    occurrence_count=5, distinct_job_count=5, evidence_summary={},
                    first_seen_at=now, last_seen_at=now, created_at=now, updated_at=now,
                ),
                CurrentSourceTaxonomyMapping(
                    taxonomy="company_industry", source_site="offertoday",
                    source_key="offertoday:100", target_code="technology",
                    source_label="Technology", role="deterministic", evidence={},
                ),
                GovernanceAuditEvent(
                    id=audit_id, domain="skill", subject_type="candidate",
                    subject_id=str(candidate_id), action="auto-create",
                    actor="local-operator", command_hash="c" * 64,
                    idempotency_key="candidate:auto-create", before_summary={},
                    after_summary={"skill_code": "python", "revision_id": "remove"},
                    evidence_refs=[], correlation_id="cutover-test", created_at=now,
                ),
                JobEmbedding(
                    job_id=job.id, document_text="Retained Engineer",
                    document_hash="d" * 64, embedding=[0.0] * 384,
                    embedding_dimensions=384, updated_at=now,
                ),
                JobSourceAttributeProjection(
                    job_id=job.id, source_site="offertoday",
                    evidence_hash="e" * 64, captured_at=now,
                ),
            )
        )
        db.flush()
        db.add_all(
            (
                CurrentJobSkillMention(
                    id=mention_id, job_id=job.id, taxonomy="skill",
                    raw_name="New Tool", normalized_key="new tool",
                    resolution="candidate", status="active", candidate_id=candidate_id,
                    source="ai-extraction", confidence=0.8, provenance={},
                    evidence_hash="f" * 64, created_at=now, updated_at=now,
                ),
                GovernanceIdempotencyRecord(
                    domain="skill", idempotency_key="candidate:auto-create",
                    command_hash="c" * 64, audit_event_id=audit_id,
                    result_payload={"skill_code": "python", "version": 9},
                    created_at=now,
                ),
                JobSourceEmploymentLabel(
                    job_id=job.id, source_site="offertoday", source_order=0,
                    raw_label="Full-time", normalized_lookup_key="full time",
                    mapped_type_code="full_time", provenance={}, captured_at=now,
                ),
                JobEmploymentType(
                    job_id=job.id, employment_type_code="full_time",
                    evidence_label_ids=[], provenance={}, created_at=now,
                ),
            )
        )
        path = JobSourceClassificationPath(
            job_id=job.id, source_site="offertoday", source_order=0,
            path_fingerprint="1" * 64, is_primary=False, provenance={}, captured_at=now,
        )
        path.nodes = [
            JobSourceClassificationPathNode(
                source_site="offertoday", source_position=0, native_depth=0,
                source_classification_id="offertoday:100", native_id="100",
                label="Technology",
            )
        ]
        db.add(path)
        company_id = str(company.id)
        job_id = str(job.id)
        db.commit()

    plan_id = uuid4()
    crawl_job_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO crawl_dispatch_plans "
                "(id,state,source_site,crawl_phase,trigger_kind,authored_scope,resolved_scope,"
                "listing_settings,detail_settings,readiness,detail_target_count,plan_fingerprint,"
                "confirmation_required,prepared_by,prepared_at,expires_at) VALUES "
                "(:id,'prepared','offertoday','listing','one_off','{}','{}','{}',NULL,'{}',0,"
                ":fingerprint,false,'cutover-test',:prepared,:expires)"
            ),
            {"id": plan_id, "fingerprint": "2" * 64, "prepared": now,
             "expires": now + timedelta(hours=1)},
        )
        connection.execute(
            text(
                "INSERT INTO crawl_jobs "
                "(id,source_site,trigger_type,dispatch_plan_id,dispatch_plan_fingerprint,status,"
                "request_payload,queued_at,created_at,updated_at) VALUES "
                "(:id,'offertoday','manual',:plan,:fingerprint,'queued','{}',:now,:now,:now)"
            ),
            {"id": crawl_job_id, "plan": plan_id, "fingerprint": "2" * 64, "now": now},
        )
        connection.execute(
            text(
                "UPDATE crawl_dispatch_plans SET state='consumed', consumed_at=:now, "
                "crawl_job_id=:job WHERE id=:plan"
            ),
            {"now": now, "job": crawl_job_id, "plan": plan_id},
        )
    return {"company_id": company_id, "job_id": job_id}


def test_disposable_postgres_and_redis_cutover_passes_twice(tmp_path: Path) -> None:
    engine, redis_client = _test_resources()
    try:
        for attempt in (1, 2):
            with engine.begin() as connection:
                connection.execute(text("DROP SCHEMA public CASCADE"))
                connection.execute(text("CREATE SCHEMA public"))
            bootstrap_database(db_engine=engine, metadata=Base.metadata)
            identities = _seed_retained_and_runtime_cycle(engine)
            redis_client.flushdb()
            redis_client.xadd(STREAM_JOB_INGEST, {"data": "pending"})
            redis_client.xgroup_create(STREAM_JOB_INGEST, "cutover-test", id="0")
            redis_client.xreadgroup(
                "cutover-test", "consumer", {STREAM_JOB_INGEST: ">"}, count=1
            )
            redis_client.xadd(STREAM_JOB_INGEST_DEAD_LETTER, {"data": "dead"})

            artifact = tmp_path / f"retained-{attempt}.json"
            cutover = SandboxCutover(source_engine=engine, metadata=Base.metadata)
            before = cutover.export_retained(artifact)
            assert before.table_counts["companies"] == 1
            assert before.table_counts["jobs"] == 1
            assert "job_embeddings" not in before.table_counts
            RedisRuntimeStateCleaner(redis_client).clear()
            clear_database(db_engine=engine, confirmed=True)
            bootstrap_database(db_engine=engine, metadata=Base.metadata)
            cutover.import_retained(artifact, target_engine=engine)
            verification = cutover.verify_retained(artifact, target_engine=engine)
            target = verify_target_state(db_engine=engine, metadata=Base.metadata)

            assert verification.matched, verification.mismatches
            assert target.clean, target.issues
            assert not redis_client.exists(STREAM_JOB_INGEST)
            assert not redis_client.exists(STREAM_JOB_INGEST_DEAD_LETTER)
            with engine.connect() as connection:
                assert str(connection.scalar(text("SELECT id FROM companies"))) == identities["company_id"]
                assert str(connection.scalar(text("SELECT id FROM jobs"))) == identities["job_id"]
                registry_rows = connection.execute(
                    text(
                        "SELECT code, label, sort_order FROM employment_types "
                        "ORDER BY sort_order"
                    )
                ).tuples().all()
                assert registry_rows == list(EMPLOYMENT_TYPE_SEEDS)
            cutover.delete_artifact_after_verification(artifact, verification)
            assert not artifact.exists()
    finally:
        redis_client.flushdb()
        redis_client.close()
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()
