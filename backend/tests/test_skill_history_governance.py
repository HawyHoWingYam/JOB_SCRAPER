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


def _create_job(db, company_id, title):
    job = Job(
        id=uuid.uuid4(),
        job_id=f"job-{uuid.uuid4()}",
        source_site="jobsdb",
        company_id=company_id,
        title=title,
        description=f"{title} description",
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

        with pytest.raises(ValueError, match="20260430_140000"):
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


def test_apply_skill_history_governance_routes_generic_terms_to_job_tags(tmp_path):
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        _, other_general = _create_skill_hierarchy(db, "Other", "General")
        polluted_skill = _create_skill(db, other_general.id, "Project Management")
        job = _create_job(db, company.id, "Delivery Lead")
        job.ai_generic_tags = ["Existing Tag", "project management"]
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

        db.refresh(job)
        assert job.ai_generic_tags == ["Existing Tag", "Project Management"]
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


def test_collect_verification_snapshot_tolerates_missing_governance_objects():
    db = _build_pre_migration_session()
    try:
        with db.bind.connect() as connection:
            snapshot = verify_migration.collect_verification_snapshot(connection)
            rendered = verify_migration.render_report(snapshot)

        assert snapshot["job_skill_mentions_total"] == 0
        assert snapshot["jobs_with_generic_tags"] == 0
        assert snapshot["skill_review_candidates_pending"] == 0
        assert snapshot["polluted_other_general_skills"] == 0
        assert "Raw job skill mentions: 0" in rendered
    finally:
        db.close()
