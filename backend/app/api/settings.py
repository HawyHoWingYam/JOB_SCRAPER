from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm_status, refresh_llm_status, reset_client
from app.database import get_db
from app.services.ai_runtime_settings_service import (
    AIRuntimeSettingsService,
    RuntimeSettingsValidationError,
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class AISettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_provider: Optional[str] = None
    ai_enrichment_run_concurrency: Optional[int] = None
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


def _build_ai_settings_response(service: AIRuntimeSettingsService) -> dict:
    effective = service.get_effective_settings()
    return {
        "persisted_config": service.serialize_persisted_config(),
        "effective_config": service.serialize_effective_config(effective),
        "runtime_status": get_llm_status(),
    }


@router.get("/ai")
async def get_ai_settings(db: Session = Depends(get_db)):
    service = AIRuntimeSettingsService(db)
    service.get_or_create()
    db.commit()
    refresh_llm_status()
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
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", *error["loc"]],
                    "msg": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors
            ],
        ) from exc

    refresh_llm_status()
    return _build_ai_settings_response(service)
