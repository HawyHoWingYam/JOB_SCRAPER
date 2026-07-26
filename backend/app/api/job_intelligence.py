from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.job_intelligence.canonical_taxonomy import (
    CanonicalJobTaxonomy,
    CanonicalReadError,
    CanonicalReviewQuery,
    CanonicalTaxonomyDecisionAdapter,
    CanonicalTaxonomyDecisionError,
)
from app.job_intelligence.foundation import (
    AuditQuery,
    AuditReader,
    DecisionCommand,
    GovernanceError,
)
from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.schemas.job_intelligence import (
    CanonicalJobStateSchema,
    CanonicalReviewItemSchema,
    CanonicalReviewItemsQuerySchema,
    CanonicalReviewPageSchema,
    CanonicalTaxonomyDecisionRequestSchema,
    CanonicalTaxonomyDecisionResultSchema,
    CanonicalTaxonomyRevisionSchema,
    CanonicalTaxonomyTreeSchema,
    CanonicalTaxonomyRecoveryConfirmRequestSchema,
    CanonicalTaxonomyRecoveryPreviewRequestSchema,
    GovernanceAuditPageSchema,
    PendingSelectionScopeSchema,
)
from app.services.enrichment_run_service import EnrichmentRunService
from app.services.canonical_taxonomy_recovery_service import (
    CanonicalTaxonomyRecoveryError,
    CanonicalTaxonomyRecoveryService,
)
from app.services.enrichment_run_service import ActiveEnrichmentRunError
from app.schemas.job_intelligence_product import (
    JobIntelligenceGovernanceSummarySchema,
)


router = APIRouter(prefix="/job-intelligence", tags=["job-intelligence"])


def _read_error(exc: CanonicalReadError) -> HTTPException:
    status_code = (
        404
        if exc.code
        in {
            "CANONICAL_TAXONOMY_NOT_ACTIVE",
            "CANONICAL_JOB_NOT_FOUND",
            "CANONICAL_REVIEW_ITEM_NOT_FOUND",
        }
        else 422
    )
    return HTTPException(status_code=status_code, detail=exc.to_detail())


def _decision_error(
    exc: GovernanceError | CanonicalTaxonomyDecisionError,
) -> HTTPException:
    code = exc.code
    if isinstance(exc, GovernanceError):
        detail = exc.to_detail()
    else:
        detail = {"code": code, "message": str(exc)}
    if code == "GOVERNANCE_DECISION_SUBJECT_NOT_FOUND":
        status_code = 404
    elif code in {
        "GOVERNANCE_DECISION_STALE_VERSION",
        "GOVERNANCE_IDEMPOTENCY_CONFLICT",
        "JOB_TAXONOMY_REVIEW_NOT_ACTIVE",
        "JOB_TAXONOMY_CURRENT_ASSIGNMENT_EXISTS",
        "JOB_TAXONOMY_ACTIVE_REVISION_MISSING",
    }:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail=detail)


def _recovery_error(exc: CanonicalTaxonomyRecoveryError) -> HTTPException:
    status_code = (
        409
        if exc.code
        in {
            "CANONICAL_TAXONOMY_RECOVERY_SCOPE_CHANGED",
            "CANONICAL_TAXONOMY_RECOVERY_NO_ITEMS",
            "CANONICAL_TAXONOMY_RECOVERY_DRIFT",
        }
        else 422
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _serialize_recovery_run(db: Session, run) -> dict[str, object]:
    from app.api.ai import _serialize_single_run

    return _serialize_single_run(run, db)


@router.get(
    "/governance/summary",
    response_model=JobIntelligenceGovernanceSummarySchema,
)
def read_job_intelligence_governance_summary(
    db: Session = Depends(get_db),
) -> JobIntelligenceGovernanceSummarySchema:
    payload = JobIntelligenceProductReadModel(db).get_governance_summary().to_payload()
    return JobIntelligenceGovernanceSummarySchema.model_validate(payload)


@router.post("/governance/job-taxonomy/recovery/preview")
def preview_canonical_taxonomy_recovery(
    request: CanonicalTaxonomyRecoveryPreviewRequestSchema,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Preview only the bounded classifier failures eligible for recovery."""
    try:
        preview = CanonicalTaxonomyRecoveryService(db).preview(
            request.scope.to_recovery_scope()
        )
    except CanonicalTaxonomyRecoveryError as exc:
        raise _recovery_error(exc) from exc
    return preview.to_payload()


@router.post("/governance/job-taxonomy/recovery/runs")
def create_canonical_taxonomy_recovery_run(
    request: CanonicalTaxonomyRecoveryConfirmRequestSchema,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Confirm a pinned preview and queue its asynchronous recovery run."""
    service = CanonicalTaxonomyRecoveryService(db)
    try:
        run = service.create_run(
            request.scope.to_recovery_scope(),
            expected_scope_fingerprint=request.expected_scope_fingerprint,
            expected_taxonomy_revision_id=request.taxonomy_revision_id,
            expected_mapping_revision_id=request.mapping_revision_id,
            confirmed=request.confirmed,
        )
    except ActiveEnrichmentRunError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "active_run_exists", "run_id": exc.run_id},
        ) from exc
    except CanonicalTaxonomyRecoveryError as exc:
        raise _recovery_error(exc) from exc

    from app.api.ai import _publish_run_request

    requested = _publish_run_request(
        db,
        service=EnrichmentRunService(db),
        run_id=run.id,
        source_service="canonical-taxonomy-recovery-api",
    )
    db.refresh(run)
    payload = _serialize_recovery_run(db, run)
    payload["execution_dispatched"] = requested
    return payload


