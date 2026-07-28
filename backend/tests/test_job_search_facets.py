from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.database import Base
from app.database import get_db
from app.job_intelligence.source_attributes import EMPLOYMENT_TYPE_SEEDS
from app.models import Company, Job
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentJobTaxonomyAssignment,
    CurrentTaxonomyNodeRecord,
)
from app.models.source_job_attributes import EmploymentType, JobEmploymentType
from app.models.source_job_attributes import (
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
)
from app.schemas.job_search import (
    JobSearchFiltersSchema,
    JobSearchLayerSchema,
    JobSearchScopeSchema,
)
from app.services.job_search_facets import JobSearchFacets
from app.services import retrieval_service as retrieval_service_module


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


def _facet_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            Job.__table__,
            EmploymentType.__table__,
            JobSourceClassificationPath.__table__,
            JobSourceClassificationPathNode.__table__,
            JobEmploymentType.__table__,
            CurrentTaxonomyNodeRecord.__table__,
            CurrentJobTaxonomyAssignment.__table__,
            CurrentCompanyIndustryAssignment.__table__,
        ],
    )
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add_all(
        EmploymentType(code=code, label=label, sort_order=sort_order)
        for code, label, sort_order in EMPLOYMENT_TYPE_SEEDS
    )
    session.commit()
    return session, engine


def test_employment_type_facet_keeps_complete_catalog_and_excludes_itself():
    db, engine = _facet_session()
    try:
        jobsdb = Company(
            company_id="facet-company-jobsdb",
            source_site="jobsdb",
            source_company_id="facet-company-jobsdb",
            name="JobsDB Company",
        )
        offertoday = Company(
            company_id="facet-company-offertoday",
            source_site="offertoday",
            source_company_id="facet-company-offertoday",
            name="OfferToday Company",
        )
        full_time_job = Job(
            job_id="facet-full-time",
            source_site="jobsdb",
            source_job_id="facet-full-time",
            company=jobsdb,
            title="Full-time role",
        )
        part_time_job = Job(
            job_id="facet-part-time",
            source_site="offertoday",
            source_job_id="facet-part-time",
            company=offertoday,
            title="Part-time role",
        )
        db.add_all([full_time_job, part_time_job])
        db.flush()
        db.add_all(
            [
                JobEmploymentType(
                    job_id=full_time_job.id,
                    employment_type_code="full_time",
                    evidence_label_ids=[],
                    provenance={},
                ),
                JobEmploymentType(
                    job_id=part_time_job.id,
                    employment_type_code="part_time",
                    evidence_label_ids=[],
                    provenance={},
                ),
            ]
        )
        db.commit()

        scope = JobSearchScopeSchema(
            layers=[
                JobSearchLayerSchema(
                    client_id="root",
                    structured_filters=JobSearchFiltersSchema(
                        employment_type_codes=["full_time"],
                    ),
                )
            ]
        )

        facets = JobSearchFacets(db).build(scope)
        employment_types = {
            option.id: option for option in facets.employment_types
        }

        assert list(employment_types) == [
            "full_time",
            "part_time",
            "permanent",
            "contract",
            "temporary",
            "internship",
            "freelance",
        ]
        assert employment_types["full_time"].count == 1
        assert employment_types["part_time"].count == 1
        assert employment_types["contract"].count == 0
    finally:
        db.close()
        engine.dispose()


