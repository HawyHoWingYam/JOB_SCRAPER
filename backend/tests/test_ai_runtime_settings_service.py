import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.database import Base
import app.ai.llm_client as llm_client_module

if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _import_runtime_settings_modules():
    try:
        from app.models.app_runtime_settings import AppRuntimeSettings
        from app.services.ai_runtime_settings_service import (
            AIRuntimeSettingsService,
            EffectiveAIRuntimeSettings,
            RuntimeSettingsValidationError,
        )
    except ModuleNotFoundError as exc:
        pytest.fail(f"AI runtime settings modules are missing: {exc}")

    return (
        AppRuntimeSettings,
        AIRuntimeSettingsService,
        EffectiveAIRuntimeSettings,
        RuntimeSettingsValidationError,
    )


def _build_sqlite_session():
    AppRuntimeSettings, _, _, _ = _import_runtime_settings_modules()

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
    return Session()


def test_get_or_create_settings_returns_singleton_row_and_allows_sparse_values():
    AppRuntimeSettings, AIRuntimeSettingsService, _, _ = _import_runtime_settings_modules()
    db = _build_sqlite_session()
    try:
        service = AIRuntimeSettingsService(db)

        first = service.get_or_create()
        second = service.get_or_create()

        assert first.id == second.id == 1
        assert first.llm_provider is None
        assert first.ai_enrichment_run_concurrency is None
        assert db.query(AppRuntimeSettings).count() == 1
    finally:
        db.close()


def test_effective_settings_merge_persisted_values_with_config_fallbacks(monkeypatch):
    _, AIRuntimeSettingsService, _, _ = _import_runtime_settings_modules()
    db = _build_sqlite_session()
    try:
        monkeypatch.setattr(settings, "llm_provider", "gemini")
        monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
        monkeypatch.setattr(settings, "anthropic_model", "claude-fallback")
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        monkeypatch.setattr(settings, "anthropic_base_url", None)
        monkeypatch.setattr(settings, "gemini_api_key", "env-gemini-key")
        monkeypatch.setattr(settings, "gemini_model", "gemini-fallback")
        monkeypatch.setattr(settings, "custom_api_key", None)
        monkeypatch.setattr(settings, "custom_model", "custom-fallback")
        monkeypatch.setattr(settings, "custom_base_url", "https://env-custom.example.com")
        monkeypatch.setattr(settings, "custom_api_format", "anthropic")
        monkeypatch.setattr(settings, "zhipu_api_key", None)

        service = AIRuntimeSettingsService(db)
        service.update_settings(
            {
                "llm_provider": "anthropic",
                "ai_enrichment_run_concurrency": 7,
                "anthropic_api_key": "db-anthropic-key-1234",
                "anthropic_model": "claude-db",
            }
        )

        effective = service.get_effective_settings()
        company_effective = service.get_effective_settings("companies")

        assert effective.llm_provider == "anthropic"
        assert effective.ai_enrichment_run_concurrency == 7
        assert effective.anthropic_api_key == "db-anthropic-key-1234"
        assert effective.anthropic_model == "claude-db"
        assert effective.gemini_api_key == "env-gemini-key"
        assert effective.gemini_model == "gemini-fallback"
        assert effective.custom_model == "custom-fallback"
        assert effective.custom_base_url == "https://env-custom.example.com"
        assert company_effective.llm_provider == "anthropic"
        assert company_effective.anthropic_model == "claude-db"
    finally:
        db.close()