@router.get("/governance/job-taxonomy/recovery/runs/{run_id}")
def read_canonical_taxonomy_recovery_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    run = EnrichmentRunService(db).get_run(run_id)
    if run is None or run.source_type != "canonical_taxonomy_recovery":
        raise HTTPException(status_code=404, detail="Recovery run not found")
    return _serialize_recovery_run(db, run)


@router.post("/governance/job-taxonomy/recovery/runs/{run_id}/retry-failed")
def retry_canonical_taxonomy_recovery_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = CanonicalTaxonomyRecoveryService(db)
    try:
        run = service.create_retry_run(run_id)
    except ActiveEnrichmentRunError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "active_run_exists", "run_id": exc.run_id},
        ) from exc
    except CanonicalTaxonomyRecoveryError as exc:
        raise _recovery_error(exc) from exc

    from app.api.ai import _publish_run_request

    _publish_run_request(
        db,
        service=EnrichmentRunService(db),
        run_id=run.id,
        source_service="canonical-taxonomy-recovery-api",
    )
    db.refresh(run)
    return _serialize_recovery_run(db, run)


@router.get(
    "/canonical-job-taxonomy/revision",
    response_model=CanonicalTaxonomyRevisionSchema,
)
def read_canonical_taxonomy_revision(
    db: Session = Depends(get_db),
) -> CanonicalTaxonomyRevisionSchema:
    try:
        contract = CanonicalJobTaxonomy(db).get_active_revision()
    except CanonicalReadError as exc:
        raise _read_error(exc) from exc
    return CanonicalTaxonomyRevisionSchema.model_validate(contract.to_payload())


@router.get(
    "/canonical-job-taxonomy/tree",
    response_model=CanonicalTaxonomyTreeSchema,
)
def read_canonical_taxonomy_tree(
    db: Session = Depends(get_db),
) -> CanonicalTaxonomyTreeSchema:
    try:
        contract = CanonicalJobTaxonomy(db).get_tree()
    except CanonicalReadError as exc:
        raise _read_error(exc) from exc
    return CanonicalTaxonomyTreeSchema.model_validate(contract.to_payload())


