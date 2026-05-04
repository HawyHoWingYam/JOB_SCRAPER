import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import jobs as jobs_api
from app.api import skills as skills_api
from app.api import stats as stats_api
from app.api import filters as filters_api
from app.database import Base
from app.models import (
    Company,
    Job,
    JobCategory,
    JobDomain,
    JobSkill,
    JobSkillMention,
    JobSubcategory,
    Skill,
    SkillCategory,
    SkillTechnology,
)
from app.schemas.job import JobDetailSchema
from app.schemas.job_search import JobSearchFiltersSchema

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


CANONICAL_PATH = (
    "Information & Communication Technology / "
    "Software Development / Backend Development"
)


def _build_sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            JobDomain.__table__,
            JobCategory.__table__,
            JobSubcategory.__table__,
            Job.__table__,
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
            JobSkill.__table__,
            JobSkillMention.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _seed_company(db):
    company = Company(
        id=uuid.uuid4(),
        company_id="company-1",
        name="Acme",
        industry="Technology",
    )
    db.add(company)
    db.commit()
    return company


def _seed_taxonomy(db):
    domain = JobDomain(
        id=uuid.uuid4(),
        name="Information & Communication Technology",
    )
    category = JobCategory(
        id=uuid.uuid4(),
        domain_id=domain.id,
        name="Software Development",
    )
    subcategory = JobSubcategory(
        id=uuid.uuid4(),
        category_id=category.id,
        name="Backend Development",
    )
    db.add_all([domain, category, subcategory])
    db.commit()
    return domain, category, subcategory


def _seed_job(
    db,
    *,
    company_id,
    job_id,
    title,
    subcategory_id=None,
):
    job = Job(
        id=uuid.uuid4(),
        job_id=job_id,
        company_id=company_id,
        title=title,
        subcategory_id=subcategory_id,
        is_deleted=False,
    )
    db.add(job)
    db.commit()
    return job


def _seed_skill_taxonomy(db):
    backend = SkillCategory(
        id=uuid.uuid4(),
        name="Backend",
    )
    backend.created_by = "seed"
    backend.is_auto_created = False
    backend.is_filter_visible = True
    backend.distinct_job_count = 20

    python = SkillTechnology(
        id=uuid.uuid4(),
        category_id=backend.id,
        name="Python",
    )
    python.created_by = "seed"
    python.is_auto_created = False
    python.is_filter_visible = True
    python.distinct_job_count = 20

    python_skill = Skill(
        id=uuid.uuid4(),
        technology_id=python.id,
        name="Python",
        aliases=None,
    )
    python_skill.created_by = "seed"
    python_skill.is_auto_created = False
    python_skill.is_filter_visible = True
    python_skill.distinct_job_count = 20

    other = SkillCategory(
        id=uuid.uuid4(),
        name="Other",
    )
    other.created_by = "ai"
    other.is_auto_created = True
    other.is_filter_visible = True
    other.distinct_job_count = 20

    general = SkillTechnology(
        id=uuid.uuid4(),
        category_id=other.id,
        name="General",
    )
    general.created_by = "ai"
    general.is_auto_created = True
    general.is_filter_visible = True
    general.distinct_job_count = 20

    linux_skill = Skill(
        id=uuid.uuid4(),
        technology_id=general.id,
        name="Linux",
        aliases=None,
    )
    linux_skill.created_by = "ai"
    linux_skill.is_auto_created = True
    linux_skill.is_filter_visible = True
    linux_skill.distinct_job_count = 20

    hidden_skill = Skill(
        id=uuid.uuid4(),
        technology_id=python.id,
        name="PySpark",
        aliases=None,
    )
    hidden_skill.created_by = "ai"
    hidden_skill.is_auto_created = True
    hidden_skill.is_filter_visible = False
    hidden_skill.distinct_job_count = 0

    db.add_all([backend, python, python_skill, other, general, linux_skill, hidden_skill])
    db.commit()

    return {
        "backend": backend,
        "python_technology": python,
        "python_skill": python_skill,
        "other": other,
        "general": general,
        "linux_skill": linux_skill,
        "hidden_skill": hidden_skill,
    }


def _link_job_skill(db, *, job_id, skill_id):
    link = JobSkill(
        job_id=job_id,
        skill_id=skill_id,
        source="ai",
        confidence=0.9,
    )
    db.add(link)
    db.flush()
    return link


def _create_match_existing_mention(db, *, job_id, raw_name, skill_id):
    mention = JobSkillMention(
        id=uuid.uuid4(),
        job_id=job_id,
        raw_name=raw_name,
        normalized_name=raw_name,
        resolution="match_existing",
        skill_id=skill_id,
        source="ai",
        confidence=0.9,
    )
    db.add(mention)
    db.flush()
    return mention


