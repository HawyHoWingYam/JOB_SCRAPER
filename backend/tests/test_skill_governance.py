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


def test_skill_normalizer_canonicalizes_uat_into_generic_user_acceptance_testing():
    db = _build_sqlite_session()
    try:
        normalizer = SkillNormalizer(db)

        result = normalizer.resolve_extracted_skill("UAT")

        assert result["action"] == "generic_tag"
        assert result["generic_tag"] == "User Acceptance Testing"
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


def test_skill_normalizer_does_not_match_c_plus_plus_to_existing_c_sharp():
    db = _build_sqlite_session()
    try:
        backend = SkillCategory(
            id=uuid.uuid4(),
            name="Backend",
            created_by="seed",
            is_auto_created=False,
        )
        dotnet = SkillTechnology(
            id=uuid.uuid4(),
            category_id=backend.id,
            name=".NET",
            created_by="seed",
            is_auto_created=False,
        )
        c_sharp = Skill(
            id=uuid.uuid4(),
            technology_id=dotnet.id,
            name="C#",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        db.add(backend)
        db.add(dotnet)
        db.add(c_sharp)
        db.commit()

        normalizer = SkillNormalizer(db)

        result = normalizer.resolve_extracted_skill(
            {"name": "C++", "kind": "technical", "resolution": "unresolved"}
        )

        assert result["action"] == "review_candidate"
        assert result["raw_name"] == "C++"
        assert normalizer.normalize_review_candidate_key(result["normalized_name"]) == "c++"
    finally:
        db.close()


def test_skill_normalizer_preserves_non_ascii_review_candidate_keys():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        normalizer = SkillNormalizer(db)

        chinese = normalizer.register_review_candidate(
            raw_name="人工智能",
            normalized_name="人工智能",
        )
        chinese_alt = normalizer.register_review_candidate(
            raw_name="数据治理",
            normalized_name="数据治理",
        )

        candidates = (
            db.query(SkillReviewCandidate)
            .order_by(SkillReviewCandidate.raw_name.asc())
            .all()
        )

        assert chinese.normalized_name == "人工智能"
        assert chinese_alt.normalized_name == "数据治理"
        assert [candidate.normalized_name for candidate in candidates] == ["人工智能", "数据治理"]
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


def test_skill_normalizer_does_not_treat_other_general_auto_skill_as_canonical_match():
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
        polluted = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name="Linux",
            created_by="ai",
            is_auto_created=True,
        )
        db.add_all([category, technology, polluted])
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill(
            {"name": "Linux", "kind": "technical", "resolution": "match_existing"}
        )

        assert decision["action"] == "review_candidate"
        assert decision["normalized_name"] == "Linux"
    finally:
        db.close()


def test_skill_normalizer_matches_canonical_alias_on_non_polluted_canonical_skill():
    db = _build_sqlite_session()
    try:
        category = SkillCategory(
            id=uuid.uuid4(),
            name="DevOps",
            created_by="seed",
            is_auto_created=False,
        )
        technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=category.id,
            name="Cloud Platforms",
            created_by="seed",
            is_auto_created=False,
        )
        azure = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name="Azure",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        db.add_all([category, technology, azure])
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill("Microsoft Azure")

        assert decision["action"] == "match_existing"
        assert decision["skill_id"] == azure.id
        assert decision["skill_name"] == "Azure"
    finally:
        db.close()


@pytest.mark.parametrize(
    ("skill_name", "raw_input"),
    [
        ("Google Workspace", "Google Suite"),
        ("ManageBac", "Manage Bac"),
        ("SSIS", "SQL Server Integration Services"),
        ("Zoom", "Zoom Meetings"),
    ],
)
def test_skill_normalizer_matches_high_value_promoted_skill_aliases(skill_name, raw_input):
    db = _build_sqlite_session()
    try:
        category = SkillCategory(
            id=uuid.uuid4(),
            name="Platforms",
            created_by="seed",
            is_auto_created=False,
        )
        technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=category.id,
            name="Collaboration",
            created_by="seed",
            is_auto_created=False,
        )
        skill = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name=skill_name,
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        db.add_all([category, technology, skill])
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill(raw_input)

        assert decision["action"] == "match_existing"
        assert decision["skill_id"] == skill.id
        assert decision["skill_name"] == skill_name
    finally:
        db.close()