def test_source_facet_excludes_source_but_respects_other_dimensions():
    db, engine = _facet_session()
    try:
        jobs = []
        for source_site, suffix, employment_type_code in (
            ("jobsdb", "jobsdb-full-time", "full_time"),
            ("offertoday", "offertoday-full-time", "full_time"),
            ("jobsdb", "jobsdb-part-time", "part_time"),
        ):
            company = Company(
                company_id=f"facet-company-{suffix}",
                source_site=source_site,
                source_company_id=f"facet-company-{suffix}",
                name=f"Company {suffix}",
            )
            job = Job(
                job_id=f"facet-job-{suffix}",
                source_site=source_site,
                source_job_id=f"facet-job-{suffix}",
                company=company,
                title=f"Role {suffix}",
            )
            jobs.append((job, employment_type_code))
            db.add(job)
        db.flush()
        db.add_all(
            JobEmploymentType(
                job_id=job.id,
                employment_type_code=employment_type_code,
                evidence_label_ids=[],
                provenance={},
            )
            for job, employment_type_code in jobs
        )
        db.commit()

        scope = JobSearchScopeSchema(
            layers=[
                JobSearchLayerSchema(
                    client_id="root",
                    structured_filters=JobSearchFiltersSchema(
                        source_site="jobsdb",
                        employment_type_codes=["full_time"],
                    ),
                )
            ]
        )

        sources = {
            option.id: option for option in JobSearchFacets(db).build(scope).sources
        }

        assert list(sources) == ["jobsdb", "ctgoodjobs", "offertoday"]
        assert sources["jobsdb"].count == 1
        assert sources["ctgoodjobs"].count == 0
        assert sources["offertoday"].count == 1
    finally:
        db.close()
        engine.dispose()


def test_source_classification_facet_uses_retained_paths_and_distinct_job_counts():
    db, engine = _facet_session()
    try:
        company = Company(
            company_id="facet-classification-company",
            source_site="jobsdb",
            source_company_id="facet-classification-company",
            name="Classification Company",
        )
        parent_and_child_job = Job(
            job_id="facet-classification-child",
            source_site="jobsdb",
            source_job_id="facet-classification-child",
            company=company,
            title="Backend role",
        )
        parent_only_job = Job(
            job_id="facet-classification-parent",
            source_site="jobsdb",
            source_job_id="facet-classification-parent",
            company=company,
            title="Technology role",
        )
        db.add_all([parent_and_child_job, parent_only_job])
        db.flush()
        parent_and_child_path = JobSourceClassificationPath(
            job_id=parent_and_child_job.id,
            source_site="jobsdb",
            source_order=0,
            path_fingerprint="1" * 64,
            is_primary=False,
            primary_basis=None,
            provenance={},
        )
        parent_only_path = JobSourceClassificationPath(
            job_id=parent_only_job.id,
            source_site="jobsdb",
            source_order=0,
            path_fingerprint="2" * 64,
            is_primary=False,
            primary_basis=None,
            provenance={},
        )
        db.add_all([parent_and_child_path, parent_only_path])
        db.flush()
        db.add_all(
            [
                JobSourceClassificationPathNode(
                    path_id=parent_and_child_path.id,
                    source_site="jobsdb",
                    source_position=0,
                    native_depth=0,
                    source_classification_id="jobsdb:6281",
                    native_id="6281",
                    label="Information Technology",
                ),
                JobSourceClassificationPathNode(
                    path_id=parent_and_child_path.id,
                    source_site="jobsdb",
                    source_position=1,
                    native_depth=1,
                    source_classification_id="jobsdb:6287",
                    native_id="6287",
                    label="Developers and Programmers",
                ),
                JobSourceClassificationPathNode(
                    path_id=parent_only_path.id,
                    source_site="jobsdb",
                    source_position=0,
                    native_depth=0,
                    source_classification_id="jobsdb:6281",
                    native_id="6281",
                    label="Information Technology",
                ),
            ]
        )
        db.commit()

        scope = JobSearchScopeSchema(
            layers=[
                JobSearchLayerSchema(
                    client_id="root",
                    structured_filters=JobSearchFiltersSchema(
                        source_site="jobsdb",
                        source_classification_ids=["jobsdb:6287"],
                    ),
                )
            ]
        )

        options = {
            option.id: option
            for option in JobSearchFacets(db).build(scope).source_classifications
        }

        assert list(options) == ["jobsdb:6281", "jobsdb:6287"]
        assert options["jobsdb:6281"].count == 2
        assert options["jobsdb:6287"].count == 1
        assert options["jobsdb:6287"].parent_id == "jobsdb:6281"
        assert options["jobsdb:6287"].path == (
            "Information Technology / Developers and Programmers"
        )
    finally:
        db.close()
        engine.dispose()


