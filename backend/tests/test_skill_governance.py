import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import (
    Company,
    Job,
    JobCategory,
    JobDomain,
    JobSkillMention,
    JobSkill,
    JobSubcategory,
    Skill,
    SkillCategory,
    SkillTechnology,
)
from app.services.ai_enrichment_service import AIEnrichmentService
from app.services.skill_normalizer import SkillNormalizer
import app.services.ai_enrichment_service as ai_enrichment_module


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
    from app.models.skill_review_candidate import SkillReviewCandidate

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
            SkillReviewCandidate.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_company(db):
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{uuid.uuid4()}",
        name=f"Test Company {uuid.uuid4()}",
    )
    db.add(company)
    db.flush()
    return company


def _create_job_taxonomy(db):
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
        name="Frontend Development",
    )
    db.add(domain)
    db.add(category)
    db.add(subcategory)
    db.flush()
    return subcategory


def _create_skill_taxonomy(db):
    category = SkillCategory(
        id=uuid.uuid4(),
        name="Frontend",
        created_by="seed",
        is_auto_created=False,
    )
    technology = SkillTechnology(
        id=uuid.uuid4(),
        category_id=category.id,
        name="JavaScript",
        created_by="seed",
        is_auto_created=False,
    )
    skill = Skill(
        id=uuid.uuid4(),
        technology_id=technology.id,
        name="React",
        aliases=None,
        created_by="seed",
        is_auto_created=False,
    )
    db.add(category)
    db.add(technology)
    db.add(skill)
    db.flush()
    return skill


def _create_job(db, company_id):
    job = Job(
        id=uuid.uuid4(),
        job_id=f"job-{uuid.uuid4()}",
        source_site="jobsdb",
        company_id=company_id,
        title="Frontend Engineer",
        description="Build React products and coordinate with stakeholders.",
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        source_subclassification_id="1001",
        source_subclassification_name="Developers/Programmers",
        created_at=datetime(2026, 4, 30, 12, 0, 0),
        updated_at=datetime(2026, 4, 30, 12, 0, 0),
    )
    db.add(job)
    db.commit()
    return job


def test_skill_normalizer_flags_generic_terms_without_creating_skills():
    db = _build_sqlite_session()
    try:
        normalizer = SkillNormalizer(db)

        result = normalizer.resolve_extracted_skill(
            {"name": "project management", "kind": "generic", "resolution": "drop"}
        )

        assert result["action"] == "generic_tag"
        assert result["generic_tag"] == "Project Management"
        assert db.query(Skill).count() == 0
    finally:
        db.close()


def test_skill_normalizer_preserves_distinct_review_candidate_keys_for_technical_symbols():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        normalizer = SkillNormalizer(db)

        c_sharp = normalizer.register_review_candidate(raw_name="C#", normalized_name="C#")
        c_plus_plus = normalizer.register_review_candidate(raw_name="C++", normalized_name="C++")
        dotnet = normalizer.register_review_candidate(raw_name=".NET", normalized_name=".NET")

        candidates = (
            db.query(SkillReviewCandidate)
            .order_by(SkillReviewCandidate.normalized_name.asc())
            .all()
        )

        assert c_sharp.normalized_name == "c#"
        assert c_plus_plus.normalized_name == "c++"
        assert dotnet.normalized_name == ".net"
        assert [candidate.normalized_name for candidate in candidates] == [".net", "c#", "c++"]
    finally:
        db.close()


