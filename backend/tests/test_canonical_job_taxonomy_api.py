from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.job_intelligence.canonical_taxonomy import (
    CanonicalJobTaxonomy,
    CanonicalReadError,
    CanonicalReviewQuery,
    CanonicalTaxonomyDecisionAdapter,
    CanonicalTaxonomyFilterQuery,
    CanonicalTaxonomyPublisher,
)
from app.job_intelligence.canonical_taxonomy.breadcrumbs import canonical_breadcrumb
from app.job_intelligence.foundation import DecisionCommand, normalized_content_hash
from app.models.canonical_job_taxonomy import (
    CANONICAL_JOB_TAXONOMY_TABLES,
    CanonicalJobSubcategory,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.company import Company
from app.models.event_outbox import EventOutbox
from app.models.governance import (
    GOVERNANCE_FOUNDATION_TABLES,
    GovernanceAuditEvent,
    GovernanceIdempotencyRecord,
)
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogCandidate,
    SourceCatalogRevision,
)
from app.schemas.job_intelligence import (
    CanonicalTaxonomyDecisionRequestSchema,
    CanonicalTaxonomyFixtureSchema,
)


SEED_PATH = Path(__file__).parents[1] / "app" / "data" / "job_category_taxonomy.json"


@pytest.fixture
def canonical_api_db():
    database_url = os.getenv("JOB_INTELLIGENCE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("JOB_INTELLIGENCE_TEST_DATABASE_URL is not configured")

    engine = create_engine(database_url)
    tables = (
        Company.__table__,
        JobDomain.__table__,
        JobCategory.__table__,
        JobSubcategory.__table__,
        Job.__table__,
        EventOutbox.__table__,
        SourceCatalogCandidate.__table__,
        SourceCatalogRevision.__table__,
        SourceCatalogActiveRevision.__table__,
        *GOVERNANCE_FOUNDATION_TABLES,
        *CANONICAL_JOB_TAXONOMY_TABLES,
    )
    Base.metadata.drop_all(engine, tables=list(reversed(tables)), checkfirst=True)
    Base.metadata.create_all(engine, tables=list(tables))
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine, tables=list(reversed(tables)), checkfirst=True)
        engine.dispose()