def test_company_effective_settings_can_override_job_profile_with_shared_provider_secrets(monkeypatch):
    _, AIRuntimeSettingsService, _, _ = _import_runtime_settings_modules()
    db = _build_sqlite_session()
    try:
        monkeypatch.setattr(settings, "llm_provider", "mock")
        monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        monkeypatch.setattr(settings, "anthropic_model", "claude-fallback")
        monkeypatch.setattr(settings, "anthropic_base_url", None)
        monkeypatch.setattr(settings, "gemini_api_key", None)
        monkeypatch.setattr(settings, "gemini_model", "gemini-fallback")
        monkeypatch.setattr(settings, "custom_api_key", None)
        monkeypatch.setattr(settings, "custom_model", "deepseek-default")
        monkeypatch.setattr(settings, "custom_base_url", "https://api.deepseek.com")
        monkeypatch.setattr(settings, "custom_api_format", "anthropic")
        monkeypatch.setattr(settings, "zhipu_api_key", None)

        service = AIRuntimeSettingsService(db)
        service.update_settings(
            {
                "llm_provider": "custom",
                "custom_api_key": "deepseek-secret",
                "custom_model": "deepseek-v4-flash",
                "custom_base_url": "https://api.deepseek.com",
                "custom_api_format": "anthropic",
                "company_llm_provider": "anthropic",
                "company_anthropic_api_key": "anthropic-secret",
                "company_anthropic_model": "claude-sonnet-4-5",
                "company_anthropic_base_url": "https://api.anthropic.com",
            }
        )

        job_effective = service.get_effective_settings("jobs")
        company_effective = service.get_effective_settings("companies")
        serialized = service.serialize_persisted_config()

        assert job_effective.llm_provider == "custom"
        assert job_effective.custom_model == "deepseek-v4-flash"
        assert company_effective.llm_provider == "anthropic"
        assert company_effective.anthropic_model == "claude-sonnet-4-5"
        assert company_effective.anthropic_api_key == "anthropic-secret"
        assert serialized["company_llm_provider"] == "anthropic"
        assert serialized["company_anthropic"]["model"] == "claude-sonnet-4-5"
        assert serialized["company_anthropic"]["api_key_preview"] == "anth...cret"
        assert serialized["custom"]["api_key_preview"] == "deep...cret"
        assert serialized["anthropic"]["api_key_preview"] is None
    finally:
        db.close()


def test_update_settings_preserves_blank_secret_and_serializes_ui_safe_values(monkeypatch):
    _, AIRuntimeSettingsService, _, _ = _import_runtime_settings_modules()
    db = _build_sqlite_session()
    try:
        monkeypatch.setattr(settings, "llm_provider", "mock")
        monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
        monkeypatch.setattr(settings, "anthropic_model", "claude-fallback")
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        monkeypatch.setattr(settings, "anthropic_base_url", None)
        monkeypatch.setattr(settings, "gemini_api_key", None)
        monkeypatch.setattr(settings, "gemini_model", "gemini-fallback")
        monkeypatch.setattr(settings, "custom_api_key", None)
        monkeypatch.setattr(settings, "custom_model", "custom-fallback")
        monkeypatch.setattr(settings, "custom_base_url", None)
        monkeypatch.setattr(settings, "custom_api_format", "anthropic")
        monkeypatch.setattr(settings, "zhipu_api_key", None)

        service = AIRuntimeSettingsService(db)
        row = service.update_settings(
            {
                "llm_provider": "anthropic",
                "ai_enrichment_run_concurrency": 9,
                "anthropic_api_key": "sk-ant-1234567890",
                "anthropic_model": "claude-sonnet-a",
                "anthropic_base_url": "https://proxy.example.com",
            }
        )
        updated = service.update_settings(
            {
                "llm_provider": "anthropic",
                "ai_enrichment_run_concurrency": 11,
                "anthropic_api_key": "",
                "anthropic_model": "claude-sonnet-b",
            }
        )

        serialized = service.serialize_persisted_config(updated)

        assert row.id == updated.id == 1
        assert updated.anthropic_api_key == "sk-ant-1234567890"
        assert updated.anthropic_model == "claude-sonnet-b"
        assert serialized["anthropic"]["has_api_key"] is True
        assert serialized["anthropic"]["api_key_preview"] == "sk-a...7890"
        assert "sk-ant-1234567890" not in str(serialized)
    finally:
        db.close()


