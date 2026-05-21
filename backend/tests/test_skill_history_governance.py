import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job, JobSkill, JobSkillMention, Skill, SkillCategory, SkillTechnology
from app.models.skill_review_candidate import SkillReviewCandidate
from scripts import govern_skill_history
from scripts import govern_skill_review_candidates
from scripts import verify_migration


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
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
            SkillReviewCandidate.__table__,
            JobSkillMention.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _build_pre_migration_session():
    engine = create_engine("sqlite:///:memory:")
    statements = [
        """
        CREATE TABLE companies (
            id CHAR(32) PRIMARY KEY,
            company_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL
        )
        """,
        """
        CREATE TABLE jobs (
            id CHAR(32) PRIMARY KEY,
            job_id VARCHAR(255) NOT NULL,
            company_id CHAR(32),
            title VARCHAR(255) NOT NULL,
            description TEXT,
            ai_category VARCHAR(255),
            ai_enriched_at DATETIME,
            subcategory_id CHAR(32),
            is_deleted BOOLEAN DEFAULT 0
        )
        """,
        """
        CREATE TABLE skill_categories (
            id CHAR(32) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            is_filter_visible BOOLEAN DEFAULT 0,
            distinct_job_count INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used_at DATETIME
        )
        """,
        """
        CREATE TABLE skill_technologies (
            id CHAR(32) PRIMARY KEY,
            category_id CHAR(32) NOT NULL,
            name VARCHAR(100) NOT NULL,
            is_filter_visible BOOLEAN DEFAULT 0,
            distinct_job_count INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used_at DATETIME
        )
        """,
        """
        CREATE TABLE skills (
            id CHAR(32) PRIMARY KEY,
            technology_id CHAR(32) NOT NULL,
            name VARCHAR(100) NOT NULL,
            aliases TEXT,
            is_filter_visible BOOLEAN DEFAULT 0,
            distinct_job_count INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used_at DATETIME
        )
        """,
        """
        CREATE TABLE job_skills (
            job_id CHAR(32) NOT NULL,
            skill_id CHAR(32) NOT NULL,
            source VARCHAR(50),
            confidence FLOAT,
            created_at DATETIME
        )
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    Session = sessionmaker(bind=engine)
    return Session()


def _build_partial_governance_session():
    engine = create_engine("sqlite:///:memory:")
    statements = [
        """
        CREATE TABLE companies (
            id CHAR(32) PRIMARY KEY,
            company_id VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL
        )
        """,
        """
        CREATE TABLE jobs (
            id CHAR(32) PRIMARY KEY,
            job_id VARCHAR(255) NOT NULL,
            company_id CHAR(32),
            title VARCHAR(255) NOT NULL,
            description TEXT,
            ai_category VARCHAR(255),
            ai_enriched_at DATETIME,
            ai_generic_tags TEXT,
            subcategory_id CHAR(32),
            is_deleted BOOLEAN DEFAULT 0
        )
        """,
        """
        CREATE TABLE skill_categories (
            id CHAR(32) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            is_filter_visible BOOLEAN DEFAULT 0,
            distinct_job_count INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used_at DATETIME
        )
        """,
        """
        CREATE TABLE skill_technologies (
            id CHAR(32) PRIMARY KEY,
            category_id CHAR(32) NOT NULL,
            name VARCHAR(100) NOT NULL,
            is_filter_visible BOOLEAN DEFAULT 0,
            distinct_job_count INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used_at DATETIME
        )
        """,
        """
        CREATE TABLE skills (
            id CHAR(32) PRIMARY KEY,
            technology_id CHAR(32) NOT NULL,
            name VARCHAR(100) NOT NULL,
            aliases TEXT,
            is_filter_visible BOOLEAN DEFAULT 0,
            distinct_job_count INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            last_used_at DATETIME
        )
        """,
        """
        CREATE TABLE job_skills (
            job_id CHAR(32) NOT NULL,
            skill_id CHAR(32) NOT NULL,
            source VARCHAR(50),
            confidence FLOAT,
            created_at DATETIME
        )
        """,
        """
        CREATE TABLE skill_review_candidates (
            id CHAR(32) PRIMARY KEY,
            raw_name VARCHAR(100) NOT NULL,
            normalized_name VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            suggested_category VARCHAR(100),
            suggested_technology VARCHAR(100),
            occurrence_count INTEGER NOT NULL DEFAULT 1,
            first_seen_job_id CHAR(32),
            last_seen_job_id CHAR(32),
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    Session = sessionmaker(bind=engine)
    return Session()


def _write_curations(tmp_path, entries, minimum_distinct_jobs=1):
    path = tmp_path / "skill_backfill_curations.json"
    path.write_text(
        json.dumps(
            {
                "minimum_distinct_jobs": minimum_distinct_jobs,
                "entries": entries,
            },
            indent=2,
        )
    )
    return path


def _create_company(db):
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{uuid.uuid4()}",
        name=f"Company {uuid.uuid4()}",
    )
    db.add(company)
    db.flush()
    return company


def _create_job(
    db,
    company_id,
    title,
    *,
    description=None,
    source_subclassification_name=None,
):
    job = Job(
        id=uuid.uuid4(),
        job_id=f"job-{uuid.uuid4()}",
        source_site="jobsdb",
        company_id=company_id,
        title=title,
        description=description or f"{title} description",
        source_subclassification_name=source_subclassification_name,
        created_at=datetime(2026, 4, 30, 10, 0, 0),
        updated_at=datetime(2026, 4, 30, 10, 0, 0),
    )
    db.add(job)
    db.flush()
    return job


def _create_skill_hierarchy(db, category_name, technology_name):
    category = SkillCategory(
        id=uuid.uuid4(),
        name=category_name,
        created_by="seed",
        is_auto_created=False,
    )
    technology = SkillTechnology(
        id=uuid.uuid4(),
        category_id=category.id,
        name=technology_name,
        created_by="seed",
        is_auto_created=False,
    )
    db.add(category)
    db.add(technology)
    db.flush()
    return category, technology


def _create_skill(db, technology_id, name, *, aliases=None, created_by="ai", is_auto_created=True):
    skill = Skill(
        id=uuid.uuid4(),
        technology_id=technology_id,
        name=name,
        aliases=aliases,
        created_by=created_by,
        is_auto_created=is_auto_created,
    )
    db.add(skill)
    db.flush()
    return skill


def _link_job_skill(db, job_id, skill_id, created_at=None):
    job_skill = JobSkill(
        job_id=job_id,
        skill_id=skill_id,
        source="ai",
        confidence=0.9,
        created_at=created_at or datetime(2026, 4, 30, 11, 0, 0),
    )
    db.add(job_skill)
    db.flush()
    return job_skill


def _create_match_existing_mention(
    db,
    *,
    job_id,
    raw_name,
    normalized_name,
    skill_id,
):
    mention = JobSkillMention(
        id=uuid.uuid4(),
        job_id=job_id,
        raw_name=raw_name,
        normalized_name=normalized_name,
        resolution="match_existing",
        skill_id=skill_id,
        source="ai",
        confidence=0.9,
    )
    db.add(mention)
    db.flush()
    return mention


def _create_review_candidate(
    db,
    raw_name,
    normalized_name,
    *,
    occurrence_count=1,
    first_seen_job_id=None,
    last_seen_job_id=None,
):
    candidate = SkillReviewCandidate(
        id=uuid.uuid4(),
        raw_name=raw_name,
        normalized_name=normalized_name,
        occurrence_count=occurrence_count,
        first_seen_job_id=first_seen_job_id,
        last_seen_job_id=last_seen_job_id,
    )
    db.add(candidate)
    db.flush()
    return candidate


def _create_review_candidate_mention(
    db,
    *,
    job_id,
    raw_name,
    normalized_name,
    review_candidate_id,
):
    mention = JobSkillMention(
        id=uuid.uuid4(),
        job_id=job_id,
        raw_name=raw_name,
        normalized_name=normalized_name,
        resolution="review_candidate",
        review_candidate_id=review_candidate_id,
        source="ai",
        confidence=0.9,
    )
    db.add(mention)
    db.flush()
    return mention


def test_audit_skill_history_classifies_polluted_skills(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        other_category, other_general = _create_skill_hierarchy(db, "Other", "General")

        python_skill = _create_skill(db, other_general.id, "Python")
        pm_skill = _create_skill(db, other_general.id, "Project Management")
        linux_skill = _create_skill(db, other_general.id, "Linux")

        job1 = _create_job(db, company.id, "Python Engineer")
        job2 = _create_job(db, company.id, "Tech Lead")
        job3 = _create_job(db, company.id, "Platform Engineer")

        _link_job_skill(db, job1.id, python_skill.id)
        _link_job_skill(db, job2.id, pm_skill.id)
        _link_job_skill(db, job3.id, linux_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "python": {
                    "action": "merge",
                    "target": {
                        "category": "Backend",
                        "technology": "Python",
                        "skill": "Python",
                    },
                },
                "project management": {
                    "action": "generic",
                    "generic_tag": "Project Management",
                },
                "linux": {
                    "action": "review",
                    "note": "Needs manual taxonomy review",
                },
            },
        )

        report = govern_skill_history.audit_skill_history(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
        )

        actions = {entry["source_skill"]["name"]: entry["action"] for entry in report["entries"]}

        assert actions == {
            "Python": "merge",
            "Project Management": "generic",
            "Linux": "review",
        }
        assert report["summary"]["merge"]["skill_count"] == 1
        assert report["summary"]["generic"]["skill_count"] == 1
        assert report["summary"]["review"]["skill_count"] == 1
    finally:
        db.close()


def test_apply_skill_history_governance_requires_governance_schema(tmp_path):
    db = _build_pre_migration_session()
    try:
        curations_path = _write_curations(
            tmp_path,
            {
                "project management": {
                    "action": "generic",
                    "generic_tag": "Project Management",
                }
            },
        )

        with pytest.raises(ValueError, match="20260501_103000"):
            govern_skill_history.apply_skill_history_governance(
                db,
                min_distinct_jobs=1,
                curation_path=curations_path,
                execute=True,
            )
    finally:
        db.close()


def test_apply_skill_history_governance_requires_job_skill_mentions_schema(tmp_path):
    db = _build_partial_governance_session()
    try:
        curations_path = _write_curations(
            tmp_path,
            {
                "linux": {
                    "action": "review",
                    "note": "Pending infra taxonomy curation",
                }
            },
        )

        with pytest.raises(ValueError, match="20260501_103000"):
            govern_skill_history.apply_skill_history_governance(
                db,
                min_distinct_jobs=1,
                curation_path=curations_path,
                execute=True,
            )
    finally:
        db.close()


def test_apply_skill_history_governance_merges_into_created_canonical_skill(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        _create_skill_hierarchy(db, "Backend", "Python")

        polluted_skill = _create_skill(db, other_general.id, "Python")
        job1 = _create_job(db, company.id, "Backend Engineer")
        job2 = _create_job(db, company.id, "Automation Engineer")
        _link_job_skill(db, job1.id, polluted_skill.id)
        _link_job_skill(db, job2.id, polluted_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "python": {
                    "action": "merge",
                    "target": {
                        "category": "Backend",
                        "technology": "Python",
                        "skill": "Python",
                    },
                }
            },
        )

        govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            execute=True,
        )

        canonical_skill = (
            db.query(Skill)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(
                Skill.name == "Python",
                SkillTechnology.name == "Python",
                SkillCategory.name == "Backend",
            )
            .one()
        )
        links = db.query(JobSkill).filter(JobSkill.skill_id == canonical_skill.id).all()

        assert canonical_skill.created_by == "seed"
        assert canonical_skill.is_auto_created is False
        assert len(links) == 2
        assert db.query(JobSkill).filter(JobSkill.skill_id == polluted_skill.id).count() == 0
        assert db.query(Skill).filter(Skill.id == polluted_skill.id).count() == 0
    finally:
        db.close()