def test_read_models_filters_and_embedding_use_only_current_canonical_assignment(
    canonical_api_db,
):
    state = _seed_read_state(canonical_api_db)
    taxonomy = CanonicalJobTaxonomy(canonical_api_db)

    revision = taxonomy.get_active_revision()
    tree = taxonomy.get_tree()
    assigned = taxonomy.get_job_state(state["accounting_job"].id)
    pending_review = taxonomy.get_job_state(state["review_job"].id)
    untouched = taxonomy.get_job_state(state["untouched_job"].id)

    assert revision.to_payload() == {
        "id": str(state["taxonomy_revision_id"]),
        "release_key": "canonical-job-taxonomy-v1",
        "content_hash": revision.content_hash,
        "status": "active",
        "lock_version": 1,
        "activated_at": revision.activated_at,
        "counts": {"domains": 25, "categories": 63, "subcategories": 198},
        "active_mapping": None,
    }
    assert tree.counts == {"domains": 25, "categories": 63, "subcategories": 198}
    assert len(tree.domains) == 25
    assert sum(len(domain.categories) for domain in tree.domains) == 63
    assert (
        sum(
            len(category.subcategories)
            for domain in tree.domains
            for category in domain.categories
        )
        == 198
    )
    assert all(
        subcategory.label not in {"General", "Unknown"}
        for domain in tree.domains
        for category in domain.categories
        for subcategory in category.subcategories
    )

    assert (
        assigned.to_payload()["assignment"]["breadcrumb"]["subcategory"]["code"]
        == "accounting.financial_accounting.accounts_payable"
    )
    assert assigned.to_payload()["assignment"]["provenance"] == {
        "evidence_hash": state["accounting_assignment"].evidence_hash,
        "source_evidence_refs": [{"kind": "fixture", "id": "accounting"}],
        "mapping_revision_id": None,
        "mapping_ids": [],
        "model": None,
        "captured_at": state["accounting_assignment"].captured_at,
    }
    assert assigned.state == "assigned"
    assert pending_review.to_payload() == {
        "job_id": str(state["review_job"].id),
        "state": "unassigned",
        "assignment": None,
        "reasons": ["classifier_provenance_missing"],
        "review_item_refs": [
            {
                "id": str(state["review"].id),
                "status": "active",
                "version": 1,
                "decision_audit_id": None,
                "deep_link": (
                    "/api/v1/job-intelligence/governance/job-taxonomy/"
                    f"review-items/{state['review'].id}"
                ),
            }
        ],
    }
    assert untouched.to_payload() == {
        "job_id": str(state["untouched_job"].id),
        "state": "unassigned",
        "assignment": None,
        "reasons": [],
        "review_item_refs": [],
    }

    accounting_or_ict = taxonomy.build_filters(
        CanonicalTaxonomyFilterQuery(
            domain_codes=("accounting", "information_communication_technology"),
        )
    )
    filtered_jobs = (
        canonical_api_db.query(Job)
        .filter(*accounting_or_ict)
        .order_by(Job.job_id)
        .all()
    )
    assert [job.job_id for job in filtered_jobs] == [
        "canonical-api-accounting",
        "canonical-api-ict",
    ]

    compatible_filters = taxonomy.build_filters(
        CanonicalTaxonomyFilterQuery(
            domain_codes=("accounting",),
            category_codes=("accounting.financial_accounting",),
            subcategory_codes=(
                "accounting.financial_accounting.accounts_payable",
                "accounting.financial_accounting.accounts_receivable",
            ),
        )
    )
    assert [
        job.job_id
        for job in canonical_api_db.query(Job).filter(*compatible_filters).all()
    ] == ["canonical-api-accounting"]

    incompatible_filters = taxonomy.build_filters(
        CanonicalTaxonomyFilterQuery(
            domain_codes=("information_communication_technology",),
            subcategory_codes=("accounting.financial_accounting.accounts_payable",),
        )
    )
    assert canonical_api_db.query(Job).filter(*incompatible_filters).count() == 0

    document = taxonomy.build_embedding_document(state["accounting_job"].id)
    assert document is not None
    assert document.to_payload() == {
        "job_id": str(state["accounting_job"].id),
        "assignment_id": str(state["accounting_assignment"].id),
        "taxonomy_revision_id": str(state["taxonomy_revision_id"]),
        "method": "operator",
        "breadcrumb": state["accounting_assignment"].breadcrumb,
        "document_text": document.document_text,
        "document_hash": document.document_hash,
    }
    assert (
        "Accounting / Financial Accounting / Accounts Payable" in document.document_text
    )
    assert "accounting.financial_accounting.accounts_payable" in document.document_text
    assert "Legacy General" not in document.document_text
    assert "Accounts Receivable" not in document.document_text
    assert taxonomy.build_embedding_document(state["review_job"].id) is None


