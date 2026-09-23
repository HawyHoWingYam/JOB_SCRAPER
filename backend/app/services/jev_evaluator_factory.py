from __future__ import annotations

import hashlib

import httpx
from sqlalchemy.orm import Session

from app.ai.system_one import NativeSystemOneClient
from app.models.jev import JevRun
from app.services.jev_run_service import JevRunConfigurationError
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService


def build_jev_evaluator(db: Session, run: JevRun) -> NativeSystemOneClient:
    """Build a client from a run's frozen endpoint while revalidating its secret."""
    settings = JevRuntimeSettingsService(db).get_or_create()
    if not settings.api_key:
        raise JevRunConfigurationError("Jev API key is missing")
    fingerprint = hashlib.sha256(settings.api_key.encode("utf-8")).hexdigest()
    if fingerprint != run.settings_snapshot.get("api_key_fingerprint"):
        raise JevRunConfigurationError("Jev API key changed after this run was created")
    return NativeSystemOneClient(
        endpoint=str(run.settings_snapshot["endpoint"]),
        api_key=settings.api_key,
        http_client=httpx.AsyncClient(
            timeout=float(run.settings_snapshot["timeout_seconds"])
        ),
    )


__all__ = ["build_jev_evaluator"]
