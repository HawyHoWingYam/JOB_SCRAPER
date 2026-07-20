"""
Schedule API Routes - CRUD endpoints for scheduled scraping tasks.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.crawl_jobs import _build_crawl_request_created_log_message
from app.crawl_control.automation_contracts import AutomationConfigurationV1
from app.crawl_control.automation_service import AutomationService
from app.crawl_control.contracts import AuthoredCrawlScopeV1
from app.crawl_control.errors import CrawlControlError
from app.crawl_control.scope_service import CrawlScopeService
from app.crawl_phases import resolve_crawl_phase
from app.database import get_db
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.crawl_job import CrawlJobSchema
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.schemas.schedule import (
    ScheduleSchema,
    ScheduleCreateSchema,
    ScheduleUpdateSchema,
    ScheduleListResponse,
    ExecutionListResponse,
    ScheduleToggleResponse,
    ImmediateScrapeRequest,
)
from app.services.crawl_request_validation import (
    normalize_source_site,
    validate_published_category_ids,
)
from app.source_catalog.errors import SourceCatalogError
from app.services.headed_crawl_runtime import HeadedCrawlWorkerUnavailableError
from app.services.source_catalog import is_supported_source_site, resolve_default_max_pages
from app.services.source_catalog_service import SourceCatalogService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules", tags=["schedules"])
repository = ScheduleRepository()
crawl_job_dispatch_service = CrawlJobDispatchService()
AUTOMATION_MUTATION_ACTOR = "local-operator"


def _compatibility_scope(
    db: Session,
    *,
    source_site: str,
    category_ids: list[int | str] | None,
) -> tuple[AuthoredCrawlScopeV1, int]:
    catalogs = SourceCatalogService(db)
    if category_ids:
        published, selected_nodes = catalogs.validate_classifications(
            source_site,
            category_ids,
        )
        compiled = catalogs.compile_nodes(published, selected_nodes)
        scope = AuthoredCrawlScopeV1.model_validate(
            {
                "source_site": source_site,
                "reviewed_catalog_revision_id": published.revision.id,
                "mode": "rules",
                "rules": [
                    {
                        "kind": "exact",
                        "classification_id": node.classification_id,
                    }
                    for node in selected_nodes
                ],
            }
        )
        return scope, len(compiled)

    published, _selected_nodes, targets = catalogs.resolve_scope(
        source_site,
        mode="all",
    )
    scope = AuthoredCrawlScopeV1(
        source_site=source_site,
        reviewed_catalog_revision_id=published.revision.id,
        mode="all",
    )
    return scope, len(targets)


def _compatibility_configuration(
    db: Session,
    data: ScheduleCreateSchema,
) -> AutomationConfigurationV1:
    unsupported_fields = [
        field_name
        for field_name in ("keywords", "location")
        if getattr(data, field_name)
    ]
    if unsupported_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "AUTOMATION_COMPATIBILITY_FIELD_UNSUPPORTED",
                "message": (
                    "Legacy schedule fields cannot be represented by a "
                    "versioned Automation"
                ),
                "context": {"fields": ",".join(unsupported_fields)},
            },
        )

    scope, query_target_count = _compatibility_scope(
        db,
        source_site=data.source_site,
        category_ids=data.category_ids,
    )
    listing_settings = None
    detail_settings = None
    if data.crawl_phase == "listing":
        listing_settings = {
            "crawl_mode": data.crawl_mode,
            "page_depth": data.max_pages,
            "run_page_cap": query_target_count * data.max_pages,
        }
    else:
        backlog_scope = (
            {"kind": "crawl_scope", "scope": scope.model_dump(mode="json")}
            if scope.mode == "rules"
            else {"kind": "source_backlog"}
        )
        detail_settings = {
            "crawl_mode": data.crawl_mode,
            "backlog_scope": backlog_scope,
            "limit": {
                "kind": "stop_after",
                "detail_run_cap": data.detail_limit,
            },
        }
    return AutomationConfigurationV1.model_validate(
        {
            "name": data.name,
            "description": data.description,
            "cron_expression": data.cron_expression,
            "timezone": data.timezone,
            "scope": scope.model_dump(mode="json"),
            "listing_settings": listing_settings,
            "detail_settings": detail_settings,
        }
    )


def _unsupported_compatibility_fields(values: dict) -> list[str]:
    return [
        field_name
        for field_name in ("keywords", "location")
        if values.get(field_name)
    ]


def _raise_unsupported_compatibility_fields(fields: list[str]) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "AUTOMATION_COMPATIBILITY_FIELD_UNSUPPORTED",
            "message": (
                "Legacy schedule fields cannot be represented by a "
                "versioned Automation"
            ),
            "context": {"fields": ",".join(fields)},
        },
    )


def _updated_compatibility_configuration(
    db: Session,
    *,
    current: AutomationConfigurationV1,
    updates: dict,
) -> AutomationConfigurationV1:
    unsupported_fields = _unsupported_compatibility_fields(updates)
    if unsupported_fields:
        _raise_unsupported_compatibility_fields(unsupported_fields)

    source_site = updates.get("source_site") or current.scope.source_site
    category_ids_were_updated = "category_ids" in updates
    source_changed = source_site != current.scope.source_site
    scope_changed = source_changed or category_ids_were_updated
    if source_changed and not category_ids_were_updated:
        if current.scope.mode != "all":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "AUTOMATION_COMPATIBILITY_SCOPE_REQUIRED",
                    "message": (
                        "Changing source_site requires an explicit legacy "
                        "category_ids scope"
                    ),
                    "context": {"source_site": source_site},
                },
            )
        compatibility_category_ids = None
    elif category_ids_were_updated:
        compatibility_category_ids = updates.get("category_ids")
    else:
        compatibility_category_ids = None

    if scope_changed:
        scope, query_target_count = _compatibility_scope(
            db,
            source_site=source_site,
            category_ids=compatibility_category_ids,
        )
    else:
        scope = current.scope
        query_target_count = CrawlScopeService(
            SourceCatalogService(db)
        ).preview(scope).resolved_scope.query_target_count

    crawl_phase = updates.get("crawl_phase") or current.crawl_phase
    crawl_mode = updates.get("crawl_mode") or current.crawl_mode
    listing_settings = None
    detail_settings = None
    if crawl_phase == "listing":
        current_listing = current.listing_settings
        page_depth = updates.get("max_pages") or (
            current_listing.page_depth
            if current_listing is not None
            else resolve_default_max_pages(source_site)
        )
        if (
            current_listing is not None
            and "max_pages" not in updates
            and not scope_changed
        ):
            run_page_cap = current_listing.run_page_cap
        else:
            run_page_cap = query_target_count * page_depth
        listing_settings = {
            "crawl_mode": crawl_mode,
            "page_depth": page_depth,
            "run_page_cap": run_page_cap,
        }
    else:
        current_detail = current.detail_settings
        if (
            current_detail is not None
            and not scope_changed
            and "detail_limit" not in updates
        ):
            detail_settings = current_detail.model_dump(mode="json")
            detail_settings["crawl_mode"] = crawl_mode
        else:
            detail_limit = updates.get("detail_limit")
            if detail_limit is None and current_detail is not None:
                detail_limit = (
                    current_detail.limit.detail_run_cap
                    if current_detail.limit.kind == "stop_after"
                    else None
                )
            backlog_scope = (
                {
                    "kind": "crawl_scope",
                    "scope": scope.model_dump(mode="json"),
                }
                if scope.mode == "rules"
                else {"kind": "source_backlog"}
            )
            detail_settings = {
                "crawl_mode": crawl_mode,
                "backlog_scope": backlog_scope,
                "limit": (
                    {"kind": "stop_after", "detail_run_cap": detail_limit}
                    if detail_limit is not None
                    else {"kind": "entire_snapshot"}
                ),
            }

    configuration = current.model_dump(mode="json")
    for field_name in (
        "name",
        "description",
        "cron_expression",
        "timezone",
    ):
        if field_name in updates:
            configuration[field_name] = updates[field_name]
    configuration.update(
        {
            "scope": scope.model_dump(mode="json"),
            "listing_settings": listing_settings,
            "detail_settings": detail_settings,
        }
    )
    return AutomationConfigurationV1.model_validate(configuration)


def _crawl_control_http_error(
    exc: CrawlControlError | SourceCatalogError,
) -> HTTPException:
    status_code = {
        "AUTOMATION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "DISPATCH_PLAN_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "CATALOG_NOT_PUBLISHED": status.HTTP_404_NOT_FOUND,
        "SOURCE_CLASSIFICATION_UNKNOWN": status.HTTP_404_NOT_FOUND,
        "SOURCE_CLASSIFICATION_NOT_EXECUTABLE": (
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ),
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
    }.get(exc.code, status.HTTP_422_UNPROCESSABLE_CONTENT)
    return HTTPException(status_code=status_code, detail=exc.to_detail())


def _require_supported_control_source_site(source_site: str | None) -> str:
    normalized = normalize_source_site(source_site)
    if not is_supported_source_site(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "SOURCE_SITE_UNSUPPORTED",
                "message": "Unsupported Crawl Control source_site",
                "context": {"source_site": normalized},
            },
        )
    return normalized


def _headed_worker_http_error(
    exc: HeadedCrawlWorkerUnavailableError,
    *,
    source_site: str,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "HEADED_WORKER_UNAVAILABLE",
            "message": str(exc),
            "context": {"source_site": source_site},
        },
    )


async def _validate_effective_category_ids(
    source_site: str | None,
    category_ids: list[int | str] | None,
    db: Session,
) -> None:
    """Validate source-aware category ids against the published revision."""
    try:
        validate_published_category_ids(db, source_site, category_ids)
    except SourceCatalogError as exc:
        raise HTTPException(
            status_code=(
                404
                if exc.code in {"CATALOG_NOT_PUBLISHED", "SOURCE_CLASSIFICATION_UNKNOWN"}
                else 422
            ),
            detail=exc.to_detail(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Get all schedules."""
    schedules = repository.get_all_schedules(db, skip, limit)
    if len(schedules) < limit:
        total = skip + len(schedules)
    else:
        total = repository.count_schedules(db)
    return ScheduleListResponse(schedules=schedules, total=total)


