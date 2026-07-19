from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.api.job_intelligence import (
    list_job_taxonomy_audit_events,
    read_job_intelligence_governance_summary,
)
from app.api import ai as ai_api
from app.api.companies import get_company, list_companies
from app.api.jobs import (
    _apply_structured_filters,
    _build_search_response_from_results,
    get_job,
)
from app.api.stats import get_dashboard_category_stats
from app.database import Base
from app.job_intelligence.foundation import Provenance
from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.job_intelligence.source_attributes import (
    EMPLOYMENT_TYPE_SEEDS,
    JobsDBSourceEvidenceAdapter,
    SourceJobAttributes,
)
from app.models.canonical_job_taxonomy import (
    CANONICAL_JOB_TAXONOMY_TABLES,
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveRevision,
    CanonicalJobTaxonomyRelease,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.company import Company
from app.models.company_industry import (
    COMPANY_INDUSTRY_TABLES,
    CompanyIndustryActiveRevision,
    CompanyIndustryAssignment,
    CompanyIndustryReviewItem,
    CompanyIndustryTaxonomyNode,
    CompanyIndustryTaxonomyRelease,
)
from app.models.governance import (
    GOVERNANCE_FOUNDATION_TABLES,
    GovernanceAuditEvent,
    GovernanceRevision,
)
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_embedding import EMBEDDING_DIMENSIONS, JobEmbedding
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.skill_governance import (
    SKILL_GOVERNANCE_TABLES,
    GovernedJobSkill,
    GovernedJobSkillMention,
    GovernedSkill,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
    SkillTaxonomyRelease,
)
from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogCandidate,
    SourceCatalogRevision,
)
from app.models.source_job_attributes import (
    SOURCE_JOB_ATTRIBUTE_TABLES,
    EmploymentType,
)
from app.schemas.job_intelligence_product import (
    JobIntelligenceProductFixtureSchema,
)
from app.schemas.job import JobDetailSchema
from app.schemas.job_search import JobSearchFiltersSchema
from app.schemas.recommendations import JobRecommendationSchema
from app.services.job_recommendation_service import JobRecommendationService


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "job_intelligence_product_surfaces.json"
)
FRONTEND_FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "frontend"
    / "src"
    / "fixtures"
    / "job_intelligence_product_surfaces.json"
)
FRONTEND_DOMAIN_FIXTURE_PAIRS = tuple(
    (
        Path(__file__).parent / "fixtures" / filename,
        Path(__file__).parents[2] / "frontend" / "src" / "fixtures" / filename,
    )
    for filename in (
        "canonical_job_taxonomy_responses.json",
        "skill_governance_responses.json",
        "company_industry_responses.json",
    )
)


