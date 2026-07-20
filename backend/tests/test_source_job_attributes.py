from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, delete, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import set_committed_value

from app.database import Base
from app.api.jobs import (
    _apply_structured_filters,
    _build_search_response_from_results,
    get_filter_options,
)
from app.job_intelligence.foundation import Provenance
from app.job_intelligence.source_attributes import (
    EMPLOYMENT_TYPE_SEEDS,
    JobsDBSourceEvidenceAdapter,
    OfferTodaySourceEvidenceAdapter,
    SourceCatalogRevisionRef,
    SourceClassificationNodeEvidence,
    SourceClassificationPathEvidence,
    SourceJobAttributeEvidence,
    SourceJobAttributeRebuildInspector,
    SourceJobAttributes,
)
from app.models.canonical_job_taxonomy import CANONICAL_JOB_TAXONOMY_TABLES
from app.models.company import Company
from app.models.crawl_job_listing import CrawlJobListing
from app.models.event_outbox import EventOutbox
from app.models.governance import GOVERNANCE_FOUNDATION_TABLES
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.source_catalog import SourceCatalogCandidate, SourceCatalogRevision
from app.models.source_job_attributes import (
    SOURCE_JOB_ATTRIBUTE_TABLES,
    EmploymentType,
    JobEmploymentType,
    JobSourceAttributeProjection,
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
    JobSourceEmploymentLabel,
)
from app.schemas.job import JobDetailSchema
from app.schemas.job_search import JobSearchFiltersSchema
from app.services.jobsdb_detail_repair_service import JobsDBDetailRepairService
from app.sources.jobsdb.parsers import parse_detail_redux_data


@pytest.fixture()
def source_attribute_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail("Source Job Attribute tests require a dedicated *_test database")
    engine = create_engine(database_url)
    tables = (
        Company.__table__,
        JobDomain.__table__,
        JobCategory.__table__,
        JobSubcategory.__table__,
        Job.__table__,
        CrawlJobListing.__table__,
        EventOutbox.__table__,
        *GOVERNANCE_FOUNDATION_TABLES,
        SourceCatalogCandidate.__table__,
        SourceCatalogRevision.__table__,
        *SOURCE_JOB_ATTRIBUTE_TABLES,
        *CANONICAL_JOB_TAXONOMY_TABLES,
    )
    Base.metadata.create_all(engine, tables=tables)
    db = sessionmaker(bind=engine)()
    try:
        db.add_all(
            EmploymentType(code=code, label=label, sort_order=sort_order)
            for code, label, sort_order in EMPLOYMENT_TYPE_SEEDS
        )
        db.commit()
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine, tables=list(reversed(tables)))
        engine.dispose()


def test_project_is_idempotent_through_the_source_job_attributes_interface(
    source_attribute_db,
):
    company = Company(
        company_id="company-1",
        source_site="jobsdb",
        source_company_id="company-1",
        name="Example Limited",
    )
    job = Job(
        job_id="job-1",
        source_site="jobsdb",
        source_job_id="job-1",
        company=company,
        title="Platform Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
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
            evidence_refs=({"kind": "listing-payload", "source_job_id": "job-1"},),
            captured_at=datetime(2026, 7, 18, 10, 0, tzinfo=timezone.utc),
        ),
    )
    module = SourceJobAttributes(source_attribute_db)

    first = module.project(job.id, evidence)
    replay = module.project(job.id, evidence)
    view = module.get(job.id)

    assert {
        "first": (first.changed, first.version),
        "replay": (replay.changed, replay.version),
        "paths": [
            [node.source_classification_id for node in path.nodes]
            for path in view.source_classification_paths
        ],
        "primary_flags": [path.is_primary for path in view.source_classification_paths],
        "employment_types": [item.code for item in view.employment_types],
        "source_employment_labels": [
            (label.raw_label, label.mapped_type_code)
            for label in view.source_employment_labels
        ],
    } == {
        "first": (True, 1),
        "replay": (False, 1),
        "paths": [
            ["jobsdb:6281", "jobsdb:6287"],
            ["jobsdb:6092"],
        ],
        "primary_flags": [False, False],
        "employment_types": ["full_time", "permanent"],
        "source_employment_labels": [
            ("Full-time", "full_time"),
            ("Permanent", "permanent"),
        ],
    }


def test_changed_evidence_replaces_projection_and_advances_one_version(
    source_attribute_db,
):
    company = Company(
        company_id="replacement-company",
        source_site="jobsdb",
        source_company_id="replacement-company",
        name="Replacement Company",
    )
    job = Job(
        job_id="replacement-job",
        source_site="jobsdb",
        source_job_id="replacement-job",
        company=company,
        title="Replacement Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    provenance = Provenance(
        method="fixture",
        source_site="jobsdb",
        evidence_refs=({"kind": "fixture", "id": "replacement"},),
        captured_at=datetime(2026, 7, 18, 10, 15, tzinfo=timezone.utc),
    )
    first_evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
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
        provenance=provenance,
    )
    replacement_evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6163",
                        "description": "Science and Technology",
                    }
                }
            ],
            "workTypes": ["Part-time"],
        },
        provenance=provenance,
    )
    module = SourceJobAttributes(source_attribute_db)

    first = module.project(job.id, first_evidence)
    replacement = module.project(job.id, replacement_evidence)
    replay = module.project(job.id, replacement_evidence)
    view = module.get(job.id)

    assert {
        "results": [
            (first.changed, first.version),
            (replacement.changed, replacement.version),
            (replay.changed, replay.version),
        ],
        "paths": [
            [node.source_classification_id for node in path.nodes]
            for path in view.source_classification_paths
        ],
        "labels": [label.raw_label for label in view.source_employment_labels],
        "types": [item.code for item in view.employment_types],
        "event_versions": [
            event.payload["version"]
            for event in source_attribute_db.query(EventOutbox)
            .order_by(EventOutbox.created_at, EventOutbox.id)
            .all()
        ],
    } == {
        "results": [(True, 1), (True, 2), (False, 2)],
        "paths": [["jobsdb:6163"]],
        "labels": ["Part-time"],
        "types": ["part_time"],
        "event_versions": [1, 2],
    }


def test_concurrent_exact_projection_serializes_to_one_version_and_event(
    source_attribute_db,
):
    company = Company(
        company_id="concurrent-company",
        source_site="jobsdb",
        source_company_id="concurrent-company",
        name="Concurrent Company",
    )
    job = Job(
        job_id="concurrent-job",
        source_site="jobsdb",
        source_job_id="concurrent-job",
        company=company,
        title="Concurrent Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.commit()
    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                }
            ],
            "workTypes": ["Full-time", "Permanent"],
        },
        provenance=Provenance(
            method="fixture",
            source_site="jobsdb",
            evidence_refs=({"kind": "fixture", "id": "concurrency"},),
            captured_at=datetime(2026, 7, 18, 10, 20, tzinfo=timezone.utc),
        ),
    )
    session_factory = sessionmaker(bind=source_attribute_db.get_bind())

    def project_once():
        db = session_factory()
        try:
            result = SourceJobAttributes(db).project(job.id, evidence)
            db.commit()
            return result.changed, result.version
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(project_once) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]

    source_attribute_db.expire_all()
    view = SourceJobAttributes(source_attribute_db).get(job.id)
    assert {
        "results": sorted(results),
        "version": view.version,
        "event_versions": [
            event.payload["version"]
            for event in source_attribute_db.query(EventOutbox).all()
        ],
    } == {
        "results": [(False, 1), (True, 1)],
        "version": 1,
        "event_versions": [1],
    }