@router.post(
    "/run-now",
    response_model=CrawlJobSchema,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_immediate_scrape(
    request: ImmediateScrapeRequest,
    db: Session = Depends(get_db)
):
    """Run scraping immediately without creating a schedule."""
    effective_source_site = _require_supported_control_source_site(
        request.source_site
    )

    if request.category_ids:
        await _validate_effective_category_ids(
            effective_source_site, request.category_ids, db
        )

    try:
        dispatch_result = crawl_job_dispatch_service.dispatch_manual_crawl_job(
            db,
            source_site=effective_source_site,
            crawl_phase=request.crawl_phase,
            crawl_mode=request.crawl_mode,
            category_ids=list(request.category_ids or []),
            max_pages=request.max_pages,
            source_listing_crawl_job_id=request.source_listing_crawl_job_id,
            detail_limit=request.detail_limit,
            skip_existing=request.skip_existing,
            requested_by="api",
        )
    except HeadedCrawlWorkerUnavailableError as exc:
        raise _headed_worker_http_error(
            exc,
            source_site=effective_source_site,
        ) from exc
    except CrawlControlError as exc:
        raise _crawl_control_http_error(exc) from exc
    return dispatch_result.crawl_job


@router.get("/{schedule_id}", response_model=ScheduleSchema)
async def get_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db)
):
    """Get a schedule by ID."""
    schedule = repository.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.post("", response_model=ScheduleSchema)