@pytest.fixture
def product_contract_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not database_url.rsplit("/", 1)[-1].endswith("_test"):
        pytest.fail("Product response contracts require a dedicated *_test database")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    tables = (
        JobDomain.__table__,
        JobCategory.__table__,
        JobSubcategory.__table__,
        Company.__table__,
        Job.__table__,
        JobEmbedding.__table__,
        SourceCatalogCandidate.__table__,
        SourceCatalogRevision.__table__,
        SourceCatalogActiveRevision.__table__,
        EventOutbox.__table__,
        *GOVERNANCE_FOUNDATION_TABLES,
        *SOURCE_JOB_ATTRIBUTE_TABLES,
        *CANONICAL_JOB_TAXONOMY_TABLES,
        *COMPANY_INDUSTRY_TABLES,
        *SKILL_GOVERNANCE_TABLES,
    )
    Base.metadata.drop_all(engine, tables=list(reversed(tables)), checkfirst=True)
    Base.metadata.create_all(engine, tables=list(tables))
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    session.add_all(
        EmploymentType(code=code, label=label, sort_order=sort_order)
        for code, label, sort_order in EMPLOYMENT_TYPE_SEEDS
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(
            engine,
            tables=list(reversed(tables)),
            checkfirst=True,
        )
        engine.dispose()


def _seed_summary_state(db) -> dict[str, object]:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    canonical_revision_id = uuid4()
    skill_revision_id = uuid4()
    industry_revision_id = uuid4()
    revisions = (
        (canonical_revision_id, "canonical-job-taxonomy", "canonical-v1", "a"),
        (skill_revision_id, "skill-taxonomy", "skills-v1", "b"),
        (industry_revision_id, "company-industry", "hsic-v2", "c"),
    )
    for revision_id, domain, release_key, hash_character in revisions:
        db.add(
            GovernanceRevision(
                id=revision_id,
                domain=domain,
                release_key=release_key,
                content_hash=hash_character * 64,
                source_metadata={},
                created_at=now,
                published_at=now,
            )
        )
    db.flush()

    db.add_all(
        [
            CanonicalJobTaxonomyRelease(
                revision_id=canonical_revision_id,
                content_hash="a" * 64,
                expected_domain_count=0,
                expected_category_count=0,
                expected_subcategory_count=0,
                materialized_domain_count=0,
                materialized_category_count=0,
                materialized_subcategory_count=0,
                status="ready",
                ready_at=now,
            ),
            SkillTaxonomyRelease(
                revision_id=skill_revision_id,
                content_hash="b" * 64,
                taxonomy_hash="d" * 64,
                rules_hash="e" * 64,
                backfill_hash="f" * 64,
                rules_document={},
                backfill_document={},
                expected_category_count=0,
                expected_technology_count=0,
                expected_skill_count=0,
                expected_alias_count=0,
                materialized_category_count=0,
                materialized_technology_count=0,
                materialized_skill_count=0,
                materialized_alias_count=0,
                status="ready",
                ready_at=now,
            ),
            CompanyIndustryTaxonomyRelease(
                revision_id=industry_revision_id,
                standard="HSIC",
                release="V2.0",
                content_hash="c" * 64,
                source_metadata={},
                expected_counts={},
                materialized_counts={},
                expected_total=0,
                materialized_total=0,
                status="ready",
                ready_at=now,
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            CanonicalJobTaxonomyActiveRevision(
                revision_id=canonical_revision_id,
                content_hash="a" * 64,
                lock_version=1,
                activated_at=now,
            ),
            SkillTaxonomyActiveRevision(
                revision_id=skill_revision_id,
                content_hash="b" * 64,
                lock_version=1,
                activated_at=now,
            ),
            CompanyIndustryActiveRevision(
                revision_id=industry_revision_id,
                content_hash="c" * 64,
                lock_version=1,
                activated_at=now,
            ),
        ]
    )

    company_one = Company(
        company_id="product-company-1",
        source_site="jobsdb",
        source_company_id="product-company-1",
        name="Product Company One",
    )
    company_two = Company(
        company_id="product-company-2",
        source_site="offertoday",
        source_company_id="product-company-2",
        name="Product Company Two",
    )
    job_one = Job(
        job_id="product-job-1",
        source_site="jobsdb",
        source_job_id="product-job-1",
        company=company_one,
        title="Product Job One",
    )
    job_two = Job(
        job_id="product-job-2",
        source_site="offertoday",
        source_job_id="product-job-2",
        company=company_two,
        title="Product Job Two",
    )
    db.add_all([job_one, job_two])
    db.flush()

    canonical_review = JobTaxonomyReviewItem(
        job_id=job_one.id,
        taxonomy_revision_id=canonical_revision_id,
        status="active",
        reasons=["classifier_provenance_missing"],
        evidence_hash="1" * 64,
        evidence_refs=[],
        recommendations=[],
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    skill_candidate = SkillCandidate(
        taxonomy_revision_id=skill_revision_id,
        normalized_key="rust",
        canonical_raw_name="Rust",
        raw_variants=["Rust"],
        status="pending",
        occurrence_count=1,
        distinct_job_count=1,
        evidence_summary={},
        recommendations=[],
        lock_version=1,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add_all(
        [
            canonical_review,
            skill_candidate,
            CompanyIndustryReviewItem(
                company_id=company_two.id,
                taxonomy_revision_id=industry_revision_id,
                source_site="offertoday",
                key_kind="label",
                raw_value="Technology",
                normalized_key="technology",
                reason="unmapped_source_evidence",
                status="active",
                evidence_hash="2" * 64,
                provenance={},
                recommendations=[],
                lock_version=1,
                created_at=now,
                updated_at=now,
            ),
            GovernanceAuditEvent(
                domain="job-taxonomy",
                subject_type="job-taxonomy-review-item",
                subject_id="product-review-item",
                action="mark_insufficient_evidence",
                actor="local-operator",
                command_hash="3" * 64,
                idempotency_key="product-summary-audit",
                before_summary={"status": "active"},
                after_summary={"status": "insufficient_evidence"},
                evidence_refs=[{"kind": "job", "id": str(job_one.id)}],
                correlation_id="product-summary-audit",
                created_at=now,
            ),
        ]
    )
    db.commit()
    return {
        "canonical_revision_id": canonical_revision_id,
        "skill_revision_id": skill_revision_id,
        "industry_revision_id": industry_revision_id,
        "job_one_id": job_one.id,
        "canonical_review_id": canonical_review.id,
        "skill_candidate_id": skill_candidate.id,
        "now": now,
    }


def _seed_rich_job_detail_state(db) -> dict[str, object]:
    state = _seed_summary_state(db)
    now = state["now"]
    company = Company(
        company_id="product-company-rich",
        source_site="jobsdb",
        source_company_id="product-company-rich",
        name="Product Company Rich",
        industry="Legacy evidence only",
    )
    job = Job(
        job_id="product-job-rich",
        source_site="jobsdb",
        source_job_id="product-job-rich",
        company=company,
        title="Platform Engineer",
    )
    db.add(job)
    db.flush()

    source_evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    },
                    "subclassification": {
                        "id": "6287",
                        "description": "Developers and Programmers",
                    },
                }
            ],
            "workTypes": ["Full-time", "Permanent"],
        },
        provenance=Provenance(
            method="jobsdb-listing-payload",
            source_site="jobsdb",
            evidence_refs=(
                {
                    "kind": "listing-payload",
                    "source_job_id": "product-job-rich",
                },
            ),
            captured_at=now,
        ),
    )
    SourceJobAttributes(db).project(job.id, source_evidence)

    canonical_domain = CanonicalJobDomain(
        revision_id=state["canonical_revision_id"],
        code="technology",
        label="Technology",
        source_order=1,
    )
    db.add(canonical_domain)
    db.flush()
    canonical_category = CanonicalJobCategory(
        revision_id=state["canonical_revision_id"],
        domain_id=canonical_domain.id,
        code="software-development",
        label="Software Development",
        source_order=1,
    )
    db.add(canonical_category)
    db.flush()
    canonical_subcategory = CanonicalJobSubcategory(
        revision_id=state["canonical_revision_id"],
        category_id=canonical_category.id,
        code="backend-development",
        label="Backend Development",
        source_order=1,
        is_assignable=True,
    )
    db.add(canonical_subcategory)
    db.flush()
    canonical_assignment = JobTaxonomyAssignment(
        job_id=job.id,
        taxonomy_revision_id=state["canonical_revision_id"],
        subcategory_id=canonical_subcategory.id,
        method="constrained_ai",
        evidence_hash="4" * 64,
        source_evidence_refs=[
            {"kind": "source-classification-path", "id": "jobsdb:6281"}
        ],
        mapping_ids=[],
        model_provider="openai",
        model_name="fixture-model",
        model_version="2026-07-19",
        breadcrumb={
            "domain": {
                "id": str(canonical_domain.id),
                "code": canonical_domain.code,
                "label": canonical_domain.label,
            },
            "category": {
                "id": str(canonical_category.id),
                "code": canonical_category.code,
                "label": canonical_category.label,
            },
            "subcategory": {
                "id": str(canonical_subcategory.id),
                "code": canonical_subcategory.code,
                "label": canonical_subcategory.label,
            },
        },
        lock_version=1,
        is_current=True,
        captured_at=now,
    )

    industry_section = CompanyIndustryTaxonomyNode(
        revision_id=state["industry_revision_id"],
        code="J",
        parent_id=None,
        level="section",
        label_en="Information and communications",
        label_zh_hant="資訊及通訊",
        label_zh_hans="资讯及通讯",
        source_order=1,
        is_assignable=True,
        source_metadata={},
    )
    db.add(industry_section)
    db.flush()
    industry_node = CompanyIndustryTaxonomyNode(
        revision_id=state["industry_revision_id"],
        code="58",
        parent_id=industry_section.id,
        level="division",
        label_en="Publishing activities",
        label_zh_hant="出版活動",
        label_zh_hans="出版活动",
        source_order=2,
        is_assignable=True,
        source_metadata={},
    )
    db.add(industry_node)
    db.flush()
    industry_assignment = CompanyIndustryAssignment(
        company_id=company.id,
        taxonomy_revision_id=state["industry_revision_id"],
        node_id=industry_node.id,
        method="authoritative_code",
        provenance={"method": "source-hsic-code"},
        evidence_hash="5" * 64,
        breadcrumb=[
            {
                "id": str(industry_section.id),
                "code": industry_section.code,
                "level": industry_section.level,
                "labels": {
                    "en": industry_section.label_en,
                    "zh_hant": industry_section.label_zh_hant,
                    "zh_hans": industry_section.label_zh_hans,
                },
            },
            {
                "id": str(industry_node.id),
                "code": industry_node.code,
                "level": industry_node.level,
                "labels": {
                    "en": industry_node.label_en,
                    "zh_hant": industry_node.label_zh_hant,
                    "zh_hans": industry_node.label_zh_hans,
                },
            },
        ],
        is_primary=True,
        primary_basis="authoritative_source",
        status="active",
        lock_version=1,
        captured_at=now,
    )

    skill_category = GovernedSkillCategory(
        revision_id=state["skill_revision_id"],
        code="programming",
        name="Programming",
        source_order=1,
        is_active=True,
    )
    db.add(skill_category)
    db.flush()
    skill_technology = GovernedSkillTechnology(
        revision_id=state["skill_revision_id"],
        category_id=skill_category.id,
        code="python-ecosystem",
        name="Python Ecosystem",
        source_order=1,
        is_active=True,
    )
    db.add(skill_technology)
    db.flush()
    governed_skill = GovernedSkill(
        revision_id=state["skill_revision_id"],
        technology_id=skill_technology.id,
        code="python",
        name="Python",
        source_order=1,
        origin="seed",
        is_active=True,
    )
    db.add(governed_skill)
    db.flush()
    matching_mention = GovernedJobSkillMention(
        job_id=job.id,
        taxonomy_revision_id=state["skill_revision_id"],
        raw_name="Python",
        normalized_key="python",
        resolution="match_existing",
        status="active",
        skill_id=governed_skill.id,
        source="ai-extraction",
        confidence=0.95,
        provenance={"method": "ai-extraction"},
        evidence_hash="6" * 64,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    unreviewed_mention = GovernedJobSkillMention(
        job_id=job.id,
        taxonomy_revision_id=state["skill_revision_id"],
        raw_name="Rust",
        normalized_key="rust",
        resolution="review_candidate",
        status="active",
        candidate_id=state["skill_candidate_id"],
        source="ai-extraction",
        confidence=0.8,
        provenance={"method": "ai-extraction"},
        evidence_hash="7" * 64,
        lock_version=1,
        created_at=now,
        updated_at=now,
    )
    skill_projection = GovernedJobSkill(
        job_id=job.id,
        taxonomy_revision_id=state["skill_revision_id"],
        skill_id=governed_skill.id,
        source="ai-extraction",
        confidence=0.95,
        provenance={"method": "ai-extraction"},
        mention_count=1,
        created_at=now,
        updated_at=now,
    )
    db.add_all(
        [
            canonical_assignment,
            industry_assignment,
            matching_mention,
            unreviewed_mention,
            skill_projection,
        ]
    )
    db.commit()
    return {
        **state,
        "job_id": job.id,
        "company_id": company.id,
        "canonical_subcategory_id": canonical_subcategory.id,
        "industry_section_id": industry_section.id,
        "industry_node_id": industry_node.id,
        "governed_skill_id": governed_skill.id,
    }


def _seed_related_job_recommendation_state(db) -> dict[str, object]:
    state = _seed_rich_job_detail_state(db)
    now = state["now"]
    source_job = db.get(Job, state["job_id"])
    source_assignment = (
        db.query(JobTaxonomyAssignment)
        .filter(
            JobTaxonomyAssignment.job_id == source_job.id,
            JobTaxonomyAssignment.is_current.is_(True),
        )
        .one()
    )
    vector_tail = [0.0] * (EMBEDDING_DIMENSIONS - 2)
    db.add(
        JobEmbedding(
            job_id=source_job.id,
            embedding_model="fixture-model",
            embedding_dimensions=EMBEDDING_DIMENSIONS,
            embedding_version=1,
            document_text="Platform Engineer Python",
            document_hash="8" * 64,
            embedding=[1.0, 0.0, *vector_tail],
            updated_at=now,
        )
    )

    candidates: list[Job] = []
    for index, (title, employment_label, embedding_prefix) in enumerate(
        (
            ("Related Platform Engineer", "Contract", (1.0, 0.0)),
            ("Related Backend Engineer", "Temporary", (0.9, 0.1)),
        ),
        start=1,
    ):
        company = Company(
            company_id=f"related-company-{index}",
            source_site="jobsdb",
            source_company_id=f"related-company-{index}",
            name=f"Related Company {index}",
        )
        candidate = Job(
            job_id=f"related-job-{index}",
            source_site="jobsdb",
            source_job_id=f"related-job-{index}",
            company=company,
            title=title,
            employment_type=f"Legacy {employment_label}",
            posted_date=now,
        )
        db.add(candidate)
        db.flush()
        SourceJobAttributes(db).project(
            candidate.id,
            JobsDBSourceEvidenceAdapter().extract(
                {"workTypes": [employment_label]},
                provenance=Provenance(
                    method="jobsdb-listing-payload",
                    source_site="jobsdb",
                    evidence_refs=(
                        {
                            "kind": "listing-payload",
                            "source_job_id": candidate.job_id,
                        },
                    ),
                    captured_at=now,
                ),
            ),
        )
        db.add_all(
            [
                JobTaxonomyAssignment(
                    job_id=candidate.id,
                    taxonomy_revision_id=state["canonical_revision_id"],
                    subcategory_id=state["canonical_subcategory_id"],
                    method="constrained_ai",
                    evidence_hash=str(index) * 64,
                    source_evidence_refs=[
                        {"kind": "source-classification-path", "id": "jobsdb:6281"}
                    ],
                    mapping_ids=[],
                    model_provider="openai",
                    model_name="fixture-model",
                    model_version="2026-07-19",
                    breadcrumb=dict(source_assignment.breadcrumb),
                    lock_version=1,
                    is_current=True,
                    captured_at=now,
                ),
                GovernedJobSkill(
                    job_id=candidate.id,
                    taxonomy_revision_id=state["skill_revision_id"],
                    skill_id=state["governed_skill_id"],
                    source="ai-extraction",
                    confidence=0.9,
                    provenance={"method": "ai-extraction"},
                    mention_count=1,
                    created_at=now,
                    updated_at=now,
                ),
                JobEmbedding(
                    job_id=candidate.id,
                    embedding_model="fixture-model",
                    embedding_dimensions=EMBEDDING_DIMENSIONS,
                    embedding_version=1,
                    document_text=title,
                    document_hash=("9" if index == 1 else "a") * 64,
                    embedding=[*embedding_prefix, *vector_tail],
                    updated_at=now,
                ),
            ]
        )
        candidates.append(candidate)

    db.commit()
    return {**state, "source_job_id": source_job.id, "candidates": candidates}


def test_product_surface_fixture_uses_versioned_backend_response_models() -> None:
    backend_payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture = JobIntelligenceProductFixtureSchema.model_validate(backend_payload)

    assert json.loads(FRONTEND_FIXTURE_PATH.read_text(encoding="utf-8")) == (
        backend_payload
    )

    assert fixture.summary.total_pending == 6
    assert [area.key for area in fixture.summary.areas] == [
        "job_taxonomy",
        "skill_candidates",
        "company_industries",
    ]
    assert fixture.summary.trusted_local.actor == "local-operator"
    assert fixture.summary.trusted_local.authentication == "none"
    assert fixture.summary.coverage.canonical_unassigned_reasons == {
        "classifier_provenance_missing": 3,
        "unmapped_source_classification": 2,
    }
    assert fixture.summary.coverage.jobs_with_unassigned_canonical_state == 2
    assert fixture.summary.coverage.jobs_with_unknown_canonical_state == 3
    assert fixture.canonical_audit.items[0].actor == "local-operator"
    assert [item.label for item in fixture.job_search.jobs[0].employment_types] == [
        "Full-time",
        "Permanent",
    ]
    assert fixture.job_search.jobs[0].canonical_taxonomy is not None
    assert fixture.job_search.jobs[0].canonical_taxonomy.state == "assigned"
    assert fixture.job_search.jobs[1].canonical_taxonomy is not None
    assert fixture.job_search.jobs[1].canonical_taxonomy.state == "unassigned"
    assert fixture.job_search.jobs[2].canonical_taxonomy is None
    assert (
        fixture.job_search.jobs[2].canonical_taxonomy_availability.unavailable_code
        == "CANONICAL_TAXONOMY_NOT_ACTIVE"
    )
    assert fixture.companies[0].company_industries is not None
    assert [
        assignment.is_primary
        for assignment in fixture.companies[0].company_industries.assignments
    ] == [True, False]
    assert fixture.companies[1].company_industries is not None
    assert (
        fixture.companies[1].company_industries.review_item_refs[0].reason
        == "unmapped_source_label"
    )
    assert fixture.companies[2].company_industries is None
    assert (
        fixture.companies[2].company_industry_availability.unavailable_code
        == "COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE"
    )
    assert fixture.job_detail.canonical_taxonomy is not None
    assert fixture.job_detail.canonical_taxonomy.state == "assigned"
    assert fixture.job_detail.company_industries is not None
    assert fixture.job_detail.company_industries.assignments[0].is_primary is True
    assert fixture.job_detail.skill_state is not None
    assert [skill.code for skill in fixture.job_detail.skill_state.skills] == ["python"]
    assert [
        mention.raw_name
        for mention in fixture.job_detail.skill_state.unreviewed_skill_mentions
    ] == ["Rust"]
    assert [
        item.label
        for item in fixture.job_recommendations.recommendations[0].employment_types
    ] == ["Full-time", "Permanent"]
    assert (
        fixture.job_recommendations.recommendations[0].canonical_taxonomy.state
        == "assigned"
    )


def test_related_job_contract_exposes_only_governed_job_intelligence() -> None:
    recommendation_id = uuid4()
    payload = {
        "id": recommendation_id,
        "job_id": "related-job-1",
        "title": "Platform Engineer",
        "company_name": "Governed Systems",
        "location": "Hong Kong",
        "employment_type": "Legacy Contract",
        "job_taxonomy": {
            "domain_id": uuid4(),
            "domain_name": "Legacy",
            "category_id": uuid4(),
            "category_name": "AI",
            "subcategory_id": uuid4(),
            "subcategory_name": "Category",
            "path": "Legacy / AI / Category",
        },
        "employment_types": [
            {"code": "full_time", "label": "Full-time", "sort_order": 1},
            {"code": "permanent", "label": "Permanent", "sort_order": 3},
        ],
        "canonical_taxonomy": {
            "job_id": recommendation_id,
            "state": "unassigned",
            "assignment": None,
            "reasons": ["classifier_provenance_missing"],
            "review_item_refs": [],
        },
        "job_intelligence_availability": {
            "source_attributes": {"available": True, "unavailable_code": None},
            "canonical_taxonomy": {"available": True, "unavailable_code": None},
            "skills": {"available": True, "unavailable_code": None},
        },
        "posted_date": "2026-07-19T08:00:00+00:00",
        "semantic_score": 0.9,
        "skill_overlap_score": 0.75,
        "taxonomy_score": 0.0,
        "freshness_score": 1.0,
        "combined_score": 0.7475,
    }

    serialized = JobRecommendationSchema.model_validate(payload).model_dump(mode="json")

    assert serialized["employment_types"] == [
        {"code": "full_time", "label": "Full-time", "sort_order": 1},
        {"code": "permanent", "label": "Permanent", "sort_order": 3},
    ]
    assert serialized["canonical_taxonomy"]["state"] == "unassigned"
    assert serialized["job_intelligence_availability"] == {
        "source_attributes": {"available": True, "unavailable_code": None},
        "canonical_taxonomy": {"available": True, "unavailable_code": None},
        "skills": {"available": True, "unavailable_code": None},
    }
    assert "employment_type" not in serialized
    assert "job_taxonomy" not in serialized


def test_related_job_contract_rejects_availability_data_conflicts() -> None:
    recommendation = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[
        "job_recommendations"
    ]["recommendations"][0]

    source_unavailable = {
        **recommendation,
        "job_intelligence_availability": {
            **recommendation["job_intelligence_availability"],
            "source_attributes": {
                "available": False,
                "unavailable_code": "SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED",
            },
        },
    }
    with pytest.raises(ValidationError):
        JobRecommendationSchema.model_validate(source_unavailable)

    canonical_unavailable = {
        **recommendation,
        "job_intelligence_availability": {
            **recommendation["job_intelligence_availability"],
            "canonical_taxonomy": {
                "available": False,
                "unavailable_code": "CANONICAL_TAXONOMY_NOT_ACTIVE",
            },
        },
    }
    with pytest.raises(ValidationError):
        JobRecommendationSchema.model_validate(canonical_unavailable)


def test_related_job_service_batches_governed_projection_reads(
    product_contract_db,
) -> None:
    state = _seed_related_job_recommendation_state(product_contract_db)
    statements: list[str] = []

    def capture_statement(_connection, _cursor, statement, *_args):
        statements.append(" ".join(statement.lower().split()))

    bind = product_contract_db.get_bind()
    event.listen(bind, "before_cursor_execute", capture_statement)
    try:
        recommendations = JobRecommendationService(
            product_contract_db
        ).recommend_for_job(state["source_job_id"], limit=2)
    finally:
        event.remove(bind, "before_cursor_execute", capture_statement)

    assert len(recommendations) == 2
    by_job_id = {item["job_id"]: item for item in recommendations}
    assert [
        item["label"] for item in by_job_id["related-job-1"]["employment_types"]
    ] == ["Contract"]
    assert [
        item["label"] for item in by_job_id["related-job-2"]["employment_types"]
    ] == ["Temporary"]
    for recommendation in recommendations:
        assert recommendation["canonical_taxonomy"]["state"] == "assigned"
        assert recommendation["taxonomy_score"] == 1.0
        assert recommendation["skill_overlap_score"] == 1.0
        assert recommendation["job_intelligence_availability"] == {
            "source_attributes": {"available": True, "unavailable_code": None},
            "canonical_taxonomy": {"available": True, "unavailable_code": None},
            "skills": {"available": True, "unavailable_code": None},
        }
        assert "employment_type" not in recommendation
        assert "job_taxonomy" not in recommendation
        JobRecommendationSchema.model_validate(recommendation)

    for projection_table in (
        "job_employment_types",
        "job_source_attribute_projections",
        "job_taxonomy_assignments",
        "job_taxonomy_review_items",
        "governed_job_skills",
    ):
        assert sum(projection_table in statement for statement in statements) == 1


def test_related_job_bulk_source_state_distinguishes_empty_from_missing_projection(
    product_contract_db,
) -> None:
    state = _seed_summary_state(product_contract_db)
    SourceJobAttributes(product_contract_db).project(
        state["job_one_id"],
        JobsDBSourceEvidenceAdapter().extract(
            {"workTypes": []},
            provenance=Provenance(
                method="jobsdb-listing-payload",
                source_site="jobsdb",
                evidence_refs=(
                    {"kind": "listing-payload", "source_job_id": "product-job-1"},
                ),
                captured_at=state["now"],
            ),
        ),
    )
    product_contract_db.commit()
    job_two_id = (
        product_contract_db.query(Job.id).filter(Job.job_id == "product-job-2").scalar()
    )

    states = JobIntelligenceProductReadModel(
        product_contract_db
    ).get_employment_type_states([state["job_one_id"], job_two_id])

    assert states[state["job_one_id"]] == {
        "employment_types": [],
        "source_attributes_availability": {
            "available": True,
            "unavailable_code": None,
        },
    }
    assert states[job_two_id] == {
        "employment_types": [],
        "source_attributes_availability": {
            "available": False,
            "unavailable_code": "SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED",
        },
    }


def test_product_surface_fixture_exports_job_browser_filter_contract() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture = JobIntelligenceProductFixtureSchema.model_validate(payload)

    assert [item.code for item in fixture.job_filters.employment_types] == [
        "full_time",
        "permanent",
    ]
    assert [item.id for item in fixture.job_filters.source_classifications] == [
        "jobsdb:6281",
        "jobsdb:6287",
    ]


def test_frontend_domain_contract_fixtures_are_exact_backend_copies() -> None:
    for backend_path, frontend_path in FRONTEND_DOMAIN_FIXTURE_PAIRS:
        assert json.loads(frontend_path.read_text(encoding="utf-8")) == json.loads(
            backend_path.read_text(encoding="utf-8")
        )


def test_job_detail_contract_rejects_missing_composed_governed_states() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["job_detail"]

    for required_field in (
        "canonical_taxonomy",
        "company_industries",
        "skill_state",
        "job_intelligence_availability",
    ):
        incomplete = dict(payload)
        incomplete.pop(required_field)
        with pytest.raises(ValidationError):
            JobDetailSchema.model_validate(incomplete)


def test_governance_summary_composes_domain_backlogs_and_coverage(
    product_contract_db,
) -> None:
    state = _seed_summary_state(product_contract_db)

    summary = JobIntelligenceProductReadModel(
        product_contract_db
    ).get_governance_summary(generated_at=state["now"])

    assert summary.to_payload() == {
        "generated_at": state["now"],
        "trusted_local": {
            "actor": "local-operator",
            "authentication": "none",
            "warning": (
                "Trusted local operation only. Governance decision routes are not "
                "authenticated and must not be exposed to an untrusted network."
            ),
        },
        "total_pending": 3,
        "areas": [
            {
                "key": "job_taxonomy",
                "label": "Job Taxonomy Review",
                "available": True,
                "pending_count": 1,
                "oldest_pending_at": state["now"],
                "active_revision_id": str(state["canonical_revision_id"]),
                "unavailable_code": None,
                "deep_link": "/job-intelligence/job-taxonomy",
            },
            {
                "key": "skill_candidates",
                "label": "Skill Candidates",
                "available": True,
                "pending_count": 1,
                "oldest_pending_at": state["now"],
                "active_revision_id": str(state["skill_revision_id"]),
                "unavailable_code": None,
                "deep_link": "/job-intelligence/skill-candidates",
            },
            {
                "key": "company_industries",
                "label": "Company Industries",
                "available": True,
                "pending_count": 1,
                "oldest_pending_at": state["now"],
                "active_revision_id": str(state["industry_revision_id"]),
                "unavailable_code": None,
                "deep_link": "/job-intelligence/company-industries",
            },
        ],
        "coverage": {
            "total_jobs": 2,
            "jobs_with_source_classification_paths": 0,
            "jobs_with_employment_types": 0,
            "jobs_with_canonical_assignment": 0,
            "jobs_without_canonical_assignment": 2,
            "jobs_with_unassigned_canonical_state": 1,
            "jobs_with_unknown_canonical_state": 1,
            "canonical_unassigned_reasons": {
                "classifier_provenance_missing": 1,
            },
            "jobs_with_governed_skills": 0,
            "jobs_with_unreviewed_skill_mentions": 0,
            "total_companies": 2,
            "companies_with_governed_industries": 0,
            "companies_without_governed_industries": 2,
        },
    }


def test_governance_summary_ignores_backlogs_from_inactive_revisions(
    product_contract_db,
) -> None:
    state = _seed_summary_state(product_contract_db)
    inactive_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    inactive_canonical_revision_id = uuid4()
    inactive_skill_revision_id = uuid4()
    inactive_industry_revision_id = uuid4()
    for revision_id, domain, release_key, hash_character in (
        (
            inactive_canonical_revision_id,
            "canonical-job-taxonomy",
            "canonical-inactive",
            "d",
        ),
        (inactive_skill_revision_id, "skill-taxonomy", "skills-inactive", "e"),
        (
            inactive_industry_revision_id,
            "company-industry",
            "industry-inactive",
            "f",
        ),
    ):
        product_contract_db.add(
            GovernanceRevision(
                id=revision_id,
                domain=domain,
                release_key=release_key,
                content_hash=hash_character * 64,
                source_metadata={},
                created_at=inactive_at,
                published_at=inactive_at,
            )
        )
    product_contract_db.flush()
    product_contract_db.add_all(
        [
            CanonicalJobTaxonomyRelease(
                revision_id=inactive_canonical_revision_id,
                content_hash="d" * 64,
                expected_domain_count=0,
                expected_category_count=0,
                expected_subcategory_count=0,
                materialized_domain_count=0,
                materialized_category_count=0,
                materialized_subcategory_count=0,
                status="ready",
                ready_at=inactive_at,
            ),
            SkillTaxonomyRelease(
                revision_id=inactive_skill_revision_id,
                content_hash="e" * 64,
                taxonomy_hash="1" * 64,
                rules_hash="2" * 64,
                backfill_hash="3" * 64,
                rules_document={},
                backfill_document={},
                expected_category_count=0,
                expected_technology_count=0,
                expected_skill_count=0,
                expected_alias_count=0,
                materialized_category_count=0,
                materialized_technology_count=0,
                materialized_skill_count=0,
                materialized_alias_count=0,
                status="ready",
                ready_at=inactive_at,
            ),
            CompanyIndustryTaxonomyRelease(
                revision_id=inactive_industry_revision_id,
                standard="HSIC",
                release="inactive",
                content_hash="f" * 64,
                source_metadata={},
                expected_counts={},
                materialized_counts={},
                expected_total=0,
                materialized_total=0,
                status="ready",
                ready_at=inactive_at,
            ),
        ]
    )
    product_contract_db.flush()
    job_two = product_contract_db.query(Job).filter(Job.job_id == "product-job-2").one()
    company_one = (
        product_contract_db.query(Company)
        .filter(Company.company_id == "product-company-1")
        .one()
    )
    product_contract_db.add_all(
        [
            JobTaxonomyReviewItem(
                job_id=job_two.id,
                taxonomy_revision_id=inactive_canonical_revision_id,
                status="active",
                reasons=["inactive_revision_only"],
                evidence_hash="4" * 64,
                evidence_refs=[],
                recommendations=[],
                lock_version=1,
                created_at=inactive_at,
                updated_at=inactive_at,
            ),
            SkillCandidate(
                taxonomy_revision_id=inactive_skill_revision_id,
                normalized_key="inactive-skill",
                canonical_raw_name="Inactive Skill",
                raw_variants=["Inactive Skill"],
                status="pending",
                occurrence_count=1,
                distinct_job_count=1,
                evidence_summary={},
                recommendations=[],
                lock_version=1,
                first_seen_at=inactive_at,
                last_seen_at=inactive_at,
                created_at=inactive_at,
                updated_at=inactive_at,
            ),
            CompanyIndustryReviewItem(
                company_id=company_one.id,
                taxonomy_revision_id=inactive_industry_revision_id,
                source_site="jobsdb",
                key_kind="label",
                raw_value="Inactive Industry",
                normalized_key="inactive industry",
                reason="unmapped_source_evidence",
                status="active",
                evidence_hash="5" * 64,
                provenance={},
                recommendations=[],
                lock_version=1,
                created_at=inactive_at,
                updated_at=inactive_at,
            ),
        ]
    )
    product_contract_db.commit()

    summary = JobIntelligenceProductReadModel(
        product_contract_db
    ).get_governance_summary(generated_at=state["now"])

    assert [area.pending_count for area in summary.areas] == [1, 1, 1]
    assert [area.oldest_pending_at for area in summary.areas] == [
        state["now"],
        state["now"],
        state["now"],
    ]
    assert summary.coverage.jobs_with_unassigned_canonical_state == 1
    assert summary.coverage.jobs_with_unknown_canonical_state == 1
    assert summary.coverage.canonical_unassigned_reasons == {
        "classifier_provenance_missing": 1,
    }


def test_product_http_contract_exposes_summary_and_canonical_audit(
    product_contract_db,
) -> None:
    _seed_summary_state(product_contract_db)

    summary = read_job_intelligence_governance_summary(db=product_contract_db)
    audit = list_job_taxonomy_audit_events(
        subject_id=None,
        cursor=None,
        limit=50,
        db=product_contract_db,
    )

    assert summary.total_pending == 3
    assert summary.trusted_local.actor == "local-operator"
    assert [area.deep_link for area in summary.areas] == [
        "/job-intelligence/job-taxonomy",
        "/job-intelligence/skill-candidates",
        "/job-intelligence/company-industries",
    ]
    assert len(audit.items) == 1
    assert audit.items[0].domain == "job-taxonomy"
    assert audit.items[0].subject_type == "job-taxonomy-review-item"


def test_dashboard_category_stats_use_only_governed_current_assignments(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)
    legacy_domain = JobDomain(name="Legacy Taxonomy")
    legacy_category = JobCategory(name="General", domain=legacy_domain)
    legacy_subcategory = JobSubcategory(
        name="General",
        category=legacy_category,
    )
    product_contract_db.add(legacy_subcategory)
    product_contract_db.flush()
    product_contract_db.get(
        Job, state["job_one_id"]
    ).subcategory_id = legacy_subcategory.id
    product_contract_db.commit()

    payload = asyncio.run(get_dashboard_category_stats(db=product_contract_db))

    assert payload == {
        "categorized_total": 1,
        "specific_total": 1,
        "fallback_total": 0,
        "top_specific_categories": [
            {
                "path": "Technology / Software Development / Backend Development",
                "label": "Backend Development",
                "count": 1,
                "share_of_specific": 100,
            }
        ],
        "other_specific_categories": {
            "count": 0,
            "bucket_count": 0,
            "share_of_specific": 0,
        },
        "fallback_buckets": [],
    }


def test_job_detail_composes_independent_governed_states_without_fabrication(
    product_contract_db,
) -> None:
    state = _seed_summary_state(product_contract_db)

    detail = asyncio.run(get_job(state["job_one_id"], product_contract_db))
    payload = detail.model_dump(mode="json")

    assert payload["job_intelligence_availability"] == {
        "source_attributes": {
            "available": False,
            "unavailable_code": "SOURCE_JOB_ATTRIBUTES_NOT_PROJECTED",
        },
        "canonical_taxonomy": {
            "available": True,
            "unavailable_code": None,
        },
        "company_industries": {
            "available": True,
            "unavailable_code": None,
        },
        "skills": {
            "available": True,
            "unavailable_code": None,
        },
    }
    assert payload["canonical_taxonomy"] == {
        "job_id": str(state["job_one_id"]),
        "state": "unassigned",
        "assignment": None,
        "reasons": ["classifier_provenance_missing"],
        "review_item_refs": [
            {
                "id": str(state["canonical_review_id"]),
                "status": "active",
                "version": 1,
                "decision_audit_id": None,
                "deep_link": (
                    "/api/v1/job-intelligence/governance/job-taxonomy/"
                    "review-items/"
                    f'{state["canonical_review_id"]}'
                ),
            }
        ],
    }
    assert payload["company_industries"] == {
        "company_id": payload["company_id"],
        "assignments": [],
        "review_item_refs": [],
    }
    assert payload["skill_state"] == {
        "job_id": str(state["job_one_id"]),
        "taxonomy_revision_id": str(state["skill_revision_id"]),
        "skills": [],
        "unreviewed_skill_mentions": [],
    }
    assert payload["source_classification_paths"] == []
    assert payload["employment_types"] == []
    assert payload["source_employment_labels"] == []


def test_job_detail_serializes_complete_projected_source_attributes(
    product_contract_db,
) -> None:
    state = _seed_summary_state(product_contract_db)
    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    },
                    "subclassification": {
                        "id": "6287",
                        "description": "Developers and Programmers",
                    },
                },
                {
                    "classification": {
                        "id": "6092",
                        "description": "Engineering",
                    }
                },
            ],
            "workTypes": ["Full-time", "Permanent"],
        },
        provenance=Provenance(
            method="jobsdb-listing-payload",
            source_site="jobsdb",
            evidence_refs=(
                {"kind": "listing-payload", "source_job_id": "product-job-1"},
            ),
            captured_at=state["now"],
        ),
    )
    SourceJobAttributes(product_contract_db).project(
        state["job_one_id"],
        evidence,
    )
    product_contract_db.commit()

    payload = asyncio.run(get_job(state["job_one_id"], product_contract_db)).model_dump(
        mode="json"
    )

    assert payload["job_intelligence_availability"]["source_attributes"] == {
        "available": True,
        "unavailable_code": None,
    }
    assert [
        [node["source_classification_id"] for node in path["nodes"]]
        for path in payload["source_classification_paths"]
    ] == [
        ["jobsdb:6281", "jobsdb:6287"],
        ["jobsdb:6092"],
    ]
    assert [item["code"] for item in payload["employment_types"]] == [
        "full_time",
        "permanent",
    ]
    assert [item["raw_label"] for item in payload["source_employment_labels"]] == [
        "Full-time",
        "Permanent",
    ]