def test_changed_projection_enqueues_one_bounded_outbox_event(source_attribute_db):
    company = Company(
        company_id="company-2",
        source_site="jobsdb",
        source_company_id="company-2",
        name="Event Example Limited",
    )
    job = Job(
        job_id="job-2",
        source_site="jobsdb",
        source_job_id="job-2",
        company=company,
        title="Data Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                }
            ],
            "workTypes": ["Full-time"],
        },
        provenance=Provenance(
            method="jobsdb-listing-payload",
            source_site="jobsdb",
            evidence_refs=({"kind": "listing-payload", "source_job_id": "job-2"},),
            captured_at=datetime(2026, 7, 18, 10, 30, tzinfo=timezone.utc),
        ),
    )
    module = SourceJobAttributes(source_attribute_db)

    first = module.project(job.id, evidence)
    module.project(job.id, evidence)
    events = source_attribute_db.query(EventOutbox).all()

    assert [
        {
            "topic": event.topic,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "event_type": event.event_type,
            "source_service": event.source_service,
            "payload": event.payload,
        }
        for event in events
    ] == [
        {
            "topic": "job-intelligence-projections",
            "aggregate_type": "job",
            "aggregate_id": str(job.id),
            "event_type": "job.source_attributes_changed",
            "source_service": "source-job-attributes",
            "payload": {
                "job_id": str(job.id),
                "source_site": "jobsdb",
                "version": 1,
                "evidence_hash": first.view.evidence_hash,
            },
        }
    ]


def test_outbox_failure_rolls_back_job_and_projection_replacement(
    source_attribute_db,
):
    company = Company(
        company_id="rollback-company",
        source_site="jobsdb",
        source_company_id="rollback-company",
        name="Rollback Company",
    )
    job = Job(
        job_id="rollback-job",
        source_site="jobsdb",
        source_job_id="rollback-job",
        company=company,
        title="Original title",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    provenance = Provenance(
        method="fixture",
        source_site="jobsdb",
        evidence_refs=({"kind": "fixture", "id": "rollback"},),
        captured_at=datetime(2026, 7, 18, 10, 45, tzinfo=timezone.utc),
    )
    original_evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                }
            ],
            "workTypes": ["Full-time"],
        },
        provenance=provenance,
    )
    SourceJobAttributes(source_attribute_db).project(job.id, original_evidence)
    source_attribute_db.commit()

    class FailingOutboxRepository:
        @staticmethod
        def enqueue(*_args, **_kwargs):
            raise RuntimeError("injected outbox failure")

    replacement_evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6092",
                        "description": "Engineering",
                    }
                }
            ],
            "workTypes": ["Permanent"],
        },
        provenance=provenance,
    )
    job.title = "Title that must roll back"

    with pytest.raises(RuntimeError, match="injected outbox failure"):
        SourceJobAttributes(
            source_attribute_db,
            outbox_repository=FailingOutboxRepository(),
        ).project(job.id, replacement_evidence)
    source_attribute_db.rollback()
    source_attribute_db.expire_all()

    reloaded_job = source_attribute_db.get(Job, job.id)
    view = SourceJobAttributes(source_attribute_db).get(job.id)
    assert {
        "title": reloaded_job.title,
        "version": view.version,
        "paths": [
            path.nodes[0].source_classification_id
            for path in view.source_classification_paths
        ],
        "types": [item.code for item in view.employment_types],
        "event_versions": [
            event.payload["version"]
            for event in source_attribute_db.query(EventOutbox).all()
        ],
    } == {
        "title": "Original title",
        "version": 1,
        "paths": ["jobsdb:6281"],
        "types": ["full_time"],
        "event_versions": [1],
    }


def test_unknown_catalog_revision_is_queryable_and_visibly_provenance_limited(
    source_attribute_db,
):
    company = Company(
        company_id="company-3",
        source_site="jobsdb",
        source_company_id="company-3",
        name="Historical Example Limited",
    )
    job = Job(
        job_id="job-3",
        source_site="jobsdb",
        source_job_id="job-3",
        company=company,
        title="Legacy Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                }
            ]
        },
        provenance=Provenance(
            method="legacy-raw-data",
            source_site="jobsdb",
            evidence_refs=({"kind": "job-raw-data", "source_job_id": "job-3"},),
            captured_at=datetime(2026, 7, 18, 11, 0, tzinfo=timezone.utc),
        ),
    )

    path = (
        SourceJobAttributes(source_attribute_db)
        .project(job.id, evidence)
        .view.source_classification_paths[0]
    )

    assert {
        "catalog_revision": path.source_catalog_revision,
        "provenance_limited": path.provenance_limited,
        "identity": path.nodes[0].source_classification_id,
    } == {
        "catalog_revision": None,
        "provenance_limited": True,
        "identity": "jobsdb:6281",
    }


def test_known_catalog_revision_round_trips_as_independent_source_identity(
    source_attribute_db,
):
    candidate = SourceCatalogCandidate(
        source_site="jobsdb",
        fingerprint="a" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        diff={},
        validation_summary={},
        state="published",
    )
    source_attribute_db.add(candidate)
    source_attribute_db.flush()
    revision = SourceCatalogRevision(
        source_site="jobsdb",
        sequence=1,
        fingerprint="a" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        candidate_id=candidate.id,
        publication_metadata={},
        published_by="local-operator",
    )
    company = Company(
        company_id="company-4",
        source_site="jobsdb",
        source_company_id="company-4",
        name="Revision Example Limited",
    )
    job = Job(
        job_id="job-4",
        source_site="jobsdb",
        source_job_id="job-4",
        company=company,
        title="Catalog Engineer",
    )
    source_attribute_db.add_all([revision, job])
    source_attribute_db.flush()
    revision_ref = SourceCatalogRevisionRef(
        source_site="jobsdb",
        revision_id=revision.id,
        fingerprint=revision.fingerprint,
    )
    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                }
            ]
        },
        provenance=Provenance(
            method="jobsdb-listing-payload",
            source_site="jobsdb",
            evidence_refs=({"kind": "listing-payload", "source_job_id": "job-4"},),
            captured_at=datetime(2026, 7, 18, 11, 30, tzinfo=timezone.utc),
        ),
        source_catalog_revision=revision_ref,
    )

    path = (
        SourceJobAttributes(source_attribute_db)
        .project(job.id, evidence)
        .view.source_classification_paths[0]
    )

    assert {
        "catalog_revision": path.source_catalog_revision,
        "provenance_limited": path.provenance_limited,
    } == {
        "catalog_revision": revision_ref,
        "provenance_limited": False,
    }