def test_update_settings_validates_provider_requirements_and_concurrency_bounds(monkeypatch):
    _, AIRuntimeSettingsService, _, RuntimeSettingsValidationError = _import_runtime_settings_modules()
    db = _build_sqlite_session()
    try:
        monkeypatch.setattr(settings, "llm_provider", "mock")
        monkeypatch.setattr(settings, "ai_enrichment_run_concurrency", 10)
        service = AIRuntimeSettingsService(db)

        with pytest.raises(RuntimeSettingsValidationError) as exc_info:
            service.update_settings(
                {
                    "llm_provider": "anthropic",
                    "company_llm_provider": "custom",
                    "ai_enrichment_run_concurrency": 0,
                    "anthropic_api_key": "",
                    "anthropic_model": "",
                    "anthropic_base_url": "not-a-url",
                    "company_custom_api_format": "",
                    "company_custom_base_url": "not-a-url",
                    "company_custom_model": "",
                }
            )

        errors = exc_info.value.errors
        assert any(error["loc"] == ["ai_enrichment_run_concurrency"] for error in errors)
        assert any(error["loc"] == ["anthropic_api_key"] for error in errors)
        assert any(error["loc"] == ["anthropic_base_url"] for error in errors)
        assert any(error["loc"] == ["custom_api_key"] for error in errors)
        assert any(error["loc"] == ["company_custom_base_url"] for error in errors)
    finally:
        db.close()


def test_reset_client_reloads_from_updated_effective_runtime_settings(monkeypatch):
    _, _, EffectiveAIRuntimeSettings, _ = _import_runtime_settings_modules()
    original_get_effective_runtime_settings = getattr(
        llm_client_module,
        "get_effective_runtime_settings",
        None,
    )
    if original_get_effective_runtime_settings is None:
        pytest.fail("llm_client is not yet wired to load effective runtime settings")

    first_effective = EffectiveAIRuntimeSettings(
        llm_provider="gemini",
        ai_enrichment_run_concurrency=10,
        anthropic_api_key=None,
        anthropic_model="claude-sonnet-4-5",
        anthropic_base_url=None,
        gemini_api_key="gemini-secret",
        gemini_model="gemini-test-a",
        custom_api_key=None,
        custom_model="claude-sonnet-4-5",
        custom_base_url=None,
        custom_api_format="anthropic",
        zhipu_api_key=None,
    )
    second_effective = EffectiveAIRuntimeSettings(
        llm_provider="custom",
        ai_enrichment_run_concurrency=10,
        anthropic_api_key=None,
        anthropic_model="claude-sonnet-4-5",
        anthropic_base_url=None,
        gemini_api_key=None,
        gemini_model="gemini-test-a",
        custom_api_key="custom-secret",
        custom_model="custom-model-b",
        custom_base_url="https://custom.example.com",
        custom_api_format="openai_responses",
        zhipu_api_key=None,
    )

    llm_client_module.reset_client()
    try:
        monkeypatch.setattr(
            llm_client_module,
            "get_effective_runtime_settings",
            lambda: first_effective,
        )
        first_client = llm_client_module.get_llm_client()
        first_status = llm_client_module.get_llm_status()

        monkeypatch.setattr(
            llm_client_module,
            "get_effective_runtime_settings",
            lambda: second_effective,
        )
        cached_client = llm_client_module.get_llm_client()
        llm_client_module.reset_client()
        reloaded_client = llm_client_module.get_llm_client()
        reloaded_status = llm_client_module.get_llm_status()

        assert first_client is cached_client
        assert first_status["configured_provider"] == "gemini"
        assert first_status["active_provider"] == "gemini"
        assert first_status["active_model"] == "gemini-test-a"
        assert reloaded_client is not first_client
        assert reloaded_status["configured_provider"] == "custom"
        assert reloaded_status["active_provider"] == "custom"
        assert reloaded_status["active_model"] == "custom-model-b"
        assert reloaded_status["is_degraded"] is False
    finally:
        llm_client_module.reset_client()
