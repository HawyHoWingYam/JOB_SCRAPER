from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.api import settings as settings_api
from app.api.settings import AISettingsUpdateRequest
from app.models.app_runtime_settings import AppRuntimeSettings
from app.models.jev import JevRuntimeSettings
from app.services.jev_runtime_settings_service import (
    JevRuntimeSettingsService,
    JevSettingsValidationError,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    AppRuntimeSettings.__table__.create(engine)
    JevRuntimeSettings.__table__.create(engine)
    return engine, sessionmaker(bind=engine)()


def test_jev_settings_defaults_and_secret_masking() -> None:
    engine, db = _session()
    try:
        payload = settings_api._build_ai_settings_response(
            settings_api.AIRuntimeSettingsService(db),
            settings_api.JevRuntimeSettingsService(db),
        )

        assert payload["jev"] == {
            "enabled": False,
            "endpoint": "https://www.rsiai.net/v1/systemone",
            "model": "jev-latest",
            "has_api_key": False,
            "api_key_preview": None,
            "sample_limit": 100,
            "question_batch_limit": 10,
            "concurrency": 2,
            "retry_limit": 0,
            "timeout_seconds": 30,
            "evidence_threshold": "0.800",
            "recommendation_threshold": "0.800",
            "duplicate_enabled": False,
            "duplicate_candidate_limit": 3,
            "duplicate_corpus_limit": 200,
            "crawl_quality_enabled": False,
            "crawl_quality_batch_limit": 20,
            "search_rerank_enabled": False,
            "search_rerank_candidate_limit": 20,
            "incident_triage_enabled": False,
            "incident_triage_event_limit": 200,
            "maintenance_enabled": False,
            "maintenance_model": "jev-latest",
            "maintenance_interval_days": 30,
            "maintenance_min_candidates": 50,
            "maintenance_batch_size": 100,
            "maintenance_threshold": "0.900",
            "maintenance_last_checked_at": None,
            "maintenance_last_started_at": None,
        }
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_ai_settings_put_updates_jev_without_starting_external_work(
    monkeypatch,
) -> None:
    engine, db = _session()
    external_calls: list[str] = []
    monkeypatch.setattr(
        settings_api,
        "refresh_llm_status",
        lambda *_args, **_kwargs: external_calls.append("status") or {},
    )
    try:
        response = await settings_api.update_ai_settings(
            AISettingsUpdateRequest(
                jev={
                    "enabled": True,
                    "api_key": "jev-secret-value",
                    "sample_limit": 25,
                    "evidence_threshold": "0.925",
                    "maintenance_enabled": True,
                    "maintenance_model": "openai/gpt-5.4",
                    "maintenance_interval_days": 45,
                    "maintenance_min_candidates": 75,
                    "maintenance_batch_size": 120,
                    "maintenance_threshold": "0.950",
                }
            ),
            db,
        )
        assert external_calls == ["status", "status"]
        assert response["jev"]["enabled"] is True
        assert response["jev"]["sample_limit"] == 25
        assert response["jev"]["evidence_threshold"] == "0.925"
        assert response["jev"]["maintenance_enabled"] is True
        assert response["jev"]["maintenance_model"] == "openai/gpt-5.4"
        assert response["jev"]["maintenance_interval_days"] == 45
        assert response["jev"]["maintenance_min_candidates"] == 75
        assert response["jev"]["maintenance_batch_size"] == 120
        assert response["jev"]["maintenance_threshold"] == "0.950"
        assert response["jev"]["has_api_key"] is True
        assert response["jev"]["api_key_preview"] == "jev-...alue"
        assert "api_key" not in response["jev"]

        second = await settings_api.update_ai_settings(
            AISettingsUpdateRequest(jev={"api_key": "", "sample_limit": 30}),
            db,
        )
        assert second["jev"]["sample_limit"] == 30
        assert second["jev"]["has_api_key"] is True
        assert second["jev"]["api_key_preview"] == "jev-...alue"
    finally:
        db.close()
        engine.dispose()


def test_jev_settings_reject_public_http_and_invalid_operational_bounds() -> None:
    engine, db = _session()
    try:
        service = JevRuntimeSettingsService(db)
        service.get_or_create()

        with pytest.raises(JevSettingsValidationError) as endpoint_error:
            service.update({"endpoint": "http://example.com/v1/systemone"})
        assert endpoint_error.value.errors[0]["loc"] == ["endpoint"]

        with pytest.raises(JevSettingsValidationError) as concurrency_error:
            service.update({"concurrency": 0})
        assert concurrency_error.value.errors == [
            {
                "loc": ["concurrency"],
                "msg": "Must be between 1 and 50",
                "type": "value_error",
            }
        ]
    finally:
        db.close()
        engine.dispose()