def test_review_reads_use_stable_cursor_pagination_and_reason_filters(
    canonical_api_db,
):
    state = _seed_read_state(canonical_api_db)
    taxonomy = CanonicalJobTaxonomy(canonical_api_db)
    second_review_job = _job(canonical_api_db, "second-review")
    second_review = _review(
        canonical_api_db,
        second_review_job,
        taxonomy_revision_id=state["taxonomy_revision_id"],
        reason="source_mapping_unmapped",
        created_at=state["review"].created_at + timedelta(minutes=1),
    )
    canonical_api_db.commit()

    first_page = taxonomy.list_review_items(
        CanonicalReviewQuery(statuses=("active",), limit=1)
    )
    second_page = taxonomy.list_review_items(
        CanonicalReviewQuery(
            statuses=("active",),
            cursor=first_page.next_cursor,
            limit=1,
        )
    )
    filtered = taxonomy.list_review_items(
        CanonicalReviewQuery(
            statuses=("active",),
            reason_codes=("classifier_provenance_missing",),
            limit=50,
        )
    )

    assert first_page.total == 2
    assert first_page.items[0].id == second_review.id
    assert first_page.next_cursor is not None
    assert second_page.total == 2
    assert second_page.items[0].id == state["review"].id
    assert second_page.next_cursor is None
    assert [item.id for item in filtered.items] == [state["review"].id]
    detail = taxonomy.get_review_item(state["review"].id)
    assert detail.evidence_refs == ({"kind": "fixture", "id": "review"},)
    assert detail.recommendations[0]["code"] == (
        "accounting.financial_accounting.accounts_receivable"
    )

    with pytest.raises(CanonicalReadError) as error:
        taxonomy.list_review_items(CanonicalReviewQuery(cursor="not-a-cursor"))
    assert error.value.code == "CANONICAL_REVIEW_CURSOR_INVALID"


def test_versioned_job_intelligence_routes_return_typed_canonical_contracts(
    canonical_api_db,
):
    from app.api import router as api_router
    from app.api.job_intelligence import (
        list_job_taxonomy_review_items,
        read_canonical_taxonomy_revision,
        read_canonical_taxonomy_tree,
        read_job_canonical_taxonomy,
        read_job_taxonomy_review_item,
    )

    state = _seed_read_state(canonical_api_db)
    revision = read_canonical_taxonomy_revision(db=canonical_api_db)
    tree = read_canonical_taxonomy_tree(db=canonical_api_db)
    job_state = read_job_canonical_taxonomy(
        state["accounting_job"].id,
        db=canonical_api_db,
    )
    unassigned_job_state = read_job_canonical_taxonomy(
        state["review_job"].id,
        db=canonical_api_db,
    )
    reviews = list_job_taxonomy_review_items(
        status=["active"],
        reason=None,
        job_id=None,
        cursor=None,
        limit=50,
        db=canonical_api_db,
    )
    review = read_job_taxonomy_review_item(
        state["review"].id,
        db=canonical_api_db,
    )

    assert revision.release_key == "canonical-job-taxonomy-v1"
    assert tree.counts.subcategories == 198
    assert job_state.state == "assigned"
    assert unassigned_job_state.state == "unassigned"
    assert reviews.total == 1
    assert review.id == state["review"].id
    runtime_fixture = CanonicalTaxonomyFixtureSchema(
        revision=revision,
        tree=tree,
        assigned_job=job_state,
        unassigned_job=unassigned_job_state,
        review_page=reviews,
    )
    runtime_payload = runtime_fixture.model_dump(mode="json")
    assert (
        CanonicalTaxonomyFixtureSchema.model_validate(runtime_payload).model_dump(
            mode="json"
        )
        == runtime_payload
    )
    assert runtime_payload["tree"]["counts"] == {
        "domains": 25,
        "categories": 63,
        "subcategories": 198,
    }
    route_paths = {route.path for route in api_router.routes}
    assert {
        "/api/v1/job-intelligence/canonical-job-taxonomy/revision",
        "/api/v1/job-intelligence/canonical-job-taxonomy/tree",
        "/api/v1/job-intelligence/jobs/{job_id}/canonical-taxonomy",
        "/api/v1/job-intelligence/governance/job-taxonomy/review-items",
        "/api/v1/job-intelligence/governance/job-taxonomy/review-items/{review_item_id}",
        "/api/v1/job-intelligence/governance/job-taxonomy/review-items/{review_item_id}/decision",
    } <= route_paths


