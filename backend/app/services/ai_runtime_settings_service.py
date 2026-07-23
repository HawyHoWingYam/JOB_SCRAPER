from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import (
    AI_ENRICHMENT_RUN_CONCURRENCY_MAX,
    AI_ENRICHMENT_RUN_CONCURRENCY_MIN,
    SUPPORTED_LLM_PROVIDERS,
    settings,
)
from app.database import SessionLocal
from app.models.app_runtime_settings import AppRuntimeSettings
from app.services.ai_provider_catalog import CUSTOM_API_FORMAT_OPTIONS
from app.utils.time import utc_now

RUNTIME_SCOPES = ("jobs", "companies")
PROFILE_TEST_STATUSES = ("untested", "passed", "failed")
CUSTOM_API_FORMAT_VALUES = {
    str(option["value"]) for option in CUSTOM_API_FORMAT_OPTIONS
}
SECRET_FIELD_NAMES = {
    "anthropic_api_key",
    "gemini_api_key",
    "custom_api_key",
    "zhipu_api_key",
    "company_anthropic_api_key",
    "company_gemini_api_key",
    "company_custom_api_key",
    "company_zhipu_api_key",
}
URL_FIELD_NAMES = {
    "anthropic_base_url",
    "custom_base_url",
    "company_anthropic_base_url",
    "company_custom_base_url",
}
PROVIDER_REQUIRED_FIELDS = {
    "anthropic": ("anthropic_api_key", "anthropic_model"),
    "claude": ("anthropic_api_key", "anthropic_model"),
    "custom": ("custom_api_key", "custom_model", "custom_base_url", "custom_api_format"),
    "gemini": ("gemini_api_key", "gemini_model"),
    "zhipu": ("zhipu_api_key",),
    "mock": tuple(),
}
PERSISTED_FIELD_NAMES = (
    "llm_provider",
    "company_llm_provider",
    "ai_enrichment_run_concurrency",
    "company_ai_enrichment_run_concurrency",
    "anthropic_api_key",
    "anthropic_model",
    "anthropic_base_url",
    "gemini_api_key",
    "gemini_model",
    "custom_api_key",
    "custom_model",
    "custom_base_url",
    "custom_api_format",
    "zhipu_api_key",
    "company_anthropic_api_key",
    "company_anthropic_model",
    "company_anthropic_base_url",
    "company_gemini_api_key",
    "company_gemini_model",
    "company_custom_api_key",
    "company_custom_model",
    "company_custom_base_url",
    "company_custom_api_format",
    "company_zhipu_api_key",
    "jobs_last_test_status",
    "jobs_last_tested_at",
    "jobs_last_test_error",
    "jobs_last_test_provider",
    "jobs_last_test_model",
    "jobs_last_test_latency_ms",
    "jobs_last_test_fingerprint",
    "jobs_last_successful_test_fingerprint",
    "companies_last_test_status",
    "companies_last_tested_at",
    "companies_last_test_error",
    "companies_last_test_provider",
    "companies_last_test_model",
    "companies_last_test_latency_ms",
    "companies_last_test_fingerprint",
    "companies_last_successful_test_fingerprint",
    "companies_web_search_last_test_status",
    "companies_web_search_last_tested_at",
    "companies_web_search_last_test_error",
    "companies_web_search_last_test_latency_ms",
    "companies_web_search_last_test_fingerprint",
)
PROFILE_FIELD_NAME_MAP = {
    "jobs": {
        "llm_provider": "llm_provider",
        "anthropic_api_key": "anthropic_api_key",
        "anthropic_model": "anthropic_model",
        "anthropic_base_url": "anthropic_base_url",
        "gemini_api_key": "gemini_api_key",
        "gemini_model": "gemini_model",
        "custom_api_key": "custom_api_key",
        "custom_model": "custom_model",
        "custom_base_url": "custom_base_url",
        "custom_api_format": "custom_api_format",
        "zhipu_api_key": "zhipu_api_key",
    },
    "companies": {
        "llm_provider": "company_llm_provider",
        "anthropic_api_key": "company_anthropic_api_key",
        "anthropic_model": "company_anthropic_model",
        "anthropic_base_url": "company_anthropic_base_url",
        "gemini_api_key": "company_gemini_api_key",
        "gemini_model": "company_gemini_model",
        "custom_api_key": "company_custom_api_key",
        "custom_model": "company_custom_model",
        "custom_base_url": "company_custom_base_url",
        "custom_api_format": "company_custom_api_format",
        "zhipu_api_key": "company_zhipu_api_key",
    },
}
PROFILE_TEST_FIELD_MAP = {
    "jobs": {
        "status": "jobs_last_test_status",
        "tested_at": "jobs_last_tested_at",
        "error": "jobs_last_test_error",
        "provider": "jobs_last_test_provider",
        "model": "jobs_last_test_model",
        "latency_ms": "jobs_last_test_latency_ms",
        "fingerprint": "jobs_last_test_fingerprint",
        "success_fingerprint": "jobs_last_successful_test_fingerprint",
    },
    "companies": {
        "status": "companies_last_test_status",
        "tested_at": "companies_last_tested_at",
        "error": "companies_last_test_error",
        "provider": "companies_last_test_provider",
        "model": "companies_last_test_model",
        "latency_ms": "companies_last_test_latency_ms",
        "fingerprint": "companies_last_test_fingerprint",
        "success_fingerprint": "companies_last_successful_test_fingerprint",
    },
}


