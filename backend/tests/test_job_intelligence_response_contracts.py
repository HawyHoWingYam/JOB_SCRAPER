from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api import jobs as jobs_api
from app.api import ai as ai_api
from app.api.companies import get_company, list_companies
from app.api.jobs import (
    _apply_structured_filters,
    _build_export_rows,
    get_job,
)
from app.database import Base, get_db
from app.job_intelligence.foundation import Provenance
from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.job_intelligence.source_attributes import (
    EMPLOYMENT_TYPE_SEEDS,
    JobsDBSourceEvidenceAdapter,
    SourceJobAttributes,
)
from app.models.company import Company
from app.models.current_taxonomy import (
    CURRENT_TAXONOMY_TABLES,
    CurrentCompanyIndustryAssignment,
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyNodeRecord,
)
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.job_embedding import EMBEDDING_DIMENSIONS, JobEmbedding
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
        "current_taxonomy_responses.json",
    )
)


@pytest.fixture
def product_contract_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("Product response contracts require a dedicated *_test database")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    tables = (
        Company.__table__,
        Job.__table__,
        JobEmbedding.__table__,
        EventOutbox.__table__,
        *SOURCE_JOB_ATTRIBUTE_TABLES,
        *CURRENT_TAXONOMY_TABLES,
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
    skill_candidate = CurrentSkillCandidate(
        taxonomy="skill",
        normalized_key="rust",
        canonical_raw_name="Rust",
        raw_variants=["Rust"],
        occurrence_count=1,
        distinct_job_count=1,
        evidence_summary={},
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(skill_candidate)
    db.commit()
    return {
        "job_one_id": job_one.id,
        "skill_candidate_id": skill_candidate.id,
        "now": now,
    }


def _job_search_client(db) -> TestClient:
    app = FastAPI()
    app.include_router(jobs_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


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

    current_industry_section_code = "J"
    current_industry_node_code = "58"
    current_skill_category_code = "programming"
    current_skill_technology_code = "programming.python-ecosystem"
    current_skill_code = "python"
    db.add_all(
        [
            CurrentTaxonomyNodeRecord(
                taxonomy="company_industry",
                code=current_industry_section_code,
                parent_code=None,
                level="section",
                labels={
                    "en": "Information and communications",
                    "zh_hant": "資訊及通訊",
                    "zh_hans": "资讯及通讯",
                },
                sort_order=1,
                is_assignable=False,
                is_active=True,
            ),
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code=current_skill_category_code,
                parent_code=None,
                level="category",
                labels={"en": "Programming"},
                sort_order=1,
                is_assignable=False,
                is_active=True,
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            CurrentTaxonomyNodeRecord(
                taxonomy="company_industry",
                code=current_industry_node_code,
                parent_code=current_industry_section_code,
                level="division",
                labels={
                    "en": "Publishing activities",
                    "zh_hant": "出版活動",
                    "zh_hans": "出版活动",
                },
                sort_order=2,
                is_assignable=True,
                is_active=True,
            ),
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code=current_skill_technology_code,
                parent_code=current_skill_category_code,
                level="technology",
                labels={"en": "Python Ecosystem"},
                sort_order=1,
                is_assignable=False,
                is_active=True,
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code=current_skill_code,
                parent_code=current_skill_technology_code,
                level="skill",
                labels={"en": "Python"},
                sort_order=1,
                is_assignable=True,
                is_active=True,
            ),
        ]
    )
    db.flush()

    current_industry_assignment = CurrentCompanyIndustryAssignment(
        company_id=company.id,
        taxonomy="company_industry",
        taxonomy_code=current_industry_node_code,
        method="authoritative_code",
        provenance={"method": "source-hsic-code"},
        evidence_hash="5" * 64,
        breadcrumb={
            "section": {
                "code": current_industry_section_code,
                "level": "section",
                "labels": {
                    "en": "Information and communications",
                    "zh_hant": "資訊及通訊",
                    "zh_hans": "资讯及通讯",
                },
            },
            "division": {
                "code": current_industry_node_code,
                "level": "division",
                "labels": {
                    "en": "Publishing activities",
                    "zh_hant": "出版活動",
                    "zh_hans": "出版活动",
                },
            },
        },
        is_primary=True,
        primary_basis="authoritative_source",
        captured_at=now,
    )
    current_matching_mention = CurrentJobSkillMention(
        job_id=job.id,
        taxonomy="skill",
        raw_name="Python",
        normalized_key="python",
        resolution="match_existing",
        status="active",
        skill_code=current_skill_code,
        source="ai-extraction",
        confidence=0.95,
        provenance={"method": "ai-extraction"},
        evidence_hash="6" * 64,
        created_at=now,
        updated_at=now,
    )
    current_candidate_mention = CurrentJobSkillMention(
        job_id=job.id,
        taxonomy="skill",
        raw_name="Rust",
        normalized_key="rust",
        resolution="candidate",
        status="active",
        candidate_id=state["skill_candidate_id"],
        source="ai-extraction",
        confidence=0.8,
        provenance={"method": "ai-extraction"},
        evidence_hash="7" * 64,
        created_at=now,
        updated_at=now,
    )
    current_skill_projection = CurrentJobSkillAssignment(
        job_id=job.id,
        skill_code=current_skill_code,
        taxonomy="skill",
        source="ai-extraction",
        confidence=0.95,
        provenance={"method": "ai-extraction"},
        mention_count=1,
        updated_at=now,
    )
    db.add_all(
        [
            current_industry_assignment,
            current_matching_mention,
            current_candidate_mention,
            current_skill_projection,
        ]
    )
    db.commit()
    return {
        **state,
        "job_id": job.id,
        "company_id": company.id,
        "current_industry_section_code": current_industry_section_code,
        "current_industry_node_code": current_industry_node_code,
        "current_skill_code": current_skill_code,
    }


def _seed_related_job_recommendation_state(db) -> dict[str, object]:
    state = _seed_rich_job_detail_state(db)
    now = state["now"]
    source_job = db.get(Job, state["job_id"])
    vector_tail = [0.0] * (EMBEDDING_DIMENSIONS - 2)
    db.add(
        JobEmbedding(
            job_id=source_job.id,
            embedding_dimensions=EMBEDDING_DIMENSIONS,
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
                CurrentJobSkillAssignment(
                    job_id=candidate.id,
                    skill_code=state["current_skill_code"],
                    taxonomy="skill",
                    source="ai-extraction",
                    confidence=0.9,
                    provenance={"method": "ai-extraction"},
                    mention_count=1,
                    updated_at=now,
                ),
                JobEmbedding(
                    job_id=candidate.id,
                    embedding_dimensions=EMBEDDING_DIMENSIONS,
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


def test_product_surface_fixture_uses_current_backend_response_models() -> None:
    backend_payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    fixture = JobIntelligenceProductFixtureSchema.model_validate(backend_payload)

    if FRONTEND_FIXTURE_PATH.exists():
        assert json.loads(FRONTEND_FIXTURE_PATH.read_text(encoding="utf-8")) == (
            backend_payload
        )

    assert [item.label for item in fixture.job_search.jobs[0].employment_types] == [
        "Full-time",
        "Permanent",
    ]
    assert fixture.companies[0].company_industries is not None
    assert [
        assignment.is_primary
        for assignment in fixture.companies[0].company_industries.assignments
    ] == [True, False]
    assert fixture.companies[1].company_industries is not None
    assert fixture.companies[1].company_industries.assignments == []
    assert fixture.companies[2].company_industries is None
    assert (
        fixture.companies[2].company_industry_availability.unavailable_code
        == "COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE"
    )
    assert fixture.job_detail.company_industries is not None
    assert fixture.job_detail.company_industries.assignments[0].is_primary is True
    assert fixture.job_detail.skill_state is not None
    assert [skill.code for skill in fixture.job_detail.skill_state.skills] == ["python"]
    assert [
        mention.raw_name for mention in fixture.job_detail.skill_state.candidate_mentions
    ] == ["Rust"]
    assert [
        mention["raw_name"] for mention in fixture.job_detail.skill_candidate_mentions
    ] == ["Rust"]
    serialized = json.dumps(fixture.model_dump(mode="json"), sort_keys=True)
    assert "taxonomy_revision" not in serialized
    assert "review_item" not in serialized
    assert "governance" not in serialized.lower()
    assert [
        item.label
        for item in fixture.job_recommendations.recommendations[0].employment_types
    ] == ["Full-time", "Permanent"]


def test_related_job_contract_exposes_only_governed_job_intelligence() -> None:
    recommendation_id = uuid4()
    payload = {
        "id": recommendation_id,
        "job_id": "related-job-1",
        "title": "Platform Engineer",
        "company_name": "Governed Systems",
        "location": "Hong Kong",
        "employment_type": "Legacy Contract",
        "employment_types": [
            {"code": "full_time", "label": "Full-time", "sort_order": 1},
            {"code": "permanent", "label": "Permanent", "sort_order": 3},
        ],
        "job_intelligence_availability": {
            "source_attributes": {"available": True, "unavailable_code": None},
            "skills": {"available": True, "unavailable_code": None},
        },
        "posted_date": "2026-07-19T08:00:00+00:00",
        "semantic_score": 0.9,
        "skill_overlap_score": 0.75,
        "freshness_score": 1.0,
        "combined_score": 0.8825,
    }

    serialized = JobRecommendationSchema.model_validate(payload).model_dump(mode="json")

    assert serialized["employment_types"] == [
        {"code": "full_time", "label": "Full-time", "sort_order": 1},
        {"code": "permanent", "label": "Permanent", "sort_order": 3},
    ]
    assert serialized["job_intelligence_availability"] == {
        "source_attributes": {"available": True, "unavailable_code": None},
        "skills": {"available": True, "unavailable_code": None},
    }
    assert "employment_type" not in serialized


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
        assert recommendation["skill_overlap_score"] == 1.0
        assert recommendation["job_intelligence_availability"] == {
            "source_attributes": {"available": True, "unavailable_code": None},
            "skills": {"available": True, "unavailable_code": None},
        }
        assert "employment_type" not in recommendation
        JobRecommendationSchema.model_validate(recommendation)

    for projection_table in (
        "job_employment_types",
        "job_source_attribute_projections",
        "current_job_skill_assignments",
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
        if not frontend_path.exists():
            continue
        assert json.loads(frontend_path.read_text(encoding="utf-8")) == json.loads(
            backend_path.read_text(encoding="utf-8")
        )


def test_job_detail_contract_rejects_missing_composed_governed_states() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["job_detail"]

    for required_field in (
        "company_industries",
        "skill_state",
        "job_intelligence_availability",
    ):
        incomplete = dict(payload)
        incomplete.pop(required_field)
        with pytest.raises(ValidationError):
            JobDetailSchema.model_validate(incomplete)


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
        "company_industries": {
            "available": True,
            "unavailable_code": None,
        },
        "skills": {
            "available": True,
            "unavailable_code": None,
        },
    }
    assert payload["company_industries"] == {
        "company_id": payload["company_id"],
        "assignments": [],
    }
    assert payload["skill_state"] == {
        "job_id": str(state["job_one_id"]),
        "skills": [],
        "candidate_mentions": [],
    }
    assert payload["skill_candidate_mentions"] == []
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
            "company_industries",
            "skills",
        )
    }
    assert payload["company_industry"] == "Legacy evidence only"
    assert [
        (assignment["taxonomy_code"], assignment["is_primary"])
        for assignment in payload["company_industries"]["assignments"]
    ] == [(state["current_industry_node_code"], True)]
    assert (
        payload["company_industries"]["assignments"][0]["breadcrumb"]["section"][
            "code"
        ]
        == "J"
    )
    assert payload["skills"] == ["Python"]
    assert [skill["code"] for skill in payload["skill_state"]["skills"]] == [
        state["current_skill_code"]
    ]
    assert [
        mention["raw_name"]
        for mention in payload["skill_state"]["candidate_mentions"]
    ] == ["Rust"]
    assert (
        payload["skill_candidate_mentions"]
        == payload["skill_state"]["candidate_mentions"]
    )
    assert "provisional_skills" not in payload
    assert "unreviewed_skill_mentions" not in payload


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
            "company_industries",
            "skills",
        )
    }
    assert payload["company_industries"]["assignments"][0]["is_primary"] is True
    assert payload["skills"] == ["Python"]
    assert [mention["raw_name"] for mention in payload["skill_candidate_mentions"]] == [
        "Rust"
    ]


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
        (assignment["taxonomy_code"], assignment["is_primary"])
        for assignment in payload["company_industries"]["assignments"]
    ] == [(state["current_industry_node_code"], True)]


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
    assert payload["company_industries"]["assignments"][0]["taxonomy_code"] == state[
        "current_industry_node_code"
    ]


