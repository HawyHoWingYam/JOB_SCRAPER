from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.config import settings
from app.database import SessionLocal
from app.models.app_runtime_settings import AppRuntimeSettings
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService


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


def _source_capabilities() -> dict[str, dict[str, Any]]:
    return {
        "jobsdb": {
            "available": True,
            "listing_supported": True,
            "detail_supported": True,
            "headless_supported": True,
            "headed_supported": True,
            "manual_action_supported": True,
            "default_crawl_mode": "headed",
            "category_id_type": "integer",
        },
        "ctgoodjobs": {
            "available": True,
            "listing_supported": True,
            "detail_supported": True,
            "headless_supported": True,
            "headed_supported": True,
            "manual_action_supported": True,
            "default_crawl_mode": "headed",
            "category_id_type": "string",
        },
    }


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
        "sources": _source_capabilities(),
    }
