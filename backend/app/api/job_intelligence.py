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
from app.job_intelligence.source_attributes import SourceCatalogProvenanceRepair
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
    CanonicalReviewPageSchema,
    CanonicalTaxonomyDecisionRequestSchema,
    CanonicalTaxonomyDecisionResultSchema,
    CanonicalTaxonomyRevisionSchema,
    CanonicalTaxonomyTreeSchema,
    GovernanceAuditPageSchema,
    PendingSelectionScopeSchema,
    PendingSelectionSummarySchema,
    ProvenanceRepairApplyRequestSchema,
    ProvenanceRepairApplyResponseSchema,
    ProvenanceRepairApplyResultSchema,
    ProvenanceRepairInspectRequestSchema,
    ProvenanceRepairInspectResponseSchema,
    ProvenanceRepairReportSchema,
)
from app.services.enrichment_run_service import EnrichmentRunService
from app.schemas.job_intelligence_product import (
    JobIntelligenceGovernanceSummarySchema,
)


router = APIRouter(prefix="/job-intelligence", tags=["job-intelligence"])


def _single_scope_source(scope: PendingSelectionScopeSchema) -> str:
    sources = set(scope.source_sites)
    sources.update(
        identity.partition(":")[0]
        for identity in (
            *scope.source_classification_ids,
            *scope.source_subclassification_ids,
        )
        if ":" in identity
    )
    if len(sources) != 1:
        raise ValueError(
            "Provenance repair requires exactly one source in the current scope"
        )
    return next(iter(sources))


def _selection_summary(report) -> PendingSelectionSummarySchema:
    return PendingSelectionSummarySchema.model_validate(
        {
            **report.to_preview_payload(),
            "selected_job_ids": list(report.selected_job_ids),
            "supported_job_ids": list(report.supported_job_ids),
            "excluded_reasons_by_job_id": report.excluded_reasons_by_job_id,
        }
    )


def _provenance_excluded_ids(report) -> tuple[UUID, ...]:
    return tuple(
        UUID(job_id)
        for job_id, reason in report.excluded_reasons_by_job_id.items()
        if reason == "source_catalog_provenance_missing"
    )


def _repair_report_schema(report) -> ProvenanceRepairReportSchema:
    return ProvenanceRepairReportSchema.model_validate(report.to_payload())


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
    "/governance/summary",
    response_model=JobIntelligenceGovernanceSummarySchema,
)
def read_job_intelligence_governance_summary(
    db: Session = Depends(get_db),
) -> JobIntelligenceGovernanceSummarySchema:
    payload = JobIntelligenceProductReadModel(db).get_governance_summary().to_payload()
    return JobIntelligenceGovernanceSummarySchema.model_validate(payload)


@router.post(
    "/governance/source-catalog-provenance/inspect",
    response_model=ProvenanceRepairInspectResponseSchema,
)
def inspect_source_catalog_provenance_repair(
    request: ProvenanceRepairInspectRequestSchema,
    db: Session = Depends(get_db),
) -> ProvenanceRepairInspectResponseSchema:
    """Inspect the current bounded AI selection without writing."""
    try:
        source_site = _single_scope_source(request.scope)
        selection = EnrichmentRunService(db).inspect_pending_selection(
            filters=request.scope.to_service_filters(),
            limit=request.limit,
        )
        repair_ids = _provenance_excluded_ids(selection)
        report = SourceCatalogProvenanceRepair(db).inspect_active(
            source_site=source_site,
            job_ids=repair_ids,
            pending_only=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProvenanceRepairInspectResponseSchema(
        selection=_selection_summary(selection),
        report=_repair_report_schema(report),
    )


@router.post(
    "/governance/source-catalog-provenance/apply",
    response_model=ProvenanceRepairApplyResponseSchema,
)
def apply_source_catalog_provenance_repair(
    request: ProvenanceRepairApplyRequestSchema,
    db: Session = Depends(get_db),
) -> ProvenanceRepairApplyResponseSchema:
    """Apply only the reviewed repairable subset after drift revalidation."""
    if not request.confirmed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PROVENANCE_REPAIR_UNCONFIRMED",
                "message": "Provenance repair requires explicit confirmation",
            },
        )

    try:
        source_site = _single_scope_source(request.scope)
        selection = EnrichmentRunService(db).inspect_pending_selection(
            filters=request.scope.to_service_filters(),
            limit=request.limit,
        )
        current_report = SourceCatalogProvenanceRepair(db).inspect_active(
            source_site=source_site,
            job_ids=_provenance_excluded_ids(selection),
            pending_only=True,
        )
        expected_job_ids = tuple(sorted(str(job_id) for job_id in request.repairable_job_ids))
        actual_job_ids = tuple(sorted(str(job_id) for job_id in current_report.repairable_job_ids))
        if expected_job_ids != actual_job_ids:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROVENANCE_REPAIR_SCOPE_CHANGED",
                    "message": "The repairable jobs changed; inspect the current batch again",
                },
            )
        if not actual_job_ids:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROVENANCE_REPAIR_NO_REPAIRABLE_JOBS",
                    "message": "No jobs in the current batch are safe to repair",
                },
            )

        repair = SourceCatalogProvenanceRepair(db)
        write_report = repair.inspect_active(
            source_site=source_site,
            job_ids=tuple(UUID(job_id) for job_id in actual_job_ids),
            pending_only=True,
        )
        if tuple(sorted(str(job_id) for job_id in write_report.repairable_job_ids)) != actual_job_ids:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PROVENANCE_REPAIR_SCOPE_CHANGED",
                    "message": "The repairable subset changed; inspect the current batch again",
                },
            )
        result = repair.apply(
            write_report,
            expected_revision_id=request.revision_id,
            expected_fingerprint=request.expected_fingerprint,
        )
        recheck = EnrichmentRunService(db).inspect_pending_selection(
            filters=request.scope.to_service_filters(),
            limit=request.limit,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return ProvenanceRepairApplyResponseSchema(
        selection=_selection_summary(recheck),
        repair=ProvenanceRepairApplyResultSchema.model_validate(result.to_payload()),
    )


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
            selection = EnrichmentRunService(db).inspect_pending_selection(
                filters=scope.to_service_filters(),
                limit=pending_limit or limit,
            )
            scoped_job_ids = tuple(UUID(job_id) for job_id in selection.selected_job_ids)
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
