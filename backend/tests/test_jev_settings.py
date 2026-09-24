from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

from app.api import settings as settings_api
from app.ai.system_one import SystemOneResult, SystemOneUsage
from app.api.settings import AISettingsUpdateRequest, JevSettingsTestRequest
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
            "endpoint": "https://openrouter.ai/api/alpha/decisions",
            "model": "~typesafe/jev-latest",
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
            "maintenance_model": "~typesafe/jev-latest",
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


def test_jev_settings_migrates_only_the_managed_legacy_openrouter_defaults() -> None:
    engine, db = _session()
    try:
        db.add(
            JevRuntimeSettings(
                id=1,
                enabled=True,
                endpoint="https://openrouter.ai/api/alpha/decisions",
                model="jev-latest",
                sample_limit=100,
                question_batch_limit=10,
                concurrency=2,
                retry_limit=0,
                timeout_seconds=30,
                evidence_threshold_millis=800,
                recommendation_threshold_millis=800,
                duplicate_enabled=False,
                duplicate_candidate_limit=3,
                duplicate_corpus_limit=200,
                crawl_quality_enabled=False,
                crawl_quality_batch_limit=20,
                search_rerank_enabled=False,
                search_rerank_candidate_limit=20,
                incident_triage_enabled=False,
                incident_triage_event_limit=200,
                maintenance_enabled=False,
                maintenance_model="jev-latest",
                maintenance_interval_days=30,
                maintenance_min_candidates=50,
                maintenance_batch_size=100,
                maintenance_threshold_millis=900,
            )
        )
        db.commit()

        migrated = JevRuntimeSettingsService(db).get_or_create()

        assert migrated.endpoint == "https://openrouter.ai/api/alpha/decisions"
        assert migrated.model == "~typesafe/jev-latest"
        assert migrated.maintenance_model == "~typesafe/jev-latest"
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


@pytest.mark.asyncio
async def test_jev_connection_test_uses_draft_without_saving_or_creating_history(
    monkeypatch,
) -> None:
    engine, db = _session()
    observed: dict[str, object] = {}

    class FakeClient:
        def __init__(self, *, endpoint, api_key, http_client):
            observed.update(endpoint=endpoint, api_key=api_key, http_client=http_client)

        async def evaluate(self, request):
            observed["request"] = request
            return SystemOneResult(
                status="answered",
                request_id="jev-request-1",
                model="draft-model",
                provider="fake-jev",
                usage=SystemOneUsage(input_tokens=9, output_tokens=3, cost=0.00005),
                latency_ms=17,
            )

        async def aclose(self):
            observed["closed"] = True
            await observed["http_client"].aclose()

    monkeypatch.setattr(settings_api, "NativeSystemOneClient", FakeClient)
    service = JevRuntimeSettingsService(db)
    service.update({"api_key": "saved-secret", "model": "saved-model"})
    db.commit()

    try:
        response = await settings_api.test_jev_settings_connection(
            JevSettingsTestRequest(
                endpoint="https://draft.example/v1/systemone",
                model="draft-model",
                api_key="",
                timeout_seconds=12,
            ),
            db,
        )

        assert response == {
            "ok": True,
            "status": "answered",
            "model": "draft-model",
            "provider": "fake-jev",
            "request_id": "jev-request-1",
            "latency_ms": 17,
            "usage": {"input_tokens": 9, "output_tokens": 3, "cost": 0.00005},
        }
        assert observed["endpoint"] == "https://draft.example/v1/systemone"
        assert observed["api_key"] == "saved-secret"
        assert observed["request"].model == "draft-model"
        assert observed["closed"] is True
        db.expire_all()
        saved = service.get_or_create()
        assert saved.endpoint == "https://openrouter.ai/api/alpha/decisions"
        assert saved.model == "saved-model"
        assert saved.api_key == "saved-secret"
    finally:
        db.close()
        engine.dispose()


@pytest.mark.asyncio
async def test_jev_connection_test_rejects_missing_key_without_provider_call(
    monkeypatch,
) -> None:
    engine, db = _session()
    monkeypatch.setattr(
        settings_api,
        "NativeSystemOneClient",
        lambda **_kwargs: pytest.fail("provider client must not be created"),
    )
    try:
        with pytest.raises(settings_api.HTTPException) as exc_info:
            await settings_api.test_jev_settings_connection(
                JevSettingsTestRequest(), db
            )
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail == [
            {
                "loc": ["body", "api_key"],
                "msg": "API key is required",
                "type": "value_error",
            }
        ]
    finally:
        db.close()
        engine.dispose()