def test_apply_skill_history_governance_merges_into_created_canonical_skill_with_canonicalized_name(
    tmp_path,
):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")

        polluted_skill = _create_skill(db, other_general.id, "Microsoft Azure")
        job1 = _create_job(db, company.id, "Cloud Engineer")
        job2 = _create_job(db, company.id, "Platform Engineer")
        _link_job_skill(db, job1.id, polluted_skill.id)
        _link_job_skill(db, job2.id, polluted_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                    "microsoft azure": {
                        "action": "merge",
                        "target": {
                            "category": "DevOps",
                            "technology": "Cloud Platforms",
                            "skill": "Azure",
                        },
                    }
                },
            )

        govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            execute=True,
        )

        canonical_skill = (
            db.query(Skill)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(
                Skill.name == "Azure",
                SkillTechnology.name == "Cloud Platforms",
                SkillCategory.name == "DevOps",
            )
            .one()
        )
        links = db.query(JobSkill).filter(JobSkill.skill_id == canonical_skill.id).all()

        assert canonical_skill.aliases is None
        assert len(links) == 2
        assert db.query(JobSkill).filter(JobSkill.skill_id == polluted_skill.id).count() == 0
        assert db.query(Skill).filter(Skill.id == polluted_skill.id).count() == 0
    finally:
        db.close()