def test_catalog_revision_delete_is_restricted_and_job_delete_cascades(
    source_attribute_db,
):
    candidate = SourceCatalogCandidate(
        source_site="jobsdb",
        fingerprint="c" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        diff={},
        validation_summary={},
        state="published",
    )
    source_attribute_db.add(candidate)
    source_attribute_db.flush()
    revision = SourceCatalogRevision(
        source_site="jobsdb",
        sequence=3,
        fingerprint="c" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        candidate_id=candidate.id,
        publication_metadata={},
        published_by="local-operator",
    )
    company = Company(
        company_id="cascade-company",
        source_site="jobsdb",
        source_company_id="cascade-company",
        name="Cascade Company",
    )
    job = Job(
        job_id="cascade-job",
        source_site="jobsdb",
        source_job_id="cascade-job",
        company=company,
        title="Cascade Engineer",
    )
    source_attribute_db.add_all([revision, job])
    source_attribute_db.flush()
    SourceJobAttributes(source_attribute_db).project(
        job.id,
        JobsDBSourceEvidenceAdapter().extract(
            {
                "classifications": [
                    {
                        "classification": {
                            "id": "6281",
                            "description": "Information Technology",
                        }
                    }
                ],
                "workTypes": ["Full-time"],
            },
            provenance=Provenance(
                method="fixture",
                source_site="jobsdb",
                evidence_refs=({"kind": "fixture", "id": "cascade"},),
                captured_at=datetime(2026, 7, 18, 11, 45, tzinfo=timezone.utc),
            ),
            source_catalog_revision=SourceCatalogRevisionRef(
                source_site="jobsdb",
                revision_id=revision.id,
                fingerprint=revision.fingerprint,
            ),
        ),
    )
    source_attribute_db.commit()
    job_id = job.id
    revision_id = revision.id

    with pytest.raises(
        IntegrityError,
        match="fk_job_source_classification_path_catalog_source",
    ):
        source_attribute_db.execute(
            delete(SourceCatalogRevision).where(SourceCatalogRevision.id == revision_id)
        )
    source_attribute_db.rollback()

    source_attribute_db.execute(delete(Job).where(Job.id == job_id))
    source_attribute_db.commit()

    assert {
        "projection": source_attribute_db.query(JobSourceAttributeProjection).count(),
        "paths": source_attribute_db.query(JobSourceClassificationPath).count(),
        "nodes": source_attribute_db.query(JobSourceClassificationPathNode).count(),
        "labels": source_attribute_db.query(JobSourceEmploymentLabel).count(),
        "employment_types": source_attribute_db.query(JobEmploymentType).count(),
        "catalog_revision": source_attribute_db.query(SourceCatalogRevision).count(),
        "outbox": source_attribute_db.query(EventOutbox).count(),
    } == {
        "projection": 0,
        "paths": 0,
        "nodes": 0,
        "labels": 0,
        "employment_types": 0,
        "catalog_revision": 1,
        "outbox": 1,
    }


def test_catalog_revision_fingerprint_mismatch_fails_before_projection_write(
    source_attribute_db,
):
    candidate = SourceCatalogCandidate(
        source_site="jobsdb",
        fingerprint="a" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        diff={},
        validation_summary={},
        state="published",
    )
    source_attribute_db.add(candidate)
    source_attribute_db.flush()
    revision = SourceCatalogRevision(
        source_site="jobsdb",
        sequence=1,
        fingerprint="a" * 64,
        normalized_payload={"version": 1, "nodes": []},
        source_payload={"categories": []},
        provenance={"method": "fixture"},
        candidate_id=candidate.id,
        publication_metadata={},
        published_by="local-operator",
    )
    company = Company(
        company_id="company-5",
        source_site="jobsdb",
        source_company_id="company-5",
        name="Mismatch Example Limited",
    )
    job = Job(
        job_id="job-5",
        source_site="jobsdb",
        source_job_id="job-5",
        company=company,
        title="Identity Engineer",
    )
    source_attribute_db.add_all([revision, job])
    source_attribute_db.flush()
    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                }
            ]
        },
        provenance=Provenance(
            method="jobsdb-listing-payload",
            source_site="jobsdb",
            evidence_refs=({"kind": "listing-payload", "source_job_id": "job-5"},),
            captured_at=datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc),
        ),
        source_catalog_revision=SourceCatalogRevisionRef(
            source_site="jobsdb",
            revision_id=revision.id,
            fingerprint="b" * 64,
        ),
    )

    with pytest.raises(ValueError, match="fingerprint"):
        SourceJobAttributes(source_attribute_db).project(job.id, evidence)

    assert source_attribute_db.get(JobSourceAttributeProjection, job.id) is None


def test_database_rejects_classification_node_from_another_source(
    source_attribute_db,
):
    company = Company(
        company_id="source-check-company",
        source_site="jobsdb",
        source_company_id="source-check-company",
        name="Source Check Company",
    )
    job = Job(
        job_id="source-check-job",
        source_site="jobsdb",
        source_job_id="source-check-job",
        company=company,
        title="Source Check Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    SourceJobAttributes(source_attribute_db).project(
        job.id,
        JobsDBSourceEvidenceAdapter().extract(
            {
                "classifications": [
                    {
                        "classification": {
                            "id": "6281",
                            "description": "Information Technology",
                        }
                    }
                ]
            },
            provenance=Provenance(
                method="fixture",
                source_site="jobsdb",
                evidence_refs=({"kind": "fixture", "id": "source-check"},),
                captured_at=datetime(2026, 7, 18, 12, 15, tzinfo=timezone.utc),
            ),
        ),
    )
    source_attribute_db.commit()
    node = source_attribute_db.query(JobSourceClassificationPathNode).one()

    node.source_classification_id = "offertoday:6281"

    with pytest.raises(
        IntegrityError,
        match="ck_job_source_classification_node_source_identity",
    ):
        source_attribute_db.flush()
    source_attribute_db.rollback()
    source_attribute_db.refresh(node)
    assert node.source_classification_id == "jobsdb:6281"


def test_projection_rejects_primary_without_explicit_basis_before_writes(
    source_attribute_db,
):
    company = Company(
        company_id="primary-validation-company",
        source_site="jobsdb",
        source_company_id="primary-validation-company",
        name="Primary Validation Company",
    )
    job = Job(
        job_id="primary-validation-job",
        source_site="jobsdb",
        source_job_id="primary-validation-job",
        company=company,
        title="Primary Validation Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    provenance = Provenance(
        method="fixture",
        source_site="jobsdb",
        evidence_refs=({"kind": "fixture", "id": "invalid-primary"},),
        captured_at=datetime(2026, 7, 18, 12, 20, tzinfo=timezone.utc),
    )
    evidence = SourceJobAttributeEvidence(
        source_site="jobsdb",
        classification_paths=(
            SourceClassificationPathEvidence(
                source_order=0,
                nodes=(
                    SourceClassificationNodeEvidence(
                        source_position=0,
                        native_depth=0,
                        source_classification_id="jobsdb:6281",
                        native_id="6281",
                        label="Information Technology",
                    ),
                ),
                source_declared_primary=True,
                primary_basis=" ",
                source_catalog_revision=None,
                provenance=provenance,
            ),
        ),
        employment_labels=(),
    )

    with pytest.raises(ValueError, match="Primary path requires a non-empty basis"):
        SourceJobAttributes(source_attribute_db).project(job.id, evidence)

    assert {
        "projection": source_attribute_db.get(
            JobSourceAttributeProjection,
            job.id,
        ),
        "outbox": source_attribute_db.query(EventOutbox).count(),
    } == {"projection": None, "outbox": 0}


def test_projection_rejects_node_identity_from_another_source_before_writes(
    source_attribute_db,
):
    company = Company(
        company_id="node-validation-company",
        source_site="jobsdb",
        source_company_id="node-validation-company",
        name="Node Validation Company",
    )
    job = Job(
        job_id="node-validation-job",
        source_site="jobsdb",
        source_job_id="node-validation-job",
        company=company,
        title="Node Validation Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    provenance = Provenance(
        method="fixture",
        source_site="jobsdb",
        evidence_refs=({"kind": "fixture", "id": "invalid-node-source"},),
        captured_at=datetime(2026, 7, 18, 12, 25, tzinfo=timezone.utc),
    )
    evidence = SourceJobAttributeEvidence(
        source_site="jobsdb",
        classification_paths=(
            SourceClassificationPathEvidence(
                source_order=0,
                nodes=(
                    SourceClassificationNodeEvidence(
                        source_position=0,
                        native_depth=0,
                        source_classification_id="offertoday:118000",
                        native_id="118000",
                        label="Information Technology",
                    ),
                ),
                source_declared_primary=False,
                primary_basis=None,
                source_catalog_revision=None,
                provenance=provenance,
            ),
        ),
        employment_labels=(),
    )

    with pytest.raises(
        ValueError,
        match="Classification node identity does not belong to jobsdb",
    ):
        SourceJobAttributes(source_attribute_db).project(job.id, evidence)

    assert {
        "projection": source_attribute_db.get(
            JobSourceAttributeProjection,
            job.id,
        ),
        "outbox": source_attribute_db.query(EventOutbox).count(),
    } == {"projection": None, "outbox": 0}