async def create_schedule(
    data: ScheduleCreateSchema,
    db: Session = Depends(get_db)
):
    """Create a new schedule."""
    _require_supported_control_source_site(data.source_site)
    await _validate_effective_category_ids(data.source_site, data.category_ids, db)
    try:
        configuration = _compatibility_configuration(db, data)
        projection = AutomationService(db).create(
            configuration,
            actor=AUTOMATION_MUTATION_ACTOR,
            initial_state="active" if data.is_active else "paused",
        )
    except (CrawlControlError, SourceCatalogError) as exc:
        raise _crawl_control_http_error(exc) from exc
    schedule = repository.get_schedule_by_id(
        db,
        projection.snapshot.automation_id,
    )
    if schedule is None:
        raise RuntimeError("Created Automation projection is missing")
    return schedule


@router.put("/{schedule_id}", response_model=ScheduleSchema)
async def update_schedule(
    schedule_id: UUID,
    data: ScheduleUpdateSchema,
    db: Session = Depends(get_db)
):
    """Update a schedule."""
    current_schedule = repository.get_schedule_by_id(db, schedule_id)
    if not current_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    update_data = data.model_dump(exclude_unset=True)
    if (
        current_schedule.scope_contract is not None
        and "is_active" in update_data
        and len(update_data) > 1
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "AUTOMATION_COMPATIBILITY_MUTATION_SPLIT_REQUIRED",
                "message": (
                    "Versioned Automation configuration and lifecycle "
                    "mutations must be submitted separately"
                ),
            },
        )
    effective_source_site = update_data.get(
        "source_site",
        normalize_source_site(getattr(current_schedule, "source_site", "jobsdb")),
    )
    if effective_source_site is None:
        effective_source_site = normalize_source_site(getattr(current_schedule, "source_site", "jobsdb"))
    effective_source_site = _require_supported_control_source_site(
        effective_source_site
    )
    if "category_ids" in update_data:
        effective_category_ids = update_data["category_ids"]
    else:
        effective_category_ids = getattr(current_schedule, "category_ids", None)

    await _validate_effective_category_ids(
        effective_source_site, effective_category_ids, db
    )

    if current_schedule.scope_contract is not None:
        service = AutomationService(db)
        try:
            projection = service.get(schedule_id)
            configuration_updates = {
                key: value
                for key, value in update_data.items()
                if key != "is_active"
            }
            if configuration_updates:
                configuration = _updated_compatibility_configuration(
                    db,
                    current=projection.snapshot.configuration,
                    updates=configuration_updates,
                )
                projection = service.update_configuration(
                    schedule_id,
                    expected_revision=projection.snapshot.revision,
                    configuration=configuration,
                    actor=AUTOMATION_MUTATION_ACTOR,
                )
            if "is_active" in update_data:
                desired_active = bool(update_data["is_active"])
                lifecycle_state = projection.snapshot.lifecycle_state
                if desired_active and lifecycle_state != "active":
                    projection = service.resume(
                        schedule_id,
                        expected_revision=projection.snapshot.revision,
                        actor=AUTOMATION_MUTATION_ACTOR,
                    )
                elif not desired_active and lifecycle_state in {
                    "active",
                    "scope_review_required",
                }:
                    projection = service.pause(
                        schedule_id,
                        expected_revision=projection.snapshot.revision,
                        actor=AUTOMATION_MUTATION_ACTOR,
                    )
        except (CrawlControlError, SourceCatalogError) as exc:
            raise _crawl_control_http_error(exc) from exc
        schedule = repository.get_schedule_by_id(db, schedule_id)
        if schedule is None:
            raise RuntimeError("Updated Automation projection is missing")
        return schedule

    schedule = repository.update_schedule(db, schedule_id, update_data)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db)
):
    """Delete a schedule."""
    current_schedule = repository.get_schedule_by_id(db, schedule_id)
    if current_schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if current_schedule.scope_contract is not None:
        try:
            AutomationService(db).archive(
                schedule_id,
                expected_revision=current_schedule.revision,
                actor=AUTOMATION_MUTATION_ACTOR,
            )
        except CrawlControlError as exc:
            raise _crawl_control_http_error(exc) from exc
        return {"message": "Schedule deleted"}

    deleted = repository.delete_schedule(db, schedule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"message": "Schedule deleted"}