def test_job_detail_uses_structured_governed_knowledge_over_legacy_evidence(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)

    payload = asyncio.run(get_job(state["job_id"], product_contract_db)).model_dump(
        mode="json"
    )

    assert payload["job_intelligence_availability"] == {
        domain: {"available": True, "unavailable_code": None}
        for domain in (
            "source_attributes",
            "canonical_taxonomy",
            "company_industries",
            "skills",
        )
    }
    assert payload["canonical_taxonomy"]["state"] == "assigned"
    assert payload["canonical_taxonomy"]["assignment"]["subcategory_id"] == str(
        state["canonical_subcategory_id"]
    )
    assert (
        payload["canonical_taxonomy"]["assignment"]["breadcrumb"]["subcategory"]["code"]
        == "backend-development"
    )
    assert payload["company_industry"] == "Legacy evidence only"
    assert [
        (assignment["node_id"], assignment["is_primary"])
        for assignment in payload["company_industries"]["assignments"]
    ] == [(str(state["industry_node_id"]), True)]
    assert (
        payload["company_industries"]["assignments"][0]["breadcrumb"][0]["code"] == "J"
    )
    assert payload["skills"] == ["Python"]
    assert payload["provisional_skills"] == ["Rust"]
    assert [skill["id"] for skill in payload["skill_state"]["skills"]] == [
        str(state["governed_skill_id"])
    ]
    assert [
        mention["raw_name"]
        for mention in payload["skill_state"]["unreviewed_skill_mentions"]
    ] == ["Rust"]
    assert (
        payload["unreviewed_skill_mentions"]
        == payload["skill_state"]["unreviewed_skill_mentions"]
    )