def test_job_detail_schema_serializes_complete_source_attribute_arrays(
    source_attribute_db,
):
    company = Company(
        company_id="company-6",
        source_site="jobsdb",
        source_company_id="company-6",
        name="Schema Example Limited",
    )
    job = Job(
        job_id="job-6",
        source_site="jobsdb",
        source_job_id="job-6",
        company=company,
        title="Schema Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
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
                }
            ],
            "workTypes": ["Full-time", "Permanent"],
        },
        provenance=Provenance(
            method="jobsdb-listing-payload",
            source_site="jobsdb",
            evidence_refs=({"kind": "listing-payload", "source_job_id": "job-6"},),
            captured_at=datetime(2026, 7, 18, 12, 30, tzinfo=timezone.utc),
        ),
    )
    SourceJobAttributes(source_attribute_db).project(job.id, evidence)
    source_attribute_db.expire_all()
    reloaded = source_attribute_db.get(Job, job.id)
    set_committed_value(reloaded, "job_skill_mentions", [])
    set_committed_value(reloaded, "governed_job_skills", [])
    set_committed_value(reloaded, "governed_skill_mentions", [])

    payload = JobDetailSchema.model_validate(reloaded).model_dump(mode="json")

    assert {
        "paths": [
            {
                "source": path["source_site"],
                "order": path["source_order"],
                "nodes": [node["source_classification_id"] for node in path["nodes"]],
                "primary": path["is_primary"],
                "provenance_limited": path["provenance_limited"],
            }
            for path in payload["source_classification_paths"]
        ],
        "employment_types": [
            (item["code"], item["label"]) for item in payload["employment_types"]
        ],
        "source_labels": [
            (
                item["source_order"],
                item["raw_label"],
                item["mapped_type_code"],
            )
            for item in payload["source_employment_labels"]
        ],
    } == {
        "paths": [
            {
                "source": "jobsdb",
                "order": 0,
                "nodes": ["jobsdb:6281", "jobsdb:6287"],
                "primary": False,
                "provenance_limited": True,
            }
        ],
        "employment_types": [
            ("full_time", "Full-time"),
            ("permanent", "Permanent"),
        ],
        "source_labels": [
            (0, "Full-time", "full_time"),
            (1, "Permanent", "permanent"),
        ],
    }


