from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.ai.llm_client import (
    LLMProfileNotReadyError,
    refresh_llm_status,
    reset_client,
    safe_llm_error_message,
)
from app.crawl_cancellation import ACTIVE_MANUAL_DETAIL_STATUSES
from app.database import get_db
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.services.ai_provider_catalog import build_ai_provider_catalog
from app.services.ai_runtime_settings_service import (
    AIRuntimeSettingsService,
    ProfileRuntimeNotReadyError,
    RuntimeSettingsValidationError,
)
from app.schemas.scraper_pacing import (
    ScraperPacingSettingsListResponse,
    ScraperPacingSettingsResponse,
    ScraperPacingSettingsUpdate,
)
from app.services.scraper_pacing_settings_service import (
    ScraperPacingSettingsService,
    serialize_scraper_pacing_row,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])
MAX_AI_TEST_ERROR_MESSAGE_LENGTH = 512


@router.get("/scraper-pacing", response_model=ScraperPacingSettingsListResponse)
def get_scraper_pacing_settings(db: Session = Depends(get_db)):
    service = ScraperPacingSettingsService(db)
    rows = service.list_settings()
    active_detail_task_count = CrawlJobRepository().count_active_manual_detail_jobs(
        db,
        statuses=ACTIVE_MANUAL_DETAIL_STATUSES,
    )
    db.commit()
    return {
        "items": [serialize_scraper_pacing_row(row) for row in rows],
        "active_detail_task_count": active_detail_task_count,
    }


@router.put(
    "/scraper-pacing/{source_site}",
    response_model=ScraperPacingSettingsResponse,
)
def update_scraper_pacing_settings(
    source_site: str,
    request: ScraperPacingSettingsUpdate,
    db: Session = Depends(get_db),
):
    service = ScraperPacingSettingsService(db)
    try:
        row = service.update(source_site, request.model_dump())
        db.commit()
        db.refresh(row)
        return serialize_scraper_pacing_row(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/scraper-pacing/{source_site}/reset",
    response_model=ScraperPacingSettingsResponse,
)
def reset_scraper_pacing_settings(
    source_site: str,
    db: Session = Depends(get_db),
):
    service = ScraperPacingSettingsService(db)
    try:
        row = service.reset(source_site)
        db.commit()
        db.refresh(row)
        return serialize_scraper_pacing_row(row)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AISettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_provider: Optional[str] = None
    company_llm_provider: Optional[str] = None
    ai_enrichment_run_concurrency: Optional[int] = None
    company_ai_enrichment_run_concurrency: Optional[int] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    company_anthropic_api_key: Optional[str] = None
    company_anthropic_model: Optional[str] = None
    company_anthropic_base_url: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    company_gemini_api_key: Optional[str] = None
    company_gemini_model: Optional[str] = None
    custom_api_key: Optional[str] = None
    custom_model: Optional[str] = None
    custom_base_url: Optional[str] = None
    custom_api_format: Optional[str] = None
    company_custom_api_key: Optional[str] = None
    company_custom_model: Optional[str] = None
    company_custom_base_url: Optional[str] = None
    company_custom_api_format: Optional[str] = None
    zhipu_api_key: Optional[str] = None
    company_zhipu_api_key: Optional[str] = None


class DraftProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_provider: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_model: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    custom_api_key: Optional[str] = None
    custom_model: Optional[str] = None
    custom_base_url: Optional[str] = None
    custom_api_format: Optional[str] = None
    zhipu_api_key: Optional[str] = None


class AISettingsTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    profile: DraftProfilePayload


def _format_validation_errors(exc: RuntimeSettingsValidationError) -> list[dict]:
    return [
        {
            "loc": ["body", *error["loc"]],
            "msg": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors
    ]


def _build_ai_settings_response(service: AIRuntimeSettingsService) -> dict:
    job_status = refresh_llm_status()
    company_status = refresh_llm_status("companies")
    return {
        "persisted_config": service.serialize_persisted_config(),
        "effective_config": service.serialize_effective_config(),
        "runtime_status": job_status,
        "company_runtime_status": company_status,
        "provider_catalog": build_ai_provider_catalog(),
    }


def _safe_ai_test_error_message(exc: Exception) -> str:
    """Keep profile-readiness diagnostics while bounding provider failures."""
    if isinstance(exc, (ProfileRuntimeNotReadyError, LLMProfileNotReadyError)):
        message = str(exc).strip()
        if len(message) <= MAX_AI_TEST_ERROR_MESSAGE_LENGTH:
            return message
        return f"{message[:MAX_AI_TEST_ERROR_MESSAGE_LENGTH - 3]}..."
    return safe_llm_error_message(exc)


async def _run_model_probe(client, scope: str) -> dict:
    started_at = time.perf_counter()
    if scope == "jobs":
        parsed = await client.generate_json(
            "Return a JSON object with exactly these values: "
            'status="ok", items=["alpha", "beta", "gamma"], count=3.'
        )
        if (
            parsed.get("status") != "ok"
            or parsed.get("items") != ["alpha", "beta", "gamma"]
            or parsed.get("count") != 3
        ):
            raise ValueError("Representative JSON probe returned unexpected values")
        response_preview = '{"status":"ok","items":[...],"count":3}'
    else:
        text = await client.generate("Reply with OK only.")
        response_preview = "OK" if (text or "").strip() else "<empty>"
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "response_preview": response_preview,
    }


