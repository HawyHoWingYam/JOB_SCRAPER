from __future__ import annotations

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

SECRET_FIELD_NAMES = {
    "anthropic_api_key",
    "gemini_api_key",
    "custom_api_key",
    "zhipu_api_key",
}
URL_FIELD_NAMES = {
    "anthropic_base_url",
    "custom_base_url",
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
    "ai_enrichment_run_concurrency",
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
)


@dataclass(frozen=True)
class EffectiveAIRuntimeSettings:
    llm_provider: str
    ai_enrichment_run_concurrency: int
    anthropic_api_key: Optional[str]
    anthropic_model: str
    anthropic_base_url: Optional[str]
    gemini_api_key: Optional[str]
    gemini_model: str
    custom_api_key: Optional[str]
    custom_model: str
    custom_base_url: Optional[str]
    custom_api_format: str
    zhipu_api_key: Optional[str]


class RuntimeSettingsValidationError(ValueError):
    """Raised when persisted runtime settings fail validation."""

    def __init__(self, errors: list[dict[str, Any]]):
        super().__init__("Invalid AI runtime settings")
        self.errors = errors


class AIRuntimeSettingsService:
    """Persist and resolve AI runtime settings with config fallbacks."""

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

        self.db.add(row)
        self.db.flush()
        self.db.refresh(row)
        return row

    def get_effective_settings(self) -> EffectiveAIRuntimeSettings:
        row = self.get_or_create()
        return self._build_effective_settings(self._row_values(row))

    def serialize_persisted_config(
        self,
        row: Optional[AppRuntimeSettings] = None,
    ) -> dict[str, Any]:
        row = row or self.get_or_create()
        values = self._row_values(row)
        return {
            "llm_provider": values["llm_provider"],
            "ai_enrichment_run_concurrency": values["ai_enrichment_run_concurrency"],
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
        }

    def serialize_effective_config(
        self,
        effective: Optional[EffectiveAIRuntimeSettings] = None,
    ) -> dict[str, Any]:
        effective = effective or self.get_effective_settings()
        return {
            "llm_provider": effective.llm_provider,
            "ai_enrichment_run_concurrency": effective.ai_enrichment_run_concurrency,
            "anthropic": {
                "model": effective.anthropic_model,
                "base_url": effective.anthropic_base_url,
                "has_api_key": bool(effective.anthropic_api_key),
            },
            "gemini": {
                "model": effective.gemini_model,
                "has_api_key": bool(effective.gemini_api_key),
            },
            "custom": {
                "model": effective.custom_model,
                "base_url": effective.custom_base_url,
                "api_format": effective.custom_api_format,
                "has_api_key": bool(effective.custom_api_key),
            },
            "zhipu": {
                "has_api_key": bool(effective.zhipu_api_key),
            },
        }

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

            if field_name == "ai_enrichment_run_concurrency":
                candidate[field_name] = value
                continue

            candidate[field_name] = self._normalize_optional_string(value)

        return candidate

    def _validate_candidate(self, candidate: dict[str, Any]) -> None:
        errors: list[dict[str, Any]] = []
        provider = (candidate.get("llm_provider") or settings.llm_provider or "").strip().lower()

        if provider not in SUPPORTED_LLM_PROVIDERS:
            errors.append(
                {
                    "loc": ["llm_provider"],
                    "msg": f"Unsupported provider '{provider}'",
                    "type": "value_error.provider",
                }
            )

        concurrency_value = candidate.get("ai_enrichment_run_concurrency")
        effective_concurrency = concurrency_value
        if effective_concurrency is None:
            effective_concurrency = getattr(settings, "ai_enrichment_run_concurrency", None)
        try:
            effective_concurrency = int(effective_concurrency)
        except (TypeError, ValueError):
            effective_concurrency = None

        if (
            effective_concurrency is None
            or effective_concurrency < AI_ENRICHMENT_RUN_CONCURRENCY_MIN
            or effective_concurrency > AI_ENRICHMENT_RUN_CONCURRENCY_MAX
        ):
            errors.append(
                {
                    "loc": ["ai_enrichment_run_concurrency"],
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

        if provider in PROVIDER_REQUIRED_FIELDS:
            effective = self._build_effective_settings(candidate)
            effective_map = asdict(effective)
            for field_name in PROVIDER_REQUIRED_FIELDS[provider]:
                value = effective_map.get(field_name)
                if value is None or (isinstance(value, str) and not value.strip()):
                    errors.append(
                        {
                            "loc": [field_name],
                            "msg": f"{field_name} is required for provider '{provider}'",
                            "type": "value_error.required",
                        }
                    )

        if errors:
            raise RuntimeSettingsValidationError(errors)

    def _build_effective_settings(
        self,
        persisted_values: dict[str, Any],
    ) -> EffectiveAIRuntimeSettings:
        return EffectiveAIRuntimeSettings(
            llm_provider=(persisted_values.get("llm_provider") or settings.llm_provider).lower(),
            ai_enrichment_run_concurrency=int(
                persisted_values.get("ai_enrichment_run_concurrency")
                or settings.ai_enrichment_run_concurrency
            ),
            anthropic_api_key=persisted_values.get("anthropic_api_key") or settings.anthropic_api_key,
            anthropic_model=persisted_values.get("anthropic_model") or settings.anthropic_model,
            anthropic_base_url=persisted_values.get("anthropic_base_url") or settings.anthropic_base_url,
            gemini_api_key=persisted_values.get("gemini_api_key") or settings.gemini_api_key,
            gemini_model=persisted_values.get("gemini_model") or settings.gemini_model,
            custom_api_key=persisted_values.get("custom_api_key") or settings.custom_api_key,
            custom_model=persisted_values.get("custom_model") or settings.custom_model,
            custom_base_url=persisted_values.get("custom_base_url") or settings.custom_base_url,
            custom_api_format=(
                persisted_values.get("custom_api_format") or settings.custom_api_format
            ),
            zhipu_api_key=persisted_values.get("zhipu_api_key") or settings.zhipu_api_key,
        )

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
        if not stripped:
            return None
        return stripped

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


def get_effective_runtime_settings() -> EffectiveAIRuntimeSettings:
    db = SessionLocal()
    try:
        return AIRuntimeSettingsService(db).get_effective_settings()
    finally:
        db.close()