def test_multi_value_filters_are_or_within_each_field_and_and_across_fields(
    source_attribute_db,
):
    module = SourceJobAttributes(source_attribute_db)
    jobs: dict[str, Job] = {}
    fixtures = (
        (
            "it-permanent",
            "6281",
            "Information Technology",
            ["Full-time", "Permanent"],
        ),
        ("engineering-permanent", "6092", "Engineering", ["Permanent"]),
        ("it-part-time", "6281", "Information Technology", ["Part-time"]),
    )
    for index, (key, classification_id, classification_name, work_types) in enumerate(
        fixtures,
        start=1,
    ):
        company = Company(
            company_id=f"filter-company-{index}",
            source_site="jobsdb",
            source_company_id=f"filter-company-{index}",
            name=f"Filter Company {index}",
        )
        job = Job(
            job_id=f"filter-job-{index}",
            source_site="jobsdb",
            source_job_id=f"filter-job-{index}",
            company=company,
            title=key,
        )
        source_attribute_db.add(job)
        source_attribute_db.flush()
        module.project(
            job.id,
            JobsDBSourceEvidenceAdapter().extract(
                {
                    "classifications": [
                        {
                            "classification": {
                                "id": classification_id,
                                "description": classification_name,
                            }
                        }
                    ],
                    "workTypes": work_types,
                },
                provenance=Provenance(
                    method="fixture",
                    source_site="jobsdb",
                    evidence_refs=({"kind": "fixture", "id": key},),
                    captured_at=datetime(
                        2026,
                        7,
                        18,
                        13,
                        index,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )
        jobs[key] = job

    source_or = (
        module.build_filters(
            source_attribute_db.query(Job),
            source_classification_ids=["jobsdb:6281", "jobsdb:6092"],
            employment_type_codes=["permanent"],
        )
        .order_by(Job.title)
        .all()
    )
    employment_or = (
        module.build_filters(
            source_attribute_db.query(Job),
            source_classification_ids=["jobsdb:6281"],
            employment_type_codes=["permanent", "part_time"],
        )
        .order_by(Job.title)
        .all()
    )

    assert {
        "source_or_and_employment": [job.title for job in source_or],
        "employment_or_and_source": [job.title for job in employment_or],
    } == {
        "source_or_and_employment": [
            "engineering-permanent",
            "it-permanent",
        ],
        "employment_or_and_source": [
            "it-part-time",
            "it-permanent",
        ],
    }


def test_job_search_route_adapter_delegates_new_arrays_to_the_module(
    source_attribute_db,
):
    module = SourceJobAttributes(source_attribute_db)
    for index, (classification_id, work_type) in enumerate(
        (("6281", "Permanent"), ("6092", "Part-time")),
        start=1,
    ):
        company = Company(
            company_id=f"route-company-{index}",
            source_site="jobsdb",
            source_company_id=f"route-company-{index}",
            name=f"Route Company {index}",
        )
        job = Job(
            job_id=f"route-job-{index}",
            source_site="jobsdb",
            source_job_id=f"route-job-{index}",
            company=company,
            title=f"route-job-{index}",
        )
        source_attribute_db.add(job)
        source_attribute_db.flush()
        module.project(
            job.id,
            JobsDBSourceEvidenceAdapter().extract(
                {
                    "classifications": [
                        {
                            "classification": {
                                "id": classification_id,
                                "description": f"Classification {classification_id}",
                            }
                        }
                    ],
                    "workTypes": [work_type],
                },
                provenance=Provenance(
                    method="fixture",
                    source_site="jobsdb",
                    evidence_refs=({"kind": "fixture", "id": str(index)},),
                    captured_at=datetime(
                        2026,
                        7,
                        18,
                        14,
                        index,
                        tzinfo=timezone.utc,
                    ),
                ),
            ),
        )

    results = _apply_structured_filters(
        source_attribute_db.query(Job),
        JobSearchFiltersSchema(
            source_classification_ids=["jobsdb:6281"],
            employment_type="Permanent",
        ),
    ).all()

    assert [job.title for job in results] == ["route-job-1"]


def test_job_filter_options_use_stable_codes_and_source_qualified_identities(
    source_attribute_db,
):
    company = Company(
        company_id="option-company-1",
        source_site="jobsdb",
        source_company_id="option-company-1",
        name="Option Company",
        industry="Legacy filter evidence",
    )
    job = Job(
        job_id="option-job-1",
        source_site="jobsdb",
        source_job_id="option-job-1",
        company=company,
        title="Option Engineer",
        location="Central",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    SourceJobAttributes(source_attribute_db).project(
        job.id,
        JobsDBSourceEvidenceAdapter().extract(
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
                "workTypes": ["Full-time", "Permanent", "Other"],
            },
            provenance=Provenance(
                method="fixture",
                source_site="jobsdb",
                evidence_refs=({"kind": "fixture", "id": "options"},),
                captured_at=datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc),
            ),
        ),
    )

    payload = asyncio.run(get_filter_options(source_attribute_db)).model_dump(
        mode="json"
    )

    assert {
        "employment_types": payload["employment_types"],
        "source_classifications": payload["source_classifications"],
        "industries": payload["industries"],
    } == {
        "employment_types": [
            {"code": "full_time", "label": "Full-time", "order": 1},
            {"code": "permanent", "label": "Permanent", "order": 3},
        ],
        "source_classifications": [
            {
                "id": "jobsdb:6281",
                "label": "Information Technology",
                "source": "jobsdb",
                "path": "Information Technology",
            },
            {
                "id": "jobsdb:6287",
                "label": "Developers and Programmers",
                "source": "jobsdb",
                "path": "Information Technology / Developers and Programmers",
            },
        ],
        "industries": [],
    }


def test_job_search_response_keeps_the_same_source_attribute_arrays(
    source_attribute_db,
):
    company = Company(
        company_id="search-company-1",
        source_site="jobsdb",
        source_company_id="search-company-1",
        name="Search Company",
    )
    job = Job(
        job_id="search-job-1",
        source_site="jobsdb",
        source_job_id="search-job-1",
        company=company,
        title="Search Engineer",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    SourceJobAttributes(source_attribute_db).project(
        job.id,
        JobsDBSourceEvidenceAdapter().extract(
            {
                "classifications": [
                    {
                        "classification": {
                            "id": "6281",
                            "description": "Information Technology",
                        }
                    }
                ],
                "workTypes": ["Full-time"],
            },
            provenance=Provenance(
                method="fixture",
                source_site="jobsdb",
                evidence_refs=({"kind": "fixture", "id": "search"},),
                captured_at=datetime(2026, 7, 18, 15, 30, tzinfo=timezone.utc),
            ),
        ),
    )

    payload = _build_search_response_from_results(
        [(job, company)],
        total=1,
        page=1,
        page_size=20,
    ).model_dump(mode="json")["jobs"][0]

    assert {
        "paths": [
            path["nodes"][0]["source_classification_id"]
            for path in payload["source_classification_paths"]
        ],
        "employment_types": [item["code"] for item in payload["employment_types"]],
    } == {
        "paths": ["jobsdb:6281"],
        "employment_types": ["full_time"],
    }


def test_jobsdb_detail_repair_projects_new_evidence_without_mutating_legacy_scalars(
    source_attribute_db,
):
    company = Company(
        company_id="repair-company-1",
        source_site="jobsdb",
        source_company_id="repair-company-1",
        name="Repair Company",
    )
    job = Job(
        job_id="repair-job-1",
        source_site="jobsdb",
        source_job_id="repair-job-1",
        company=company,
        title="Degraded Engineer",
        source_classification_id="legacy:classification",
        source_classification_name="Legacy Classification",
        source_subclassification_id="legacy:subclassification",
        source_subclassification_name="Legacy Subclassification",
        employment_type="Legacy Employment",
    )
    source_attribute_db.add(job)
    source_attribute_db.flush()
    parsed = parse_detail_redux_data(
        {
            "jobdetails": {
                "result": {
                    "job": {
                        "title": "Repaired Engineer",
                        "content": "A sufficiently complete repaired description",
                        "tracking": {
                            "classificationInfo": {
                                "classificationId": "6281",
                                "classification": "Information Technology",
                                "subClassificationId": "6289",
                                "subClassification": "Security",
                            }
                        },
                        "workTypes": {"label": "Contract"},
                    }
                }
            }
        },
        "repair-job-1",
    )

    JobsDBDetailRepairService(source_attribute_db).apply_parsed_detail(job, parsed)
    view = SourceJobAttributes(source_attribute_db).get(job.id)

    assert {
        "legacy": (
            job.source_classification_id,
            job.source_classification_name,
            job.source_subclassification_id,
            job.source_subclassification_name,
            job.employment_type,
        ),
        "paths": [
            [node.source_classification_id for node in path.nodes]
            for path in view.source_classification_paths
        ],
        "employment_types": [item.code for item in view.employment_types],
    } == {
        "legacy": (
            "legacy:classification",
            "Legacy Classification",
            "legacy:subclassification",
            "Legacy Subclassification",
            "Legacy Employment",
        ),
        "paths": [["jobsdb:6281", "jobsdb:6289"]],
        "employment_types": ["contract"],
    }


def test_rebuild_inspector_reports_recoverable_and_unrecoverable_without_writes(
    source_attribute_db,
):
    company = Company(
        company_id="inspect-company-1",
        source_site="jobsdb",
        source_company_id="inspect-company-1",
        name="Inspector Company",
    )
    complete_evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                },
                {
                    "classification": {
                        "id": "6092",
                        "description": "Engineering",
                    }
                },
            ],
            "workTypes": [
                "Full-time",
                "Unknown relationship",
                {"unexpected": "must-not-be-retained"},
            ],
        },
        provenance=Provenance(
            method="historical-fixture",
            source_site="jobsdb",
            evidence_refs=({"kind": "fixture", "id": "complete"},),
            captured_at=datetime(2026, 7, 18, 16, 0, tzinfo=timezone.utc),
        ),
    )
    complete_evidence_payload = complete_evidence.to_payload()
    complete_evidence_payload["classification_paths"][0][
        "source_declared_primary"
    ] = True
    complete_evidence_payload["classification_paths"][0][
        "primary_basis"
    ] = "source-explicit-primary"
    complete_evidence = SourceJobAttributeEvidence.from_payload(
        complete_evidence_payload
    )
    source_attribute_db.add_all(
        [
            Job(
                job_id="inspect-complete",
                source_site="jobsdb",
                source_job_id="inspect-complete",
                company=company,
                title="Complete evidence",
                raw_data={"source_attribute_evidence": complete_evidence.to_payload()},
            ),
            Job(
                job_id="inspect-scalar",
                source_site="jobsdb",
                source_job_id="inspect-scalar",
                company=company,
                title="Scalar evidence",
                source_classification_id="6281",
                source_classification_name="Information Technology",
                employment_type="Full-time, Permanent",
                raw_data={"classification_id": "6281", "work_type": "Full-time"},
            ),
            Job(
                job_id="inspect-malformed",
                source_site="jobsdb",
                source_job_id="inspect-malformed",
                company=company,
                title="Malformed evidence",
                raw_data={"source_attribute_evidence": {"bad": "payload"}},
            ),
            Job(
                job_id="inspect-empty",
                source_site="jobsdb",
                source_job_id="inspect-empty",
                company=company,
                title="No preserved evidence",
            ),
        ]
    )
    source_attribute_db.commit()
    before = {
        "jobs": source_attribute_db.query(Job).count(),
        "outbox": source_attribute_db.query(EventOutbox).count(),
    }

    report = SourceJobAttributeRebuildInspector(source_attribute_db).inspect()

    after = {
        "jobs": source_attribute_db.query(Job).count(),
        "outbox": source_attribute_db.query(EventOutbox).count(),
    }
    assert {
        "report": report.to_payload(),
        "before": before,
        "after": after,
        "session_state": (
            len(source_attribute_db.new),
            len(source_attribute_db.dirty),
            len(source_attribute_db.deleted),
        ),
    } == {
        "report": {
            "jobs_inspected": 4,
            "sources": [
                {
                    "source_site": "jobsdb",
                    "jobs_inspected": 4,
                    "recoverable_jobs": 1,
                    "recoverable_classification_paths": 2,
                    "recoverable_employment_labels": 3,
                    "mapped_employment_labels": 1,
                    "multi_path_jobs": 1,
                    "explicit_primary_paths": 1,
                    "evidence_source_distribution": {"job_raw_data": 1},
                    "path_count_distribution": {"2": 1},
                    "unknown_employment_labels": 1,
                    "ambiguous_jobs": 0,
                    "conflicting_legacy_jobs": 0,
                    "missing_catalog_revision_paths": 2,
                    "provenance_limited_jobs": 4,
                    "malformed_jobs": 2,
                    "unrecoverable_jobs": 3,
                    "unrecoverable_cause_distribution": {
                        "malformed_source_attribute_evidence": 1,
                        "no_preserved_evidence": 1,
                        "parser_discarded_to_legacy_scalars": 1,
                    },
                }
            ],
        },
        "before": {"jobs": 4, "outbox": 0},
        "after": {"jobs": 4, "outbox": 0},
        "session_state": (0, 0, 0),
    }


