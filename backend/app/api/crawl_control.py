from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.crawl_control.automation_contracts import (
    AutomationDeleteImpactV1,
    AutomationDeleteReviewGrantV1,
    AutomationLifecycleState,
    AutomationProjectionV1,
)
from app.crawl_control.automation_service import AutomationService
from app.crawl_control.contracts import CrawlScopePreviewV1, SourceSite
from app.crawl_control.dispatch_plan_contracts import (
    DispatchPlanPreparationV1,
    DispatchPlanSnapshotV1,
    OneOffRunV1,
    SavedAutomationRunV1,
)
from app.crawl_control.dispatch_plan_service import DispatchPlanService
from app.crawl_control.errors import CrawlControlError
from app.crawl_control.scope_service import CrawlScopeService
from app.crawl_control.task_control_board_service import (
    TaskControlBoardProjectionService,
    build_crawl_control_run_projection,
)
from app.crawl_control.task_control_board_contracts import (
    TaskControlBoardProjectionV1,
)
from app.database import get_db
from app.schemas.crawl_control import (
    AutomationCreateRequestV1,
    AutomationListResponseV1,
    AutomationPermanentDeleteRequestV1,
    AutomationRestoreRequestV1,
    AutomationRevisionRequestV1,
    AutomationUpdateRequestV1,
    CrawlScopePreviewRequestV1,
    DispatchPlanDispatchRequestV1,
    DispatchPlanDispatchResponseV1,
)
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.services.source_catalog_service import SourceCatalogService
from app.source_catalog.errors import SourceCatalogError


router = APIRouter(tags=["crawl-control"])
AUTOMATION_API_ACTOR = "local-operator"
crawl_job_dispatch_service = CrawlJobDispatchService()
SUPPORTED_CONTROL_SOURCE_SITES = frozenset(
    {"jobsdb", "ctgoodjobs", "offertoday"}
)


_CRAWL_CONTROL_ERROR_STATUS = {
    "AUTOMATION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DISPATCH_PLAN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "CATALOG_NOT_PUBLISHED": status.HTTP_404_NOT_FOUND,
    "SOURCE_CLASSIFICATION_UNKNOWN": status.HTTP_404_NOT_FOUND,
    "SCOPE_RULE_INVALID": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "WORKLOAD_CAP_EXCEEDED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "BACKLOG_SAFETY_CAP_EXCEEDED": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "AUTOMATION_REVISION_CONFLICT": status.HTTP_409_CONFLICT,
    "AUTOMATION_TRANSITION_INVALID": status.HTTP_409_CONFLICT,
    "AUTOMATION_DELETE_REVIEW_STALE": status.HTTP_409_CONFLICT,
    "SCOPE_REVIEW_REQUIRED": status.HTTP_409_CONFLICT,
    "DETAIL_RUN_CONFLICT": status.HTTP_409_CONFLICT,
    "DISPATCH_PLAN_REVIEW_REQUIRED": status.HTTP_409_CONFLICT,
    "DISPATCH_PLAN_EXPIRED": status.HTTP_409_CONFLICT,
    "DISPATCH_PLAN_STALE": status.HTTP_409_CONFLICT,
    "DISPATCH_PLAN_ALREADY_CONSUMED": status.HTTP_409_CONFLICT,
    "DISPATCH_PLAN_FINGERPRINT_MISMATCH": status.HTTP_409_CONFLICT,
}


def crawl_control_http_error(
    exc: CrawlControlError | SourceCatalogError,
) -> HTTPException:
    return HTTPException(
        status_code=_CRAWL_CONTROL_ERROR_STATUS.get(
            exc.code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ),
        detail=exc.to_detail(),
    )


def _normalize_control_source_site(
    source_site: str | None,
) -> SourceSite | None:
    if source_site is None:
        return None
    normalized = source_site.strip().lower()
    if normalized not in SUPPORTED_CONTROL_SOURCE_SITES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "SOURCE_SITE_UNSUPPORTED",
                "message": "Unsupported Crawl Control source_site",
                "context": {"source_site": normalized},
            },
        )
    return cast(SourceSite, normalized)


def _set_automation_revision_headers(
    response: Response,
    projection: AutomationProjectionV1,
) -> None:
    revision = projection.snapshot.revision
    response.headers["ETag"] = f'"{revision}"'
    response.headers["X-Automation-Revision"] = str(revision)


