from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.database import SessionLocal
from app.models.app_runtime_settings import AppRuntimeSettings
from app.services.headed_crawl_runtime import get_headed_crawl_worker_status
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.services.source_catalog import build_source_catalog
from app.repositories.source_catalog_repository import SourceCatalogRepository


def _source_catalog_health() -> dict[str, dict[str, Any]]:
    db = SessionLocal()
    repository = SourceCatalogRepository()
    try:
        health: dict[str, dict[str, Any]] = {}
        for source_site in build_source_catalog():
            revision = repository.get_active_revision(db, source_site=source_site)
            health[source_site] = {
                "published": revision is not None,
                "revision_id": str(revision.id) if revision is not None else None,
                "sequence": revision.sequence if revision is not None else None,
                "fingerprint": (
                    revision.fingerprint[:12] if revision is not None else None
                ),
            }
        return health
    except SQLAlchemyError as exc:
        return {
            source_site: {
                "published": False,
                "revision_id": None,
                "sequence": None,
                "fingerprint": None,
                "reason": "catalog_health_unavailable",
                "error_type": type(exc).__name__,
            }
            for source_site in build_source_catalog()
        }
    finally:
        db.close()


def get_profile_runtime_metadata(scope: str) -> Any:
    db = SessionLocal()
    try:
        row = (
            db.query(AppRuntimeSettings)
            .filter(AppRuntimeSettings.id == 1)
            .one_or_none()
        )
        if row is None:
            return SimpleNamespace(
                scope=scope,
                configured_provider=None,
                config_fingerprint=None,
                last_test_status="untested",
                last_tested_at=None,
                last_test_error=None,
                last_test_provider=None,
                last_test_model=None,
                last_test_latency_ms=None,
                last_test_fingerprint=None,
                last_successful_test_fingerprint=None,
                requires_test=False,
                is_ready=False,
                is_degraded=False,
                degradation_reason="profile_not_configured",
                model=None,
                active_fingerprint=None,
                last_tested_fingerprint=None,
            )
        return AIRuntimeSettingsService(db).get_profile_runtime_metadata(scope, row=row)
    finally:
        db.close()


def _runtime_status(scope: str) -> dict[str, Any]:
    metadata = get_profile_runtime_metadata(scope)
    last_tested_at = getattr(metadata, "last_tested_at", None)
    if last_tested_at and hasattr(last_tested_at, "isoformat"):
        last_tested_at = last_tested_at.isoformat()

    return {
        "available": bool(metadata.is_ready),
        "is_ready": bool(metadata.is_ready),
        "is_degraded": bool(getattr(metadata, "is_degraded", False)),
        "requires_test": bool(metadata.requires_test),
        "provider": metadata.configured_provider,
        "model": getattr(metadata, "model", None)
        or getattr(metadata, "last_test_model", None),
        "active_fingerprint": getattr(metadata, "active_fingerprint", None)
        or getattr(metadata, "config_fingerprint", None),
        "last_tested_fingerprint": getattr(metadata, "last_tested_fingerprint", None)
        or getattr(metadata, "last_test_fingerprint", None),
        "reason": getattr(metadata, "degradation_reason", None)
        or getattr(metadata, "last_test_error", None),
        "last_tested_at": last_tested_at,
    }


def _sidecar_capability(url: str | None, *, configured_reason: str) -> dict[str, Any]:
    configured = bool((url or "").strip())
    return {
        "available": configured,
        "configured": configured,
        "url_configured": configured,
        "reason": None if configured else configured_reason,
    }


def _host_manual_action_helper_capability() -> dict[str, Any]:
    helper_url = f"http://{settings.manual_action_helper_host}:{settings.jobsdb_headed_manual_action_helper_port}"
    return {
        "available": None,
        "configured": True,
        "reachable": None,
        "reason": "health_check_required",
        "helper_url": helper_url,
        "health_url": f"{helper_url}/health",
        "manual_start_workdir": "backend",
        "manual_start_command": "python -m app.workers.run_manual_action_helper",
        "open_browser_supported": True,
        "reuse_open_browser_supported": True,
        "close_profile_windows_supported": True,
    }


def _source_capabilities() -> dict[str, dict[str, Any]]:
    catalog_health = _source_catalog_health()
    capabilities = {
        source_site: {
            "available": True,
            "listing_supported": True,
            "detail_supported": True,
            "headless_supported": "headless" in entry["supported_crawl_modes"],
            "headed_supported": "headed" in entry["supported_crawl_modes"],
            "manual_action_supported": True,
            "label": entry["label"],
            "category_id_type": entry["category_id_type"],
            "supported_crawl_modes": entry["supported_crawl_modes"],
            "default_crawl_mode": entry["default_crawl_mode"],
            "default_max_pages": entry["default_max_pages"],
            "source_catalog": catalog_health[source_site],
        }
        for source_site, entry in build_source_catalog().items()
    }
    ctgoodjobs = capabilities.get("ctgoodjobs")
    if ctgoodjobs is not None:
        ctgoodjobs["proxy_supported"] = True
        ctgoodjobs["proxy_modes_supported"] = list(ctgoodjobs["supported_crawl_modes"])
        ctgoodjobs["proxy_enabled"] = bool(settings.ctgoodjobs_proxy_enabled)
    return capabilities


def get_scheduler_runtime_status() -> dict:
    from app.services.scheduler_runtime import get_scheduler_runtime_status as _get_status

    return _get_status()


def build_runtime_capabilities() -> dict[str, Any]:
    retrieval = _sidecar_capability(
        settings.retrieval_api_url,
        configured_reason="retrieval_api_url_not_configured",
    )
    recommendations = _sidecar_capability(
        settings.recommendation_api_url,
        configured_reason="recommendation_api_url_not_configured",
    )
    scheduler = get_scheduler_runtime_status()

    return {
        "search": {
            "lexical": {"available": True, "reason": None},
            "semantic": retrieval,
            "hybrid": dict(retrieval),
            "export": {
                "lexical": {"available": True, "reason": None},
                "semantic": dict(retrieval),
                "hybrid": dict(retrieval),
            },
        },
        "recommendations": {
            "similar_jobs": recommendations,
        },
        "ai": {
            "jobs": _runtime_status("jobs"),
            "companies": _runtime_status("companies"),
        },
        "scheduler": {
            "available": bool(scheduler.get("enabled", True)),
            **scheduler,
        },
        "crawl_workers": {
            "headed": get_headed_crawl_worker_status(),
        },
        "manual_actions": _host_manual_action_helper_capability(),
        "sources": _source_capabilities(),
    }