@router.get(
    "/jobs/{job_id}/canonical-taxonomy",
    response_model=CanonicalJobStateSchema,
)
def read_job_canonical_taxonomy(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> CanonicalJobStateSchema:
    try:
        contract = CanonicalJobTaxonomy(db).get_job_state(job_id)
    except CanonicalReadError as exc:
        raise _read_error(exc) from exc
    return CanonicalJobStateSchema.model_validate(contract.to_payload())


@router.get(
    "/governance/job-taxonomy/review-items",
    response_model=CanonicalReviewPageSchema,
)
def list_job_taxonomy_review_items(
    status: list[str] | None = Query(default=None),
    reason: list[str] | None = Query(default=None),
    job_id: UUID | None = None,
    job_ids: list[UUID] | None = Query(default=None),
    source_site: list[str] | None = Query(default=None),
    source_classification_id: list[str] | None = Query(default=None),
    source_subclassification_id: list[str] | None = Query(default=None),
    posted_date_from: date | None = None,
    posted_date_to: date | None = None,
    pending_limit: int | None = Query(default=None, ge=1, le=5000),
    cursor: str | None = None,
    page: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> CanonicalReviewPageSchema:
    return _list_job_taxonomy_review_items(
        status=status,
        reason=reason,
        job_id=job_id,
        job_ids=job_ids,
        source_site=source_site,
        source_classification_id=source_classification_id,
        source_subclassification_id=source_subclassification_id,
        posted_date_from=posted_date_from,
        posted_date_to=posted_date_to,
        pending_limit=pending_limit,
        cursor=cursor,
        page=page,
        limit=limit,
        db=db,
    )


@router.post(
    "/governance/job-taxonomy/review-items/query",
    response_model=CanonicalReviewPageSchema,
)
def query_job_taxonomy_review_items(
    request: CanonicalReviewItemsQuerySchema,
    db: Session = Depends(get_db),
) -> CanonicalReviewPageSchema:
    """Query large bounded scopes without putting all IDs in the URL."""
    return _list_job_taxonomy_review_items(
        status=request.status or None,
        reason=request.reason or None,
        job_id=request.job_id,
        job_ids=request.job_ids or None,
        source_site=request.source_site or None,
        source_classification_id=request.source_classification_id or None,
        source_subclassification_id=request.source_subclassification_id or None,
        posted_date_from=request.posted_date_from,
        posted_date_to=request.posted_date_to,
        pending_limit=request.pending_limit,
        cursor=request.cursor,
        page=request.page,
        limit=request.limit,
        db=db,
    )


def _resolved_query_value(value):
    """Keep direct Python route calls equivalent to FastAPI-bound calls."""
    return getattr(value, "default", value)


def _list_job_taxonomy_review_items(
    *,
    status: list[str] | None,
    reason: list[str] | None,
    job_id: UUID | None,
    job_ids: list[UUID] | None,
    source_site: list[str] | None,
    source_classification_id: list[str] | None,
    source_subclassification_id: list[str] | None,
    posted_date_from: date | None,
    posted_date_to: date | None,
    pending_limit: int | None,
    cursor: str | None,
    page: int | None,
    limit: int,
    db: Session,
) -> CanonicalReviewPageSchema:
    status = _resolved_query_value(status)
    reason = _resolved_query_value(reason)
    job_id = _resolved_query_value(job_id)
    job_ids = _resolved_query_value(job_ids)
    source_site = _resolved_query_value(source_site)
    source_classification_id = _resolved_query_value(source_classification_id)
    source_subclassification_id = _resolved_query_value(source_subclassification_id)
    pending_limit = _resolved_query_value(pending_limit)
    page = _resolved_query_value(page)
    limit = _resolved_query_value(limit)
    try:
        scope = PendingSelectionScopeSchema(
            source_sites=source_site or [],
            source_classification_ids=source_classification_id or [],
            source_subclassification_ids=source_subclassification_id or [],
            posted_date_from=posted_date_from,
            posted_date_to=posted_date_to,
        )
        scoped_job_ids = tuple(job_ids or ())
        if scope.has_constraints or pending_limit is not None:
            scoped_job_ids = tuple(
                UUID(selected_job_id)
                for selected_job_id in EnrichmentRunService(
                    db
                ).select_active_review_job_ids(
                    filters=scope.to_service_filters(),
                    reason_codes=reason or (),
                    job_ids=scoped_job_ids,
                    limit=pending_limit or 5000,
                )
            )
            if not scoped_job_ids:
                offset = (page - 1) * limit if page is not None else None
                return CanonicalReviewPageSchema(
                    items=[],
                    next_cursor=None,
                    total=0,
                    page=page,
                    limit=limit if page is not None else None,
                    offset=offset,
                    page_count=1 if page is not None else None,
                )
        query = CanonicalReviewQuery(
            statuses=tuple(status) if status is not None else ("active",),
            reason_codes=tuple(reason or ()),
            job_id=job_id,
            job_ids=scoped_job_ids,
            cursor=cursor,
            page=page,
            limit=limit,
        )
        contract = CanonicalJobTaxonomy(db).list_review_items(query)
    except CanonicalReadError as exc:
        raise _read_error(exc) from exc
    return CanonicalReviewPageSchema.model_validate(contract.to_payload())


@router.get(
    "/governance/job-taxonomy/review-items/{review_item_id}",
    response_model=CanonicalReviewItemSchema,
)
def read_job_taxonomy_review_item(
    review_item_id: UUID,
    db: Session = Depends(get_db),
) -> CanonicalReviewItemSchema:
    try:
        contract = CanonicalJobTaxonomy(db).get_review_item(review_item_id)
    except CanonicalReadError as exc:
        raise _read_error(exc) from exc
    return CanonicalReviewItemSchema.model_validate(contract.to_payload())


@router.post(
    "/governance/job-taxonomy/review-items/{review_item_id}/decision",
    response_model=CanonicalTaxonomyDecisionResultSchema,
)
def decide_job_taxonomy_review_item(
    review_item_id: UUID,
    request: CanonicalTaxonomyDecisionRequestSchema,
    db: Session = Depends(get_db),
) -> CanonicalTaxonomyDecisionResultSchema:
    command = DecisionCommand(
        subject_id=str(review_item_id),
        action=request.action,
        target_id=str(request.target_id) if request.target_id is not None else None,
        expected_version=request.expected_version,
        idempotency_key=request.idempotency_key,
        confirmed=request.confirmed,
        note=request.note,
        correlation_id=request.correlation_id,
    )
    try:
        result = CanonicalTaxonomyDecisionAdapter(db).decide(command)
    except (GovernanceError, CanonicalTaxonomyDecisionError) as exc:
        raise _decision_error(exc) from exc
    return CanonicalTaxonomyDecisionResultSchema.model_validate(
        {
            **result.to_payload(),
            "replayed": result.replayed,
        }
    )


@router.get(
    "/governance/job-taxonomy/audit-events",
    response_model=GovernanceAuditPageSchema,
)
def list_job_taxonomy_audit_events(
    subject_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> GovernanceAuditPageSchema:
    try:
        page = AuditReader(db).list(
            AuditQuery(
                domain="job-taxonomy",
                subject_type="job-taxonomy-review-item",
                subject_id=subject_id,
                cursor=cursor,
                limit=limit,
            )
        )
    except ValueError as exc:
        raise _read_error(
            CanonicalReadError(
                "CANONICAL_AUDIT_CURSOR_INVALID",
                str(exc),
            )
        ) from exc
    return GovernanceAuditPageSchema.from_contract(page)