def test_operator_decision_route_is_idempotent_and_persists_audit_deep_link(
    canonical_api_db,
):
    from app.api.job_intelligence import decide_job_taxonomy_review_item

    state = _seed_read_state(canonical_api_db)
    target = (
        canonical_api_db.query(CanonicalJobSubcategory)
        .filter_by(
            revision_id=state["taxonomy_revision_id"],
            code="accounting.financial_accounting.accounts_payable",
        )
        .one()
    )
    request = CanonicalTaxonomyDecisionRequestSchema(
        action="assign_existing_subcategory",
        target_id=target.id,
        expected_version=1,
        idempotency_key="canonical-api-assign-1",
        confirmed=True,
        note="Confirmed from preserved evidence",
        correlation_id="canonical-api-correlation-1",
    )

    result = decide_job_taxonomy_review_item(
        state["review"].id,
        request,
        db=canonical_api_db,
    )
    replay = decide_job_taxonomy_review_item(
        state["review"].id,
        request,
        db=canonical_api_db,
    )

    canonical_api_db.expire_all()
    review = canonical_api_db.get(JobTaxonomyReviewItem, state["review"].id)
    assert review is not None
    assert {
        "result": (result.version, result.replayed),
        "replay": (replay.version, replay.replayed, replay.audit_event_id),
        "review": (
            review.status,
            review.lock_version,
            review.decision_audit_id,
            review.assignment_id,
        ),
        "audit_count": canonical_api_db.query(GovernanceAuditEvent).count(),
        "outbox_count": canonical_api_db.query(EventOutbox)
        .filter_by(event_type="job.canonical_taxonomy_decided")
        .count(),
    } == {
        "result": (2, False),
        "replay": (2, True, result.audit_event_id),
        "review": (
            "assigned",
            2,
            result.audit_event_id,
            review.assignment_id,
        ),
        "audit_count": 1,
        "outbox_count": 1,
    }
    detail = CanonicalJobTaxonomy(canonical_api_db).get_review_item(review.id)
    assert detail.decision_audit_id == result.audit_event_id
    assert detail.to_payload()["deep_link"].endswith(str(review.id))


def test_operator_decision_api_rejects_unconfirmed_stale_and_invalid_target_without_writes(
    canonical_api_db,
):
    from app.api.job_intelligence import decide_job_taxonomy_review_item

    state = _seed_read_state(canonical_api_db)
    invalid_requests = (
        (
            CanonicalTaxonomyDecisionRequestSchema(
                action="mark_insufficient_evidence",
                expected_version=1,
                idempotency_key="canonical-api-unconfirmed",
                confirmed=False,
            ),
            422,
            "GOVERNANCE_DECISION_UNCONFIRMED",
        ),
        (
            CanonicalTaxonomyDecisionRequestSchema(
                action="mark_insufficient_evidence",
                expected_version=9,
                idempotency_key="canonical-api-stale",
                confirmed=True,
            ),
            409,
            "GOVERNANCE_DECISION_STALE_VERSION",
        ),
        (
            CanonicalTaxonomyDecisionRequestSchema(
                action="assign_existing_subcategory",
                target_id=uuid4(),
                expected_version=1,
                idempotency_key="canonical-api-invalid-target",
                confirmed=True,
            ),
            422,
            "JOB_TAXONOMY_DECISION_TARGET_INVALID",
        ),
    )

    for request, expected_status, expected_code in invalid_requests:
        with pytest.raises(HTTPException) as error:
            decide_job_taxonomy_review_item(
                state["review"].id,
                request,
                db=canonical_api_db,
            )
        assert error.value.status_code == expected_status
        assert error.value.detail["code"] == expected_code

    canonical_api_db.expire_all()
    review = canonical_api_db.get(JobTaxonomyReviewItem, state["review"].id)
    assert review is not None
    assert (review.status, review.lock_version, review.decision_audit_id) == (
        "active",
        1,
        None,
    )
    assert canonical_api_db.query(JobTaxonomyAssignment).count() == 2
    assert canonical_api_db.query(GovernanceAuditEvent).count() == 0
    assert canonical_api_db.query(GovernanceIdempotencyRecord).count() == 0
    assert (
        canonical_api_db.query(EventOutbox)
        .filter_by(event_type="job.canonical_taxonomy_decided")
        .count()
        == 0
    )