def test_audit_review_candidates_preserves_distinct_curation_keys_for_technical_symbols(tmp_path):
    db = _build_sqlite_session()
    try:
        candidate_c_sharp = _create_review_candidate(
            db,
            "C#",
            "c#",
            occurrence_count=2,
        )
        candidate_c_plus_plus = _create_review_candidate(
            db,
            "C++",
            "c++",
            occurrence_count=1,
        )
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "C#": {
                    "action": "merge",
                    "target": {
                        "category": "Backend",
                        "technology": ".NET",
                        "skill": "C#",
                    },
                },
                "C++": {
                    "action": "generic",
                    "generic_tag": "C++",
                },
            },
            minimum_distinct_jobs=1,
        )

        report = govern_skill_review_candidates.audit_review_candidates(
            db,
            min_occurrence_count=1,
            curation_path=curations_path,
        )
        entries = {
            entry["review_candidate"]["normalized_name"]: entry
            for entry in report["entries"]
        }

        assert entries[candidate_c_sharp.normalized_name]["action"] == "merge"
        assert entries[candidate_c_plus_plus.normalized_name]["action"] == "generic"
        assert report["summary"] == {"merge": 1, "generic": 1, "review": 0}
    finally:
        db.close()


def test_apply_skill_review_candidate_governance_merges_into_created_canonical_skill(
    tmp_path,
):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        job1 = _create_job(db, company.id, "Cloud Engineer")
        job2 = _create_job(db, company.id, "Platform Engineer")
        candidate = _create_review_candidate(
            db,
            "AWS",
            "aws",
            occurrence_count=2,
            first_seen_job_id=job1.id,
            last_seen_job_id=job2.id,
        )
        _create_review_candidate_mention(
            db,
            job_id=job1.id,
            raw_name="AWS",
            normalized_name="aws",
            review_candidate_id=candidate.id,
        )
        _create_review_candidate_mention(
            db,
            job_id=job2.id,
            raw_name="AWS",
            normalized_name="aws",
            review_candidate_id=candidate.id,
        )
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "aws": {
                    "action": "merge",
                    "target": {
                        "category": "DevOps",
                        "technology": "Cloud Platforms",
                        "skill": "AWS",
                    },
                }
            },
            minimum_distinct_jobs=1,
        )

        govern_skill_review_candidates.apply_review_candidate_governance(
            db,
            min_occurrence_count=1,
            curation_path=curations_path,
            execute=True,
        )

        canonical_skill = (
            db.query(Skill)
            .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
            .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
            .filter(
                Skill.name == "AWS",
                SkillTechnology.name == "Cloud Platforms",
                SkillCategory.name == "DevOps",
            )
            .one()
        )
        mentions = (
            db.query(JobSkillMention)
            .filter(JobSkillMention.job_id.in_([job1.id, job2.id]))
            .order_by(JobSkillMention.job_id.asc())
            .all()
        )
        links = db.query(JobSkill).filter(JobSkill.skill_id == canonical_skill.id).all()

        db.refresh(candidate)
        assert candidate.status == "resolved"
        assert candidate.occurrence_count == 0
        assert len(links) == 2
        assert [(mention.resolution, mention.skill_id, mention.review_candidate_id) for mention in mentions] == [
            ("match_existing", canonical_skill.id, None),
            ("match_existing", canonical_skill.id, None),
        ]
    finally:
        db.close()


