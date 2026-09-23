from datetime import datetime

from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import jobs as jobs_api
from app.api.job_search_query import exact_anchor_fragments
from app.database import Base
from app.database import get_db
from app.job_intelligence.source_attributes import EMPLOYMENT_TYPE_SEEDS
from app.models import Company, Job
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentTaxonomyAliasRecord,
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
            CurrentTaxonomyAliasRecord.__table__,
            CurrentJobSkillAssignment.__table__,
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


def test_post_job_search_facets_returns_contextual_catalog():
    db, engine = _facet_session()
    try:
        app = FastAPI()
        app.include_router(jobs_api.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).post(
            "/api/jobs/search/facets",
            json={
                "scope": {"layers": []},
                "retrieval_mode": "lexical",
            },
        )

        assert response.status_code == 200
        assert response.json()["employment_types"][0] == {
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


def test_post_job_search_facets_matches_search_expression_validation():
    db, engine = _facet_session()
    try:
        app = FastAPI()
        app.include_router(jobs_api.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)
        scope = {
            "layers": [
                {
                    "client_id": "root",
                    "text_expression": '"unterminated',
                }
            ]
        }

        search_response = client.post(
            "/api/jobs/search",
            json={"scope": scope, "include_facets": False},
        )
        facets_response = client.post(
            "/api/jobs/search/facets",
            json={"scope": scope, "retrieval_mode": "lexical"},
        )

        assert facets_response.status_code == search_response.status_code == 422
        assert facets_response.json()["detail"] == search_response.json()["detail"]
    finally:
        db.close()
        engine.dispose()


def test_exact_anchor_fragments_are_necessary_under_search_normalization():
    assert exact_anchor_fragments("ERP") == ("erp",)
    assert exact_anchor_fragments("data_science") == ("data", "science")
    assert exact_anchor_fragments("C++") == ("c",)
    assert exact_anchor_fragments("++") == ()


def test_execute_search_page_returns_window_total_and_preserves_empty_pages():
    db, engine = _facet_session()
    try:
        company = Company(
            company_id="window-count-company",
            source_site="jobsdb",
            source_company_id="window-count-company",
            name="Window Count Company",
        )
        db.add_all(
            [
                Job(
                    job_id="window-oldest",
                    source_site="jobsdb",
                    source_job_id="window-oldest",
                    company=company,
                    title="Oldest",
                    posted_date=datetime(2026, 7, 1),
                ),
                Job(
                    job_id="window-middle",
                    source_site="jobsdb",
                    source_job_id="window-middle",
                    company=company,
                    title="Middle",
                    posted_date=datetime(2026, 7, 2),
                ),
                Job(
                    job_id="window-newest",
                    source_site="jobsdb",
                    source_job_id="window-newest",
                    company=company,
                    title="Newest",
                    posted_date=datetime(2026, 7, 3),
                ),
            ]
        )
        db.commit()
        query = jobs_api._build_query_from_scope(
            db,
            JobSearchScopeSchema(layers=[]),
        )
        statements: list[str] = []

        def capture_statement(_connection, _cursor, statement, *_args):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", capture_statement)
        rows, total = jobs_api.execute_search_page(
            query,
            page=1,
            page_size=2,
        )
        event.remove(engine, "before_cursor_execute", capture_statement)

        assert [job.job_id for job, _company in rows] == [
            "window-newest",
            "window-middle",
        ]
        assert total == 3
        assert any("OVER" in statement.upper() for statement in statements)
        assert not any(
            "SELECT COUNT(*) AS COUNT_1" in statement.upper()
            for statement in statements
        )

        rows, total = jobs_api.execute_search_page(
            query,
            page=3,
            page_size=2,
        )
        assert rows == []
        assert total == 3

        rows, total = jobs_api.execute_search_page(
            query.order_by(Job.title.asc()),
            page=1,
            page_size=3,
            preserve_query_order=True,
        )
        assert [job.job_id for job, _company in rows] == [
            "window-middle",
            "window-newest",
            "window-oldest",
        ]
        assert total == 3

        rows, total = jobs_api.execute_search_page(
            query.filter(Job.title == "Missing"),
            page=1,
            page_size=2,
        )
        assert rows == []
        assert total == 0
    finally:
        db.close()
        engine.dispose()


def test_semantic_and_hybrid_facets_use_the_candidate_scope_without_ranking():
    db, engine = _facet_session()
    try:
        jobsdb = Company(
            company_id="facet-candidate-jobsdb",
            source_site="jobsdb",
            source_company_id="facet-candidate-jobsdb",
            name="Candidate JobsDB Company",
        )
        ctgoodjobs = Company(
            company_id="facet-candidate-ctgoodjobs",
            source_site="ctgoodjobs",
            source_company_id="facet-candidate-ctgoodjobs",
            name="Candidate CTGoodJobs Company",
        )
        db.add_all(
            [
                Job(
                    job_id="facet-platform-role",
                    source_site="jobsdb",
                    source_job_id="facet-platform-role",
                    company=jobsdb,
                    title="Platform Engineer",
                ),
                Job(
                    job_id="facet-operations-role",
                    source_site="ctgoodjobs",
                    source_job_id="facet-operations-role",
                    company=ctgoodjobs,
                    title="Operations Analyst",
                ),
            ]
        )
        db.commit()

        app = FastAPI()
        app.include_router(jobs_api.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db
        client = TestClient(app)

        for retrieval_mode in ("semantic", "hybrid"):
            response = client.post(
                "/api/jobs/search/facets",
                json={
                    "scope": {
                        "layers": [
                            {
                                "client_id": "root",
                                "text_expression": "platform",
                            }
                        ]
                    },
                    "retrieval_mode": retrieval_mode,
                },
            )

            assert response.status_code == 200
            counts = {
                option["id"]: option["count"]
                for option in response.json()["sources"]
            }
            assert counts == {"jobsdb": 1, "ctgoodjobs": 1, "offertoday": 0}
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