async def _run_web_search_probe(client) -> dict:
    if not bool(getattr(client, "supports_web_search", lambda: False)()):
        return {
            "attempted": False,
            "supported": False,
            "ok": False,
            "latency_ms": None,
            "error_message": "This provider does not support web search.",
        }

    started_at = time.perf_counter()
    try:
        probe_result = await client.probe_web_search(
            "Search the web for the official OpenAI home page and reply with OK only."
        )
    except Exception as exc:
        return {
            "attempted": True,
            "supported": True,
            "ok": False,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
            "error_message": safe_llm_error_message(exc),
        }

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    return {
        "attempted": True,
        "supported": True,
        "ok": True,
        "latency_ms": latency_ms,
        "error_message": None,
        "output_types": probe_result.get("output_types", []),
    }


async def probe_profile_configuration(
    scope: str,
    profile_payload: dict,
    service: AIRuntimeSettingsService,
) -> dict:
    draft_values = service.draft_profile_values_from_payload(scope, profile_payload)
    service._validate_profile(draft_values, scope)
    effective = service._build_effective_settings(draft_values, scope)
    service._validate_effective_settings(scope, effective)
    fingerprint = service.build_config_fingerprint(scope, draft_values)
    try:
        client = service.build_draft_client(scope, draft_values)
        model_check = await _run_model_probe(client, scope)
        result = {
            "ok": True,
            "scope": scope,
            "configured_provider": effective.llm_provider,
            "active_provider": effective.llm_provider,
            "model": getattr(client, "model", None),
            "latency_ms": model_check["latency_ms"],
            "config_fingerprint": fingerprint,
            "response_preview": model_check["response_preview"],
            "model_check": model_check,
        }
        if scope == "companies":
            result["web_search_check"] = await _run_web_search_probe(client)
        return result
    finally:
        reset_client(scope)


@router.get("/ai")
async def get_ai_settings(db: Session = Depends(get_db)):
    service = AIRuntimeSettingsService(db)
    service.get_or_create()
    db.commit()
    return _build_ai_settings_response(service)


@router.put("/ai")
async def update_ai_settings(
    request: AISettingsUpdateRequest,
    db: Session = Depends(get_db),
):
    service = AIRuntimeSettingsService(db)
    try:
        service.update_settings(request.model_dump(exclude_unset=True))
        db.commit()
    except RuntimeSettingsValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=_format_validation_errors(exc)) from exc

    return _build_ai_settings_response(service)


@router.post("/ai/test")
async def test_ai_settings_profile(
    request: AISettingsTestRequest,
    db: Session = Depends(get_db),
):
    service = AIRuntimeSettingsService(db)

    try:
        result = await probe_profile_configuration(
            request.scope,
            request.profile.model_dump(exclude_unset=True),
            service,
        )
        service.record_profile_test_result(
            request.scope,
            ok=True,
            configured_provider=result.get("configured_provider"),
            model=result.get("model"),
            latency_ms=result.get("latency_ms"),
            config_fingerprint=result.get("config_fingerprint"),
            error_message=None,
        )
        if request.scope == "companies":
            web_search_check = result.get("web_search_check") or {}
            if web_search_check.get("ok"):
                web_search_status = "passed"
            elif web_search_check.get("attempted"):
                web_search_status = "failed"
            else:
                web_search_status = "unsupported"
            service.record_company_web_search_test_result(
                status=web_search_status,
                latency_ms=web_search_check.get("latency_ms"),
                config_fingerprint=result.get("config_fingerprint"),
                error_message=web_search_check.get("error_message"),
            )
        db.commit()
        result["scope"] = request.scope
        return result
    except RuntimeSettingsValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=_format_validation_errors(exc)) from exc
    except Exception as exc:
        safe_error = _safe_ai_test_error_message(exc)
        fingerprint = None
        try:
            draft_values = service.draft_profile_values_from_payload(
                request.scope,
                request.profile.model_dump(exclude_unset=True),
            )
            fingerprint = service.build_config_fingerprint(request.scope, draft_values)
        except Exception:
            fingerprint = None

        service.record_profile_test_result(
            request.scope,
            ok=False,
            configured_provider=request.profile.llm_provider,
            model=(
                request.profile.custom_model
                or request.profile.gemini_model
                or request.profile.anthropic_model
            ),
            latency_ms=None,
            config_fingerprint=fingerprint,
            error_message=safe_error,
        )
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "scope": request.scope,
                "error_message": safe_error,
                "config_fingerprint": fingerprint,
            },
        ) from exc