def test_apply_skill_history_governance_routes_generic_terms_to_job_mentions(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        polluted_skill = _create_skill(db, other_general.id, "Project Management")
        job = _create_job(db, company.id, "Delivery Lead")
        _link_job_skill(db, job.id, polluted_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "project management": {
                    "action": "generic",
                    "generic_tag": "Project Management",
                }
            },
        )

        govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            execute=True,
        )

        mentions = (
            db.query(JobSkillMention)
            .filter_by(job_id=job.id, resolution="generic_tag")
            .order_by(JobSkillMention.raw_name.asc())
            .all()
        )
        assert [(mention.raw_name, mention.generic_tag) for mention in mentions] == [
            ("Project Management", "Project Management")
        ]
        assert db.query(JobSkill).filter(JobSkill.skill_id == polluted_skill.id).count() == 0
        assert db.query(Skill).filter(Skill.id == polluted_skill.id).count() == 0
    finally:
        db.close()


def test_apply_skill_history_governance_routes_reviewed_skills_out_of_controlled_layer(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        polluted_skill = _create_skill(db, other_general.id, "Linux")
        job1 = _create_job(db, company.id, "Systems Engineer")
        job2 = _create_job(db, company.id, "Infrastructure Engineer")
        _link_job_skill(db, job1.id, polluted_skill.id)
        _link_job_skill(db, job2.id, polluted_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "linux": {
                    "action": "review",
                    "note": "Pending infra taxonomy curation",
                }
            },
        )

        govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            execute=True,
        )

        candidate = db.query(SkillReviewCandidate).filter_by(normalized_name="linux").one()

        assert candidate.raw_name == "Linux"
        assert candidate.occurrence_count == 2
        assert db.query(JobSkill).filter(JobSkill.skill_id == polluted_skill.id).count() == 0
        assert db.query(Skill).filter(Skill.id == polluted_skill.id).count() == 0
    finally:
        db.close()