def test_operator_outbox_failure_rolls_back_assignment_review_audit_and_idempotency(
    canonical_api_db,
):
    state = _seed_read_state(canonical_api_db)
    target = (
        canonical_api_db.query(CanonicalJobSubcategory)
        .filter_by(
            revision_id=state["taxonomy_revision_id"],
            code="accounting.financial_accounting.accounts_payable",
        )
        .one()
    )
    command = DecisionCommand(
        subject_id=str(state["review"].id),
        action="assign_existing_subcategory",
        target_id=str(target.id),
        expected_version=1,
        idempotency_key="canonical-api-outbox-failure",
        confirmed=True,
    )

    with pytest.raises(RuntimeError, match="forced canonical outbox failure"):
        CanonicalTaxonomyDecisionAdapter(
            canonical_api_db,
            outbox_repository=_FailingOutboxRepository(),
        ).decide(command)

    canonical_api_db.expire_all()
    review = canonical_api_db.get(JobTaxonomyReviewItem, state["review"].id)
    assert review is not None
    assert {
        "review": (
            review.status,
            review.lock_version,
            review.assignment_id,
            review.decision_audit_id,
        ),
        "assignment_count": canonical_api_db.query(JobTaxonomyAssignment).count(),
        "audit_count": canonical_api_db.query(GovernanceAuditEvent).count(),
        "idempotency_count": canonical_api_db.query(
            GovernanceIdempotencyRecord
        ).count(),
        "operator_outbox_count": canonical_api_db.query(EventOutbox)
        .filter_by(event_type="job.canonical_taxonomy_decided")
        .count(),
    } == {
        "review": ("active", 1, None, None),
        "assignment_count": 2,
        "audit_count": 0,
        "idempotency_count": 0,
        "operator_outbox_count": 0,
    }


def test_canonical_read_contract_fixture_is_valid_and_live_consumers_are_not_switched():
    backend_root = Path(__file__).parents[1]
    fixture = json.loads(
        (
            backend_root
            / "tests"
            / "fixtures"
            / "canonical_job_taxonomy_responses.json"
        ).read_text(encoding="utf-8")
    )
    parsed = CanonicalTaxonomyFixtureSchema.model_validate(fixture)

    assert parsed.model_dump(mode="json") == fixture
    assert parsed.assigned_job.state == "assigned"
    assert parsed.unassigned_job.state == "unassigned"
    assert parsed.review_page.items[0].reasons == ["classifier_provenance_missing"]
    assert parsed.tree.counts.model_dump() == {
        "domains": 1,
        "categories": 1,
        "subcategories": 2,
    }

    live_embedding_worker = (
        backend_root / "app" / "workers" / "run_embedding_worker.py"
    ).read_text(encoding="utf-8")
    live_jobs_api = (backend_root / "app" / "api" / "jobs.py").read_text(
        encoding="utf-8"
    )
    assert "canonical_taxonomy" not in live_embedding_worker
    assert "CanonicalJobTaxonomy" not in live_embedding_worker
    assert "CanonicalTaxonomyFilterQuery" not in live_jobs_api


