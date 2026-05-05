import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job, JobSkill, JobSkillMention, Skill, SkillCategory, SkillTechnology
from scripts import batch_enrich_jobs

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            Job.__table__,
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
            JobSkill.__table__,
            JobSkillMention.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _seed_company(db):
    company = Company(
        id=uuid.uuid4(),
        company_id="company-1",
        name="Acme",
    )
    db.add(company)
    db.flush()
    return company


def _seed_visible_skill(db, name="Python"):
    category = SkillCategory(
        id=uuid.uuid4(),
        name="Backend",
        created_by="seed",
        is_auto_created=False,
        is_filter_visible=True,
    )
    technology = SkillTechnology(
        id=uuid.uuid4(),
        category_id=category.id,
        name="Python",
        created_by="seed",
        is_auto_created=False,
        is_filter_visible=True,
    )
    skill = Skill(
        id=uuid.uuid4(),
        technology_id=technology.id,
        name=name,
        aliases=None,
        created_by="seed",
        is_auto_created=False,
        is_filter_visible=True,
    )
    db.add_all([category, technology, skill])
    db.flush()
    return skill


def _seed_job(
    db,
    *,
    company_id,
    job_id,
    ai_enriched_at=None,
):
    job = Job(
        id=uuid.uuid4(),
        job_id=job_id,
        source_site="jobsdb",
        company_id=company_id,
        title=job_id,
        description=f"{job_id} description",
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_id="1001",
        source_subclassification_name="Developers/Programmers",
        ai_enriched_at=ai_enriched_at,
        is_deleted=False,
    )
    db.add(job)
    db.flush()
    return job


def _link_visible_skill(db, *, job_id, skill_id, raw_name):
    db.add(
        JobSkill(
            job_id=job_id,
            skill_id=skill_id,
            source="ai",
            confidence=0.9,
        )
    )
    db.add(
        JobSkillMention(
            id=uuid.uuid4(),
            job_id=job_id,
            raw_name=raw_name,
            normalized_name=raw_name.lower(),
            resolution="match_existing",
            skill_id=skill_id,
            source="ai",
            confidence=0.9,
        )
    )
    db.flush()


def _add_review_candidate_mention(db, *, job_id, raw_name):
    db.add(
        JobSkillMention(
            id=uuid.uuid4(),
            job_id=job_id,
            raw_name=raw_name,
            normalized_name=raw_name.lower(),
            resolution="review_candidate",
            source="ai",
            confidence=0.8,
        )
    )
    db.flush()


class RecordingService:
    def __init__(self):
        self.calls = []

    async def enrich_job(self, job, db):
        self.calls.append(job.job_id)
        return {"status": "success"}


def test_batch_enrich_include_enriched_can_target_low_governed_skill_jobs():
    Session = _build_sqlite_session_factory()
    with Session() as db:
        company = _seed_company(db)
        visible_skill = _seed_visible_skill(db)
        unenriched = _seed_job(db, company_id=company.id, job_id="unenriched-job")
        enriched_low = _seed_job(
            db,
            company_id=company.id,
            job_id="enriched-low-skill-job",
            ai_enriched_at=datetime(2026, 5, 1, 12, 0, 0),
        )
        enriched_with_skill = _seed_job(
            db,
            company_id=company.id,
            job_id="enriched-with-skill-job",
            ai_enriched_at=datetime(2026, 5, 1, 13, 0, 0),
        )
        _link_visible_skill(
            db,
            job_id=enriched_with_skill.id,
            skill_id=visible_skill.id,
            raw_name="Python",
        )
        db.commit()

    service = RecordingService()
    result = asyncio.run(
        batch_enrich_jobs.batch_enrich(
            db_factory=Session,
            service=service,
            dry_run=False,
            delay_seconds=0,
            include_enriched=True,
            max_governed_skills=0,
        )
    )

    assert result["total"] == 2
    assert service.calls == ["unenriched-job", "enriched-low-skill-job"]


def test_batch_enrich_require_no_mentions_excludes_provisional_only_jobs():
    Session = _build_sqlite_session_factory()
    with Session() as db:
        company = _seed_company(db)
        no_mentions = _seed_job(
            db,
            company_id=company.id,
            job_id="no-mentions-job",
            ai_enriched_at=datetime(2026, 5, 1, 12, 0, 0),
        )
        provisional_only = _seed_job(
            db,
            company_id=company.id,
            job_id="provisional-only-job",
            ai_enriched_at=datetime(2026, 5, 1, 13, 0, 0),
        )
        _add_review_candidate_mention(
            db,
            job_id=provisional_only.id,
            raw_name="Google Suite",
        )
        db.commit()

    service = RecordingService()
    result = asyncio.run(
        batch_enrich_jobs.batch_enrich(
            db_factory=Session,
            service=service,
            dry_run=False,
            delay_seconds=0,
            include_enriched=True,
            require_no_mentions=True,
        )
    )

    assert result["total"] == 1
    assert service.calls == ["no-mentions-job"]


def test_batch_enrich_rerun_below_governed_skills_targets_less_than_three():
    Session = _build_sqlite_session_factory()
    with Session() as db:
        company = _seed_company(db)
        skill_one = _seed_visible_skill(db, name="Python")
        skill_two = Skill(
            id=uuid.uuid4(),
            technology_id=skill_one.technology_id,
            name="FastAPI",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
            is_filter_visible=True,
        )
        db.add(skill_two)
        db.flush()
        below_threshold = _seed_job(
            db,
            company_id=company.id,
            job_id="below-threshold-job",
            ai_enriched_at=datetime(2026, 5, 1, 12, 0, 0),
        )
        at_threshold = _seed_job(
            db,
            company_id=company.id,
            job_id="at-threshold-job",
            ai_enriched_at=datetime(2026, 5, 1, 13, 0, 0),
        )
        _link_visible_skill(
            db,
            job_id=below_threshold.id,
            skill_id=skill_one.id,
            raw_name="Python",
        )
        _link_visible_skill(
            db,
            job_id=at_threshold.id,
            skill_id=skill_one.id,
            raw_name="Python",
        )
        _link_visible_skill(
            db,
            job_id=at_threshold.id,
            skill_id=skill_two.id,
            raw_name="FastAPI",
        )
        db.commit()

    service = RecordingService()
    result = asyncio.run(
        batch_enrich_jobs.batch_enrich(
            db_factory=Session,
            service=service,
            dry_run=False,
            delay_seconds=0,
            include_enriched=True,
            rerun_below_governed_skills=2,
        )
    )

    assert result["total"] == 1
    assert service.calls == ["below-threshold-job"]