def test_rebuild_inspector_batches_source_keys_and_merges_rows_deterministically(
    source_attribute_db,
    monkeypatch,
):
    jobsdb_company = Company(
        company_id="inspect-query-jobsdb-company",
        source_site="jobsdb",
        source_company_id="inspect-query-jobsdb-company",
        name="JobsDB Query Inspector Company",
    )
    offertoday_company = Company(
        company_id="inspect-query-offertoday-company",
        source_site="offertoday",
        source_company_id="inspect-query-offertoday-company",
        name="OfferToday Query Inspector Company",
    )
    cases = (
        ("jobsdb", "jobsdb-only", "6281"),
        ("jobsdb", "shared-key", "6092"),
        ("jobsdb", "shared-key-2", "6163"),
        ("offertoday", "offertoday-only", "118000"),
        ("offertoday", "shared-key", "119000"),
    )
    captured_at = datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc)
    jobs = []
    staging_rows = []
    for index, (source_site, source_job_id, classification_id) in enumerate(cases):
        company = jobsdb_company if source_site == "jobsdb" else offertoday_company
        job = Job(
            job_id=f"inspect-query-{source_site}-{source_job_id}",
            source_site=source_site,
            source_job_id=source_job_id,
            company=company,
            title=f"Query evidence {index}",
        )
        provenance = Provenance(
            method="historical-fixture",
            source_site=source_site,
            evidence_refs=(
                {"kind": "fixture", "id": f"batch-query-{source_site}-{index}"},
            ),
            captured_at=captured_at,
        )
        if source_site == "jobsdb":
            evidence = JobsDBSourceEvidenceAdapter().extract(
                {
                    "classifications": [
                        {
                            "classification": {
                                "id": classification_id,
                                "description": f"JobsDB {classification_id}",
                            }
                        }
                    ]
                },
                provenance=provenance,
            )
        else:
            evidence = OfferTodaySourceEvidenceAdapter().extract(
                {
                    "jobFunctions": [
                        {
                            "code": classification_id,
                            "name": f"OfferToday {classification_id}",
                            "children": [],
                        }
                    ]
                },
                provenance=provenance,
            )
        jobs.append(job)
        staging_rows.append(
            CrawlJobListing(
                crawl_job_id=UUID(int=index + 1),
                source_site=source_site,
                source_job_id=source_job_id,
                source_url=f"https://example.test/{source_site}/{source_job_id}",
                listing_payload={"source_attribute_evidence": evidence.to_payload()},
            )
        )
    source_attribute_db.add_all(
        [jobsdb_company, offertoday_company, *jobs, *staging_rows]
    )
    source_attribute_db.commit()
    monkeypatch.setattr(
        SourceJobAttributeRebuildInspector,
        "_STAGING_LOOKUP_BATCH_SIZE",
        2,
        raising=False,
    )
    staging_parameter_counts = []

    def capture_selects(_connection, _cursor, statement, parameters, *_args):
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "FROM crawl_job_listings" in statement
        ):
            staging_parameter_counts.append(len(parameters))

    engine = source_attribute_db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_selects)
    try:
        inspector = SourceJobAttributeRebuildInspector(source_attribute_db)
        report = inspector.inspect()
    finally:
        event.remove(engine, "before_cursor_execute", capture_selects)
    recovered = inspector.recover()

    assert report.jobs_inspected == 5
    assert staging_parameter_counts == [4, 4, 2]
    assert {
        source.source_site: (source.jobs_inspected, source.recoverable_jobs)
        for source in report.sources
    } == {"jobsdb": (3, 3), "offertoday": (2, 2)}
    assert {
        (item.source_site, item.source_job_id): tuple(
            node.source_classification_id
            for path in item.evidence.classification_paths
            for node in path.nodes
        )
        for item in recovered
        if item.evidence is not None
    } == {
        (source_site, source_job_id): (f"{source_site}:{classification_id}",)
        for source_site, source_job_id, classification_id in cases
    }


def test_rebuild_inspector_prefers_newest_usable_staging_detail_evidence(
    source_attribute_db,
):
    captured_at = datetime(2026, 7, 18, 16, 0, tzinfo=timezone.utc)
    provenance = Provenance(
        method="historical-fixture",
        source_site="jobsdb",
        evidence_refs=({"kind": "fixture", "id": "staging-selection"},),
        captured_at=captured_at,
    )

    def evidence(*classification_ids: str, unknown_label: bool = False):
        work_types = ["Full-time"]
        if unknown_label:
            work_types.append("Unknown relationship")
        return JobsDBSourceEvidenceAdapter().extract(
            {
                "classifications": [
                    {
                        "classification": {
                            "id": classification_id,
                            "description": f"Classification {classification_id}",
                        }
                    }
                    for classification_id in classification_ids
                ],
                "workTypes": work_types,
            },
            provenance=provenance,
        )

    company = Company(
        company_id="inspect-staging-company",
        source_site="jobsdb",
        source_company_id="inspect-staging-company",
        name="Staging Inspector Company",
    )
    job = Job(
        job_id="inspect-staging",
        source_site="jobsdb",
        source_job_id="inspect-staging",
        company=company,
        title="Staging evidence",
        raw_data={"source_attribute_evidence": evidence("raw-1").to_payload()},
    )
    older = datetime(2026, 7, 18, 13, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 7, 18, 14, 0, tzinfo=timezone.utc)
    newest = datetime(2026, 7, 18, 15, 0, tzinfo=timezone.utc)
    source_attribute_db.add_all(
        [
            job,
            CrawlJobListing(
                id=UUID("00000000-0000-0000-0000-000000000001"),
                crawl_job_id=UUID("10000000-0000-0000-0000-000000000001"),
                source_site="jobsdb",
                source_job_id="inspect-staging",
                source_url="https://example.test/jobs/inspect-staging",
                listing_payload={},
                detail_payload={
                    "source_attribute_evidence": evidence("old-1").to_payload()
                },
                detail_status="completed",
                detail_completed_at=older,
                created_at=older,
                updated_at=older,
            ),
            CrawlJobListing(
                id=UUID("00000000-0000-0000-0000-000000000002"),
                crawl_job_id=UUID("10000000-0000-0000-0000-000000000002"),
                source_site="jobsdb",
                source_job_id="inspect-staging",
                source_url="https://example.test/jobs/inspect-staging",
                listing_payload={},
                detail_payload={
                    "source_attribute_evidence": evidence(
                        "new-1",
                        "new-2",
                        unknown_label=True,
                    ).to_payload()
                },
                detail_status="completed",
                detail_completed_at=newer,
                created_at=newer,
                updated_at=newer,
            ),
            CrawlJobListing(
                id=UUID("00000000-0000-0000-0000-000000000003"),
                crawl_job_id=UUID("10000000-0000-0000-0000-000000000003"),
                source_site="jobsdb",
                source_job_id="inspect-staging",
                source_url="https://example.test/jobs/inspect-staging",
                listing_payload={
                    "source_attribute_evidence": evidence(
                        "listing-1", "listing-2", "listing-3"
                    ).to_payload()
                },
                detail_payload={"source_attribute_evidence": {"bad": "payload"}},
                detail_status="completed",
                detail_completed_at=newest,
                created_at=newest,
                updated_at=newest,
            ),
        ]
    )
    source_attribute_db.commit()

    report = SourceJobAttributeRebuildInspector(source_attribute_db).inspect()

    assert report.to_payload() == {
        "jobs_inspected": 1,
        "sources": [
            {
                "source_site": "jobsdb",
                "jobs_inspected": 1,
                "recoverable_jobs": 1,
                "recoverable_classification_paths": 2,
                "recoverable_employment_labels": 2,
                "mapped_employment_labels": 1,
                "multi_path_jobs": 1,
                "explicit_primary_paths": 0,
                "evidence_source_distribution": {"staging_detail_payload": 1},
                "path_count_distribution": {"2": 1},
                "unknown_employment_labels": 1,
                "ambiguous_jobs": 0,
                "conflicting_legacy_jobs": 0,
                "missing_catalog_revision_paths": 2,
                "provenance_limited_jobs": 1,
                "malformed_jobs": 1,
                "unrecoverable_jobs": 0,
                "unrecoverable_cause_distribution": {},
            }
        ],
    }