@router.post(
    "/crawl-scopes/preview",
    response_model=CrawlScopePreviewV1,
)
def preview_crawl_scope(
    request: CrawlScopePreviewRequestV1,
    db: Session = Depends(get_db),
) -> CrawlScopePreviewV1:
    try:
        return CrawlScopeService(SourceCatalogService(db)).preview(
            request.scope,
            listing_settings=request.listing_settings,
        )
    except (CrawlControlError, SourceCatalogError) as exc:
        raise crawl_control_http_error(exc) from exc


@router.get(
    "/automations",
    response_model=AutomationListResponseV1,
)
def list_automations(
    source_site: str | None = None,
    lifecycle_state: AutomationLifecycleState | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> AutomationListResponseV1:
    normalized_source_site = _normalize_control_source_site(source_site)
    items, total = AutomationService(db).list(
        source_site=normalized_source_site,
        lifecycle_state=lifecycle_state,
        offset=offset,
        limit=limit,
    )
    return AutomationListResponseV1(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        source_site=normalized_source_site,
        lifecycle_state=lifecycle_state,
    )


@router.get(
    "/automations/{automation_id}",
    response_model=AutomationProjectionV1,
)
def get_automation(
    automation_id: UUID,
    response: Response,
    db: Session = Depends(get_db),
) -> AutomationProjectionV1:
    try:
        projection = AutomationService(db).get(automation_id)
    except CrawlControlError as exc:
        raise crawl_control_http_error(exc) from exc
    _set_automation_revision_headers(response, projection)
    return projection


@router.post(
    "/automations",
    response_model=AutomationProjectionV1,
    status_code=status.HTTP_201_CREATED,
)
def create_automation(
    request: AutomationCreateRequestV1,
    response: Response,
    db: Session = Depends(get_db),
) -> AutomationProjectionV1:
    try:
        projection = AutomationService(db).create(
            request.configuration,
            actor=AUTOMATION_API_ACTOR,
            initial_state=request.initial_state,
        )
    except (CrawlControlError, SourceCatalogError) as exc:
        raise crawl_control_http_error(exc) from exc
    _set_automation_revision_headers(response, projection)
    return projection


@router.put(
    "/automations/{automation_id}",
    response_model=AutomationProjectionV1,
)
def update_automation(
    automation_id: UUID,
    request: AutomationUpdateRequestV1,
    response: Response,
    db: Session = Depends(get_db),
) -> AutomationProjectionV1:
    try:
        projection = AutomationService(db).update_configuration(
            automation_id,
            expected_revision=request.expected_revision,
            configuration=request.configuration,
            actor=AUTOMATION_API_ACTOR,
        )
    except (CrawlControlError, SourceCatalogError) as exc:
        raise crawl_control_http_error(exc) from exc
    _set_automation_revision_headers(response, projection)
    return projection


def _transition_automation(
    *,
    automation_id: UUID,
    expected_revision: int,
    operation: str,
    response: Response,
    db: Session,
    activate: bool = False,
) -> AutomationProjectionV1:
    service = AutomationService(db)
    try:
        if operation == "pause":
            projection = service.pause(
                automation_id,
                expected_revision=expected_revision,
                actor=AUTOMATION_API_ACTOR,
            )
        elif operation == "resume":
            projection = service.resume(
                automation_id,
                expected_revision=expected_revision,
                actor=AUTOMATION_API_ACTOR,
            )
        elif operation == "archive":
            projection = service.archive(
                automation_id,
                expected_revision=expected_revision,
                actor=AUTOMATION_API_ACTOR,
            )
        elif operation == "restore":
            projection = service.restore(
                automation_id,
                expected_revision=expected_revision,
                actor=AUTOMATION_API_ACTOR,
                activate=activate,
            )
        else:
            raise ValueError(f"Unsupported Automation operation: {operation}")
    except (CrawlControlError, SourceCatalogError) as exc:
        raise crawl_control_http_error(exc) from exc
    _set_automation_revision_headers(response, projection)
    return projection


@router.post(
    "/automations/{automation_id}/pause",
    response_model=AutomationProjectionV1,
)
def pause_automation(
    automation_id: UUID,
    request: AutomationRevisionRequestV1,
    response: Response,
    db: Session = Depends(get_db),
) -> AutomationProjectionV1:
    return _transition_automation(
        automation_id=automation_id,
        expected_revision=request.expected_revision,
        operation="pause",
        response=response,
        db=db,
    )


@router.post(
    "/automations/{automation_id}/resume",
    response_model=AutomationProjectionV1,
)
def resume_automation(
    automation_id: UUID,
    request: AutomationRevisionRequestV1,
    response: Response,
    db: Session = Depends(get_db),
) -> AutomationProjectionV1:
    return _transition_automation(
        automation_id=automation_id,
        expected_revision=request.expected_revision,
        operation="resume",
        response=response,
        db=db,
    )


@router.post(
    "/automations/{automation_id}/archive",
    response_model=AutomationProjectionV1,
)
def archive_automation(
    automation_id: UUID,
    request: AutomationRevisionRequestV1,
    response: Response,
    db: Session = Depends(get_db),
) -> AutomationProjectionV1:
    return _transition_automation(
        automation_id=automation_id,
        expected_revision=request.expected_revision,
        operation="archive",
        response=response,
        db=db,
    )


@router.post(
    "/automations/{automation_id}/restore",
    response_model=AutomationProjectionV1,
)
def restore_automation(
    automation_id: UUID,
    request: AutomationRestoreRequestV1,
    response: Response,
    db: Session = Depends(get_db),
) -> AutomationProjectionV1:
    return _transition_automation(
        automation_id=automation_id,
        expected_revision=request.expected_revision,
        operation="restore",
        response=response,
        db=db,
        activate=request.activate,
    )


@router.post(
    "/automations/{automation_id}/delete-reviews",
    response_model=AutomationDeleteReviewGrantV1,
)
def review_automation_permanent_delete(
    automation_id: UUID,
    db: Session = Depends(get_db),
) -> AutomationDeleteReviewGrantV1:
    try:
        return AutomationService(db).review_permanent_delete(
            automation_id,
            actor=AUTOMATION_API_ACTOR,
        )
    except CrawlControlError as exc:
        raise crawl_control_http_error(exc) from exc


@router.delete(
    "/automations/{automation_id}",
    response_model=AutomationDeleteImpactV1,
)
def permanently_delete_automation(
    automation_id: UUID,
    request: AutomationPermanentDeleteRequestV1,
    db: Session = Depends(get_db),
) -> AutomationDeleteImpactV1:
    try:
        return AutomationService(db).permanently_delete(
            automation_id,
            expected_revision=request.expected_revision,
            actor=AUTOMATION_API_ACTOR,
            review_token=request.review_token,
        )
    except CrawlControlError as exc:
        raise crawl_control_http_error(exc) from exc


@router.post(
    "/dispatch-plans",
    response_model=DispatchPlanPreparationV1,
    status_code=status.HTTP_201_CREATED,
)
def prepare_dispatch_plan(
    request: OneOffRunV1 | SavedAutomationRunV1,
    db: Session = Depends(get_db),
) -> DispatchPlanPreparationV1:
    try:
        return DispatchPlanService(db).prepare_run(
            request,
            prepared_by=AUTOMATION_API_ACTOR,
        )
    except (CrawlControlError, SourceCatalogError) as exc:
        raise crawl_control_http_error(exc) from exc


@router.get(
    "/dispatch-plans/{plan_id}",
    response_model=DispatchPlanSnapshotV1,
)
def get_dispatch_plan(
    plan_id: UUID,
    db: Session = Depends(get_db),
) -> DispatchPlanSnapshotV1:
    try:
        return DispatchPlanService(db).get(plan_id)
    except CrawlControlError as exc:
        raise crawl_control_http_error(exc) from exc


@router.post(
    "/dispatch-plans/{plan_id}/dispatch",
    response_model=DispatchPlanDispatchResponseV1,
    status_code=status.HTTP_202_ACCEPTED,
)
def dispatch_plan(
    plan_id: UUID,
    request: DispatchPlanDispatchRequestV1,
    response: Response,
    db: Session = Depends(get_db),
) -> DispatchPlanDispatchResponseV1:
    try:
        result = crawl_job_dispatch_service.dispatch_prepared_plan(
            db,
            plan_id=plan_id,
            confirmation_token=request.confirmation_token,
            expected_plan_fingerprint=request.expected_plan_fingerprint,
            requested_by=AUTOMATION_API_ACTOR,
        )
    except CrawlControlError as exc:
        raise crawl_control_http_error(exc) from exc
    assert result.dispatch_plan is not None
    response.headers["X-Crawl-Job-Id"] = str(result.crawl_job.id)
    return DispatchPlanDispatchResponseV1(
        plan=result.dispatch_plan,
        run=build_crawl_control_run_projection(
            result.crawl_job,
            dispatch_plan_snapshot=result.dispatch_plan,
        ),
    )


@router.get(
    "/task-control-board",
    response_model=TaskControlBoardProjectionV1,
)
def get_task_control_board(
    source_site: str | None = None,
    run_limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
) -> TaskControlBoardProjectionV1:
    normalized_source_site = _normalize_control_source_site(source_site)
    return TaskControlBoardProjectionService(db).get(
        source_site=normalized_source_site,
        run_limit=run_limit,
    )