@pytest.mark.parametrize(
    ("skill_name", "technology_name", "raw_input"),
    [
        ("Jira", "Collaboration Tools", "Jira"),
        ("Product Management", "Product Management", "Product Management"),
        ("Help Desk Support", "Service & Support", "Help Desk Support"),
    ],
)
def test_skill_normalizer_role_mode_product_ba_support_allows_canonical_match_for_domain_skills(
    skill_name,
    technology_name,
    raw_input,
):
    db = _build_sqlite_session()
    try:
        category = SkillCategory(
            id=uuid.uuid4(),
            name="Product & Delivery" if technology_name != "Service & Support" else "Support & Operations",
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
        skill = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name=skill_name,
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        db.add_all([category, technology, skill])
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill(
            {"name": raw_input, "kind": "technical", "resolution": "unresolved"},
            role_mode="product_ba_support",
        )

        assert decision["action"] == "match_existing"
        assert decision["skill_id"] == skill.id
        assert decision["skill_name"] == skill_name
    finally:
        db.close()


def test_skill_normalizer_prefers_legitimate_duplicate_over_polluted_other_general_skill():
    db = _build_sqlite_session()
    try:
        canonical_category = SkillCategory(
            id=uuid.uuid4(),
            name="Infrastructure",
            created_by="seed",
            is_auto_created=False,
        )
        canonical_technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=canonical_category.id,
            name="Operating Systems",
            created_by="seed",
            is_auto_created=False,
        )
        canonical_skill = Skill(
            id=uuid.uuid4(),
            technology_id=canonical_technology.id,
            name="Linux",
            created_by="seed",
            is_auto_created=False,
        )
        polluted_category = SkillCategory(
            id=uuid.uuid4(),
            name="Other",
            created_by="ai",
            is_auto_created=True,
        )
        polluted_technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=polluted_category.id,
            name="General",
            created_by="ai",
            is_auto_created=True,
        )
        polluted_skill = Skill(
            id=uuid.uuid4(),
            technology_id=polluted_technology.id,
            name="Linux",
            created_by="ai",
            is_auto_created=True,
        )
        db.add_all(
            [
                canonical_category,
                canonical_technology,
                canonical_skill,
                polluted_category,
                polluted_technology,
                polluted_skill,
            ]
        )
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill(
            {"name": "Linux", "kind": "technical", "resolution": "match_existing"}
        )

        assert decision["action"] == "match_existing"
        assert decision["skill_id"] == canonical_skill.id
        assert decision["skill_name"] == "Linux"
    finally:
        db.close()


def test_skill_normalizer_uses_existing_skill_hint_after_polluted_exact_hit():
    db = _build_sqlite_session()
    try:
        canonical_category = SkillCategory(
            id=uuid.uuid4(),
            name="Infrastructure",
            created_by="seed",
            is_auto_created=False,
        )
        canonical_technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=canonical_category.id,
            name="Containers",
            created_by="seed",
            is_auto_created=False,
        )
        canonical_skill = Skill(
            id=uuid.uuid4(),
            technology_id=canonical_technology.id,
            name="Kubernetes",
            created_by="seed",
            is_auto_created=False,
        )
        polluted_category = SkillCategory(
            id=uuid.uuid4(),
            name="Other",
            created_by="ai",
            is_auto_created=True,
        )
        polluted_technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=polluted_category.id,
            name="General",
            created_by="ai",
            is_auto_created=True,
        )
        polluted_skill = Skill(
            id=uuid.uuid4(),
            technology_id=polluted_technology.id,
            name="K8s",
            created_by="ai",
            is_auto_created=True,
        )
        db.add_all(
            [
                canonical_category,
                canonical_technology,
                canonical_skill,
                polluted_category,
                polluted_technology,
                polluted_skill,
            ]
        )
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill(
            {
                "name": "K8s",
                "existing_skill": "Kubernetes",
                "kind": "technical",
                "resolution": "match_existing",
            }
        )

        assert decision["action"] == "match_existing"
        assert decision["skill_id"] == canonical_skill.id
        assert decision["skill_name"] == "Kubernetes"
    finally:
        db.close()


def test_skill_normalizer_rejects_suppressed_review_terms_even_with_canonical_skill():
    db = _build_sqlite_session()
    try:
        category = SkillCategory(
            id=uuid.uuid4(),
            name="Data",
            created_by="seed",
            is_auto_created=False,
        )
        technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=category.id,
            name="Business Intelligence",
            created_by="seed",
            is_auto_created=False,
        )
        skill = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name="Data Analysis",
            created_by="seed",
            is_auto_created=False,
        )
        db.add_all([category, technology, skill])
        db.commit()

        decision = SkillNormalizer(db).resolve_extracted_skill(
            {
                "name": "Data analysis",
                "kind": "technical",
                "resolution": "match_existing",
                "existing_skill": "Data Analysis",
            }
        )

        assert decision == {
            "action": "reject",
            "reason": "suppressed_review_term",
            "raw_name": "Data analysis",
            "normalized_name": "Data analysis",
        }
    finally:
        db.close()