def test_manual_job_snapshot_uses_the_same_composed_read_model(
    product_contract_db,
    monkeypatch,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)
    snapshot_sessions = sessionmaker(
        bind=product_contract_db.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(ai_api, "SessionLocal", snapshot_sessions)

    payload = ai_api._load_job_snapshot(state["job_id"])

    assert payload["job_intelligence_availability"] == {
        domain: {"available": True, "unavailable_code": None}
        for domain in (
            "source_attributes",
            "canonical_taxonomy",
            "company_industries",
            "skills",
        )
    }
    assert payload["canonical_taxonomy"]["state"] == "assigned"
    assert payload["company_industries"]["assignments"][0]["is_primary"] is True
    assert payload["skills"] == ["Python"]
    assert payload["provisional_skills"] == ["Rust"]


def test_company_detail_exposes_governed_industries_without_promoting_legacy_text(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)

    response = asyncio.run(get_company(state["company_id"], product_contract_db))
    payload = response.model_dump(mode="json")

    assert payload["industry"] == "Legacy evidence only"
    assert payload["company_industry_availability"] == {
        "available": True,
        "unavailable_code": None,
    }
    assert payload["company_industries"]["company_id"] == str(state["company_id"])
    assert [
        (assignment["node_id"], assignment["is_primary"])
        for assignment in payload["company_industries"]["assignments"]
    ] == [(str(state["industry_node_id"]), True)]


def test_company_detail_ignores_review_refs_from_inactive_revision(
    product_contract_db,
) -> None:
    _seed_summary_state(product_contract_db)
    inactive_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    inactive_revision_id = uuid4()
    product_contract_db.add(
        GovernanceRevision(
            id=inactive_revision_id,
            domain="company-industry",
            release_key="company-industry-inactive-detail",
            content_hash="9" * 64,
            source_metadata={},
            created_at=inactive_at,
            published_at=inactive_at,
        )
    )
    product_contract_db.flush()
    product_contract_db.add(
        CompanyIndustryTaxonomyRelease(
            revision_id=inactive_revision_id,
            standard="HSIC",
            release="inactive-detail",
            content_hash="9" * 64,
            source_metadata={},
            expected_counts={},
            materialized_counts={},
            expected_total=0,
            materialized_total=0,
            status="ready",
            ready_at=inactive_at,
        )
    )
    product_contract_db.flush()
    company = (
        product_contract_db.query(Company)
        .filter(Company.company_id == "product-company-1")
        .one()
    )
    product_contract_db.add(
        CompanyIndustryReviewItem(
            company_id=company.id,
            taxonomy_revision_id=inactive_revision_id,
            source_site="jobsdb",
            key_kind="label",
            raw_value="Inactive Industry",
            normalized_key="inactive industry",
            reason="unmapped_source_evidence",
            status="active",
            evidence_hash="8" * 64,
            provenance={},
            recommendations=[],
            lock_version=1,
            created_at=inactive_at,
            updated_at=inactive_at,
        )
    )
    product_contract_db.commit()

    payload = JobIntelligenceProductReadModel(product_contract_db).get_company_detail(
        company.id
    )

    assert payload["company_industry_availability"] == {
        "available": True,
        "unavailable_code": None,
    }
    assert payload["company_industries"] == {
        "company_id": str(company.id),
        "assignments": [],
        "review_item_refs": [],
    }


def test_company_list_batches_the_same_governed_industry_contract(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)

    response = asyncio.run(
        list_companies(
            q=None,
            status="all",
            page=1,
            page_size=100,
            db=product_contract_db,
        )
    )
    rich_company = next(
        item for item in response["items"] if item.id == state["company_id"]
    )
    payload = rich_company.model_dump(mode="json")

    assert payload["company_industry_availability"]["available"] is True
    assert payload["company_industries"]["assignments"][0]["node_id"] == str(
        state["industry_node_id"]
    )


def test_job_browser_filters_use_governed_ids_and_industry_descendants(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)
    filters = JobSearchFiltersSchema(
        canonical_subcategory_ids=[str(state["canonical_subcategory_id"])],
        company_industry_node_ids=[str(state["industry_section_id"])],
    )

    query = product_contract_db.query(Job).join(
        Company,
        Company.id == Job.company_id,
    )
    matches = _apply_structured_filters(query, filters).all()

    assert [job.id for job in matches] == [state["job_id"]]
    assert filters.canonical_subcategory_ids == [str(state["canonical_subcategory_id"])]
    assert filters.company_industry_node_ids == [str(state["industry_section_id"])]


def test_job_browser_cards_expose_batched_canonical_state(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)
    row = (
        product_contract_db.query(Job, Company)
        .join(Company, Company.id == Job.company_id)
        .filter(Job.id == state["job_id"])
        .one()
    )

    response = _build_search_response_from_results(
        [row],
        total=1,
        page=1,
        page_size=20,
    ).model_dump(mode="json")
    card = response["jobs"][0]

    assert card["canonical_taxonomy_availability"] == {
        "available": True,
        "unavailable_code": None,
    }
    assert card["canonical_taxonomy"]["state"] == "assigned"
    assert (
        card["canonical_taxonomy"]["assignment"]["breadcrumb"]["subcategory"]["code"]
        == "backend-development"
    )