def test_job_taxonomy_facet_keeps_full_tree_and_aggregates_descendant_jobs():
    db, engine = _facet_session()
    try:
        company = Company(
            company_id="facet-taxonomy-company",
            source_site="jobsdb",
            source_company_id="facet-taxonomy-company",
            name="Taxonomy Company",
        )
        backend_job = Job(
            job_id="facet-taxonomy-backend",
            source_site="jobsdb",
            source_job_id="facet-taxonomy-backend",
            company=company,
            title="Backend Engineer",
        )
        frontend_job = Job(
            job_id="facet-taxonomy-frontend",
            source_site="jobsdb",
            source_job_id="facet-taxonomy-frontend",
            company=company,
            title="Frontend Engineer",
        )
        db.add_all([backend_job, frontend_job])
        db.flush()
        domain_code = "technology"
        category_code = "technology.software-development"
        backend_code = f"{category_code}.backend-development"
        frontend_code = f"{category_code}.frontend-development"
        db.add_all(
            [
                CurrentTaxonomyNodeRecord(
                    taxonomy="job",
                    code=domain_code,
                    parent_code=None,
                    level="domain",
                    labels={"en": "Technology"},
                    sort_order=1,
                    is_assignable=False,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="job",
                    code=category_code,
                    parent_code=domain_code,
                    level="category",
                    labels={"en": "Software Development"},
                    sort_order=1,
                    is_assignable=False,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="job",
                    code=backend_code,
                    parent_code=category_code,
                    level="subcategory",
                    labels={"en": "Backend Development"},
                    sort_order=1,
                    is_assignable=True,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="job",
                    code=frontend_code,
                    parent_code=category_code,
                    level="subcategory",
                    labels={"en": "Frontend Development"},
                    sort_order=2,
                    is_assignable=True,
                    is_active=True,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                CurrentJobTaxonomyAssignment(
                    job_id=backend_job.id,
                    taxonomy="job",
                    taxonomy_code=backend_code,
                    method="fixture",
                    evidence_hash="1" * 64,
                    source_evidence_refs=[],
                    mapping_ids=[],
                    model_provenance=None,
                    breadcrumb={},
                ),
                CurrentJobTaxonomyAssignment(
                    job_id=frontend_job.id,
                    taxonomy="job",
                    taxonomy_code=frontend_code,
                    method="fixture",
                    evidence_hash="2" * 64,
                    source_evidence_refs=[],
                    mapping_ids=[],
                    model_provenance=None,
                    breadcrumb={},
                ),
            ]
        )
        db.commit()

        scope = JobSearchScopeSchema(
            layers=[
                JobSearchLayerSchema(
                    client_id="root",
                    structured_filters=JobSearchFiltersSchema(
                        canonical_subcategory_ids=[backend_code],
                    ),
                )
            ]
        )

        options = {
            option.id: option
            for option in JobSearchFacets(db).build(scope).canonical_job_taxonomy
        }

        assert list(options) == [
            domain_code,
            category_code,
            backend_code,
            frontend_code,
        ]
        assert options[domain_code].count == 2
        assert options[category_code].count == 2
        assert options[backend_code].count == 1
        assert options[frontend_code].count == 1
        assert options[category_code].parent_id == domain_code
        assert options[frontend_code].level == "subcategory"
    finally:
        db.close()
        engine.dispose()


def test_company_industry_facet_counts_jobs_once_per_ancestor():
    db, engine = _facet_session()
    try:
        company = Company(
            company_id="facet-industry-company",
            source_site="jobsdb",
            source_company_id="facet-industry-company",
            name="Industry Company",
        )
        first_job = Job(
            job_id="facet-industry-first",
            source_site="jobsdb",
            source_job_id="facet-industry-first",
            company=company,
            title="Publishing role",
        )
        second_job = Job(
            job_id="facet-industry-second",
            source_site="jobsdb",
            source_job_id="facet-industry-second",
            company=company,
            title="Media role",
        )
        db.add_all([first_job, second_job])
        db.flush()
        section_code = "J"
        publishing_code = "58"
        media_code = "59"
        db.add_all(
            [
                CurrentTaxonomyNodeRecord(
                    taxonomy="company_industry",
                    code=section_code,
                    parent_code=None,
                    level="section",
                    labels={"en": "Information and communications"},
                    sort_order=1,
                    is_assignable=False,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="company_industry",
                    code=publishing_code,
                    parent_code=section_code,
                    level="division",
                    labels={"en": "Publishing activities"},
                    sort_order=1,
                    is_assignable=True,
                    is_active=True,
                ),
                CurrentTaxonomyNodeRecord(
                    taxonomy="company_industry",
                    code=media_code,
                    parent_code=section_code,
                    level="division",
                    labels={"en": "Media activities"},
                    sort_order=2,
                    is_assignable=True,
                    is_active=True,
                ),
            ]
        )
        db.flush()
        db.add_all(
            [
                CurrentCompanyIndustryAssignment(
                    company_id=company.id,
                    taxonomy="company_industry",
                    taxonomy_code=publishing_code,
                    method="fixture",
                    provenance={},
                    evidence_hash="3" * 64,
                    breadcrumb={},
                    is_primary=True,
                    primary_basis="fixture",
                ),
                CurrentCompanyIndustryAssignment(
                    company_id=company.id,
                    taxonomy="company_industry",
                    taxonomy_code=media_code,
                    method="fixture",
                    provenance={},
                    evidence_hash="4" * 64,
                    breadcrumb={},
                    is_primary=False,
                    primary_basis=None,
                ),
            ]
        )
        db.commit()

        scope = JobSearchScopeSchema(
            layers=[
                JobSearchLayerSchema(
                    client_id="root",
                    structured_filters=JobSearchFiltersSchema(
                        company_industry_node_ids=[publishing_code],
                    ),
                )
            ]
        )

        options = {
            option.id: option
            for option in JobSearchFacets(db).build(scope).company_industries
        }

        assert options[section_code].count == 2
        assert options[publishing_code].count == 2
        assert options[media_code].count == 2
        assert options[publishing_code].parent_id == section_code
    finally:
        db.close()
        engine.dispose()


def test_post_job_search_returns_facets_with_results_by_default():
    db, engine = _facet_session()
    try:
        app = FastAPI()
        app.include_router(jobs_api.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).post(
            "/api/jobs/search",
            json={
                "scope": {"layers": []},
                "page": 1,
                "page_size": 20,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["jobs"] == []
        assert payload["facets"]["employment_types"][0] == {
            "id": "full_time",
            "label": "Full-time",
            "count": 0,
            "order": 1,
            "parent_id": None,
            "level": None,
            "source": None,
            "path": None,
            "is_selectable": True,
        }
    finally:
        db.close()
        engine.dispose()


def test_post_job_search_can_omit_facets_for_pagination():
    db, engine = _facet_session()
    try:
        app = FastAPI()
        app.include_router(jobs_api.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).post(
            "/api/jobs/search",
            json={
                "scope": {"layers": []},
                "page": 1,
                "page_size": 20,
                "include_facets": False,
            },
        )

        assert response.status_code == 200
        assert response.json()["facets"] is None
    finally:
        db.close()
        engine.dispose()


def test_post_job_search_applies_layered_date_and_experience_windows():
    db, engine = _facet_session()
    try:
        company = Company(
            company_id="search-window-company",
            source_site="jobsdb",
            source_company_id="search-window-company",
            name="Search Window Company",
        )
        db.add_all(
            [
                Job(
                    job_id="date-boundary-unspecified",
                    source_site="jobsdb",
                    source_job_id="date-boundary-unspecified",
                    company=company,
                    title="Unspecified entry role",
                    posted_date=datetime(2026, 7, 15, 23, 59),
                    experience_level="not_specified",
                    experience_min_years=None,
                    experience_max_years=None,
                ),
                Job(
                    job_id="date-boundary-senior",
                    source_site="jobsdb",
                    source_job_id="date-boundary-senior",
                    company=company,
                    title="Senior boundary role",
                    posted_date=datetime(2026, 7, 15, 0, 1),
                    experience_level="senior",
                    experience_min_years=5,
                    experience_max_years=8,
                ),
                Job(
                    job_id="outside-date-junior",
                    source_site="jobsdb",
                    source_job_id="outside-date-junior",
                    company=company,
                    title="Junior outside date role",
                    posted_date=datetime(2026, 7, 14, 23, 59),
                    experience_level="entry",
                    experience_min_years=1,
                    experience_max_years=2,
                ),
                Job(
                    job_id="unknown-without-entry-signal",
                    source_site="jobsdb",
                    source_job_id="unknown-without-entry-signal",
                    company=company,
                    title="Unknown experience role",
                    posted_date=datetime(2026, 7, 15, 12, 0),
                    experience_level=None,
                    experience_min_years=None,
                    experience_max_years=None,
                ),
            ]
        )
        db.commit()

        app = FastAPI()
        app.include_router(jobs_api.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        date_response = client.post(
            "/api/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "structured_filters": {
                                "posted_date_from": "2026-07-15",
                                "posted_date_to": "2026-07-15",
                            },
                        }
                    ]
                },
                "include_facets": False,
            },
        )
        assert date_response.status_code == 200
        assert {job["job_id"] for job in date_response.json()["jobs"]} == {
            "date-boundary-unspecified",
            "date-boundary-senior",
            "unknown-without-entry-signal",
        }

        layered_response = client.post(
            "/api/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "structured_filters": {
                                "posted_date_from": "2026-07-15",
                                "posted_date_to": "2026-07-15",
                            },
                        },
                        {
                            "client_id": "refine-1",
                            "structured_filters": {
                                "experience_years_from": 0,
                                "experience_years_to": 1,
                            },
                        },
                    ]
                },
                "include_facets": False,
            },
        )
        assert layered_response.status_code == 200
        assert [job["job_id"] for job in layered_response.json()["jobs"]] == [
            "date-boundary-unspecified"
        ]

        reversed_response = client.post(
            "/api/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "structured_filters": {
                                "experience_years_from": 4,
                                "experience_years_to": 2,
                            },
                        }
                    ]
                },
                "include_facets": False,
            },
        )
        assert reversed_response.status_code == 422
    finally:
        db.close()
        engine.dispose()


