from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.job_intelligence.source_attributes import (
    SourceJobAttributes,
    reconcile_employment_type_registry,
)
from app.messaging.topics import STREAM_JOB_INGEST
from app.models.company import Company
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.source_classification import SourceClassification
from app.models.source_job_attributes import (
    SOURCE_JOB_ATTRIBUTE_TABLES,
    JobEmploymentType,
)
from app.repositories.company_repository import CompanyRepository
from app.repositories.job_repository import JobRepository
from app.services.offertoday_detail_pipeline import (
    OfferTodayDetailPipeline,
    OfferTodayDetailTarget,
)
from app.sources.contracts import (
    build_jobsdb_listing_canonical_job,
    build_offertoday_canonical_job,
)
from app.sources.jobsdb.parsers import parse_search_response
from app.sources.offertoday.parsers import parse_offertoday_detail_response
from app.workers.run_ingest_worker import (
    IngestWorkerService,
    InvalidIngestPayloadError,
)


class _FakeBus:
    def __init__(self) -> None:
        self.acks: list[tuple[str, str, str]] = []

    def ensure_group(self, _stream, _group) -> None:
        return None

    def ack(self, stream, group, message_id) -> None:
        self.acks.append((stream, group, message_id))


class _FakeOutboxPublisher:
    def __init__(self) -> None:
        self.publish_calls = 0

    def publish_pending_batch(self, _db, *, limit) -> int:
        self.publish_calls += 1
        return 0


def test_source_aware_repository_rejects_legacy_attribute_keys_before_db_access():
    class NoDatabaseAccess:
        def query(self, *_args, **_kwargs):
            raise AssertionError("legacy payload must fail before database access")

    with pytest.raises(
        ValueError,
        match=(
            "employment_type, source_classification_id, "
            "source_classification_name, source_subclassification_id, "
            "source_subclassification_name"
        ),
    ):
        JobRepository().upsert_source_job(
            NoDatabaseAccess(),
            {
                "source_site": "jobsdb",
                "source_job_id": "legacy-payload",
                "employment_type": None,
                "source_classification_id": None,
                "source_classification_name": None,
                "source_subclassification_id": None,
                "source_subclassification_name": None,
            },
            auto_commit=False,
        )


def test_generic_repository_create_and_upsert_are_retired_before_db_access():
    class NoDatabaseAccess:
        def __getattr__(self, _name):
            raise AssertionError(
                "retired repository writes must not access the database"
            )

    repository = JobRepository()
    for method_name in ("create_job", "upsert_job"):
        with pytest.raises(
            ValueError,
            match="generic Job writes are retired; use upsert_source_job",
        ):
            getattr(repository, method_name)(
                NoDatabaseAccess(),
                {"job_id": "legacy-generic-write"},
                auto_commit=False,
            )

    with pytest.raises(
        ValueError,
        match=(
            "generic Job update cannot write legacy Source Job Attribute "
            "fields: employment_type"
        ),
    ):
        repository.update_job(
            NoDatabaseAccess(),
            uuid4(),
            {"employment_type": "Full-time"},
            auto_commit=False,
        )


def test_authoritative_ingest_rejects_missing_source_attribute_evidence():
    worker = IngestWorkerService(
        bus=_FakeBus(),
        outbox_publisher=_FakeOutboxPublisher(),
    )

    with pytest.raises(InvalidIngestPayloadError) as exc_info:
        worker.project_source_attributes(
            object(),
            SimpleNamespace(id="job-without-evidence"),
            {"source_site": "jobsdb", "source_job_id": "job-without-evidence"},
        )

    assert exc_info.value.reason == "missing_source_attribute_evidence"


@pytest.fixture()
def source_attribute_engine():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")
    if not (make_url(database_url).database or "").endswith("_test"):
        pytest.fail(
            "Source Job Attribute ingest tests require a dedicated *_test database"
        )
    engine = create_engine(database_url)
    tables = (
        Company.__table__,
        Job.__table__,
        EventOutbox.__table__,
        SourceClassification.__table__,
        *SOURCE_JOB_ATTRIBUTE_TABLES,
    )
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        reconcile_employment_type_registry(connection, allow_unknown_codes=False)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine, tables=list(reversed(tables)))
        engine.dispose()


