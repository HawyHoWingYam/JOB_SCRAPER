from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import retrieval as retrieval_api
from app.database import Base, get_db
from app.models import (
    Company,
    Job,
    JobEmbedding,
    JobSkill,
    JobSkillMention,
    Skill,
    SkillCategory,
    SkillReviewCandidate,
    SkillTechnology,
)
from app.models.job_embedding import EMBEDDING_DIMENSIONS
from app.repositories.job_embedding_repository import JobEmbeddingRepository
from app.services.retrieval_service import RetrievalService


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://admin:dev_password@localhost:5433/jobsdb",
)


class FakeQueryEmbeddingModel:
    def encode(self, value, normalize_embeddings=True):
        if isinstance(value, list):
            return [self._encode_one(item) for item in value]
        return self._encode_one(value)

    def _encode_one(self, value: str):
        normalized = str(value or "").lower()
        vector = [0.0] * EMBEDDING_DIMENSIONS
        if "platform" in normalized:
            vector[0] = 1.0
        elif "erp" in normalized:
            vector[1] = 1.0
        else:
            vector[0] = 0.5
            vector[1] = 0.5
        return vector


def _platform_vector():
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[0] = 1.0
    return vector


def _erp_vector():
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[1] = 1.0
    return vector


def _build_postgres_session():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text("DROP TABLE IF EXISTS job_embeddings CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS job_skill_mentions CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS job_skills CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS skill_review_candidates CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS skills CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS skill_technologies CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS skill_categories CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS jobs CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS companies CASCADE"))
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            Job.__table__,
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
            SkillReviewCandidate.__table__,
            JobSkill.__table__,
            JobSkillMention.__table__,
            JobEmbedding.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session, engine


def _build_test_client(Session, monkeypatch):
    app = FastAPI()
    app.include_router(retrieval_api.router, prefix="/api/v1")

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        retrieval_api,
        "RetrievalService",
        lambda db: RetrievalService(db, query_embedding_model=FakeQueryEmbeddingModel()),
        raising=False,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client


def _create_company(db, *, name, industry):
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{uuid.uuid4()}",
        source_site="jobsdb",
        source_company_id=f"source-company-{uuid.uuid4()}",
        name=name,
        industry=industry,
    )
    db.add(company)
    db.flush()
    return company


def _create_job(db, *, company, title, description, industry, embedding, posted_date):
    job = Job(
        id=uuid.uuid4(),
        job_id=f"jobsdb:{uuid.uuid4()}",
        source_site="jobsdb",
        source_job_id=f"source-job-{uuid.uuid4()}",
        company_id=company.id,
        title=title,
        description=description,
        source_classification_name=industry,
        posted_date=posted_date,
        created_at=posted_date,
        updated_at=posted_date,
    )
    db.add(job)
    db.flush()

    JobEmbeddingRepository().upsert_embedding(
        db,
        job_id=job.id,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2",
        embedding_dimensions=EMBEDDING_DIMENSIONS,
        embedding_version=1,
        document_text=description,
        document_hash=f"hash-{job.id}",
        embedding=embedding,
        auto_commit=False,
    )
    db.commit()
    return job


def _seed_jobs(db):
    healthcare = _create_company(db, name="Acme Health", industry="Healthcare")
    technology = _create_company(db, name="Platform Labs", industry="Technology")

    healthcare_platform = _create_job(
        db,
        company=healthcare,
        title="Platform Engineer",
        description="Build internal platform tooling",
        industry="Information & Communication Technology",
        embedding=_platform_vector(),
        posted_date=datetime(2026, 5, 6, 9, 0, 0),
    )
    healthcare_erp = _create_job(
        db,
        company=healthcare,
        title="ERP Operations Analyst",
        description="Run ERP operations and reporting",
        industry="Information & Communication Technology",
        embedding=_erp_vector(),
        posted_date=datetime(2026, 5, 5, 9, 0, 0),
    )
    technology_platform = _create_job(
        db,
        company=technology,
        title="Platform Architect",
        description="Lead platform architecture",
        industry="Information & Communication Technology",
        embedding=_platform_vector(),
        posted_date=datetime(2026, 5, 4, 9, 0, 0),
    )

    return {
        "healthcare_platform": healthcare_platform,
        "healthcare_erp": healthcare_erp,
        "technology_platform": technology_platform,
    }


@pytest.mark.asyncio
async def test_post_search_defaults_to_lexical_mode(monkeypatch):
    Session, engine = _build_postgres_session()
    client = _build_test_client(Session, monkeypatch)
    try:
        db = Session()
        try:
            _seed_jobs(db)
        finally:
            db.close()

        response = await client.post(
            "/api/v1/internal/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "text_expression": "platform",
                            "structured_filters": {},
                        }
                    ]
                },
                "page": 1,
                "page_size": 20,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert [job["title"] for job in payload["jobs"]] == [
            "Platform Engineer",
            "Platform Architect",
        ]
    finally:
        await client.aclose()
        engine.dispose()


@pytest.mark.asyncio
async def test_semantic_mode_uses_only_last_layer_text_and_preserves_prior_filters(monkeypatch):
    Session, engine = _build_postgres_session()
    client = _build_test_client(Session, monkeypatch)
    try:
        db = Session()
        try:
            _seed_jobs(db)
        finally:
            db.close()

        response = await client.post(
            "/api/v1/internal/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "text_expression": "",
                            "structured_filters": {"industry": "Healthcare"},
                        },
                        {
                            "client_id": "refine-1",
                            "text_expression": "platform",
                            "structured_filters": {},
                        },
                    ]
                },
                "retrieval_mode": "semantic",
                "page": 1,
                "page_size": 20,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert [job["title"] for job in payload["jobs"]] == [
            "Platform Engineer",
            "ERP Operations Analyst",
        ]
    finally:
        await client.aclose()
        engine.dispose()


@pytest.mark.asyncio
async def test_hybrid_mode_uses_same_last_layer_semantic_contract(monkeypatch):
    Session, engine = _build_postgres_session()
    client = _build_test_client(Session, monkeypatch)
    try:
        db = Session()
        try:
            _seed_jobs(db)
        finally:
            db.close()

        response = await client.post(
            "/api/v1/internal/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "text_expression": "",
                            "structured_filters": {"industry": "Healthcare"},
                        },
                        {
                            "client_id": "refine-1",
                            "text_expression": "platform",
                            "structured_filters": {},
                        },
                    ]
                },
                "retrieval_mode": "hybrid",
                "page": 1,
                "page_size": 20,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert [job["title"] for job in payload["jobs"]] == [
            "Platform Engineer",
            "ERP Operations Analyst",
        ]
    finally:
        await client.aclose()
        engine.dispose()


@pytest.mark.asyncio
async def test_semantic_mode_falls_back_to_lexical_when_last_layer_query_is_empty(monkeypatch):
    Session, engine = _build_postgres_session()
    client = _build_test_client(Session, monkeypatch)
    try:
        db = Session()
        try:
            _seed_jobs(db)
        finally:
            db.close()

        response = await client.post(
            "/api/v1/internal/jobs/search",
            json={
                "scope": {
                    "layers": [
                        {
                            "client_id": "root",
                            "text_expression": "platform",
                            "structured_filters": {},
                        },
                        {
                            "client_id": "refine-1",
                            "text_expression": "",
                            "structured_filters": {"industry": "Healthcare"},
                        },
                    ]
                },
                "retrieval_mode": "semantic",
                "page": 1,
                "page_size": 20,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert [job["title"] for job in payload["jobs"]] == [
            "Platform Engineer",
        ]
    finally:
        await client.aclose()
        engine.dispose()