def test_semantic_post_uses_candidate_scope_for_facets(monkeypatch):
    captured = {}

    class FakeEmbeddingModel:
        def encode(self, _text, *, normalize_embeddings):
            assert normalize_embeddings is True
            return [0.5]

    def fake_build_search_response(_query, **kwargs):
        captured.update(kwargs)
        return {
            "jobs": [],
            "total": 0,
            "page": kwargs["page"],
            "page_size": kwargs["page_size"],
            "total_pages": 0,
            "applied_scope": kwargs["applied_scope"],
            "layer_summaries": kwargs["layer_summaries"],
            "facets": None,
        }

    monkeypatch.setattr(
        retrieval_service_module,
        "_build_default_query_embedding_model",
        FakeEmbeddingModel,
    )
    monkeypatch.setattr(
        retrieval_service_module,
        "build_lexical_query",
        lambda _db, scope: scope,
    )
    monkeypatch.setattr(
        retrieval_service_module,
        "apply_semantic_order",
        lambda query, _vector: query,
    )
    monkeypatch.setattr(jobs_api, "_build_search_response", fake_build_search_response)

    async def fake_retrieval_api(request, *, layer_summaries):
        return retrieval_service_module.RetrievalService(object()).search(
            request,
            layer_summaries=layer_summaries,
        )

    monkeypatch.setattr(jobs_api, "_search_via_retrieval_api", fake_retrieval_api)

    app = FastAPI()
    app.include_router(jobs_api.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: object()
    response = TestClient(app).post(
        "/api/jobs/search",
        json={
            "scope": {
                "layers": [
                    {
                        "client_id": "root",
                        "text_expression": "jobsdb",
                        "structured_filters": {"source_site": "jobsdb"},
                    },
                    {
                        "client_id": "refine-1",
                        "text_expression": "platform engineer",
                        "structured_filters": {"employment_type_codes": ["full_time"]},
                    },
                ]
            },
            "retrieval_mode": "semantic",
            "include_facets": True,
        },
    )

    assert response.status_code == 200
    assert captured["applied_scope"].layers[-1].text_expression == "platform engineer"
    assert captured["facet_scope"].layers[0].text_expression == "jobsdb"
    assert captured["facet_scope"].layers[-1].text_expression == ""
