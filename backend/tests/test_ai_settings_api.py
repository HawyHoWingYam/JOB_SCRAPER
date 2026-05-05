import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.database import Base, get_db
from app.api import router as api_router
from app.api.ai import router as ai_router
from app.api.companies import router as companies_router
import app.ai.llm_client as llm_client_module
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _import_runtime_settings_model():
    try:
        from app.models.app_runtime_settings import AppRuntimeSettings
    except ModuleNotFoundError as exc:
        pytest.fail(f"AI runtime settings model is missing: {exc}")
    return AppRuntimeSettings


def _build_test_client(monkeypatch):
    AppRuntimeSettings = _import_runtime_settings_model()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[AppRuntimeSettings.__table__],
    )
    Session = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(ai_router)
    app.include_router(companies_router, prefix="/api/v1")

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        llm_client_module,
        "get_effective_runtime_settings",
        lambda scope="jobs": AIRuntimeSettingsService(Session()).get_effective_settings(scope),
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return client, Session


class FakeProbeClient:
    def __init__(self, response_text="OK"):
        self.response_text = response_text
        self.model = "gpt-5.2"

    async def generate(self, *_args, **_kwargs):
        return self.response_text


@pytest.mark.asyncio
async def test_get_ai_settings_returns_ui_safe_shapes_and_runtime_status(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, Session = _build_test_client(monkeypatch)
    try:
        response = await client.get("/api/v1/settings/ai")

        assert response.status_code == 200
        payload = response.json()
        assert payload["persisted_config"]["llm_provider"] is None
        assert payload["effective_config"]["llm_provider"] is None
        assert payload["runtime_status"]["configured_provider"] is None
        assert payload["runtime_status"]["active_provider"] in {"", None}
        assert payload["persisted_config"]["anthropic"]["api_key_preview"] is None

        AppRuntimeSettings = _import_runtime_settings_model()
        db = Session()
        try:
            row = db.query(AppRuntimeSettings).one_or_none()
            assert row is not None
            assert row.id == 1
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_ai_settings_refreshes_stale_degraded_runtime_status(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, Session = _build_test_client(monkeypatch)
    try:
        monkeypatch.setattr(
            llm_client_module,
            "get_effective_runtime_settings",
            lambda: (_ for _ in ()).throw(RuntimeError("settings table missing")),
        )
        with pytest.raises(RuntimeError):
            llm_client_module.get_llm_client()
        degraded_status = llm_client_module.refresh_llm_status()

        assert degraded_status["is_degraded"] is True
        assert degraded_status["configured_provider"] == "unknown"

        monkeypatch.setattr(
            llm_client_module,
            "get_effective_runtime_settings",
            lambda: AIRuntimeSettingsService(Session()).get_effective_settings(),
        )

        response = await client.get("/api/v1/settings/ai")

        assert response.status_code == 200
        payload = response.json()
        assert payload["runtime_status"]["configured_provider"] is None
        assert payload["runtime_status"]["active_provider"] in {"", None}
        assert payload["runtime_status"]["is_degraded"] is True
        assert payload["runtime_status"]["degradation_reason"] == "Profile is not configured"
    finally:
        await client.aclose()
        llm_client_module.reset_client()


@pytest.mark.asyncio
async def test_put_ai_settings_persists_values_preserves_blank_secret_and_masks_response(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, Session = _build_test_client(monkeypatch)
    try:
        first = await client.put(
            "/api/v1/settings/ai",
            json={
                "llm_provider": "gemini",
                "ai_enrichment_run_concurrency": 6,
                "gemini_api_key": "gem-secret-123456",
                "gemini_model": "gemini-live",
            },
        )
        second = await client.put(
            "/api/v1/settings/ai",
            json={
                "llm_provider": "gemini",
                "ai_enrichment_run_concurrency": 8,
                "gemini_api_key": "",
                "gemini_model": "gemini-live-2",
            },
        )

        assert first.status_code == 200
        assert second.status_code == 200
        payload = second.json()
        assert payload["persisted_config"]["gemini"]["has_api_key"] is True
        assert payload["persisted_config"]["gemini"]["api_key_preview"] == "gem-...3456"
        assert payload["effective_config"]["ai_enrichment_run_concurrency"] == 8
        assert payload["runtime_status"]["configured_provider"] == "gemini"
        assert payload["runtime_status"]["active_provider"] in {"", None}
        assert payload["runtime_status"]["requires_test"] is True
        assert "gem-secret-123456" not in second.text

        AppRuntimeSettings = _import_runtime_settings_model()
        db = Session()
        try:
            row = db.query(AppRuntimeSettings).one()
            assert row.gemini_api_key == "gem-secret-123456"
            assert row.gemini_model == "gemini-live-2"
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_put_ai_settings_returns_validation_errors_for_invalid_provider_payload(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, _ = _build_test_client(monkeypatch)
    monkeypatch.setattr(
        llm_client_module,
        "_load_profile_metadata",
        lambda scope="jobs": type(
            "Meta",
            (),
            {
                "is_ready": True,
                "requires_test": False,
                "last_test_status": "passed",
                "last_tested_at": None,
                "last_test_error": None,
                "last_test_provider": "gemini",
                "last_test_model": "gemini-live",
                "last_test_latency_ms": 10,
                "last_test_fingerprint": f"{scope}:fingerprint",
                "last_successful_test_fingerprint": f"{scope}:fingerprint",
            },
        )(),
    )
    try:
        response = await client.put(
            "/api/v1/settings/ai",
            json={
                "llm_provider": "anthropic",
                "ai_enrichment_run_concurrency": 0,
                "anthropic_api_key": "",
                "anthropic_model": "",
            },
        )

        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(error["loc"] == ["body", "ai_enrichment_run_concurrency"] for error in errors)
        assert any(error["loc"] == ["body", "anthropic_api_key"] for error in errors)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_put_ai_settings_rejects_unknown_fields(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, _ = _build_test_client(monkeypatch)
    try:
        response = await client.put(
            "/api/v1/settings/ai",
            json={
                "llm_provider": "mock",
                "unexpected_field": "should-not-be-accepted",
            },
        )

        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any(error["loc"] == ["body", "unexpected_field"] for error in errors)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_put_ai_settings_returns_blocked_runtime_status_when_provider_init_fails(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    original_spec = llm_client_module.PROVIDER_REGISTRY.get("gemini")
    if original_spec is None:
        pytest.fail("llm_client provider registry is unexpectedly missing gemini")

    llm_client_module.reset_client()
    client, _ = _build_test_client(monkeypatch)
    monkeypatch.setattr(
        llm_client_module,
        "_load_profile_metadata",
        lambda scope="jobs": type(
            "Meta",
            (),
            {
                "is_ready": True,
                "requires_test": False,
                "last_test_status": "passed",
                "last_tested_at": None,
                "last_test_error": None,
                "last_test_provider": "gemini",
                "last_test_model": "gemini-live",
                "last_test_latency_ms": 10,
                "last_test_fingerprint": f"{scope}:fingerprint",
                "last_successful_test_fingerprint": f"{scope}:fingerprint",
            },
        )(),
    )

    monkeypatch.setitem(
        llm_client_module.PROVIDER_REGISTRY,
        "gemini",
        llm_client_module.ProviderSpec(
            name="gemini",
            required_settings=(("gemini_api_key", "GEMINI_API_KEY"),),
            builder=lambda runtime_settings: (_ for _ in ()).throw(RuntimeError("boom")),
        ),
    )
    try:
        response = await client.put(
            "/api/v1/settings/ai",
            json={
                "llm_provider": "gemini",
                "ai_enrichment_run_concurrency": 5,
                "gemini_api_key": "gem-secret-123456",
                "gemini_model": "gemini-live",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["runtime_status"]["configured_provider"] == "gemini"
        assert payload["runtime_status"]["active_provider"] in {"", None}
        assert payload["runtime_status"]["is_degraded"] is True
        assert payload["runtime_status"]["degradation_reason"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_put_ai_settings_persists_separate_company_profile_and_returns_company_runtime_status(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, Session = _build_test_client(monkeypatch)
    try:
        response = await client.put(
            "/api/v1/settings/ai",
            json={
                "llm_provider": "custom",
                "custom_api_key": "deepseek-secret",
                "custom_model": "deepseek-v4-flash",
                "custom_base_url": "https://api.deepseek.com",
                "custom_api_format": "anthropic",
                "company_llm_provider": "anthropic",
                "company_anthropic_api_key": "anthropic-secret",
                "company_anthropic_model": "claude-sonnet-4-5",
                "company_anthropic_base_url": "https://api.anthropic.com",
                "ai_enrichment_run_concurrency": 5,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["persisted_config"]["llm_provider"] == "custom"
        assert payload["persisted_config"]["company_llm_provider"] == "anthropic"
        assert payload["persisted_config"]["company_anthropic"]["model"] == "claude-sonnet-4-5"
        assert payload["persisted_config"]["company_anthropic"]["api_key_preview"] == "anth...cret"
        assert payload["runtime_status"]["configured_provider"] == "custom"
        assert payload["company_runtime_status"]["configured_provider"] == "anthropic"
        assert payload["company_runtime_status"]["active_provider"] in {"", None}
        assert payload["company_runtime_status"]["requires_test"] is True

        AppRuntimeSettings = _import_runtime_settings_model()
        db = Session()
        try:
            row = db.query(AppRuntimeSettings).one()
            assert row.llm_provider == "custom"
            assert row.company_llm_provider == "anthropic"
            assert row.company_anthropic_api_key == "anthropic-secret"
            assert row.company_anthropic_model == "claude-sonnet-4-5"
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_ai_settings_test_validates_draft_profile_and_records_passed_probe(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, Session = _build_test_client(monkeypatch)

    monkeypatch.setattr(
        "app.services.ai_runtime_settings_service.AIRuntimeSettingsService.build_draft_client",
        lambda *_args, **_kwargs: FakeProbeClient(),
    )
    try:
        response = await client.post(
            "/api/v1/settings/ai/test",
            json={
                "scope": "jobs",
                "profile": {
                    "llm_provider": "custom",
                    "custom_api_key": "test-secret",
                    "custom_model": "gpt-5.2",
                    "custom_base_url": "https://api.example.com",
                    "custom_api_format": "openai_responses",
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["scope"] == "jobs"
        assert payload["config_fingerprint"].startswith("jobs:")

        AppRuntimeSettings = _import_runtime_settings_model()
        db = Session()
        try:
            row = db.query(AppRuntimeSettings).one()
            assert row.jobs_last_test_status == "passed"
            assert row.jobs_last_successful_test_fingerprint.startswith("jobs:")
        finally:
            db.close()
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_enrichment_run_rejects_untested_jobs_profile(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, _ = _build_test_client(monkeypatch)
    monkeypatch.setattr(
        "app.api.ai.ensure_profile_runtime_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            __import__("app.services.ai_runtime_settings_service", fromlist=["ProfileRuntimeNotReadyError"]).ProfileRuntimeNotReadyError(
                "jobs",
                "jobs profile must be tested before running AI enrichment",
                code="profile_requires_test",
            )
        ),
    )
    try:
        response = await client.post("/api/v1/ai/runs", json={"mode": "pending"})

        assert response.status_code == 409
        assert response.json()["detail"] == "jobs profile must be tested before running AI enrichment"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_create_company_enrichment_run_rejects_untested_companies_profile(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "mock")
    monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
    llm_client_module.reset_client()
    client, _ = _build_test_client(monkeypatch)
    monkeypatch.setattr(
        "app.api.companies.ensure_profile_runtime_ready",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            __import__("app.services.ai_runtime_settings_service", fromlist=["ProfileRuntimeNotReadyError"]).ProfileRuntimeNotReadyError(
                "companies",
                "companies profile must be tested before running company descriptions",
                code="profile_requires_test",
            )
        ),
    )
    try:
        response = await client.post("/api/v1/companies/enrichment-runs")

        assert response.status_code == 409
        assert response.json()["detail"] == "companies profile must be tested before running company descriptions"
    finally:
        await client.aclose()