@router.post("/{schedule_id}/toggle", response_model=ScheduleToggleResponse)
async def toggle_schedule(
    schedule_id: UUID,
    db: Session = Depends(get_db)
):
    """Toggle schedule active status."""
    current_schedule = repository.get_schedule_by_id(db, schedule_id)
    if not current_schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if current_schedule.scope_contract is not None:
        service = AutomationService(db)
        try:
            if current_schedule.lifecycle_state == "active":
                service.pause(
                    schedule_id,
                    expected_revision=current_schedule.revision,
                    actor=AUTOMATION_MUTATION_ACTOR,
                )
            else:
                service.resume(
                    schedule_id,
                    expected_revision=current_schedule.revision,
                    actor=AUTOMATION_MUTATION_ACTOR,
                )
        except CrawlControlError as exc:
            raise _crawl_control_http_error(exc) from exc
        schedule = repository.get_schedule_by_id(db, schedule_id)
        if schedule is None:
            raise RuntimeError("Toggled Automation projection is missing")
        return ScheduleToggleResponse(
            id=schedule.id,
            is_active=schedule.is_active,
            next_run_at=schedule.next_run_at,
        )

    if (
        normalize_source_site(getattr(current_schedule, "source_site", "jobsdb")) == "ctgoodjobs"
        and not bool(getattr(current_schedule, "is_active", False))
    ):
        try:
            await _validate_effective_category_ids(
                getattr(current_schedule, "source_site", "jobsdb"),
                getattr(current_schedule, "category_ids", None),
                db,
            )
        except HTTPException as exc:
            if exc.status_code != 422:
                raise

            schedule = repository.update_schedule(db, schedule_id, {"is_active": False})
            return ScheduleToggleResponse(
                id=schedule.id,
                is_active=schedule.is_active,
                next_run_at=schedule.next_run_at,
            )

    schedule = repository.toggle_schedule(db, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    return ScheduleToggleResponse(
        id=schedule.id,
        is_active=schedule.is_active,
        next_run_at=schedule.next_run_at
    )


@router.post(
    "/{schedule_id}/run",
    response_model=CrawlJobSchema,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_schedule_now(
    schedule_id: UUID,
    request: Request,
    db: Session = Depends(get_db)
):
    """Run a schedule immediately."""
    schedule = repository.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    effective_source_site = _require_supported_control_source_site(
        getattr(schedule, "source_site", "jobsdb")
    )

    await _validate_effective_category_ids(
        effective_source_site,
        getattr(schedule, "category_ids", None),
        db,
    )

    try:
        dispatch_result = crawl_job_dispatch_service.dispatch_schedule_crawl_job(
            db,
            schedule=schedule,
            requested_by="api",
            trigger_type="manual",
        )
    except HeadedCrawlWorkerUnavailableError as exc:
        raise _headed_worker_http_error(
            exc,
            source_site=effective_source_site,
        ) from exc
    except CrawlControlError as exc:
        raise _crawl_control_http_error(exc) from exc
    request_id = getattr(getattr(request, "state", None), "request_id", None)
    resolved_request_payload = dict(getattr(dispatch_result.crawl_job, "request_payload", {}) or {})
    logger.info(
        _build_crawl_request_created_log_message(
            request_id=request_id,
            source_site=effective_source_site,
            crawl_job_id=str(dispatch_result.crawl_job.id),
            crawl_phase=resolve_crawl_phase(resolved_request_payload.get("crawl_phase")),
            crawl_mode=resolved_request_payload.get("crawl_mode") or "default",
            max_pages=resolved_request_payload.get("max_pages")
            if resolved_request_payload.get("max_pages") is not None
            else resolve_default_max_pages(effective_source_site),
            category_count=len(
                resolved_request_payload.get("category_ids")
                or getattr(schedule, "category_ids", None)
                or []
            ),
            source_listing_crawl_job_id=str(
                resolved_request_payload.get("source_listing_crawl_job_id") or ""
            ) or None,
            trigger="schedule",
            schedule_id=str(schedule.id),
        )
    )
    return dispatch_result.crawl_job


@router.get("/{schedule_id}/history", response_model=ExecutionListResponse)
async def get_schedule_history(
    schedule_id: UUID,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Get execution history for a schedule."""
    schedule = repository.get_schedule_by_id(db, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    executions = repository.get_executions(db, schedule_id, limit)
    if len(executions) < limit:
        total = len(executions)
    else:
        total = repository.count_executions(db, schedule_id)
    return ExecutionListResponse(executions=executions, total=total)