def test_apply_skill_history_governance_recomputes_review_occurrence_count_from_mentions(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        polluted_skill = _create_skill(db, other_general.id, "Linux")
        existing_job = _create_job(db, company.id, "Legacy Systems Engineer")
        migrated_job1 = _create_job(db, company.id, "Systems Engineer")
        migrated_job2 = _create_job(db, company.id, "Infrastructure Engineer")
        existing_candidate = _create_review_candidate(
            db,
            "Linux",
            "linux",
            occurrence_count=99,
            first_seen_job_id=existing_job.id,
            last_seen_job_id=existing_job.id,
        )
        _create_review_candidate_mention(
            db,
            job_id=existing_job.id,
            raw_name="Linux",
            normalized_name="linux",
            review_candidate_id=existing_candidate.id,
        )
        _link_job_skill(db, migrated_job1.id, polluted_skill.id)
        _link_job_skill(db, migrated_job2.id, polluted_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "linux": {
                    "action": "review",
                    "note": "Pending infra taxonomy curation",
                }
            },
        )

        govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            execute=True,
        )
        govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            execute=True,
        )

        db.refresh(existing_candidate)
        mentions = (
            db.query(JobSkillMention)
            .filter_by(
                review_candidate_id=existing_candidate.id,
                resolution="review_candidate",
            )
            .all()
        )

        assert existing_candidate.occurrence_count == 3
        assert {mention.job_id for mention in mentions} == {
            existing_job.id,
            migrated_job1.id,
            migrated_job2.id,
        }
        assert db.query(JobSkill).filter(JobSkill.skill_id == polluted_skill.id).count() == 0
        assert db.query(Skill).filter(Skill.id == polluted_skill.id).count() == 0
    finally:
        db.close()


def test_apply_skill_history_governance_marks_phrase_like_one_off_for_review(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        phrase_skill = _create_skill(
            db,
            other_general.id,
            "Technology solutions implementation lifecycle",
        )
        job = _create_job(db, company.id, "Delivery Lead")
        _link_job_skill(db, job.id, phrase_skill.id)
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=100)

        report = govern_skill_history.apply_skill_history_governance(
            db,
            curation_path=curations_path,
            execute=False,
        )

        review_entries = {
            entry["source_skill"]["name"]: entry
            for entry in report["entries"]
            if entry["action"] == "review"
        }

        assert (
            review_entries["Technology solutions implementation lifecycle"]["note"]
            == "Phrase-like one-off skill mention"
        )
        assert report["minimum_distinct_jobs"] == 100
    finally:
        db.close()


def test_audit_skill_history_uses_normalizer_to_auto_genericize_suppressed_terms(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        suppressed_skill = _create_skill(db, other_general.id, "Data Analysis")
        job = _create_job(db, company.id, "Analyst")
        _link_job_skill(db, job.id, suppressed_skill.id)
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=1)

        report = govern_skill_history.audit_skill_history(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
        )

        data_analysis_entry = next(
            entry for entry in report["entries"] if entry["source_skill"]["name"] == "Data Analysis"
        )
        assert data_analysis_entry["action"] == "generic"
        assert data_analysis_entry["generic_tag"] == "Data Analysis"
    finally:
        db.close()


