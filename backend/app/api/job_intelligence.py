from __future__ import annotations

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
from app.job_intelligence.foundation import DecisionCommand, GovernanceError
from app.schemas.job_intelligence import (
    CanonicalJobStateSchema,
    CanonicalReviewItemSchema,
    CanonicalReviewPageSchema,
    CanonicalTaxonomyDecisionRequestSchema,
    CanonicalTaxonomyDecisionResultSchema,
    CanonicalTaxonomyRevisionSchema,
    CanonicalTaxonomyTreeSchema,
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
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> CanonicalReviewPageSchema:
    try:
        query = CanonicalReviewQuery(
            statuses=tuple(status) if status is not None else ("active",),
            reason_codes=tuple(reason or ()),
            job_id=job_id,
            cursor=cursor,
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
