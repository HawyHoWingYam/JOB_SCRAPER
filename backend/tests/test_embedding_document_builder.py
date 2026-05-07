from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import Company, Job, JobSkillMention, Skill, SkillCategory, SkillTechnology
from app.services.embedding_document_builder import EmbeddingDocumentBuilder


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
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
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
            JobSkillMention.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_job_fixture(db):
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{uuid.uuid4()}",
        source_site="jobsdb",
        source_company_id=f"source-company-{uuid.uuid4()}",
        name="Acme Health",
        industry="Technology",
    )
    db.add(company)
    db.flush()

    category = SkillCategory(
        id=uuid.uuid4(),
        name="Backend",
        created_by="seed",
        is_auto_created=False,
        is_filter_visible=True,
    )
    technology = SkillTechnology(
        id=uuid.uuid4(),
        category_id=category.id,
        name="Python",
        created_by="seed",
        is_auto_created=False,
        is_filter_visible=True,
    )
    python_skill = Skill(
        id=uuid.uuid4(),
        technology_id=technology.id,
        name="Python",
        created_by="seed",
        is_auto_created=False,
        is_filter_visible=True,
    )
    kubernetes_skill = Skill(
        id=uuid.uuid4(),
        technology_id=technology.id,
        name="Kubernetes",
        created_by="seed",
        is_auto_created=False,
        is_filter_visible=True,
    )
    db.add_all([category, technology, python_skill, kubernetes_skill])
    db.flush()

    job = Job(
        id=uuid.uuid4(),
        job_id=f"jobsdb:{uuid.uuid4()}",
        source_site="jobsdb",
        source_job_id=f"source-job-{uuid.uuid4()}",
        company_id=company.id,
        title="Senior Platform Engineer",
        description=(
            "<div>Build&nbsp;data platforms</div>\n"
            "<ul><li>Operate Kubernetes clusters</li></ul>"
        ),
        source_classification_name="Information & Communication Technology",
        source_subclassification_name="Engineering - Software",
        ai_summary="Own the platform data stack.",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.flush()

    db.add_all(
        [
            JobSkillMention(
                id=uuid.uuid4(),
                job_id=job.id,
                raw_name="Python",
                normalized_name="python",
                resolution="match_existing",
                skill_id=python_skill.id,
                source="ai",
                confidence=0.9,
            ),
            JobSkillMention(
                id=uuid.uuid4(),
                job_id=job.id,
                raw_name="Kubernetes",
                normalized_name="kubernetes",
                resolution="match_existing",
                skill_id=kubernetes_skill.id,
                source="ai",
                confidence=0.9,
            ),
        ]
    )
    db.commit()
    db.refresh(job)
    return job


def test_embedding_document_builder_returns_deterministic_normalized_document():
    db = _build_sqlite_session()
    try:
        job = _create_job_fixture(db)
        builder = EmbeddingDocumentBuilder()

        first = builder.build_for_job(job)
        second = builder.build_for_job(job)

        assert first.document_text == (
            "Title: Senior Platform Engineer\n"
            "Company: Acme Health\n"
            "Source Taxonomy: Information & Communication Technology | Engineering - Software\n"
            "AI Summary: Own the platform data stack.\n"
            "Skills: Kubernetes | Python\n"
            "Description: Build data platforms Operate Kubernetes clusters"
        )
        assert first.document_hash == second.document_hash
        assert first.document_text == second.document_text
    finally:
        db.close()


def test_embedding_document_builder_hash_changes_when_summary_changes():
    db = _build_sqlite_session()
    try:
        job = _create_job_fixture(db)
        builder = EmbeddingDocumentBuilder()

        first = builder.build_for_job(job)
        job.ai_summary = "Design the internal developer platform."
        db.commit()
        db.refresh(job)
        second = builder.build_for_job(job)

        assert first.document_hash != second.document_hash
        assert "Design the internal developer platform." in second.document_text
    finally:
        db.close()


def test_embedding_document_builder_skips_empty_sections_and_truncates_description_excerpt():
    db = _build_sqlite_session()
    try:
        job = _create_job_fixture(db)
        builder = EmbeddingDocumentBuilder(description_excerpt_chars=80)

        job.ai_summary = None
        job.source_subclassification_name = None
        job.description = "<p>" + ("Alpha beta gamma " * 20) + "</p>"
        db.commit()
        db.refresh(job)

        document = builder.build_for_job(job)

        assert "AI Summary:" not in document.document_text
        assert "Source Taxonomy: Information & Communication Technology" in document.document_text
        assert "Engineering - Software" not in document.document_text
        description_line = document.document_text.splitlines()[-1]
        assert description_line.startswith("Description: ")
        assert len(description_line) == len("Description: ") + 80
    finally:
        db.close()