def test_audit_skill_history_uses_normalizer_to_auto_merge_matchable_terms(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        other_category = SkillCategory(
            id=uuid.uuid4(),
            name="Other",
            created_by="ai",
            is_auto_created=True,
        )
        other_general = SkillTechnology(
            id=uuid.uuid4(),
            category_id=other_category.id,
            name="General",
            created_by="ai",
            is_auto_created=True,
        )
        db.add_all([other_category, other_general])
        db.flush()
        backend_category, python_technology = _create_skill_hierarchy(db, "Backend", "Python")
        _create_skill(
            db,
            python_technology.id,
            "Python",
            created_by="seed",
            is_auto_created=False,
        )
        polluted_skill = _create_skill(db, other_general.id, "Python")
        job = _create_job(db, company.id, "Backend Engineer")
        _link_job_skill(db, job.id, polluted_skill.id)
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=1)

        report = govern_skill_history.audit_skill_history(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
        )

        python_entry = next(
            entry for entry in report["entries"] if entry["source_skill"]["name"] == "Python"
        )
        assert python_entry["action"] == "merge"
        assert python_entry["target"] == {
            "category": backend_category.name,
            "technology": python_technology.name,
            "skill": "Python",
        }
    finally:
        db.close()


def test_apply_skill_history_governance_routes_phrase_like_review_out_of_controlled_layer(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        phrase_skill = _create_skill(
            db,
            other_general.id,
            "Technology solutions implementation lifecycle",
        )
        job = _create_job(db, company.id, "Delivery Lead")
        _link_job_skill(db, job.id, phrase_skill.id)
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=100)

        govern_skill_history.apply_skill_history_governance(
            db,
            curation_path=curations_path,
            execute=True,
        )

        candidate = (
            db.query(SkillReviewCandidate)
            .filter_by(normalized_name="technology solutions implementation lifecycle")
            .one()
        )

        assert candidate.raw_name == "Technology solutions implementation lifecycle"
        assert candidate.occurrence_count == 1
        assert db.query(JobSkill).filter(JobSkill.skill_id == phrase_skill.id).count() == 0
        assert db.query(Skill).filter(Skill.id == phrase_skill.id).count() == 0
    finally:
        db.close()


def test_rebuild_skill_taxonomy_metrics_recalculates_counts_and_visibility(monkeypatch):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        category, technology = _create_skill_hierarchy(db, "Backend", "Python")
        skill = _create_skill(
            db,
            technology.id,
            "Python",
            created_by="seed",
            is_auto_created=False,
        )
        jobs = [_create_job(db, company.id, f"Job {index}") for index in range(1, 3)]
        _link_job_skill(db, jobs[0].id, skill.id, created_at=datetime(2026, 4, 30, 11, 0, 0))
        _link_job_skill(db, jobs[1].id, skill.id, created_at=datetime(2026, 4, 30, 12, 0, 0))
        _create_match_existing_mention(
            db,
            job_id=jobs[0].id,
            raw_name="Python",
            normalized_name="Python",
            skill_id=skill.id,
        )
        _create_match_existing_mention(
            db,
            job_id=jobs[1].id,
            raw_name="Python",
            normalized_name="Python",
            skill_id=skill.id,
        )

        category.usage_count = 99
        category.distinct_job_count = 99
        category.is_filter_visible = False
        technology.usage_count = 99
        technology.distinct_job_count = 99
        technology.is_filter_visible = False
        skill.usage_count = 99
        skill.distinct_job_count = 99
        skill.is_filter_visible = False
        db.commit()

        monkeypatch.setattr(govern_skill_history.settings, "filter_skill_l3_min_jobs", 2)
        monkeypatch.setattr(govern_skill_history.settings, "filter_skill_l2_min_jobs", 2)
        monkeypatch.setattr(govern_skill_history.settings, "filter_skill_l1_min_jobs", 2)

        govern_skill_history.rebuild_skill_taxonomy_metrics(db)

        db.refresh(category)
        db.refresh(technology)
        db.refresh(skill)

        assert skill.usage_count == 2
        assert skill.distinct_job_count == 2
        assert skill.is_filter_visible is True
        assert technology.usage_count == 2
        assert technology.distinct_job_count == 2
        assert technology.is_filter_visible is True
        assert category.usage_count == 2
        assert category.distinct_job_count == 2
        assert category.is_filter_visible is True
        assert skill.last_used_at is not None
    finally:
        db.close()