def test_ingest_event_persists_source_attributes_without_legacy_dual_write(
    source_attribute_engine,
):
    parsed = parse_search_response(
        {
            "data": [
                {
                    "id": "ingest-job-1",
                    "title": "Platform Engineer",
                    "companyName": "Ingest Example Limited",
                    "advertiser": {
                        "id": "ingest-company-1",
                        "description": "Ingest Example Limited",
                    },
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
                }
            ]
        }
    )["jobs"][0]
    canonical = build_jobsdb_listing_canonical_job(
        parsed,
        source_url="https://hk.jobsdb.com/job/ingest-job-1",
    ).to_dict()
    event = SimpleNamespace(
        event_type="crawl.item_emitted",
        event_id="event-1",
        payload={"job": canonical},
    )
    message = SimpleNamespace(
        event=event,
        message_id="message-1",
    )
    bus = _FakeBus()
    publisher = _FakeOutboxPublisher()
    SessionFactory = sessionmaker(bind=source_attribute_engine)
    worker = IngestWorkerService(
        bus=bus,
        outbox_publisher=publisher,
        session_factory=SessionFactory,
    )

    asyncio.run(worker._handle_message(message))

    db = SessionFactory()
    try:
        job = db.query(Job).filter(Job.source_job_id == "ingest-job-1").one()
        view = SourceJobAttributes(db).get(job.id)
        event_types = [
            row.event_type
            for row in db.query(EventOutbox).order_by(EventOutbox.id).all()
        ]
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
            "outbox": event_types,
            "acks": bus.acks,
            "publish_calls": publisher.publish_calls,
        } == {
            "legacy": (None, None, None, None, None),
            "paths": [
                ["jobsdb:6281", "jobsdb:6287"],
                ["jobsdb:6092"],
            ],
            "employment_types": ["full_time", "permanent"],
            "outbox": [
                "job.source_attributes_changed",
                "job.ingested",
            ],
            "acks": [(STREAM_JOB_INGEST, "ingest-workers", "message-1")],
            "publish_calls": 1,
        }
    finally:
        db.close()


def test_offertoday_detail_pipeline_persists_governed_employment_types(
    source_attribute_engine,
):
    class Runtime:
        def transition_detail_completed(self, *_args, **_kwargs):
            return None

        def record_detail_persisted(self, *_args, **_kwargs):
            return None

    parsed = parse_offertoday_detail_response(
        {
            "data": {
                "jobId": "registry-detail-job",
                "encryptJobId": "encrypted-registry-detail-job",
                "jobName": "Registry Detail Engineer",
                "companyName": "Registry Detail Limited",
                "jobDesc": "<p>Canonical detail description</p>",
                "addressVO": {},
                "jobFunctions": [
                    {"code": "118000", "name": "Information Technology"}
                ],
                "jobType": 1,
                "jobTypeDesc": "全職",
                "employType": {"name": "兼職"},
            }
        }
    )
    canonical = build_offertoday_canonical_job(parsed)
    target = OfferTodayDetailTarget.from_runtime_target(
        {
            "listing_id": uuid4(),
            "duplicate_listing_ids": [],
            "source_job_id": "registry-detail-job",
            "listing_payload": {
                "job_id": "registry-detail-job",
                "encrypted_job_id": "encrypted-registry-detail-job",
                "encrypted_job_id_source": "encryptJobId",
            },
        }
    )
    SessionFactory = sessionmaker(bind=source_attribute_engine)
    pipeline = OfferTodayDetailPipeline(
        session_factory=SessionFactory,
        crawl_runtime=Runtime(),
        company_repository=CompanyRepository(),
        job_repository=JobRepository(),
    )

    result = pipeline._persist_success(
        target=target,
        detail_crawl_job_id=uuid4(),
        detail_payload={"code": 0},
        failure_detail_payload=None,
        canonical_job=canonical,
    )

    assert result.outcome.value == "success"
    with SessionFactory() as db:
        job = db.query(Job).filter(Job.source_job_id == "registry-detail-job").one()
        codes = [
            row.employment_type_code
            for row in db.query(JobEmploymentType)
            .filter(JobEmploymentType.job_id == job.id)
            .order_by(JobEmploymentType.employment_type_code)
        ]
    assert codes == ["full_time", "part_time"]
