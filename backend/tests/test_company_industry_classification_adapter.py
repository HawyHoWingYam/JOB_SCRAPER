from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import UUID, create_engine, event, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.job_intelligence.current_taxonomies.company_mapping_manifest import (
    load_company_industry_mapping_manifest,
)
from app.models.company import Company
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentSourceTaxonomyMapping,
    CurrentTaxonomyNodeRecord,
)
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.services.classification_batch_runtime import ClassificationCandidate
from app.services.classification_domain_adapters import (
    CompanyIndustryClassificationAdapter,
)


@compiles(UUID, "sqlite")
def _compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


def _manifest(tmp_path: Path):
    path = tmp_path / "company-mapping.json"
    path.write_text(
        json.dumps(
            {
                "taxonomy": "company_industry",
                "sources": [
                    {
                        "source_site": "offertoday",
                        "entries": [
                            {
                                "source_label": "電訊",
                                "source_key": "label:電訊",
                                "disposition": "mapped",
                                "target_codes": ["611000"],
                            },
                            {
                                "source_label": "其他",
                                "source_key": "label:其他",
                                "disposition": "non_mapping",
                                "reason": "Explicit Other label.",
                            },
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return load_company_industry_mapping_manifest(path)


@pytest.fixture
def company_db() -> Session:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    for table in (
        Company.__table__,
        Job.__table__,
        CurrentTaxonomyNodeRecord.__table__,
        CurrentCompanyIndustryAssignment.__table__,
        CurrentSourceTaxonomyMapping.__table__,
        EventOutbox.__table__,
    ):
        table.create(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        session.add(
            CurrentTaxonomyNodeRecord(
                taxonomy="company_industry",
                code="611000",
                parent_code=None,
                level="subclass",
                labels={"en": "Telecommunications network operation"},
                sort_order=1,
                is_assignable=True,
                is_active=True,
            )
        )
        session.flush()
        session.add(
            CurrentSourceTaxonomyMapping(
                taxonomy="company_industry",
                source_site="offertoday",
                source_key="label:電訊",
                source_label="電訊",
                target_code="611000",
                role="deterministic",
                evidence={
                    "managed_by": "company_industry_source_mapping_manifest",
                    "disposition": "mapped",
                },
            )
        )
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


def _company_with_job(db: Session, *, name: str, label: str) -> Company:
    company = Company(
        id=uuid4(),
        company_id=f"offertoday:{name}",
        source_site="offertoday",
        source_company_id=name,
        name=name,
        is_deleted=False,
    )
    db.add(company)
    db.flush()
    db.add(
        Job(
            id=uuid4(),
            job_id=f"offertoday:{name}:job",
            source_site="offertoday",
            source_job_id=f"{name}:job",
            company_id=company.id,
            title=f"{name} job",
            raw_data={"industry": {"name": label}},
            is_deleted=False,
        )
    )
    db.flush()
    return company


def test_company_selection_counts_mapped_unsupported_and_governed_exclusions(
    tmp_path: Path,
    company_db: Session,
):
    mapped = _company_with_job(company_db, name="Mapped", label="電訊")
    excluded = _company_with_job(company_db, name="Excluded", label="其他")
    unsupported = _company_with_job(company_db, name="Unsupported", label="新行業")
    company_db.commit()
    adapter = CompanyIndustryClassificationAdapter(manifest=_manifest(tmp_path))

    selection = adapter.select_candidates(company_db, filters={}, limit=3)

    assert selection.selected_item_count == 3
    assert selection.mapped_item_count == 1
    assert selection.unmapped_item_count == 1
    assert selection.excluded_item_count == 1
    assert {item.subject_id for item in selection.candidates} == {
        str(mapped.id),
        str(unsupported.id),
    }
    assert str(excluded.id) not in {item.subject_id for item in selection.candidates}
    unsupported_item = next(
        item for item in selection.candidates if item.subject_id == str(unsupported.id)
    )
    assert "no governed disposition" in str(unsupported_item.payload)


def test_company_retry_omits_subject_that_is_now_an_explicit_non_mapping(
    tmp_path: Path,
    company_db: Session,
):
    excluded = _company_with_job(company_db, name="Excluded", label="其他")
    unsupported = _company_with_job(company_db, name="Unsupported", label="新行業")
    company_db.commit()
    adapter = CompanyIndustryClassificationAdapter(manifest=_manifest(tmp_path))
    historical = (
        ClassificationCandidate(subject_id=str(excluded.id)),
        ClassificationCandidate(subject_id=str(unsupported.id)),
    )

    retryable = adapter.filter_retry_candidates(company_db, historical)

    assert [candidate.subject_id for candidate in retryable] == [str(unsupported.id)]


def test_manifest_database_drift_is_an_actionable_unsupported_item(
    tmp_path: Path,
    company_db: Session,
):
    company = _company_with_job(company_db, name="Drift", label="電訊")
    row = company_db.get(
        CurrentSourceTaxonomyMapping,
        ("company_industry", "offertoday", "label:電訊", "611000"),
    )
    company_db.delete(row)
    company_db.commit()
    adapter = CompanyIndustryClassificationAdapter(manifest=_manifest(tmp_path))

    selection = adapter.select_candidates(company_db, filters={}, limit=1)

    assert selection.mapped_item_count == 0
    assert selection.unmapped_item_count == 1
    assert selection.candidates[0].subject_id == str(company.id)
    assert "manifest/database mapping drift" in str(selection.candidates[0].payload)


@pytest.mark.asyncio
async def test_mapping_drift_after_start_snapshot_fails_before_assignment(
    tmp_path: Path,
    company_db: Session,
):
    _company_with_job(company_db, name="Drift", label="電訊")
    company_db.commit()
    adapter = CompanyIndustryClassificationAdapter(manifest=_manifest(tmp_path))
    candidate = adapter.select_candidates(company_db, filters={}, limit=1).candidates[0]
    row = company_db.get(
        CurrentSourceTaxonomyMapping,
        ("company_industry", "offertoday", "label:電訊", "611000"),
    )
    company_db.delete(row)
    company_db.commit()

    with pytest.raises(ValueError, match="manifest/database mapping drift"):
        await adapter.process_candidate(company_db, candidate)

    assert company_db.scalar(
        select(CurrentCompanyIndustryAssignment)
    ) is None


@pytest.mark.asyncio
async def test_mapped_company_candidate_records_provenance_bearing_assignment(
    tmp_path: Path,
    company_db: Session,
):
    company = _company_with_job(company_db, name="Mapped", label="電訊")
    company_db.commit()
    adapter = CompanyIndustryClassificationAdapter(manifest=_manifest(tmp_path))
    candidate = adapter.select_candidates(company_db, filters={}, limit=1).candidates[0]

    await adapter.process_candidate(company_db, candidate)
    company_db.commit()

    assignment = company_db.scalar(
        select(CurrentCompanyIndustryAssignment).where(
            CurrentCompanyIndustryAssignment.company_id == company.id
        )
    )
    assert assignment is not None
    assert assignment.taxonomy_code == "611000"
    assert assignment.method == "source_mapping"
    assert assignment.provenance["raw_label"] == "電訊"
    assert assignment.provenance["mapping"] == {
        "source_key": "label:電訊",
        "target_code": "611000",
    }
