from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import UUID as SQLAlchemyUUID
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles

from app.api.stats import (
    get_skill_dashboard_bucket,
    get_skill_stats,
    router,
)
from app.database import Base, get_db
from app.models.app_runtime_settings import AppRuntimeSettings
from app.models.company import Company
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyNodeRecord,
)
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
from app.models.manual_job import ManualJobEvidence
from app.models.source_job_attributes import JobSourceAttributeProjection


@compiles(SQLAlchemyUUID, "sqlite")
@compiles(PostgreSQLUUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def stats_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    tables = (
        Company.__table__,
        Job.__table__,
        ManualJobEvidence.__table__,
        JobSourceAttributeProjection.__table__,
        CurrentTaxonomyNodeRecord.__table__,
        CurrentJobSkillAssignment.__table__,
        CurrentSkillCandidate.__table__,
        CurrentJobSkillMention.__table__,
        AppRuntimeSettings.__table__,
        EnrichmentRun.__table__,
        EnrichmentRunItem.__table__,
    )
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _company(db) -> Company:
    company = Company(
        company_id=f"company-{uuid4()}",
        source_site="jobsdb",
        source_company_id=f"source-company-{uuid4()}",
        name="Stats Test Company",
    )
    db.add(company)
    db.flush()
    return company


def _job(
    db,
    company: Company,
    *,
    enriched: bool = False,
    deleted: bool = False,
    ready: bool = False,
    source_site: str = "jobsdb",
) -> Job:
    source_id = str(uuid4())
    job = Job(
        job_id=f"{source_site}:{source_id}",
        source_site=source_site,
        source_job_id=source_id,
        company_id=company.id,
        title=f"Stats Job {source_id}",
        description="Enough evidence for a focused stats test.",
        ai_enriched_at=datetime.now(UTC) if enriched else None,
        is_deleted=deleted,
    )
    db.add(job)
    db.flush()
    if ready:
        db.add(
            JobSourceAttributeProjection(
                job_id=job.id,
                source_site=source_site,
                evidence_hash="s" * 64,
            )
        )
        db.flush()
    return job


def _node(
    taxonomy: str,
    code: str,
    label: str,
    level: str,
    *,
    parent_code: str | None = None,
    assignable: bool = False,
    active: bool = True,
) -> CurrentTaxonomyNodeRecord:
    return CurrentTaxonomyNodeRecord(
        taxonomy=taxonomy,
        code=code,
        parent_code=parent_code,
        level=level,
        labels={"en": label},
        sort_order=0,
        is_assignable=assignable,
        is_active=active,
    )


def _assign_skill(db, job: Job, code: str) -> None:
    db.add(
        CurrentJobSkillAssignment(
            job_id=job.id,
            taxonomy="skill",
            skill_code=code,
            source="ai_enrichment",
            provenance={"source": "stats-test"},
            mention_count=1,
        )
    )


def _candidate(db, name: str, distinct_jobs: int) -> CurrentSkillCandidate:
    candidate = CurrentSkillCandidate(
        taxonomy="skill",
        normalized_key=name.casefold(),
        canonical_raw_name=name,
        raw_variants=[name],
        occurrence_count=distinct_jobs,
        distinct_job_count=distinct_jobs,
        evidence_summary={"distinct_jobs": distinct_jobs},
    )
    db.add(candidate)
    db.flush()
    return candidate


def _candidate_mention(db, job: Job, candidate: CurrentSkillCandidate) -> None:
    db.add(
        CurrentJobSkillMention(
            job_id=job.id,
            taxonomy="skill",
            raw_name=candidate.canonical_raw_name,
            normalized_key=candidate.normalized_key,
            resolution="candidate",
            status="active",
            candidate_id=candidate.id,
            source="ai-extraction",
            provenance={"source": "stats-test"},
            evidence_hash=uuid4().hex * 2,
        )
    )


@pytest.mark.asyncio
async def test_skill_stats_use_enriched_population_stable_codes_and_candidate_backlog(
    stats_db,
):
    company = _company(stats_db)
    stats_db.add_all(
        [
            _node("skill", "backend", "Backend", "skill_category"),
            _node(
                "skill",
                "languages",
                "Languages",
                "technology",
                parent_code="backend",
            ),
            _node(
                "skill",
                "java",
                "Java",
                "skill",
                parent_code="languages",
                assignable=True,
            ),
            _node(
                "skill",
                "python",
                "Python",
                "skill",
                parent_code="languages",
                assignable=True,
            ),
        ]
    )
    stats_db.add(AppRuntimeSettings(id=1, skill_auto_create_distinct_job_threshold=2))
    stats_db.flush()

    first = _job(stats_db, company, enriched=True)
    second = _job(stats_db, company, enriched=True)
    third = _job(stats_db, company, enriched=True)
    deleted = _job(stats_db, company, enriched=True, deleted=True)
    not_processed = _job(stats_db, company)
    _assign_skill(stats_db, first, "java")
    _assign_skill(stats_db, first, "python")
    _assign_skill(stats_db, second, "java")
    _assign_skill(stats_db, deleted, "python")
    _assign_skill(stats_db, not_processed, "python")

    ready_candidate = _candidate(stats_db, "Rust", 2)
    waiting_candidate = _candidate(stats_db, "Elixir", 1)
    deleted_candidate = _candidate(stats_db, "Fortran", 3)
    _candidate_mention(stats_db, first, ready_candidate)
    _candidate_mention(stats_db, second, ready_candidate)
    _candidate_mention(stats_db, second, waiting_candidate)
    _candidate_mention(stats_db, third, waiting_candidate)
    _candidate_mention(stats_db, deleted, deleted_candidate)
    stats_db.commit()

    payload = await get_skill_stats(limit=30, category=None, db=stats_db)

    assert payload["processed_total"] == 3
    assert payload["matched_job_total"] == 2
    assert payload["match_coverage"] == 67
    assert payload["candidate_backlog"] == {
        "unresolved_candidate_total": 2,
        "affected_job_total": 3,
        "ready_candidate_total": 1,
        "ready_threshold": 2,
    }
    assert payload["skills"] == [
        {
            "code": "java",
            "name": "Java",
            "category": "Backend",
            "count": 2,
            "prevalence": 67,
            "dashboard_bucket": "Backend",
        },
        {
            "code": "python",
            "name": "Python",
            "category": "Backend",
            "count": 1,
            "prevalence": 33,
            "dashboard_bucket": "Backend",
        },
    ]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jenkins", "Platform & Cloud"),
        ("GitHub Actions", "Platform & Cloud"),
        ("Unix", "Systems & Network"),
        ("VMware", "Systems & Network"),
    ],
)
def test_skill_dashboard_bucket_is_backend_owned(name, expected):
    assert get_skill_dashboard_bucket(name, "DevOps") == expected


def test_skill_stats_reject_out_of_bounds_limits(stats_db):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield stats_db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    assert client.get("/api/stats/skills?limit=0").status_code == 422
    assert client.get("/api/stats/skills?limit=101").status_code == 422