def test_skill_normalizer_rejects_suppressed_review_terms():
    db = _build_sqlite_session()
    try:
        decision = SkillNormalizer(db).resolve_extracted_skill(
            {
                "name": "IT systems administration",
                "kind": "technical",
                "resolution": "unresolved",
            }
        )

        assert decision == {
            "action": "reject",
            "reason": "suppressed_review_term",
            "raw_name": "IT systems administration",
            "normalized_name": "IT systems administration",
        }
    finally:
        db.close()


def test_skill_normalizer_candidate_slice_uses_description_and_source_context():
    db = _build_sqlite_session()
    try:
        devops = SkillCategory(
            id=uuid.uuid4(),
            name="DevOps",
            created_by="seed",
            is_auto_created=False,
        )
        operating_systems = SkillTechnology(
            id=uuid.uuid4(),
            category_id=devops.id,
            name="Operating Systems",
            created_by="seed",
            is_auto_created=False,
        )
        windows_server = Skill(
            id=uuid.uuid4(),
            technology_id=operating_systems.id,
            name="Windows Server",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        linux = Skill(
            id=uuid.uuid4(),
            technology_id=operating_systems.id,
            name="Linux",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        db.add_all([devops, operating_systems, windows_server, linux])
        db.commit()

        candidate_slice = SkillNormalizer(db).get_taxonomy_candidate_slice(
            "Platform Specialist",
            description="Administer Windows Server and Linux production infrastructure.",
            source_subclassification_name="Networks & Systems Administration",
        )

        assert candidate_slice["category_hint"] == "DevOps"
        assert candidate_slice["technology_hint"] == "Operating Systems"
        assert "Windows Server" in candidate_slice["existing_skills"]
    finally:
        db.close()


def test_skill_normalizer_candidate_slice_separates_review_and_suppressed_terms():
    db = _build_sqlite_session()
    try:
        candidate_slice = SkillNormalizer(db).get_taxonomy_candidate_slice(
            "Systems Engineer",
            description=(
                "Provide IT systems administration support, manage DNS services, "
                "and maintain network operations."
            ),
            source_subclassification_name="Networks & Systems Administration",
        )

        assert "DNS" in candidate_slice["review_only_terms"]
        assert "it systems administration" in candidate_slice["suppressed_review_terms"]
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
        generic_mentions = (
            db.query(JobSkillMention)
            .filter_by(job_id=job.id, resolution="generic_tag")
            .all()
        )
        assert not hasattr(job, "ai_generic_tags")
        assert [(mention.raw_name, mention.generic_tag) for mention in generic_mentions] == [
            ("Project Management", "Project Management")
        ]
        assert len(review_candidates) == 1
        assert review_candidates[0].normalized_name == "graphql"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ai_enrichment_service_drops_suppressed_review_terms_without_creating_mentions():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        react = _create_skill_taxonomy(db)
        job = _create_job(db, company.id)
        captured = {}

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
                    "summary": "Supports infra and apps.",
                    "skills": [
                        {
                            "name": "React",
                            "kind": "technical",
                            "resolution": "match_existing",
                            "existing_skill": "React",
                        },
                        {
                            "name": "IT systems administration",
                            "kind": "technical",
                            "resolution": "unresolved",
                        },
                        {
                            "name": "DNS",
                            "kind": "technical",
                            "resolution": "unresolved",
                        },
                    ],
                    "confidence": 0.9,
                    "experience": {"experience_level": "mid_level"},
                }

        class FakeSkillNormalizer:
            def __init__(self, _db):
                self._skill_id = react.id

            def get_taxonomy_candidate_slice(self, *_args, **_kwargs):
                return {
                    "category_hint": "DevOps",
                    "technology_hint": "Networking",
                    "existing_categories": ["DevOps"],
                    "existing_technologies": ["Networking"],
                    "existing_skills": ["React"],
                    "review_only_terms": ["DNS"],
                    "suppressed_review_terms": ["it systems administration"],
                }

            def resolve_extracted_skill(self, payload, **_kwargs):
                name = payload["name"]
                if name == "React":
                    return {
                        "action": "match_existing",
                        "skill_id": self._skill_id,
                        "skill_name": "React",
                    }
                if name == "IT systems administration":
                    return {
                        "action": "reject",
                        "reason": "suppressed_review_term",
                        "raw_name": name,
                        "normalized_name": name,
                    }
                return {
                    "action": "review_candidate",
                    "raw_name": name,
                    "normalized_name": name,
                    "suggested_category": None,
                    "suggested_technology": None,
                }

            def register_review_candidate(
                self,
                *,
                raw_name,
                normalized_name,
                job_id=None,
                suggested_category=None,
                suggested_technology=None,
                description="",
                source_subclassification_name=None,
            ):
                captured["raw_name"] = raw_name
                captured["normalized_name"] = normalized_name
                captured["description"] = description
                captured["source_subclassification_name"] = source_subclassification_name
                candidate = SkillReviewCandidate(
                    id=uuid.uuid4(),
                    raw_name=raw_name,
                    normalized_name=normalized_name.lower(),
                    suggested_category=suggested_category,
                    suggested_technology=suggested_technology,
                    first_seen_job_id=job_id,
                    last_seen_job_id=job_id,
                )
                db.add(candidate)
                db.flush()
                return candidate

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

        service = AIEnrichmentService()
        service.insight_extractor = FakeExtractor()

        original_skill_normalizer = ai_enrichment_module.SkillNormalizer
        original_job_normalizer = ai_enrichment_module.JobCategoryNormalizer
        ai_enrichment_module.SkillNormalizer = FakeSkillNormalizer
        ai_enrichment_module.JobCategoryNormalizer = FakeJobCategoryNormalizer
        try:
            result = await service.enrich_job(job, db)
        finally:
            ai_enrichment_module.SkillNormalizer = original_skill_normalizer
            ai_enrichment_module.JobCategoryNormalizer = original_job_normalizer

        mentions = (
            db.query(JobSkillMention)
            .filter_by(job_id=job.id)
            .order_by(JobSkillMention.raw_name.asc())
            .all()
        )

        assert result["status"] == "success"
        assert [(mention.raw_name, mention.resolution) for mention in mentions] == [
            ("DNS", "review_candidate"),
            ("React", "match_existing"),
        ]
        assert captured == {
            "raw_name": "DNS",
            "normalized_name": "DNS",
            "description": "Build React products and coordinate with stakeholders.",
            "source_subclassification_name": "Developers/Programmers",
        }
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ai_enrichment_service_passes_description_and_source_context_to_skill_candidates():
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        react = _create_skill_taxonomy(db)
        job = _create_job(db, company.id)
        job.title = "Platform Specialist"
        job.description = "Administer Windows Server and Linux production infrastructure."
        job.source_subclassification_name = "Networks & Systems Administration"
        db.commit()

        captured = {}

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
                        }
                    ],
                    "confidence": 0.94,
                    "experience": {"experience_level": "mid_level"},
                }

        class FakeSkillNormalizer:
            def __init__(self, _db):
                self._skill_id = react.id

            def get_taxonomy_candidate_slice(
                self,
                title,
                *,
                description="",
                source_subclassification_name=None,
                limit=10,
                role_mode=None,
            ):
                captured["title"] = title
                captured["description"] = description
                captured["source_subclassification_name"] = source_subclassification_name
                captured["limit"] = limit
                captured["role_mode"] = role_mode
                return {
                    "category_hint": "Frontend",
                    "technology_hint": "JavaScript",
                    "existing_categories": ["Frontend"],
                    "existing_technologies": ["JavaScript"],
                    "existing_skills": ["React"],
                    "review_only_terms": [],
                }

            def resolve_extracted_skill(self, _payload, **_kwargs):
                return {
                    "action": "match_existing",
                    "skill_id": self._skill_id,
                    "skill_name": "React",
                }

        class FakeJobCategoryNormalizer:
            def __init__(self, _db):
                self._subcategory = subcategory

            def get_taxonomy_candidate_slice(self, **_kwargs):
                return {
                    "source_classification_id": "6281",
                    "source_classification_name": "Information & Communication Technology",
                    "source_subclassification_name": "Networks & Systems Administration",
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

        service = AIEnrichmentService()
        service.insight_extractor = FakeExtractor()

        original_skill_normalizer = ai_enrichment_module.SkillNormalizer
        original_job_normalizer = ai_enrichment_module.JobCategoryNormalizer
        ai_enrichment_module.SkillNormalizer = FakeSkillNormalizer
        ai_enrichment_module.JobCategoryNormalizer = FakeJobCategoryNormalizer
        try:
            result = await service.enrich_job(job, db)
        finally:
            ai_enrichment_module.SkillNormalizer = original_skill_normalizer
            ai_enrichment_module.JobCategoryNormalizer = original_job_normalizer

        assert result["status"] == "success"
        assert captured == {
            "title": "Platform Specialist",
            "description": "Administer Windows Server and Linux production infrastructure.",
            "source_subclassification_name": "Networks & Systems Administration",
            "limit": 10,
            "role_mode": "technical_heavy",
        }
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
async def test_ai_enrichment_service_drops_suppressed_review_terms_even_with_canonical_skill():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        category = SkillCategory(
            id=uuid.uuid4(),
            name="Data",
            created_by="seed",
            is_auto_created=False,
        )
        technology = SkillTechnology(
            id=uuid.uuid4(),
            category_id=category.id,
            name="Business Intelligence",
            created_by="seed",
            is_auto_created=False,
        )
        data_analysis = Skill(
            id=uuid.uuid4(),
            technology_id=technology.id,
            name="Data Analysis",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        db.add_all([category, technology, data_analysis])
        db.flush()
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
                    "summary": "Analyzes delivery metrics.",
                    "skills": [
                        {
                            "name": "Data analysis",
                            "kind": "technical",
                            "resolution": "match_existing",
                            "existing_skill": "Data Analysis",
                        }
                    ],
                    "confidence": 0.91,
                    "experience": {"experience_level": "mid_level"},
                }

        class FakeJobCategoryNormalizer:
            def __init__(self, _db):
                self._subcategory = subcategory

            def get_taxonomy_candidate_slice(self, **_kwargs):
                return {
                    "source_classification_id": "6281",
                    "source_classification_name": "Information & Communication Technology",
                    "source_subclassification_name": "Business/Systems Analysts",
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

        service = AIEnrichmentService()
        service.insight_extractor = FakeExtractor()

        original_normalizer = ai_enrichment_module.JobCategoryNormalizer
        ai_enrichment_module.JobCategoryNormalizer = FakeJobCategoryNormalizer
        try:
            result = await service.enrich_job(job, db)
        finally:
            ai_enrichment_module.JobCategoryNormalizer = original_normalizer

        mentions = db.query(JobSkillMention).filter_by(job_id=job.id).all()
        review_candidates = db.query(SkillReviewCandidate).all()
        linked_skills = db.query(JobSkill).filter_by(job_id=job.id).all()

        assert result["status"] == "success"
        assert len(linked_skills) == 0
        assert mentions == []
        assert review_candidates == []
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ai_enrichment_service_reenrichment_replaces_mentions_without_job_generic_tags():
    from app.models.skill_review_candidate import SkillReviewCandidate

    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        _create_skill_taxonomy(db)
        job = _create_job(db, company.id)
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
        assert not hasattr(job, "ai_generic_tags")
        assert [(m.raw_name, m.generic_tag) for m in final_mentions if m.resolution == "generic_tag"] == [
            ("Stakeholder Management", "Stakeholder Management")
        ]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_ai_enrichment_service_reenrichment_removes_stale_ai_job_skills():
    db = _build_sqlite_session()
    try:
        company = _create_company(db)
        subcategory = _create_job_taxonomy(db)
        react = _create_skill_taxonomy(db)
        vue = Skill(
            id=uuid.uuid4(),
            technology_id=react.technology_id,
            name="Vue.js",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        angular = Skill(
            id=uuid.uuid4(),
            technology_id=react.technology_id,
            name="Angular",
            aliases=None,
            created_by="seed",
            is_auto_created=False,
        )
        db.add(vue)
        db.add(angular)
        db.flush()

        job = _create_job(db, company.id)
        db.add(
            JobSkill(
                job_id=job.id,
                skill_id=angular.id,
                source="manual",
                confidence=None,
            )
        )
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
                                "name": "Vue.js",
                                "kind": "technical",
                                "resolution": "match_existing",
                                "existing_skill": "Vue.js",
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
        finally:
            ai_enrichment_module.JobCategoryNormalizer = original_normalizer

        job_skills = (
            db.query(JobSkill)
            .filter(JobSkill.job_id == job.id)
            .order_by(JobSkill.source.asc(), JobSkill.skill_id.asc())
            .all()
        )
        ai_skill_ids = sorted(
            job_skill.skill_id for job_skill in job_skills if job_skill.source == "ai"
        )
        manual_skill_ids = sorted(
            job_skill.skill_id for job_skill in job_skills if job_skill.source == "manual"
        )

        assert ai_skill_ids == [react.id]
        assert manual_skill_ids == [angular.id]
        assert vue.id not in [job_skill.skill_id for job_skill in job_skills]
    finally:
        db.close()
