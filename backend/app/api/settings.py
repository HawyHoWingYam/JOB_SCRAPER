from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm_client, get_llm_status, refresh_llm_status, reset_client
from app.database import get_db
from app.services.ai_runtime_settings_service import (
    AIRuntimeSettingsService,
    RuntimeSettingsValidationError,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class AISettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_provider: Optional[str] = None
    company_llm_provider: Optional[str] = None
    ai_enrichment_run_concurrency: Optional[int] = None
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
    started_at = time.perf_counter()
    try:
        client = service.build_draft_client(scope, draft_values)
        text = await client.generate("Reply with OK only.")
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        return {
            "ok": True,
            "scope": scope,
            "configured_provider": effective.llm_provider,
            "active_provider": effective.llm_provider,
            "model": getattr(client, "model", None),
            "latency_ms": latency_ms,
            "config_fingerprint": fingerprint,
            "response_preview": (text or "").strip()[:80],
        }
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
        db.commit()
        result["scope"] = request.scope
        return result
    except RuntimeSettingsValidationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=_format_validation_errors(exc)) from exc
    except Exception as exc:
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
            error_message=str(exc),
        )
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "scope": request.scope,
                "error_message": str(exc),
                "config_fingerprint": fingerprint,
            },
        ) from exc
