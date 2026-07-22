from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.job_intelligence.company_industry import (
    CompanyIndustry,
    CompanyIndustryDecisionAdapter,
    CompanyIndustryDecisionError,
    CompanyIndustryReadError,
    CompanyIndustryReviewQuery,
)
from app.job_intelligence.foundation import (
    AuditQuery,
    AuditReader,
    DecisionCommand,
    GovernanceError,
)
from app.schemas.company_industry import (
    CompanyIndustryCompanyStateSchema,
    CompanyIndustryDecisionRequestSchema,
    CompanyIndustryDecisionResultSchema,
    CompanyIndustryReviewItemSchema,
    CompanyIndustryReviewPageSchema,
    CompanyIndustryRevisionSchema,
    CompanyIndustryTreeSchema,
    SourceIndustryMappingSchema,
)
from app.schemas.job_intelligence import GovernanceAuditPageSchema


router = APIRouter(prefix="/job-intelligence", tags=["job-intelligence"])


def _read_error(exc: CompanyIndustryReadError) -> HTTPException:
    not_found_codes = {
        "COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE",
        "COMPANY_INDUSTRY_PARENT_NOT_FOUND",
        "COMPANY_INDUSTRY_NODE_NOT_FOUND",
        "COMPANY_INDUSTRY_COMPANY_NOT_FOUND",
        "COMPANY_INDUSTRY_REVIEW_ITEM_NOT_FOUND",
    }
    conflict_codes = {
        "COMPANY_INDUSTRY_ACTIVE_REVISION_INVALID",
        "COMPANY_INDUSTRY_HIERARCHY_INVALID",
    }
    if exc.code in not_found_codes:
        status_code = 404
    elif exc.code in conflict_codes:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _decision_error(
    exc: GovernanceError | CompanyIndustryDecisionError,
) -> HTTPException:
    if isinstance(exc, GovernanceError):
        detail = exc.to_detail()
        code = exc.code
    else:
        detail = {"code": exc.code, "message": str(exc)}
        code = exc.code
    if code == "GOVERNANCE_DECISION_SUBJECT_NOT_FOUND":
        status_code = 404
    elif code in {
        "GOVERNANCE_DECISION_STALE_VERSION",
        "GOVERNANCE_IDEMPOTENCY_CONFLICT",
        "COMPANY_INDUSTRY_REVIEW_NOT_ACTIVE",
        "COMPANY_INDUSTRY_MAPPING_CONFLICT",
    }:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail=detail)


@router.get(
    "/company-industries/revision",
    response_model=CompanyIndustryRevisionSchema,
)
def read_company_industry_revision(
    db: Session = Depends(get_db),
) -> CompanyIndustryRevisionSchema:
    try:
        payload = CompanyIndustry(db).get_active_revision().to_payload()
    except CompanyIndustryReadError as exc:
        raise _read_error(exc) from exc
    return CompanyIndustryRevisionSchema.model_validate(payload)


@router.get(
    "/company-industries/tree",
    response_model=CompanyIndustryTreeSchema,
)
def read_company_industry_tree(
    parent_id: UUID | None = None,
    db: Session = Depends(get_db),
) -> CompanyIndustryTreeSchema:
    try:
        payload = CompanyIndustry(db).get_tree(parent_id).to_payload()
    except CompanyIndustryReadError as exc:
        raise _read_error(exc) from exc
    return CompanyIndustryTreeSchema.model_validate(payload)


@router.get(
    "/companies/{company_id}/industries",
    response_model=CompanyIndustryCompanyStateSchema,
)
def read_company_industry_state(
    company_id: UUID,
    db: Session = Depends(get_db),
) -> CompanyIndustryCompanyStateSchema:
    try:
        payload = CompanyIndustry(db).get_company_state(company_id).to_payload()
    except CompanyIndustryReadError as exc:
        raise _read_error(exc) from exc
    return CompanyIndustryCompanyStateSchema.model_validate(payload)


@router.get(
    "/governance/company-industries/review-items",
    response_model=CompanyIndustryReviewPageSchema,
)
def list_company_industry_review_items(
    status: list[str] | None = Query(default=None),
    source_site: list[str] | None = Query(default=None),
    reason: list[str] | None = Query(default=None),
    company_id: UUID | None = None,
    raw_value: str | None = None,
    cursor: str | None = None,
    page: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> CompanyIndustryReviewPageSchema:
    try:
        page = CompanyIndustry(db).list_review_items(
            CompanyIndustryReviewQuery(
                statuses=tuple(status) if status is not None else ("active",),
                source_sites=tuple(source_site or ()),
                reasons=tuple(reason or ()),
                company_id=company_id,
                raw_value=raw_value,
                cursor=cursor,
                page=page,
                limit=limit,
            )
        )
    except CompanyIndustryReadError as exc:
        raise _read_error(exc) from exc
    return CompanyIndustryReviewPageSchema.model_validate(page.to_payload())


@router.get(
    "/governance/company-industries/review-items/{review_item_id}",
    response_model=CompanyIndustryReviewItemSchema,
)
def read_company_industry_review_item(
    review_item_id: UUID,
    db: Session = Depends(get_db),
) -> CompanyIndustryReviewItemSchema:
    try:
        payload = CompanyIndustry(db).get_review_item(review_item_id).to_payload()
    except CompanyIndustryReadError as exc:
        raise _read_error(exc) from exc
    return CompanyIndustryReviewItemSchema.model_validate(payload)


@router.post(
    "/governance/company-industries/review-items/{review_item_id}/decision",
    response_model=CompanyIndustryDecisionResultSchema,
)
def decide_company_industry_review_item(
    review_item_id: UUID,
    request: CompanyIndustryDecisionRequestSchema,
    db: Session = Depends(get_db),
) -> CompanyIndustryDecisionResultSchema:
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
        result = CompanyIndustryDecisionAdapter(db).decide(command)
    except (GovernanceError, CompanyIndustryDecisionError) as exc:
        raise _decision_error(exc) from exc
    return CompanyIndustryDecisionResultSchema.model_validate(
        {**result.to_payload(), "replayed": result.replayed}
    )


@router.get(
    "/governance/company-industries/mappings",
    response_model=list[SourceIndustryMappingSchema],
)
def list_company_industry_mappings(
    source_site: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[SourceIndustryMappingSchema]:
    mappings = CompanyIndustry(db).list_mappings(
        source_sites=tuple(source_site or ()),
        statuses=tuple(status) if status is not None else ("active",),
    )
    return [
        SourceIndustryMappingSchema.model_validate(mapping.to_payload())
        for mapping in mappings
    ]


@router.get(
    "/governance/company-industries/audit-events",
    response_model=GovernanceAuditPageSchema,
)
def list_company_industry_audit_events(
    subject_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> GovernanceAuditPageSchema:
    try:
        page = AuditReader(db).list(
            AuditQuery(
                domain="company-industry",
                subject_id=subject_id,
                cursor=cursor,
                limit=limit,
            )
        )
    except ValueError as exc:
        raise _read_error(
            CompanyIndustryReadError(
                "COMPANY_INDUSTRY_AUDIT_CURSOR_INVALID",
                str(exc),
            )
        ) from exc
    return GovernanceAuditPageSchema.from_contract(page)


__all__ = ["router"]