def _seed_read_state(db):
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    publisher = CanonicalTaxonomyPublisher(db)
    revision = publisher.materialize(seed)
    publisher.activate(revision, expected_lock_version=0)

    legacy_domain = JobDomain(
        name="Legacy General", created_by="ai", is_auto_created=True
    )
    db.add(legacy_domain)
    db.flush()
    legacy_category = JobCategory(
        domain_id=legacy_domain.id,
        name="Legacy General",
        created_by="ai",
        is_auto_created=True,
    )
    db.add(legacy_category)
    db.flush()
    legacy_subcategory = JobSubcategory(
        category_id=legacy_category.id,
        name="Legacy General",
        created_by="ai",
        is_auto_created=True,
    )
    db.add(legacy_subcategory)
    db.flush()

    accounting_job = _job(db, "accounting", legacy_subcategory=legacy_subcategory)
    ict_job = _job(db, "ict")
    review_job = _job(db, "review")
    untouched_job = _job(db, "untouched")
    accounting_assignment = _assignment(
        db,
        accounting_job,
        taxonomy_revision_id=revision.revision_id,
        target_code="accounting.financial_accounting.accounts_payable",
        evidence_id="accounting",
    )
    _assignment(
        db,
        ict_job,
        taxonomy_revision_id=revision.revision_id,
        target_code=(
            "information_communication_technology.software_development."
            "backend_development"
        ),
        evidence_id="ict",
    )
    review = _review(
        db,
        review_job,
        taxonomy_revision_id=revision.revision_id,
        reason="classifier_provenance_missing",
        created_at=datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
    )
    db.commit()
    return {
        "taxonomy_revision_id": revision.revision_id,
        "accounting_job": accounting_job,
        "ict_job": ict_job,
        "review_job": review_job,
        "untouched_job": untouched_job,
        "accounting_assignment": accounting_assignment,
        "review": review,
    }


def _job(db, suffix, *, legacy_subcategory=None):
    company = Company(
        company_id=f"canonical-api-company-{suffix}",
        source_site="ctgoodjobs",
        source_company_id=f"canonical-api-company-{suffix}",
        name=f"Canonical API Company {suffix}",
    )
    job = Job(
        job_id=f"canonical-api-{suffix}",
        source_site="ctgoodjobs",
        source_job_id=f"canonical-api-{suffix}",
        company=company,
        title=f"Canonical API {suffix}",
        subcategory_id=(legacy_subcategory.id if legacy_subcategory else None),
    )
    db.add(job)
    db.flush()
    return job


def _assignment(db, job, *, taxonomy_revision_id, target_code, evidence_id):
    target = (
        db.query(CanonicalJobSubcategory)
        .filter_by(
            revision_id=taxonomy_revision_id,
            code=target_code,
        )
        .one()
    )
    assignment = JobTaxonomyAssignment(
        job_id=job.id,
        taxonomy_revision_id=taxonomy_revision_id,
        subcategory_id=target.id,
        mapping_revision_id=None,
        method="operator",
        evidence_hash=normalized_content_hash(
            {"job_id": str(job.id), "target_code": target_code}
        ),
        source_evidence_refs=[{"kind": "fixture", "id": evidence_id}],
        mapping_ids=[],
        model_provider=None,
        model_name=None,
        model_version=None,
        breadcrumb=canonical_breadcrumb(
            db,
            target.id,
            taxonomy_revision_id=taxonomy_revision_id,
        ),
        lock_version=1,
        is_current=True,
        captured_at=datetime(2026, 7, 19, 11, 0, tzinfo=timezone.utc),
    )
    db.add(assignment)
    db.flush()
    return assignment


def _review(db, job, *, taxonomy_revision_id, reason, created_at):
    recommendation = (
        db.query(CanonicalJobSubcategory)
        .filter_by(
            revision_id=taxonomy_revision_id,
            code="accounting.financial_accounting.accounts_receivable",
        )
        .one()
    )
    review = JobTaxonomyReviewItem(
        job_id=job.id,
        taxonomy_revision_id=taxonomy_revision_id,
        mapping_revision_id=None,
        status="active",
        reasons=[reason],
        evidence_hash=normalized_content_hash(
            {"job_id": str(job.id), "reason": reason}
        ),
        evidence_refs=[{"kind": "fixture", "id": "review"}],
        recommendations=[
            {
                "subcategory_id": str(recommendation.id),
                "code": recommendation.code,
                "label": recommendation.label,
            }
        ],
        lock_version=1,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(review)
    db.flush()
    return review


class _FailingOutboxRepository:
    def enqueue(self, *_args, **_kwargs):
        raise RuntimeError("forced canonical outbox failure")