@dataclass(frozen=True)
class EffectiveAIRuntimeSettings:
    llm_provider: Optional[str]
    ai_enrichment_run_concurrency: int
    anthropic_api_key: Optional[str]
    anthropic_model: Optional[str]
    anthropic_base_url: Optional[str]
    gemini_api_key: Optional[str]
    gemini_model: Optional[str]
    custom_api_key: Optional[str]
    custom_model: Optional[str]
    custom_base_url: Optional[str]
    custom_api_format: Optional[str]
    zhipu_api_key: Optional[str]


@dataclass(frozen=True)
class ProfileRuntimeMetadata:
    scope: str
    configured_provider: Optional[str]
    config_fingerprint: Optional[str]
    last_test_status: str
    last_tested_at: Optional[str]
    last_test_error: Optional[str]
    last_test_provider: Optional[str]
    last_test_model: Optional[str]
    last_test_latency_ms: Optional[int]
    last_test_fingerprint: Optional[str]
    last_successful_test_fingerprint: Optional[str]
    requires_test: bool
    is_ready: bool
    web_search_last_test_status: str
    web_search_last_tested_at: Optional[str]
    web_search_last_test_error: Optional[str]
    web_search_last_test_latency_ms: Optional[int]
    web_search_last_test_fingerprint: Optional[str]
    web_search_available: bool
    web_search_reason: Optional[str]


@dataclass(frozen=True)
class DraftProbeRequest:
    scope: str
    llm_provider: Optional[str]
    anthropic_api_key: Optional[str]
    anthropic_model: Optional[str]
    anthropic_base_url: Optional[str]
    gemini_api_key: Optional[str]
    gemini_model: Optional[str]
    custom_api_key: Optional[str]
    custom_model: Optional[str]
    custom_base_url: Optional[str]
    custom_api_format: Optional[str]
    zhipu_api_key: Optional[str]


class RuntimeSettingsValidationError(ValueError):
    """Raised when persisted runtime settings fail validation."""

    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("Invalid AI runtime settings")
        self.errors = errors


class ProfileRuntimeNotReadyError(RuntimeError):
    """Raised when a runtime profile is saved but not runnable."""

    def __init__(self, scope: str, message: str, *, code: str):
        super().__init__(message)
        self.scope = scope
        self.code = code