def test_rebuild_inspector_marks_conflicting_equally_fresh_evidence_ambiguous(
    source_attribute_db,
):
    observed_at = datetime(2026, 7, 18, 15, 30, tzinfo=timezone.utc)
    provenance = Provenance(
        method="historical-fixture",
        source_site="jobsdb",
        evidence_refs=({"kind": "fixture", "id": "ambiguous-staging"},),
        captured_at=observed_at,
    )

    def evidence(*classification_ids: str):
        return JobsDBSourceEvidenceAdapter().extract(
            {
                "classifications": [
                    {
                        "classification": {
                            "id": classification_id,
                            "description": f"Classification {classification_id}",
                        }
                    }
                    for classification_id in classification_ids
                ],
                "workTypes": ["Full-time"],
            },
            provenance=provenance,
        )

    company = Company(
        company_id="inspect-ambiguous-company",
        source_site="jobsdb",
        source_company_id="inspect-ambiguous-company",
        name="Ambiguous Inspector Company",
    )
    source_attribute_db.add_all(
        [
            Job(
                job_id="inspect-ambiguous",
                source_site="jobsdb",
                source_job_id="inspect-ambiguous",
                company=company,
                title="Ambiguous evidence",
            ),
            CrawlJobListing(
                id=UUID("00000000-0000-0000-0000-000000000011"),
                crawl_job_id=UUID("30000000-0000-0000-0000-000000000001"),
                source_site="jobsdb",
                source_job_id="inspect-ambiguous",
                source_url="https://example.test/jobs/inspect-ambiguous",
                listing_payload={},
                detail_payload={
                    "source_attribute_evidence": evidence("6281").to_payload()
                },
                detail_status="completed",
                detail_completed_at=observed_at,
                created_at=observed_at,
                updated_at=observed_at,
            ),
            CrawlJobListing(
                id=UUID("00000000-0000-0000-0000-000000000012"),
                crawl_job_id=UUID("30000000-0000-0000-0000-000000000002"),
                source_site="jobsdb",
                source_job_id="inspect-ambiguous",
                source_url="https://example.test/jobs/inspect-ambiguous",
                listing_payload={},
                detail_payload={
                    "source_attribute_evidence": evidence("6092", "6163").to_payload()
                },
                detail_status="completed",
                detail_completed_at=observed_at,
                created_at=observed_at,
                updated_at=observed_at,
            ),
        ]
    )
    source_attribute_db.commit()

    report = SourceJobAttributeRebuildInspector(source_attribute_db).inspect()

    assert report.to_payload()["sources"] == [
        {
            "source_site": "jobsdb",
            "jobs_inspected": 1,
            "recoverable_jobs": 1,
            "recoverable_classification_paths": 2,
            "recoverable_employment_labels": 1,
            "mapped_employment_labels": 1,
            "multi_path_jobs": 1,
            "explicit_primary_paths": 0,
            "evidence_source_distribution": {"staging_detail_payload": 1},
            "path_count_distribution": {"2": 1},
            "unknown_employment_labels": 0,
            "ambiguous_jobs": 1,
            "conflicting_legacy_jobs": 0,
            "missing_catalog_revision_paths": 2,
            "provenance_limited_jobs": 1,
            "malformed_jobs": 0,
            "unrecoverable_jobs": 0,
            "unrecoverable_cause_distribution": {},
        }
    ]


def test_rebuild_inspector_reports_legacy_disagreement_only_for_typed_evidence(
    source_attribute_db,
):
    evidence = JobsDBSourceEvidenceAdapter().extract(
        {
            "classifications": [
                {
                    "classification": {
                        "id": "6281",
                        "description": "Information Technology",
                    }
                }
            ],
            "workTypes": ["Full-time"],
        },
        provenance=Provenance(
            method="historical-fixture",
            source_site="jobsdb",
            evidence_refs=({"kind": "fixture", "id": "legacy-conflict"},),
            captured_at=datetime(2026, 7, 18, 16, 30, tzinfo=timezone.utc),
        ),
    )
    company = Company(
        company_id="inspect-conflict-company",
        source_site="jobsdb",
        source_company_id="inspect-conflict-company",
        name="Conflict Inspector Company",
    )
    source_attribute_db.add(
        Job(
            job_id="inspect-conflict",
            source_site="jobsdb",
            source_job_id="inspect-conflict",
            company=company,
            title="Conflicting legacy evidence",
            source_classification_id="6092",
            source_classification_name="Engineering",
            employment_type="Permanent",
            raw_data={"source_attribute_evidence": evidence.to_payload()},
        )
    )
    source_attribute_db.commit()

    report = SourceJobAttributeRebuildInspector(source_attribute_db).inspect()

    assert report.to_payload()["sources"] == [
        {
            "source_site": "jobsdb",
            "jobs_inspected": 1,
            "recoverable_jobs": 1,
            "recoverable_classification_paths": 1,
            "recoverable_employment_labels": 1,
            "mapped_employment_labels": 1,
            "multi_path_jobs": 0,
            "explicit_primary_paths": 0,
            "evidence_source_distribution": {"job_raw_data": 1},
            "path_count_distribution": {"1": 1},
            "unknown_employment_labels": 0,
            "ambiguous_jobs": 0,
            "conflicting_legacy_jobs": 1,
            "missing_catalog_revision_paths": 1,
            "provenance_limited_jobs": 1,
            "malformed_jobs": 0,
            "unrecoverable_jobs": 0,
            "unrecoverable_cause_distribution": {},
        }
    ]


