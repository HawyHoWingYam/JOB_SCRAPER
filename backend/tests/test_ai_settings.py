from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.app_runtime_settings import AppRuntimeSettings
from app.services.ai_runtime_settings_service import (
    AIRuntimeSettingsService,
    RuntimeSettingsValidationError,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    AppRuntimeSettings.__table__.create(engine)
    return engine, sessionmaker(bind=engine)()


def _configured_company_payload():
    return {
        "company_llm_provider": "custom",
        "company_custom_api_key": "secret",
        "company_custom_model": "grok-4.5",
        "company_custom_base_url": "https://api.krill-ai.com/v1",
        "company_custom_api_format": "openai_chat_completions",
    }


def test_company_web_search_capability_requires_current_successful_probe():
    engine, db = _session()
    try:
        service = AIRuntimeSettingsService(db)
        service.update_settings(_configured_company_payload())
        values = service._row_values(service.get_or_create())
        fingerprint = service.build_config_fingerprint("companies", values)
        service.record_profile_test_result(
            "companies",
            ok=True,
            configured_provider="custom",
            model="grok-4.5",
            latency_ms=10,
            config_fingerprint=fingerprint,
            error_message=None,
        )
        service.record_company_web_search_test_result(
            status="passed",
            latency_ms=20,
            config_fingerprint=fingerprint,
            error_message=None,
        )

        metadata = service.get_profile_runtime_metadata("companies")
        assert metadata.is_ready is True
        assert metadata.web_search_available is True
        assert metadata.web_search_reason is None

        service.update_settings({"company_custom_model": "grok-4.5-next"})
        stale_metadata = service.get_profile_runtime_metadata("companies")
        assert stale_metadata.web_search_available is False
        assert "Test the Company profile" in stale_metadata.web_search_reason
    finally:
        db.close()
        engine.dispose()


def test_failed_search_probe_does_not_block_ordinary_company_profile():
    engine, db = _session()
    try:
        service = AIRuntimeSettingsService(db)
        service.update_settings(_configured_company_payload())
        values = service._row_values(service.get_or_create())
        fingerprint = service.build_config_fingerprint("companies", values)
        service.record_profile_test_result(
            "companies",
            ok=True,
            configured_provider="custom",
            model="grok-4.5",
            latency_ms=10,
            config_fingerprint=fingerprint,
            error_message=None,
        )
        service.record_company_web_search_test_result(
            status="failed",
            latency_ms=30,
            config_fingerprint=fingerprint,
            error_message="Krill rejected the search contract",
        )

        metadata = service.get_profile_runtime_metadata("companies")
        assert metadata.is_ready is True
        assert metadata.web_search_available is False
        assert metadata.web_search_reason == "Krill rejected the search contract"
    finally:
        db.close()
        engine.dispose()


def test_unknown_custom_api_format_is_rejected():
    engine, db = _session()
    try:
        service = AIRuntimeSettingsService(db)
        payload = _configured_company_payload()
        payload["company_custom_api_format"] = "unknown_format"

        try:
            service.update_settings(payload)
        except RuntimeSettingsValidationError as exc:
            assert any(
                error["type"] == "value_error.custom_api_format"
                for error in exc.errors
            )
        else:
            raise AssertionError("unknown custom format should fail validation")
    finally:
        db.close()
        engine.dispose()