class AIRuntimeSettingsService:
    """Persist and resolve AI runtime settings with fully isolated profiles."""

    def __init__(self, db: Session):
        self.db = db

    def get_or_create(self) -> AppRuntimeSettings:
        row = self.db.query(AppRuntimeSettings).filter(AppRuntimeSettings.id == 1).one_or_none()
        if row is None:
            row = AppRuntimeSettings(id=1)
            self.db.add(row)
            self.db.flush()
        return row

    def update_settings(self, payload: dict[str, Any]) -> AppRuntimeSettings:
        row = self.get_or_create()
        candidate = self._build_candidate_values(row, payload)
        self._validate_candidate(candidate)

        for field_name, value in candidate.items():
            setattr(row, field_name, value)

        for scope in RUNTIME_SCOPES:
            current_fingerprint = self.build_config_fingerprint(scope, candidate)
            test_fields = PROFILE_TEST_FIELD_MAP[scope]
            last_successful = candidate.get(test_fields["success_fingerprint"])
            if current_fingerprint != last_successful:
                setattr(row, test_fields["status"], "untested")

        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def get_effective_settings(self, scope: str = "jobs") -> EffectiveAIRuntimeSettings:
        self._ensure_valid_scope(scope)
        row = self.get_or_create()
        return self._build_effective_settings(self._row_values(row), scope)

    def get_profile_runtime_metadata(
        self,
        scope: str,
        row: Optional[AppRuntimeSettings] = None,
    ) -> ProfileRuntimeMetadata:
        self._ensure_valid_scope(scope)
        row = row or self.get_or_create()
        values = self._row_values(row)
        effective = self._build_effective_settings(values, scope)
        test_fields = PROFILE_TEST_FIELD_MAP[scope]
        configured_provider = (effective.llm_provider or None)
        config_fingerprint = self.build_config_fingerprint(scope, values)
        last_status = values.get(test_fields["status"]) or "untested"
        last_successful = values.get(test_fields["success_fingerprint"])
        requires_test = bool(configured_provider) and config_fingerprint != last_successful
        is_ready = bool(configured_provider) and not requires_test and last_status == "passed"
        tested_at = values.get(test_fields["tested_at"])
        web_search_status = "not_applicable"
        web_search_tested_at = None
        web_search_error = None
        web_search_latency_ms = None
        web_search_fingerprint = None
        web_search_available = False
        web_search_reason: Optional[str] = (
            "Web Search is available only for Company Enrichment."
        )
        if scope == "companies":
            web_search_status = (
                values.get("companies_web_search_last_test_status") or "untested"
            )
            raw_web_search_tested_at = values.get(
                "companies_web_search_last_tested_at"
            )
            web_search_tested_at = (
                raw_web_search_tested_at.isoformat()
                if raw_web_search_tested_at
                else None
            )
            web_search_error = values.get("companies_web_search_last_test_error")
            web_search_latency_ms = values.get(
                "companies_web_search_last_test_latency_ms"
            )
            web_search_fingerprint = values.get(
                "companies_web_search_last_test_fingerprint"
            )
            fingerprint_matches = bool(
                config_fingerprint
                and web_search_fingerprint == config_fingerprint
            )
            web_search_available = bool(
                is_ready
                and web_search_status == "passed"
                and fingerprint_matches
            )
            if web_search_available:
                web_search_reason = None
            elif not is_ready:
                web_search_reason = "Test the Company profile successfully first."
            elif not fingerprint_matches:
                web_search_reason = (
                    "Test the current Company profile to verify Web Search support."
                )
            else:
                web_search_reason = web_search_error or (
                    "The configured Company provider did not pass the Web Search probe."
                )

        return ProfileRuntimeMetadata(
            scope=scope,
            configured_provider=configured_provider,
            config_fingerprint=config_fingerprint,
            last_test_status=last_status if last_status in PROFILE_TEST_STATUSES else "untested",
            last_tested_at=tested_at.isoformat() if tested_at else None,
            last_test_error=values.get(test_fields["error"]),
            last_test_provider=values.get(test_fields["provider"]),
            last_test_model=values.get(test_fields["model"]),
            last_test_latency_ms=values.get(test_fields["latency_ms"]),
            last_test_fingerprint=values.get(test_fields["fingerprint"]),
            last_successful_test_fingerprint=last_successful,
            requires_test=requires_test,
            is_ready=is_ready,
            web_search_last_test_status=web_search_status,
            web_search_last_tested_at=web_search_tested_at,
            web_search_last_test_error=web_search_error,
            web_search_last_test_latency_ms=web_search_latency_ms,
            web_search_last_test_fingerprint=web_search_fingerprint,
            web_search_available=web_search_available,
            web_search_reason=web_search_reason,
        )

    def ensure_profile_runtime_ready(self, scope: str) -> EffectiveAIRuntimeSettings:
        effective = self.get_effective_settings(scope)
        metadata = self.get_profile_runtime_metadata(scope)
        if not metadata.configured_provider:
            raise ProfileRuntimeNotReadyError(scope, f"{scope} profile is not configured", code="profile_not_configured")
        if metadata.requires_test:
            raise ProfileRuntimeNotReadyError(
                scope,
                f"{scope} profile must be tested before running",
                code="profile_requires_test",
            )
        if not metadata.is_ready:
            raise ProfileRuntimeNotReadyError(
                scope,
                f"{scope} profile is blocked by the last failed test",
                code="profile_test_failed",
            )
        self._validate_effective_settings(scope, effective)
        return effective

    def build_draft_client(self, scope: str, draft_values: dict[str, Any]):
        from app.ai.llm_client import PROVIDER_REGISTRY, LLMProfileNotReadyError

        effective = self._build_effective_settings(draft_values, scope)
        self._validate_effective_settings(scope, effective)
        provider = (effective.llm_provider or "").strip().lower()
        spec = PROVIDER_REGISTRY.get(provider)
        if spec is None:
            raise LLMProfileNotReadyError(scope, f"Unsupported LLM provider: {provider}", code="unsupported_provider")
        missing = [
            field_name
            for field_name in PROVIDER_REQUIRED_FIELDS.get(provider, tuple())
            if not asdict(effective).get(field_name)
        ]
        if missing:
            raise LLMProfileNotReadyError(
                scope,
                f"Provider '{provider}' missing required settings: {', '.join(missing)}",
                code="missing_required_settings",
            )

        return spec.builder(effective)

    def record_profile_test_result(
        self,
        scope: str,
        *,
        ok: bool,
        configured_provider: Optional[str],
        model: Optional[str],
        latency_ms: Optional[int],
        config_fingerprint: Optional[str],
        error_message: Optional[str],
    ) -> AppRuntimeSettings:
        self._ensure_valid_scope(scope)
        row = self.get_or_create()
        test_fields = PROFILE_TEST_FIELD_MAP[scope]
        timestamp = utc_now()

        setattr(row, test_fields["status"], "passed" if ok else "failed")
        setattr(row, test_fields["tested_at"], timestamp)
        setattr(row, test_fields["error"], None if ok else error_message)
        setattr(row, test_fields["provider"], configured_provider)
        setattr(row, test_fields["model"], model)
        setattr(row, test_fields["latency_ms"], latency_ms)
        setattr(row, test_fields["fingerprint"], config_fingerprint)
        if ok:
            setattr(row, test_fields["success_fingerprint"], config_fingerprint)

        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def record_company_web_search_test_result(
        self,
        *,
        status: str,
        latency_ms: Optional[int],
        config_fingerprint: Optional[str],
        error_message: Optional[str],
    ) -> AppRuntimeSettings:
        if status not in {"passed", "failed", "unsupported"}:
            raise ValueError(f"Unsupported Web Search test status '{status}'")

        row = self.get_or_create()
        row.companies_web_search_last_test_status = status
        row.companies_web_search_last_tested_at = utc_now()
        row.companies_web_search_last_test_error = error_message
        row.companies_web_search_last_test_latency_ms = latency_ms
        row.companies_web_search_last_test_fingerprint = config_fingerprint
        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def serialize_persisted_config(
        self,
        row: Optional[AppRuntimeSettings] = None,
    ) -> dict[str, Any]:
        row = row or self.get_or_create()
        values = self._row_values(row)
        return {
            "llm_provider": values["llm_provider"],
            "company_llm_provider": values["company_llm_provider"],
            "ai_enrichment_run_concurrency": values["ai_enrichment_run_concurrency"],
            "company_ai_enrichment_run_concurrency": values["company_ai_enrichment_run_concurrency"],
            "anthropic": {
                "model": values["anthropic_model"],
                "base_url": values["anthropic_base_url"],
                "has_api_key": bool(values["anthropic_api_key"]),
                "api_key_preview": self._mask_secret(values["anthropic_api_key"]),
            },
            "gemini": {
                "model": values["gemini_model"],
                "has_api_key": bool(values["gemini_api_key"]),
                "api_key_preview": self._mask_secret(values["gemini_api_key"]),
            },
            "custom": {
                "model": values["custom_model"],
                "base_url": values["custom_base_url"],
                "api_format": values["custom_api_format"],
                "has_api_key": bool(values["custom_api_key"]),
                "api_key_preview": self._mask_secret(values["custom_api_key"]),
            },
            "zhipu": {
                "has_api_key": bool(values["zhipu_api_key"]),
                "api_key_preview": self._mask_secret(values["zhipu_api_key"]),
            },
            "company_anthropic": {
                "has_api_key": bool(values["company_anthropic_api_key"]),
                "api_key_preview": self._mask_secret(values["company_anthropic_api_key"]),
                "model": values["company_anthropic_model"],
                "base_url": values["company_anthropic_base_url"],
            },
            "company_gemini": {
                "has_api_key": bool(values["company_gemini_api_key"]),
                "api_key_preview": self._mask_secret(values["company_gemini_api_key"]),
                "model": values["company_gemini_model"],
            },
            "company_custom": {
                "has_api_key": bool(values["company_custom_api_key"]),
                "api_key_preview": self._mask_secret(values["company_custom_api_key"]),
                "model": values["company_custom_model"],
                "base_url": values["company_custom_base_url"],
                "api_format": values["company_custom_api_format"],
            },
            "company_zhipu": {
                "has_api_key": bool(values["company_zhipu_api_key"]),
                "api_key_preview": self._mask_secret(values["company_zhipu_api_key"]),
            },
        }

    def serialize_effective_config(self) -> dict[str, Any]:
        job_effective = self.get_effective_settings("jobs")
        company_effective = self.get_effective_settings("companies")
        return {
            "llm_provider": job_effective.llm_provider,
            "company_llm_provider": company_effective.llm_provider,
            "ai_enrichment_run_concurrency": self.get_effective_concurrency("jobs"),
            "company_ai_enrichment_run_concurrency": self.get_effective_concurrency("companies"),
            "anthropic": {
                "model": job_effective.anthropic_model,
                "base_url": job_effective.anthropic_base_url,
                "has_api_key": bool(job_effective.anthropic_api_key),
            },
            "gemini": {
                "model": job_effective.gemini_model,
                "has_api_key": bool(job_effective.gemini_api_key),
            },
            "custom": {
                "model": job_effective.custom_model,
                "base_url": job_effective.custom_base_url,
                "api_format": job_effective.custom_api_format,
                "has_api_key": bool(job_effective.custom_api_key),
            },
            "zhipu": {
                "has_api_key": bool(job_effective.zhipu_api_key),
            },
            "company_anthropic": {
                "has_api_key": bool(company_effective.anthropic_api_key),
                "api_key_preview": self._mask_secret(company_effective.anthropic_api_key),
                "model": company_effective.anthropic_model,
                "base_url": company_effective.anthropic_base_url,
            },
            "company_gemini": {
                "has_api_key": bool(company_effective.gemini_api_key),
                "api_key_preview": self._mask_secret(company_effective.gemini_api_key),
                "model": company_effective.gemini_model,
            },
            "company_custom": {
                "has_api_key": bool(company_effective.custom_api_key),
                "api_key_preview": self._mask_secret(company_effective.custom_api_key),
                "model": company_effective.custom_model,
                "base_url": company_effective.custom_base_url,
                "api_format": company_effective.custom_api_format,
            },
            "company_zhipu": {
                "has_api_key": bool(company_effective.zhipu_api_key),
                "api_key_preview": self._mask_secret(company_effective.zhipu_api_key),
            },
        }

    def get_effective_concurrency(self, scope: str = "jobs") -> int:
        self._ensure_valid_scope(scope)
        row = self.get_or_create()
        if scope == "companies":
            candidate = getattr(row, "company_ai_enrichment_run_concurrency", None)
            if candidate is None:
                candidate = getattr(settings, "company_ai_enrichment_run_concurrency", None)
            if candidate is None:
                candidate = getattr(row, "ai_enrichment_run_concurrency", None)
            if candidate is None:
                candidate = getattr(settings, "ai_enrichment_run_concurrency", None)
        else:
            candidate = getattr(row, "ai_enrichment_run_concurrency", None)
            if candidate is None:
                candidate = getattr(settings, "ai_enrichment_run_concurrency", None)
        try:
            value = int(candidate if candidate is not None else 0)
        except (TypeError, ValueError):
            value = AI_ENRICHMENT_RUN_CONCURRENCY_MIN
        return max(AI_ENRICHMENT_RUN_CONCURRENCY_MIN, min(value, AI_ENRICHMENT_RUN_CONCURRENCY_MAX))

    def build_config_fingerprint(self, scope: str, values: dict[str, Any]) -> Optional[str]:
        self._ensure_valid_scope(scope)
        effective = self._build_effective_settings(values, scope)
        provider = (effective.llm_provider or "").strip().lower()
        if not provider:
            return None

        payload = {
            "scope": scope,
            "llm_provider": provider,
            "anthropic_api_key": self._normalize_secret_value(effective.anthropic_api_key),
            "anthropic_model": self._normalize_optional_string(effective.anthropic_model),
            "anthropic_base_url": self._normalize_optional_string(effective.anthropic_base_url),
            "gemini_api_key": self._normalize_secret_value(effective.gemini_api_key),
            "gemini_model": self._normalize_optional_string(effective.gemini_model),
            "custom_api_key": self._normalize_secret_value(effective.custom_api_key),
            "custom_model": self._normalize_optional_string(effective.custom_model),
            "custom_base_url": self._normalize_optional_string(effective.custom_base_url),
            "custom_api_format": self._normalize_optional_string(effective.custom_api_format),
            "zhipu_api_key": self._normalize_secret_value(effective.zhipu_api_key),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f"{scope}:{hashlib.sha256(encoded).hexdigest()}"

    def draft_profile_values_from_payload(self, scope: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_valid_scope(scope)
        row = self.get_or_create()
        candidate = self._row_values(row)
        profile_field_map = PROFILE_FIELD_NAME_MAP[scope]

        provider = self._normalize_optional_string(payload.get("llm_provider"))
        candidate[profile_field_map["llm_provider"]] = provider

        for effective_field_name, persisted_field_name in profile_field_map.items():
            if effective_field_name == "llm_provider":
                continue
            if effective_field_name not in payload:
                continue
            if persisted_field_name in SECRET_FIELD_NAMES:
                normalized_secret = self._normalize_secret_update(payload.get(effective_field_name))
                if normalized_secret is not None:
                    candidate[persisted_field_name] = normalized_secret
                continue
            candidate[persisted_field_name] = self._normalize_optional_string(payload.get(effective_field_name))

        return candidate

    def _build_candidate_values(
        self,
        row: AppRuntimeSettings,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = self._row_values(row)

        for field_name in PERSISTED_FIELD_NAMES:
            if field_name not in payload:
                continue

            value = payload[field_name]
            if field_name in SECRET_FIELD_NAMES:
                normalized_secret = self._normalize_secret_update(value)
                if normalized_secret is not None:
                    candidate[field_name] = normalized_secret
                continue

            if field_name in {"ai_enrichment_run_concurrency", "company_ai_enrichment_run_concurrency"}:
                candidate[field_name] = value
                continue

            candidate[field_name] = value if field_name.endswith("_tested_at") else self._normalize_optional_string(value)

        return candidate

    def _validate_candidate(self, candidate: dict[str, Any]) -> None:
        errors: list[dict[str, Any]] = []

        concurrency_specs = (
            ("ai_enrichment_run_concurrency", getattr(settings, "ai_enrichment_run_concurrency", None)),
            (
                "company_ai_enrichment_run_concurrency",
                (
                    candidate.get("ai_enrichment_run_concurrency")
                    if candidate.get("ai_enrichment_run_concurrency") is not None
                    else getattr(settings, "company_ai_enrichment_run_concurrency", None)
                    if getattr(settings, "company_ai_enrichment_run_concurrency", None) is not None
                    else getattr(settings, "ai_enrichment_run_concurrency", None)
                ),
            ),
        )
        for field_name, fallback_value in concurrency_specs:
            raw_concurrency = candidate.get(field_name)
            if raw_concurrency is None:
                raw_concurrency = fallback_value
            try:
                effective_concurrency: Optional[int] = int(
                    raw_concurrency if raw_concurrency is not None else 0
                )
            except (TypeError, ValueError):
                effective_concurrency = None

            if (
                effective_concurrency is None
                or effective_concurrency < AI_ENRICHMENT_RUN_CONCURRENCY_MIN
                or effective_concurrency > AI_ENRICHMENT_RUN_CONCURRENCY_MAX
            ):
                errors.append(
                    {
                        "loc": [field_name],
                        "msg": (
                            f"Concurrency must be between "
                            f"{AI_ENRICHMENT_RUN_CONCURRENCY_MIN} and {AI_ENRICHMENT_RUN_CONCURRENCY_MAX}"
                        ),
                        "type": "value_error.concurrency",
                    }
                )

        for field_name in URL_FIELD_NAMES:
            if candidate.get(field_name) and not self._is_valid_url(candidate[field_name]):
                errors.append(
                    {
                        "loc": [field_name],
                        "msg": "Must be a valid URL",
                        "type": "value_error.url",
                    }
                )

        errors.extend(self._validate_profile(candidate, "jobs"))
        errors.extend(self._validate_profile(candidate, "companies"))

        if errors:
            raise RuntimeSettingsValidationError(errors)

    def _validate_profile(self, candidate: dict[str, Any], scope: str) -> list[dict[str, Any]]:
        effective = self._build_effective_settings(candidate, scope)
        provider = (effective.llm_provider or "").strip().lower()
        provider_field = "llm_provider" if scope == "jobs" else "company_llm_provider"

        errors: list[dict[str, Any]] = []
        if not provider:
            return errors
        if provider not in SUPPORTED_LLM_PROVIDERS:
            errors.append(
                {
                    "loc": [provider_field],
                    "msg": f"Unsupported provider '{provider}'",
                    "type": "value_error.provider",
                }
            )
            return errors

        effective_map = asdict(effective)
        for field_name in PROVIDER_REQUIRED_FIELDS.get(provider, tuple()):
            value = effective_map.get(field_name)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(
                    {
                        "loc": [self._validation_loc_for_field(scope, field_name)],
                        "msg": f"{self._validation_loc_for_field(scope, field_name)} is required for provider '{provider}'",
                        "type": "value_error.required",
                    }
                )

        if (
            provider == "custom"
            and effective.custom_api_format not in CUSTOM_API_FORMAT_VALUES
        ):
            errors.append(
                {
                    "loc": [
                        self._validation_loc_for_field(scope, "custom_api_format")
                    ],
                    "msg": (
                        "Unsupported custom API format "
                        f"'{effective.custom_api_format}'"
                    ),
                    "type": "value_error.custom_api_format",
                }
            )

        return errors

    def _build_effective_settings(
        self,
        persisted_values: dict[str, Any],
        scope: str = "jobs",
    ) -> EffectiveAIRuntimeSettings:
        self._ensure_valid_scope(scope)
        field_map = PROFILE_FIELD_NAME_MAP[scope]
        provider = self._normalize_optional_string(persisted_values.get(field_map["llm_provider"]))

        return EffectiveAIRuntimeSettings(
            llm_provider=(provider.lower() if provider else None),
            ai_enrichment_run_concurrency=self.get_effective_concurrency(scope),
            anthropic_api_key=self._normalize_optional_string(persisted_values.get(field_map["anthropic_api_key"])),
            anthropic_model=self._normalize_optional_string(persisted_values.get(field_map["anthropic_model"])),
            anthropic_base_url=self._normalize_optional_string(persisted_values.get(field_map["anthropic_base_url"])),
            gemini_api_key=self._normalize_optional_string(persisted_values.get(field_map["gemini_api_key"])),
            gemini_model=self._normalize_optional_string(persisted_values.get(field_map["gemini_model"])),
            custom_api_key=self._normalize_optional_string(persisted_values.get(field_map["custom_api_key"])),
            custom_model=self._normalize_optional_string(persisted_values.get(field_map["custom_model"])),
            custom_base_url=self._normalize_optional_string(persisted_values.get(field_map["custom_base_url"])),
            custom_api_format=self._normalize_optional_string(persisted_values.get(field_map["custom_api_format"])),
            zhipu_api_key=self._normalize_optional_string(persisted_values.get(field_map["zhipu_api_key"])),
        )

    def _validate_effective_settings(self, scope: str, effective: EffectiveAIRuntimeSettings) -> None:
        provider = (effective.llm_provider or "").strip().lower()
        if not provider:
            raise ProfileRuntimeNotReadyError(scope, f"{scope} profile is not configured", code="profile_not_configured")
        if provider not in SUPPORTED_LLM_PROVIDERS:
            raise ProfileRuntimeNotReadyError(
                scope,
                f"{scope} profile has unsupported provider '{provider}'",
                code="profile_invalid_provider",
            )
        effective_map = asdict(effective)
        missing = [
            field_name
            for field_name in PROVIDER_REQUIRED_FIELDS.get(provider, tuple())
            if not effective_map.get(field_name)
        ]
        if missing:
            raise ProfileRuntimeNotReadyError(
                scope,
                f"{scope} profile is missing required settings: {', '.join(missing)}",
                code="profile_missing_settings",
            )
        if (
            provider == "custom"
            and effective.custom_api_format not in CUSTOM_API_FORMAT_VALUES
        ):
            raise ProfileRuntimeNotReadyError(
                scope,
                (
                    f"{scope} profile has unsupported custom API format "
                    f"'{effective.custom_api_format}'"
                ),
                code="profile_invalid_custom_api_format",
            )

    @staticmethod
    def _validation_loc_for_field(scope: str, field_name: str) -> str:
        if field_name in SECRET_FIELD_NAMES:
            return field_name
        if scope == "companies":
            return f"company_{field_name}"
        return field_name

    @staticmethod
    def _row_values(row: AppRuntimeSettings) -> dict[str, Any]:
        return {field_name: getattr(row, field_name) for field_name in PERSISTED_FIELD_NAMES}

    @staticmethod
    def _normalize_secret_update(value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            return str(value)
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _normalize_secret_value(value: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value).strip() or None

    @staticmethod
    def _normalize_optional_string(value: Any) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            return str(value)
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _mask_secret(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    @staticmethod
    def _is_valid_url(value: str) -> bool:
        parsed = urlparse(value)
        return bool(parsed.scheme and parsed.netloc)

    @staticmethod
    def _ensure_valid_scope(scope: str) -> None:
        if scope not in RUNTIME_SCOPES:
            raise ValueError(f"Unsupported runtime scope '{scope}'")


def get_effective_runtime_settings(scope: str = "jobs") -> EffectiveAIRuntimeSettings:
    db = SessionLocal()
    try:
        return AIRuntimeSettingsService(db).get_effective_settings(scope)
    finally:
        db.close()


def ensure_profile_runtime_ready(scope: str) -> EffectiveAIRuntimeSettings:
    db = SessionLocal()
    try:
        return AIRuntimeSettingsService(db).ensure_profile_runtime_ready(scope)
    finally:
        db.close()