def test_search_response_returns_canonical_job_taxonomy_and_hides_ai_category():
    db = _build_sqlite_session()
    try:
        company = _seed_company(db)
        domain, category, backend = _seed_taxonomy(db)
        _seed_job(
            db,
            company_id=company.id,
            job_id="job-canonical",
            title="Backend Engineer",
            subcategory_id=backend.id,
        )

        query = db.query(Job, Company).join(Company, Job.company_id == Company.id)
        query = query.filter(Job.is_deleted.is_(False))
        response = jobs_api._build_search_response(query, page=1, page_size=20)
        payload = response.model_dump(mode="json")

        assert "ai_category" not in payload["jobs"][0]
        assert payload["jobs"][0]["job_taxonomy"] == {
            "domain_id": str(domain.id),
            "domain_name": "Information & Communication Technology",
            "category_id": str(category.id),
            "category_name": "Software Development",
            "subcategory_id": str(backend.id),
            "subcategory_name": "Backend Development",
            "path": CANONICAL_PATH,
        }
    finally:
        db.close()


def test_structured_filters_use_canonical_ids_not_legacy_category_text():
    db = _build_sqlite_session()
    try:
        company = _seed_company(db)
        _, _, backend = _seed_taxonomy(db)
        matching_job = _seed_job(
            db,
            company_id=company.id,
            job_id="job-canonical",
            title="Backend Engineer",
            subcategory_id=backend.id,
        )
        _seed_job(
            db,
            company_id=company.id,
            job_id="job-other",
            title="Account Executive",
        )

        query = db.query(Job, Company).join(Company, Job.company_id == Company.id)
        query = query.filter(Job.is_deleted.is_(False))
        query = jobs_api._apply_structured_filters(
            query,
            JobSearchFiltersSchema(subcategory_ids=[str(backend.id)]),
        )
        results = query.order_by(Job.job_id.asc()).all()

        assert [(job.job_id, company.name) for job, company in results] == [
            (matching_job.job_id, "Acme"),
        ]
    finally:
        db.close()


def test_category_stats_only_group_jobs_with_canonical_taxonomy():
    db = _build_sqlite_session()
    try:
        company = _seed_company(db)
        _, _, backend = _seed_taxonomy(db)

        _seed_job(
            db,
            company_id=company.id,
            job_id="job-canonical-1",
            title="Backend Engineer",
            subcategory_id=backend.id,
        )
        _seed_job(
            db,
            company_id=company.id,
            job_id="job-canonical-2",
            title="Platform Engineer",
            subcategory_id=backend.id,
        )
        _seed_job(
            db,
            company_id=company.id,
            job_id="job-uncategorized",
            title="Account Executive",
        )

        results = asyncio.run(stats_api.get_category_stats(db=db))

        assert results == [
            {"category": CANONICAL_PATH, "count": 2},
        ]
    finally:
        db.close()


def test_job_detail_returns_only_governed_match_existing_skills():
    db = _build_sqlite_session()
    try:
        company = _seed_company(db)
        _, _, backend = _seed_taxonomy(db)
        skills = _seed_skill_taxonomy(db)
        job = _seed_job(
            db,
            company_id=company.id,
            job_id="job-governed-skills",
            title="Platform Engineer",
            subcategory_id=backend.id,
        )

        _link_job_skill(db, job_id=job.id, skill_id=skills["python_skill"].id)
        _link_job_skill(db, job_id=job.id, skill_id=skills["linux_skill"].id)
        _create_match_existing_mention(
            db,
            job_id=job.id,
            raw_name="Python",
            skill_id=skills["python_skill"].id,
        )
        db.commit()

        result = asyncio.run(jobs_api.get_job(job.id, db=db))
        payload = JobDetailSchema.model_validate(result).model_dump(mode="json")

        assert payload["skills"] == ["Python"]
    finally:
        db.close()


def test_skill_stats_only_count_governed_match_existing_mentions():
    db = _build_sqlite_session()
    try:
        company = _seed_company(db)
        skills = _seed_skill_taxonomy(db)

        canonical_job = _seed_job(
            db,
            company_id=company.id,
            job_id="job-python",
            title="Python Engineer",
        )
        polluted_job = _seed_job(
            db,
            company_id=company.id,
            job_id="job-linux",
            title="Linux Engineer",
        )

        _link_job_skill(db, job_id=canonical_job.id, skill_id=skills["python_skill"].id)
        _link_job_skill(db, job_id=polluted_job.id, skill_id=skills["linux_skill"].id)
        _create_match_existing_mention(
            db,
            job_id=canonical_job.id,
            raw_name="Python",
            skill_id=skills["python_skill"].id,
        )
        db.commit()

        results = asyncio.run(stats_api.get_skill_stats(limit=10, db=db))

        assert results == {
            "skills": [
                {"name": "Python", "category": "Backend", "count": 1},
            ]
        }
    finally:
        db.close()


def test_skill_search_and_filters_hide_other_general_and_invisible_skills():
    db = _build_sqlite_session()
    try:
        skills = _seed_skill_taxonomy(db)

        search_payload = asyncio.run(skills_api.search_skills(q="Py", limit=10, db=db))
        skill_filters = filters_api.get_skills(technology_id=None, db=db)
        category_filters = filters_api.get_skill_categories(db=db)

        assert search_payload == {
            "skills": [
                {
                    "id": str(skills["python_skill"].id),
                    "name": "Python",
                    "category": "Backend",
                }
            ]
        }
        assert skill_filters == [
            {
                "id": str(skills["python_skill"].id),
                "name": "Python",
                "technology_id": str(skills["python_technology"].id),
            }
        ]
        assert category_filters == [
            {"id": str(skills["backend"].id), "name": "Backend"},
        ]
    finally:
        db.close()
