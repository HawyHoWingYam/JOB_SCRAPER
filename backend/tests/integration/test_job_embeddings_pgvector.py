import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job, JobCategory, JobDomain, JobEmbedding, JobSubcategory
from app.models.job_embedding import EMBEDDING_DIMENSIONS
from app.repositories.job_embedding_repository import JobEmbeddingRepository


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://admin:dev_password@localhost:5434/jobsdb",
)


def _build_postgres_session():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text("DROP TABLE IF EXISTS job_embeddings CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS jobs CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS companies CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS job_subcategories CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS job_categories CASCADE"))
        connection.execute(text("DROP TABLE IF EXISTS job_domains CASCADE"))
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            JobDomain.__table__,
            JobCategory.__table__,
            JobSubcategory.__table__,
            Job.__table__,
            JobEmbedding.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session(), engine


def _create_company_and_job(db):
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{uuid.uuid4()}",
        name=f"Company {uuid.uuid4()}",
        industry="Technology",
    )
    db.add(company)
    db.flush()

    job = Job(
        id=uuid.uuid4(),
        job_id=f"jobsdb:{uuid.uuid4()}",
        source_site="jobsdb",
        company_id=company.id,
        title="Platform Engineer",
        description="Distributed systems and data tooling",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    return job


def _unit_vector():
    return [1.0] + ([0.0] * (EMBEDDING_DIMENSIONS - 1))


def _tilted_vector():
    return [0.9, 0.1] + ([0.0] * (EMBEDDING_DIMENSIONS - 2))


def test_job_embedding_repository_persists_vectors_and_supports_cosine_query():
    db, engine = _build_postgres_session()
    try:
        repository = JobEmbeddingRepository()
        job = _create_company_and_job(db)

        repository.upsert_embedding(
            db,
            job_id=job.id,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dimensions=EMBEDDING_DIMENSIONS,
            embedding_version=1,
            document_text="platform engineer distributed systems",
            document_hash="hash-a",
            embedding=_unit_vector(),
        )
        repository.upsert_embedding(
            db,
            job_id=job.id,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2",
            embedding_dimensions=EMBEDDING_DIMENSIONS,
            embedding_version=2,
            document_text="platform engineer distributed systems updated",
            document_hash="hash-b",
            embedding=_tilted_vector(),
        )

        stored = db.query(JobEmbedding).filter(JobEmbedding.job_id == job.id).one()
        assert stored.document_hash == "hash-b"
        assert stored.embedding_dimensions == EMBEDDING_DIMENSIONS

        ranked_ids = [
            row[0]
            for row in db.query(JobEmbedding.job_id)
            .order_by(JobEmbedding.embedding.cosine_distance(_unit_vector()))
            .limit(1)
            .all()
        ]

        assert ranked_ids == [job.id]
    finally:
        db.close()
        engine.dispose()


def test_job_embedding_repository_rejects_non_384_dimension_vectors():
    db, engine = _build_postgres_session()
    try:
        repository = JobEmbeddingRepository()
        job = _create_company_and_job(db)

        with pytest.raises(ValueError, match="384"):
            repository.upsert_embedding(
                db,
                job_id=job.id,
                embedding_model="sentence-transformers/all-MiniLM-L6-v2",
                embedding_dimensions=128,
                embedding_version=1,
                document_text="platform engineer distributed systems",
                document_hash="hash-a",
                embedding=[1.0] * 128,
            )
    finally:
        db.close()
        engine.dispose()