def test_rebuild_skill_taxonomy_metrics_only_counts_governed_match_existing_mentions(monkeypatch):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        backend_category, python_technology = _create_skill_hierarchy(db, "Backend", "Python")
        canonical_skill = _create_skill(
            db,
            python_technology.id,
            "Python",
            created_by="seed",
            is_auto_created=False,
        )
        other_category, other_general = _create_skill_hierarchy(db, "Other", "General")
        polluted_skill = _create_skill(db, other_general.id, "Linux")

        canonical_job = _create_job(db, company.id, "Python Engineer")
        polluted_job = _create_job(db, company.id, "Linux Engineer")

        _link_job_skill(db, canonical_job.id, canonical_skill.id, created_at=datetime(2026, 4, 30, 11, 0, 0))
        _link_job_skill(db, polluted_job.id, polluted_skill.id, created_at=datetime(2026, 4, 30, 12, 0, 0))
        _create_match_existing_mention(
            db,
            job_id=canonical_job.id,
            raw_name="Python",
            normalized_name="Python",
            skill_id=canonical_skill.id,
        )
        db.commit()

        monkeypatch.setattr(govern_skill_history.settings, "filter_skill_l3_min_jobs", 1)
        monkeypatch.setattr(govern_skill_history.settings, "filter_skill_l2_min_jobs", 1)
        monkeypatch.setattr(govern_skill_history.settings, "filter_skill_l1_min_jobs", 1)

        govern_skill_history.rebuild_skill_taxonomy_metrics(db)

        db.refresh(canonical_skill)
        db.refresh(polluted_skill)
        db.refresh(python_technology)
        db.refresh(backend_category)
        db.refresh(other_general)
        db.refresh(other_category)

        assert canonical_skill.distinct_job_count == 1
        assert canonical_skill.is_filter_visible is True
        assert python_technology.distinct_job_count == 1
        assert backend_category.distinct_job_count == 1
        assert polluted_skill.distinct_job_count == 0
        assert polluted_skill.is_filter_visible is False
        assert other_general.distinct_job_count == 0
        assert other_general.is_filter_visible is False
        assert other_category.distinct_job_count == 0
        assert other_category.is_filter_visible is False
    finally:
        db.close()


def test_apply_review_candidate_governance_backfills_suggested_hierarchy_for_pending_reviews(
    tmp_path,
):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        job = _create_job(db, company.id, "Database Engineer")
        database_category, sql_technology = _create_skill_hierarchy(db, "Database", "SQL")
        _create_skill(
            db,
            sql_technology.id,
            "PostgreSQL",
            created_by="seed",
            is_auto_created=False,
        )
        candidate = _create_review_candidate(
            db,
            "PostgreSQL",
            "postgresql",
            occurrence_count=1,
            first_seen_job_id=job.id,
            last_seen_job_id=job.id,
        )
        _create_review_candidate_mention(
            db,
            job_id=job.id,
            raw_name="PostgreSQL",
            normalized_name="postgresql",
            review_candidate_id=candidate.id,
        )
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=1)

        report = govern_skill_review_candidates.apply_review_candidate_governance(
            db,
            min_occurrence_count=1,
            curation_path=curations_path,
            execute=True,
        )

        db.refresh(candidate)

        assert report["processed"]["review"] == 1
        assert candidate.status == "pending"
        assert candidate.suggested_category == "Database"
        assert candidate.suggested_technology == "SQL"
    finally:
        db.close()


def test_apply_review_candidate_governance_backfills_suggestions_from_job_context(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        job = _create_job(
            db,
            company.id,
            "Systems Engineer",
            description="Maintain DNS services and network routing for enterprise systems.",
            source_subclassification_name="Networks & Systems Administration",
        )
        candidate = _create_review_candidate(
            db,
            "DNS",
            "dns",
            occurrence_count=1,
            first_seen_job_id=job.id,
            last_seen_job_id=job.id,
        )
        _create_review_candidate_mention(
            db,
            job_id=job.id,
            raw_name="DNS",
            normalized_name="dns",
            review_candidate_id=candidate.id,
        )
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=1)

        govern_skill_review_candidates.apply_review_candidate_governance(
            db,
            min_occurrence_count=1,
            curation_path=curations_path,
            execute=True,
        )

        db.refresh(candidate)

        assert candidate.status == "pending"
        assert candidate.suggested_category == "DevOps"
        assert candidate.suggested_technology == "Networking"
    finally:
        db.close()