def test_skill_normalizer_prioritizes_generic_policy_over_existing_polluted_skill():
    db = _build_sqlite_session()
    try:
        category = SkillCategory(
            id=uuid.uuid4(),
            name="Other",
            created_by="ai",
            is_auto_created=True,
        )
        technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=category.id,
            name="General",
            created_by="ai",
            is_auto_created=True,
        )
        polluted_skill = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name="Project Management",
            aliases=None,
            created_by="ai",
            is_auto_created=True,
        )
        db.add(category)
        db.add(technology)
        db.add(polluted_skill)
        db.commit()

        normalizer = SkillNormalizer(db)

        result = normalizer.resolve_extracted_skill("Project Management")

        assert result["action"] == "generic_tag"
        assert result["generic_tag"] == "Project Management"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ai_enrichment_service_routes_generic_tags_and_review_candidates():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        react = _create_skill_taxonomy(db)
        job = _create_job(db, company.id)

        class FakeExtractor:
            async def extract(self, **_kwargs):
                return {
                    "classification": {
                        "source_path_decision": {
                            "domain": "Information & Communication Technology",
                            "category": "Software Development",
                            "subcategory": "Frontend Development",
                            "resolution": "match_existing",
                        },
                        "final_taxonomy_decision": {
                            "domain": "Information & Communication Technology",
                            "category": "Software Development",
                            "subcategory": "Frontend Development",
                            "resolution": "match_existing",
                        },
                    },
                    "summary": "Builds frontend applications.",
                    "skills": [
                        {
                            "name": "React",
                            "kind": "technical",
                            "resolution": "match_existing",
                            "existing_skill": "React",
                        },
                        {
                            "name": "Project Management",
                            "kind": "generic",
                            "resolution": "drop",
                        },
                        {
                            "name": "GraphQL",
                            "kind": "technical",
                            "resolution": "unresolved",
                        },
                    ],
                    "confidence": 0.94,
                    "experience": {"experience_level": "mid_level"},
                }

        class FakeJobCategoryNormalizer:
            def __init__(self, _db):
                self._subcategory = subcategory

            def get_taxonomy_candidate_slice(self, **_kwargs):
                return {
                    "source_classification_id": "6281",
                    "source_classification_name": "Information & Communication Technology",
                    "source_subclassification_name": "Developers/Programmers",
                    "allowed_domains": ["Information & Communication Technology"],
                    "allowed_categories": ["Software Development"],
                    "allowed_subcategories": ["Frontend Development"],
                    "default_path": [
                        "Information & Communication Technology",
                        "Software Development",
                        "Frontend Development",
                    ],
                }

            def resolve_taxonomy_decision(self, *_args, **_kwargs):
                return self._subcategory.id

            def get_category_hierarchy(self, _subcategory_id):
                return {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Frontend Development",
                }

        service = AIEnrichmentService()
        service.insight_extractor = FakeExtractor()

        original_normalizer = ai_enrichment_module.JobCategoryNormalizer
        ai_enrichment_module.JobCategoryNormalizer = FakeJobCategoryNormalizer
        try:
            result = await service.enrich_job(job, db)
        finally:
            ai_enrichment_module.JobCategoryNormalizer = original_normalizer

        db.refresh(job)
        linked_skills = db.query(JobSkill).filter(JobSkill.job_id == job.id).all()
        review_candidates = db.query(SkillReviewCandidate).all()

        assert result["status"] == "success"
        assert len(linked_skills) == 1
        assert linked_skills[0].skill_id == react.id
        assert job.ai_generic_tags == ["Project Management"]
        assert len(review_candidates) == 1
        assert review_candidates[0].normalized_name == "graphql"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ai_enrichment_service_writes_skill_mentions_for_all_resolutions():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        react = _create_skill_taxonomy(db)
        job = _create_job(db, company.id)

        class FakeExtractor:
            async def extract(self, **_kwargs):
                return {
                    "classification": {
                        "source_path_decision": {
                            "domain": "Information & Communication Technology",
                            "category": "Software Development",
                            "subcategory": "Frontend Development",
                            "resolution": "match_existing",
                        },
                        "final_taxonomy_decision": {
                            "domain": "Information & Communication Technology",
                            "category": "Software Development",
                            "subcategory": "Frontend Development",
                            "resolution": "match_existing",
                        },
                    },
                    "summary": "Builds frontend applications.",
                    "skills": [
                        {
                            "name": "React",
                            "kind": "technical",
                            "resolution": "match_existing",
                            "existing_skill": "React",
                        },
                        {
                            "name": "Project Management",
                            "kind": "generic",
                            "resolution": "drop",
                        },
                        {
                            "name": "GraphQL",
                            "kind": "technical",
                            "resolution": "unresolved",
                        },
                    ],
                    "confidence": 0.94,
                    "experience": {"experience_level": "mid_level"},
                }

        class FakeJobCategoryNormalizer:
            def __init__(self, _db):
                self._subcategory = subcategory

            def get_taxonomy_candidate_slice(self, **_kwargs):
                return {
                    "source_classification_id": "6281",
                    "source_classification_name": "Information & Communication Technology",
                    "source_subclassification_name": "Developers/Programmers",
                    "allowed_domains": ["Information & Communication Technology"],
                    "allowed_categories": ["Software Development"],
                    "allowed_subcategories": ["Frontend Development"],
                    "default_path": [
                        "Information & Communication Technology",
                        "Software Development",
                        "Frontend Development",
                    ],
                }

            def resolve_taxonomy_decision(self, *_args, **_kwargs):
                return self._subcategory.id

            def get_category_hierarchy(self, _subcategory_id):
                return {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Frontend Development",
                }

        service = AIEnrichmentService()
        service.insight_extractor = FakeExtractor()

        original_normalizer = ai_enrichment_module.JobCategoryNormalizer
        ai_enrichment_module.JobCategoryNormalizer = FakeJobCategoryNormalizer
        try:
            result = await service.enrich_job(job, db)
        finally:
            ai_enrichment_module.JobCategoryNormalizer = original_normalizer

        mentions = (
            db.query(JobSkillMention)
            .filter_by(job_id=job.id)
            .order_by(JobSkillMention.raw_name.asc())
            .all()
        )
        review_candidates = db.query(SkillReviewCandidate).all()

        assert result["status"] == "success"
        assert len(review_candidates) == 1
        assert [(m.raw_name, m.resolution) for m in mentions] == [
            ("GraphQL", "review_candidate"),
            ("Project Management", "generic_tag"),
            ("React", "match_existing"),
        ]
        assert [m.skill_id for m in mentions if m.raw_name == "React"] == [react.id]
        assert [m.generic_tag for m in mentions if m.raw_name == "Project Management"] == [
            "Project Management"
        ]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ai_enrichment_service_reenrichment_replaces_mentions_and_merges_generic_tags():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        _create_skill_taxonomy(db)
        job = _create_job(db, company.id)
        job.ai_generic_tags = ["Legacy Tag"]
        db.commit()

        def build_insight(skills):
            return {
                "classification": {
                    "source_path_decision": {
                        "domain": "Information & Communication Technology",
                        "category": "Software Development",
                        "subcategory": "Frontend Development",
                        "resolution": "match_existing",
                    },
                    "final_taxonomy_decision": {
                        "domain": "Information & Communication Technology",
                        "category": "Software Development",
                        "subcategory": "Frontend Development",
                        "resolution": "match_existing",
                    },
                },
                "summary": "Builds frontend applications.",
                "skills": skills,
                "confidence": 0.94,
                "experience": {"experience_level": "mid_level"},
            }

        class FakeExtractor:
            def __init__(self):
                self._responses = [
                    build_insight(
                        [
                            {
                                "name": "React",
                                "kind": "technical",
                                "resolution": "match_existing",
                                "existing_skill": "React",
                            },
                            {
                                "name": "Project Management",
                                "kind": "generic",
                                "resolution": "drop",
                            },
                            {
                                "name": "GraphQL",
                                "kind": "technical",
                                "resolution": "unresolved",
                            },
                        ]
                    ),
                    build_insight(
                        [
                            {
                                "name": "React",
                                "kind": "technical",
                                "resolution": "match_existing",
                                "existing_skill": "React",
                            },
                            {
                                "name": "project management",
                                "kind": "generic",
                                "resolution": "drop",
                            },
                            {
                                "name": "graphql",
                                "kind": "technical",
                                "resolution": "unresolved",
                            },
                        ]
                    ),
                    build_insight(
                        [
                            {
                                "name": "React",
                                "kind": "technical",
                                "resolution": "match_existing",
                                "existing_skill": "React",
                            },
                            {
                                "name": "Stakeholder Management",
                                "kind": "generic",
                                "resolution": "drop",
                            },
                        ]
                    ),
                ]

            async def extract(self, **_kwargs):
                return self._responses.pop(0)

        class FakeJobCategoryNormalizer:
            def __init__(self, _db):
                self._subcategory = subcategory

            def get_taxonomy_candidate_slice(self, **_kwargs):
                return {
                    "source_classification_id": "6281",
                    "source_classification_name": "Information & Communication Technology",
                    "source_subclassification_name": "Developers/Programmers",
                    "allowed_domains": ["Information & Communication Technology"],
                    "allowed_categories": ["Software Development"],
                    "allowed_subcategories": ["Frontend Development"],
                    "default_path": [
                        "Information & Communication Technology",
                        "Software Development",
                        "Frontend Development",
                    ],
                }

            def resolve_taxonomy_decision(self, *_args, **_kwargs):
                return self._subcategory.id

            def get_category_hierarchy(self, _subcategory_id):
                return {
                    "domain": "Information & Communication Technology",
                    "category": "Software Development",
                    "subcategory": "Frontend Development",
                }

        service = AIEnrichmentService()
        service.insight_extractor = FakeExtractor()

        original_normalizer = ai_enrichment_module.JobCategoryNormalizer
        ai_enrichment_module.JobCategoryNormalizer = FakeJobCategoryNormalizer
        try:
            await service.enrich_job(job, db)
            await service.enrich_job(job, db)

            second_mentions = (
                db.query(JobSkillMention)
                .filter_by(job_id=job.id)
                .order_by(JobSkillMention.raw_name.asc())
                .all()
            )
            second_candidates = db.query(SkillReviewCandidate).all()
            second_generic_mentions = [
                mention for mention in second_mentions if mention.resolution == "generic_tag"
            ]

            assert [(m.raw_name, m.normalized_name, m.resolution) for m in second_mentions] == [
                ("React", "React", "match_existing"),
                ("graphql", "graphql", "review_candidate"),
                ("project management", "Project Management", "generic_tag"),
            ]
            assert [(m.raw_name, m.generic_tag) for m in second_generic_mentions] == [
                ("project management", "Project Management")
            ]
            assert len(second_candidates) == 1
            assert second_candidates[0].normalized_name == "graphql"
            assert second_candidates[0].occurrence_count == 1

            await service.enrich_job(job, db)
        finally:
            ai_enrichment_module.JobCategoryNormalizer = original_normalizer

        db.refresh(job)
        final_mentions = (
            db.query(JobSkillMention)
            .filter_by(job_id=job.id)
            .order_by(JobSkillMention.raw_name.asc())
            .all()
        )
        final_candidates = db.query(SkillReviewCandidate).all()

        assert [(m.raw_name, m.resolution) for m in final_mentions] == [
            ("React", "match_existing"),
            ("Stakeholder Management", "generic_tag"),
        ]
        assert final_candidates[0].normalized_name == "graphql"
        assert final_candidates[0].occurrence_count == 0
        assert set(job.ai_generic_tags or []) == {
            "Legacy Tag",
            "Project Management",
            "Stakeholder Management",
        }
    finally:
        db.close()