def test_rebuild_inspector_recovers_offertoday_arrays_from_preserved_raw_data(
    source_attribute_db,
):
    company = Company(
        company_id="inspect-offertoday-company",
        source_site="offertoday",
        source_company_id="inspect-offertoday-company",
        name="OfferToday Inspector Company",
    )
    source_attribute_db.add(
        Job(
            job_id="inspect-offertoday",
            source_site="offertoday",
            source_job_id="inspect-offertoday",
            company=company,
            title="Preserved raw evidence",
            raw_data={
                "raw_data": {
                    "jobFunctions": [
                        {"code": "118000", "name": "IT", "children": []},
                        {
                            "code": "119000",
                            "name": "Engineering",
                            "children": [],
                        },
                    ],
                    "jobType": "1",
                    "jobTypeDesc": "全職",
                }
            },
        )
    )
    source_attribute_db.commit()

    report = SourceJobAttributeRebuildInspector(source_attribute_db).inspect()

    assert report.to_payload() == {
        "jobs_inspected": 1,
        "sources": [
            {
                "source_site": "offertoday",
                "jobs_inspected": 1,
                "recoverable_jobs": 1,
                "recoverable_classification_paths": 2,
                "recoverable_employment_labels": 1,
                "mapped_employment_labels": 1,
                "multi_path_jobs": 1,
                "explicit_primary_paths": 0,
                "evidence_source_distribution": {"job_raw_data": 1},
                "path_count_distribution": {"2": 1},
                "unknown_employment_labels": 0,
                "ambiguous_jobs": 0,
                "conflicting_legacy_jobs": 0,
                "missing_catalog_revision_paths": 2,
                "provenance_limited_jobs": 1,
                "malformed_jobs": 0,
                "unrecoverable_jobs": 0,
                "unrecoverable_cause_distribution": {},
            }
        ],
    }


def test_rebuild_inspector_recovers_jobsdb_arrays_from_raw_listing_staging(
    source_attribute_db,
):
    company = Company(
        company_id="inspect-jobsdb-staging-company",
        source_site="jobsdb",
        source_company_id="inspect-jobsdb-staging-company",
        name="JobsDB Staging Inspector Company",
    )
    job = Job(
        job_id="inspect-jobsdb-staging",
        source_site="jobsdb",
        source_job_id="inspect-jobsdb-staging",
        company=company,
        title="Preserved staging evidence",
        raw_data={"classification_id": "6281"},
    )
    observed_at = datetime(2026, 7, 18, 17, 0, tzinfo=timezone.utc)
    source_attribute_db.add_all(
        [
            job,
            CrawlJobListing(
                crawl_job_id=UUID("20000000-0000-0000-0000-000000000001"),
                source_site="jobsdb",
                source_job_id="inspect-jobsdb-staging",
                source_url="https://hk.jobsdb.com/job/inspect-jobsdb-staging",
                listing_payload={
                    "classifications": [
                        {
                            "classification": {
                                "id": "6281",
                                "description": "Information Technology",
                            }
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
                detail_status="pending",
                created_at=observed_at,
                updated_at=observed_at,
            ),
        ]
    )
    source_attribute_db.commit()

    report = SourceJobAttributeRebuildInspector(source_attribute_db).inspect()

    assert report.to_payload()["sources"] == [
        {
            "source_site": "jobsdb",
            "jobs_inspected": 1,
            "recoverable_jobs": 1,
            "recoverable_classification_paths": 2,
            "recoverable_employment_labels": 2,
            "mapped_employment_labels": 2,
            "multi_path_jobs": 1,
            "explicit_primary_paths": 0,
            "evidence_source_distribution": {"staging_listing_payload": 1},
            "path_count_distribution": {"2": 1},
            "unknown_employment_labels": 0,
            "ambiguous_jobs": 0,
            "conflicting_legacy_jobs": 0,
            "missing_catalog_revision_paths": 2,
            "provenance_limited_jobs": 1,
            "malformed_jobs": 0,
            "unrecoverable_jobs": 0,
            "unrecoverable_cause_distribution": {},
        }
    ]


def test_rebuild_inspection_cli_emits_deterministic_json_and_has_no_write_mode(
    monkeypatch,
    capsys,
):
    from scripts import inspect_source_job_attributes

    class ReadOnlySession:
        closed = False

        def close(self):
            self.closed = True

        def commit(self):
            raise AssertionError("read-only inspection must not commit")

        def flush(self):
            raise AssertionError("read-only inspection must not flush")

        def add(self, _value):
            raise AssertionError("read-only inspection must not add rows")

        def delete(self, _value):
            raise AssertionError("read-only inspection must not delete rows")

    class Report:
        @staticmethod
        def to_payload():
            return {"sources": [], "jobs_inspected": 0}

    db = ReadOnlySession()
    inspected_sessions = []

    class Inspector:
        def __init__(self, session):
            inspected_sessions.append(session)

        @staticmethod
        def inspect():
            return Report()

    monkeypatch.setattr(inspect_source_job_attributes, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        inspect_source_job_attributes,
        "SourceJobAttributeRebuildInspector",
        Inspector,
    )

    assert inspect_source_job_attributes.main([]) == 0
    assert capsys.readouterr().out == '{"jobs_inspected":0,"sources":[]}\n'
    assert inspected_sessions == [db]
    assert db.closed is True

    for forbidden_option in ("--apply", "--execute"):
        with pytest.raises(SystemExit) as exc_info:
            inspect_source_job_attributes.main([forbidden_option])
        assert exc_info.value.code == 2


def test_rebuild_inspection_cli_emits_a_deterministic_human_summary(
    monkeypatch,
    capsys,
):
    from scripts import inspect_source_job_attributes

    payload = {
        "jobs_inspected": 3,
        "sources": [
            {
                "source_site": "jobsdb",
                "jobs_inspected": 3,
                "recoverable_jobs": 1,
                "recoverable_classification_paths": 2,
                "recoverable_employment_labels": 3,
                "mapped_employment_labels": 1,
                "multi_path_jobs": 1,
                "explicit_primary_paths": 1,
                "evidence_source_distribution": {"job_raw_data": 1},
                "path_count_distribution": {"2": 1},
                "unknown_employment_labels": 1,
                "ambiguous_jobs": 0,
                "conflicting_legacy_jobs": 0,
                "missing_catalog_revision_paths": 2,
                "provenance_limited_jobs": 3,
                "malformed_jobs": 1,
                "unrecoverable_jobs": 2,
                "unrecoverable_cause_distribution": {
                    "malformed_source_attribute_evidence": 1,
                    "parser_discarded_to_legacy_scalars": 1,
                },
            }
        ],
    }

    class Session:
        closed = False

        def close(self):
            self.closed = True

    class Report:
        @staticmethod
        def to_payload():
            return payload

    class Inspector:
        def __init__(self, _db):
            pass

        @staticmethod
        def inspect():
            return Report()

    db = Session()
    monkeypatch.setattr(inspect_source_job_attributes, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        inspect_source_job_attributes,
        "SourceJobAttributeRebuildInspector",
        Inspector,
    )

    assert inspect_source_job_attributes.main(["--format", "human"]) == 0
    assert capsys.readouterr().out == (
        "Source Job Attribute rebuild inspection (read-only)\n"
        "jobs_inspected: 3\n"
        "jobsdb: inspected=3 recoverable=1 unrecoverable=2 multi_path=1 "
        "recoverable_paths=2 recoverable_employment_labels=3 "
        "mapped_employment_labels=1 explicit_primary_paths=1 "
        "unknown_employment_labels=1 ambiguous=0 legacy_conflicts=0 "
        "malformed=1 missing_catalog_revision_paths=2 provenance_limited=3 "
        'evidence_sources={"job_raw_data":1} path_counts={"2":1} '
        "unrecoverable_causes="
        '{"malformed_source_attribute_evidence":1,'
        '"parser_discarded_to_legacy_scalars":1}\n'
    )
    assert db.closed is True
