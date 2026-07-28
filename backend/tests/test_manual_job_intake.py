from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models.company import Company
from app.models.job import Job
from app.models.manual_job import ManualJobEvidence, ManualJobMutationReceipt
from app.models.source_job_attributes import EmploymentType, JobEmploymentType
from app.schemas.job import ManualJobCreateSchema
from app.services.manual_job_intake import (
    ManualJobDuplicateCandidatesError,
    ManualJobIdempotencyConflictError,
    ManualJobIntake,
    ManualJobNotEditableError,
)


@pytest.fixture()
def db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("Manual Job intake tests require a dedicated *_test database")

    engine = create_engine(database_url)
    tables = (
        Company.__table__,
        EmploymentType.__table__,
        Job.__table__,
        JobEmploymentType.__table__,
        ManualJobEvidence.__table__,
        ManualJobMutationReceipt.__table__,
    )
    Base.metadata.drop_all(engine, tables=list(reversed(tables)), checkfirst=True)
    Base.metadata.create_all(engine, tables=list(tables))
    session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )()
    try:
        session.add_all(
            [
                EmploymentType(code="full_time", label="Full-time", sort_order=1),
                EmploymentType(code="permanent", label="Permanent", sort_order=2),
            ]
        )
        session.commit()
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(
            engine,
            tables=list(reversed(tables)),
            checkfirst=True,
        )
        engine.dispose()


def _existing_company(db: Session, *, name: str = "Existing Company") -> Company:
    token = str(uuid4())
    company = Company(
        company_id=f"manual:{token}",
        source_site="manual",
        source_company_id=token,
        name=name,
    )
    db.add(company)
    db.commit()
    return company


def _command(company: Company, **overrides) -> ManualJobCreateSchema:
    payload = {
        "company": {"mode": "existing", "company_id": str(company.id)},
        "title": "Platform Engineer",
        "description": "Build reliable platforms",
        "employment_type_codes": ["full_time", "permanent"],
    }
    payload.update(overrides)
    return ManualJobCreateSchema.model_validate(payload)


def test_create_persists_one_atomic_manual_result_and_replays(db: Session) -> None:
    company = _existing_company(db)
    command = _command(company)
    service = ManualJobIntake(db)

    created = service.create(command, idempotency_key="create-1")
    db.commit()
    replayed = service.create(command, idempotency_key="create-1")

    assert created.job.source_site == "manual"
    assert created.job.company_id == company.id
    assert created.job.ai_enriched_at is None
    assert replayed.replayed is True
    assert replayed.job.id == created.job.id
    assert db.query(Job).count() == 1
    assert db.query(ManualJobEvidence).count() == 1
    assert db.query(ManualJobMutationReceipt).count() == 1
    assert {
        row.employment_type_code for row in db.query(JobEmploymentType).all()
    } == {"full_time", "permanent"}


def test_reusing_idempotency_key_for_different_command_conflicts(db: Session) -> None:
    company = _existing_company(db)
    service = ManualJobIntake(db)
    service.create(_command(company), idempotency_key="create-1")
    db.commit()

    with pytest.raises(ManualJobIdempotencyConflictError):
        service.create(
            _command(company, title="Different Job"),
            idempotency_key="create-1",
        )


def test_new_company_duplicate_requires_bound_confirmation(db: Session) -> None:
    _existing_company(db, name="Evidence Company")
    service = ManualJobIntake(db)
    payload = {
        "company": {
            "mode": "new",
            "name": " evidence company ",
            "website": "example.com",
        },
        "title": "Platform Engineer",
        "description": "Build reliable platforms",
    }
    command = ManualJobCreateSchema.model_validate(payload)

    with pytest.raises(ManualJobDuplicateCandidatesError) as caught:
        service.create(command, idempotency_key="create-duplicate")

    confirmation = caught.value.detail["confirmation"]
    confirmed = ManualJobCreateSchema.model_validate(
        {**payload, "duplicate_confirmation": confirmation}
    )
    result = service.create(confirmed, idempotency_key="create-duplicate")
    db.commit()

    assert result.company.name == "evidence company"
    assert result.company.website == "https://example.com"
    assert db.query(Company).count() == 2


def test_manual_update_marks_previously_enriched_evidence_stale(db: Session) -> None:
    company = _existing_company(db)
    service = ManualJobIntake(db)
    created = service.create(_command(company), idempotency_key="create-1")
    db.commit()
    evidence = db.query(ManualJobEvidence).one()
    evidence.enriched_evidence_hash = evidence.evidence_hash
    created.job.ai_enriched_at = created.job.created_at
    db.commit()
    previous_enriched_hash = evidence.enriched_evidence_hash

    updated = service.update(
        created.job.id,
        _command(company, description="Materially changed evidence"),
        idempotency_key="update-1",
    )
    db.commit()
    db.refresh(evidence)

    assert updated.job.description == "Materially changed evidence"
    assert evidence.evidence_hash != previous_enriched_hash
    assert evidence.enriched_evidence_hash == previous_enriched_hash


def test_collected_source_job_is_not_manual_editable(db: Session) -> None:
    company = _existing_company(db)
    collected = Job(
        job_id="jobsdb-job",
        source_site="jobsdb",
        source_job_id="jobsdb-job",
        company_id=company.id,
        title="Collected Job",
    )
    db.add(collected)
    db.commit()

    with pytest.raises(ManualJobNotEditableError):
        ManualJobIntake(db).update(
            collected.id,
            _command(company, title="Edited"),
            idempotency_key="update-collected",
        )