def test_job_browser_filters_use_company_industry_descendants(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)
    filters = JobSearchFiltersSchema(
        company_industry_node_ids=[state["current_industry_section_code"]],
    )

    query = product_contract_db.query(Job).join(
        Company,
        Company.id == Job.company_id,
    )
    matches = _apply_structured_filters(query, filters).all()

    assert [job.id for job in matches] == [state["job_id"]]
    assert filters.company_industry_node_ids == [state["current_industry_section_code"]]


def test_job_browser_rejects_legacy_company_industry_filter_authority() -> None:
    with pytest.raises(
        ValidationError,
        match="industry is retired; use company_industry_node_ids",
    ):
        JobSearchFiltersSchema(industry="Legacy evidence only")


def test_get_job_browser_rejects_legacy_company_industry_filter_with_http_422() -> None:
    response = _job_search_client(None).get(
        "/api/jobs/search",
        params={"industry": "Legacy evidence only"},
    )

    assert response.status_code == 422
    assert "industry is retired; use company_industry_node_ids" in response.text


def test_get_job_browser_filters_by_company_industry_node_ids(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)

    response = _job_search_client(product_contract_db).get(
        "/api/jobs/search",
        params={
            "company_industry_node_ids": state["current_industry_section_code"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [job["id"] for job in payload["jobs"]] == [str(state["job_id"])]


def test_job_browser_export_reads_current_skills_without_legacy_relationships(
    product_contract_db,
) -> None:
    state = _seed_rich_job_detail_state(product_contract_db)
    query = (
        product_contract_db.query(Job, Company)
        .join(Company, Company.id == Job.company_id)
        .filter(Job.id == state["job_id"])
    )

    rows = _build_export_rows(query)

    assert len(rows) == 1
    assert rows[0]["skills"] == "Python"