def test_audit_review_candidates_includes_recommendations_and_cluster_ids(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, collaboration = _create_skill_hierarchy(db, "Platforms", "Collaboration")
        _create_skill(
            db,
            collaboration.id,
            "Google Workspace",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        job1 = _create_job(db, company.id, "School IT Support")
        job2 = _create_job(db, company.id, "Workspace Administrator")
        candidate1 = _create_review_candidate(
            db,
            "Google Suite",
            "google suite",
            occurrence_count=2,
            first_seen_job_id=job1.id,
            last_seen_job_id=job2.id,
        )
        candidate2 = _create_review_candidate(
            db,
            "Google Workspace Admin",
            "google workspace admin",
            occurrence_count=1,
            first_seen_job_id=job2.id,
            last_seen_job_id=job2.id,
        )
        _create_review_candidate_mention(
            db,
            job_id=job1.id,
            raw_name="Google Suite",
            normalized_name="google suite",
            review_candidate_id=candidate1.id,
        )
        _create_review_candidate_mention(
            db,
            job_id=job2.id,
            raw_name="Google Workspace Admin",
            normalized_name="google workspace admin",
            review_candidate_id=candidate2.id,
        )
        db.commit()

        curations_path = _write_curations(tmp_path, {}, minimum_distinct_jobs=1)

        report = govern_skill_review_candidates.audit_review_candidates(
            db,
            min_occurrence_count=1,
            curation_path=curations_path,
        )

        entries = {
            entry["review_candidate"]["normalized_name"]: entry
            for entry in report["entries"]
        }

        assert entries["google suite"]["recommendations"][0]["skill"] == "Google Workspace"
        assert entries["google workspace admin"]["recommendations"][0]["skill"] == "Google Workspace"
        assert entries["google suite"]["cluster_id"] == entries["google workspace admin"]["cluster_id"]
    finally:
        db.close()


def test_audit_skill_history_only_curated_skips_default_review_entries(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")

        curated_skill = _create_skill(db, other_general.id, "Project Management")
        uncurated_skill = _create_skill(db, other_general.id, "Unmapped Legacy Phrase")
        job1 = _create_job(db, company.id, "Delivery Lead")
        job2 = _create_job(db, company.id, "Support Lead")
        _link_job_skill(db, job1.id, curated_skill.id)
        _link_job_skill(db, job2.id, uncurated_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "project management": {
                    "action": "generic",
                    "generic_tag": "Project Management",
                }
            },
            minimum_distinct_jobs=1,
        )

        report = govern_skill_history.audit_skill_history(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            only_curated=True,
        )

        assert [
            (entry["source_skill"]["name"], entry["action"])
            for entry in report["entries"]
        ] == [("Project Management", "generic")]
    finally:
        db.close()


def test_apply_skill_history_governance_only_curated_skips_uncurated_review_entries(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")

        curated_skill = _create_skill(db, other_general.id, "Project Management")
        uncurated_skill = _create_skill(db, other_general.id, "Unmapped Legacy Phrase")
        job1 = _create_job(db, company.id, "Delivery Lead")
        job2 = _create_job(db, company.id, "Support Lead")
        _link_job_skill(db, job1.id, curated_skill.id)
        _link_job_skill(db, job2.id, uncurated_skill.id)
        db.commit()

        curations_path = _write_curations(
            tmp_path,
            {
                "project management": {
                    "action": "generic",
                    "generic_tag": "Project Management",
                }
            },
            minimum_distinct_jobs=1,
        )

        report = govern_skill_history.apply_skill_history_governance(
            db,
            min_distinct_jobs=1,
            curation_path=curations_path,
            only_curated=True,
            execute=True,
        )

        generic_mentions = (
            db.query(JobSkillMention)
            .filter_by(job_id=job1.id, resolution="generic_tag")
            .all()
        )
        pending_candidates = db.query(SkillReviewCandidate).filter_by(status="pending").all()

        assert report["processed"] == {"merge": 0, "generic": 1, "review": 0}
        assert [(mention.raw_name, mention.generic_tag) for mention in generic_mentions] == [
            ("Project Management", "Project Management")
        ]
        assert pending_candidates == []
        assert db.query(JobSkill).filter(JobSkill.skill_id == uncurated_skill.id).count() == 1
    finally:
        db.close()


def test_collect_verification_snapshot_tolerates_missing_governance_objects():
    db = _build_pre_migration_session()
    try:
        with db.bind.connect() as connection:
            snapshot = verify_migration.collect_verification_snapshot(connection)
            rendered = verify_migration.render_report(snapshot)

        assert snapshot["job_skill_mentions_total"] == 0
        assert snapshot["skill_review_candidates_pending"] == 0
        assert snapshot["polluted_other_general_skills"] == 0
        assert "Raw job skill mentions: 0" in rendered
    finally:
        db.close()
