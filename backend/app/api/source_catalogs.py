from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.schemas.source_catalog import CatalogActorRequest, CatalogPublishRequest
from app.scraper.log_events import build_scrape_log_event
from app.source_catalog.errors import SourceCatalogError
from app.source_catalog.validation import CatalogValidationCoordinator
from app.services.source_catalog_service import (
    SourceCatalogService,
    build_production_source_catalog_adapters,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/source-catalogs", tags=["source-catalogs"])


def _service(db: Session) -> SourceCatalogService:
    # Production impact evaluation is intentionally absent until versioned
    # Automation/Crawl Scope integration supplies it.
    return SourceCatalogService(db)


def _http_error(exc: SourceCatalogError) -> HTTPException:
    status = {
        "CATALOG_NOT_PUBLISHED": 404,
        "SOURCE_CLASSIFICATION_UNKNOWN": 404,
        "SOURCE_CLASSIFICATION_NOT_EXECUTABLE": 422,
        "CATALOG_CANDIDATE_STALE": 409,
        "CATALOG_VALIDATION_REQUIRED": 409,
        "CATALOG_VALIDATION_FAILED": 409,
        "CATALOG_MANUAL_ACTION_REQUIRED": 409,
        "CATALOG_IMPACT_STALE": 409,
    }.get(exc.code, 422)
    return HTTPException(status_code=status, detail=exc.to_detail())


def _candidate_not_found_error() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "CATALOG_CANDIDATE_STALE",
            "message": "Candidate not found",
        },
    )


def _revision_payload(revision) -> dict[str, Any]:
    return {
        "id": str(revision.id),
        "source_site": revision.source_site,
        "sequence": revision.sequence,
        "fingerprint": revision.fingerprint,
        "predecessor_revision_id": (
            str(revision.predecessor_revision_id)
            if revision.predecessor_revision_id
            else None
        ),
        "published_by": revision.published_by,
        "published_at": revision.published_at,
    }


def _candidate_payload(candidate) -> dict[str, Any]:
    return {
        "id": str(candidate.id),
        "source_site": candidate.source_site,
        "base_revision_id": (
            str(candidate.base_revision_id) if candidate.base_revision_id else None
        ),
        "fingerprint": candidate.fingerprint,
        "state": candidate.state,
        "normalized_payload": candidate.normalized_payload,
        "diff": candidate.diff,
        "validation_summary": candidate.validation_summary,
        "provenance": candidate.provenance,
        "created_at": candidate.created_at,
        "validated_at": candidate.validated_at,
        "published_at": candidate.published_at,
    }


def _run_payload(run) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "candidate_id": str(run.candidate_id),
        "validation_kind": run.validation_kind,
        "classification_id": run.classification_id,
        "target_hash_prefix": run.expected_target_hash[:12],
        "status": run.status,
        "attempt": run.attempt,
        "evidence": run.evidence,
        "error": run.error,
        "manual_action": run.manual_action,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }


@router.get("")
def list_source_catalogs(db: Session = Depends(get_db)):
    repository = SourceCatalogRepository()
    summaries = []
    for source_site in ("jobsdb", "ctgoodjobs", "offertoday"):
        active = repository.get_active_revision(db, source_site=source_site)
        candidates = repository.list_candidates(db, source_site=source_site, limit=1)
        summaries.append(
            {
                "source_site": source_site,
                "published_revision": _revision_payload(active) if active else None,
                "latest_candidate": (
                    {
                        "id": str(candidates[0].id),
                        "fingerprint": candidates[0].fingerprint,
                        "state": candidates[0].state,
                        "created_at": candidates[0].created_at,
                    }
                    if candidates
                    else None
                ),
            }
        )
    return {"sources": summaries}


@router.get("/{source_site}/published")
def get_published_source_catalog(source_site: str, db: Session = Depends(get_db)):
    try:
        published = _service(db).get_published(source_site)
    except SourceCatalogError as exc:
        raise _http_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "revision": _revision_payload(published.revision),
        "catalog": published.catalog.normalized_payload(),
    }


@router.post("/{source_site}/candidates", status_code=201)
def discover_source_catalog_candidate(
    source_site: str,
    db: Session = Depends(get_db),
):
    try:
        candidate, created = _service(db).discover(source_site)
    except (SourceCatalogError, ValueError) as exc:
        if isinstance(exc, SourceCatalogError):
            raise _http_error(exc) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    logger.info(
        build_scrape_log_event(
            "SOURCE_CATALOG_CANDIDATE_DISCOVERED",
            source=source_site,
            candidate_id=str(candidate.id),
            fingerprint=candidate.fingerprint[:12],
            node_count=len((candidate.normalized_payload or {}).get("nodes") or []),
            reused=not created,
        )
    )
    return {"created": created, "candidate": _candidate_payload(candidate)}


@router.get("/{source_site}/candidates/{candidate_id}")
def get_source_catalog_candidate(
    source_site: str,
    candidate_id: str,
    db: Session = Depends(get_db),
):
    candidate = SourceCatalogRepository().get_candidate(db, candidate_id)
    if candidate is None or candidate.source_site != source_site:
        raise _candidate_not_found_error()
    return _candidate_payload(candidate)


@router.post("/{source_site}/candidates/{candidate_id}/validation-runs", status_code=202)
def start_source_catalog_validation(
    source_site: str,
    candidate_id: str,
    db: Session = Depends(get_db),
):
    repository = SourceCatalogRepository()
    candidate = repository.get_candidate(db, candidate_id)
    if candidate is None or candidate.source_site != source_site:
        raise _candidate_not_found_error()
    try:
        runs = CatalogValidationCoordinator(
            db,
            repository=repository,
            adapters=build_production_source_catalog_adapters(),
        ).start(candidate.id)
    except (SourceCatalogError, ValueError) as exc:
        if isinstance(exc, SourceCatalogError):
            raise _http_error(exc) from exc
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"candidate_id": str(candidate.id), "runs": [_run_payload(run) for run in runs]}


@router.get("/{source_site}/candidates/{candidate_id}/validation-runs")
def list_source_catalog_validation_runs(
    source_site: str,
    candidate_id: str,
    db: Session = Depends(get_db),
):
    repository = SourceCatalogRepository()
    candidate = repository.get_candidate(db, candidate_id)
    if candidate is None or candidate.source_site != source_site:
        raise _candidate_not_found_error()
    runs = repository.list_validation_runs(db, candidate_id=candidate.id)
    return {"candidate_id": str(candidate.id), "runs": [_run_payload(run) for run in runs]}


@router.post("/{source_site}/candidates/{candidate_id}/publication-reviews")
def review_source_catalog_publication(
    source_site: str,
    candidate_id: str,
    request: CatalogActorRequest,
    db: Session = Depends(get_db),
):
    try:
        grant = _service(db).review_publication(
            candidate_id,
            actor=request.actor,
            expected_source_site=source_site,
        )
    except SourceCatalogError as exc:
        raise _http_error(exc) from exc
    return {
        "review_id": str(grant.review_id),
        "review_token": grant.review_token,
        "expires_at": grant.expires_at,
        "impact": grant.impact,
    }


@router.post("/{source_site}/candidates/{candidate_id}/publish")
def publish_source_catalog_candidate(
    source_site: str,
    candidate_id: str,
    request: CatalogPublishRequest,
    db: Session = Depends(get_db),
):
    try:
        revision = _service(db).publish(
            candidate_id,
            review_token=request.review_token,
            actor=request.actor,
            expected_source_site=source_site,
        )
    except SourceCatalogError as exc:
        raise _http_error(exc) from exc
    return {"revision": _revision_payload(revision)}


@router.get("/{source_site}/revisions")
def list_source_catalog_revisions(
    source_site: str,
    db: Session = Depends(get_db),
):
    revisions = SourceCatalogRepository().list_revisions(db, source_site=source_site)
    return {"source_site": source_site, "revisions": [_revision_payload(row) for row in revisions]}


@router.post("/{source_site}/revisions/{revision_id}/rollback-reviews")
def review_source_catalog_rollback(
    source_site: str,
    revision_id: str,
    request: CatalogActorRequest,
    db: Session = Depends(get_db),
):
    try:
        grant = _service(db).review_rollback(
            revision_id,
            actor=request.actor,
            expected_source_site=source_site,
        )
    except SourceCatalogError as exc:
        raise _http_error(exc) from exc
    return {
        "review_id": str(grant.review_id),
        "review_token": grant.review_token,
        "expires_at": grant.expires_at,
        "impact": grant.impact,
    }


@router.post("/{source_site}/revisions/{revision_id}/rollback")
def rollback_source_catalog_revision(
    source_site: str,
    revision_id: str,
    request: CatalogPublishRequest,
    db: Session = Depends(get_db),
):
    try:
        revision = _service(db).rollback(
            revision_id,
            review_token=request.review_token,
            actor=request.actor,
            expected_source_site=source_site,
        )
    except SourceCatalogError as exc:
        raise _http_error(exc) from exc
    return {"revision": _revision_payload(revision)}
