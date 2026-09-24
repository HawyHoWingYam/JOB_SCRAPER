from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.jev import JevRuntimeSettings


DEFAULT_ENDPOINT = "https://www.rsiai.net/v1/systemone"
DEFAULT_MODEL = "jev-latest"


class JevSettingsValidationError(ValueError):
    def __init__(self, errors: list[dict[str, object]]) -> None:
        super().__init__("Invalid Jev settings")
        self.errors = errors


class JevRuntimeSettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create(self) -> JevRuntimeSettings:
        row = self.db.get(JevRuntimeSettings, 1)
        if row is None:
            row = JevRuntimeSettings(
                id=1,
                enabled=False,
                endpoint=DEFAULT_ENDPOINT,
                model=DEFAULT_MODEL,
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
                maintenance_model=DEFAULT_MODEL,
                maintenance_interval_days=30,
                maintenance_min_candidates=50,
                maintenance_batch_size=100,
                maintenance_threshold_millis=900,
            )
            self.db.add(row)
            self.db.flush()
        return row

    def update(self, values: dict[str, object]) -> JevRuntimeSettings:
        row = self.get_or_create()
        candidate = self._values(row)
        for key, value in values.items():
            if key == "api_key":
                normalized = str(value or "").strip()
                if normalized:
                    candidate[key] = normalized
            elif key in {
                "evidence_threshold",
                "recommendation_threshold",
                "maintenance_threshold",
            }:
                candidate[f"{key}_millis"] = self._threshold_millis(value, key)
            elif isinstance(value, str):
                candidate[key] = value.strip()
            else:
                candidate[key] = value
        self._validate(candidate)
        for key, value in candidate.items():
            setattr(row, key, value)
        self.db.flush()
        return row

    def serialize(self) -> dict[str, object]:
        row = self.get_or_create()
        return {
            "enabled": bool(row.enabled),
            "endpoint": row.endpoint,
            "model": row.model,
            "has_api_key": bool(row.api_key),
            "api_key_preview": self._mask_secret(row.api_key),
            "sample_limit": row.sample_limit,
            "question_batch_limit": row.question_batch_limit,
            "concurrency": row.concurrency,
            "retry_limit": row.retry_limit,
            "timeout_seconds": row.timeout_seconds,
            "evidence_threshold": self._render_threshold(row.evidence_threshold_millis),
            "recommendation_threshold": self._render_threshold(
                row.recommendation_threshold_millis
            ),
            "duplicate_enabled": bool(row.duplicate_enabled),
            "duplicate_candidate_limit": row.duplicate_candidate_limit,
            "duplicate_corpus_limit": row.duplicate_corpus_limit,
            "crawl_quality_enabled": bool(row.crawl_quality_enabled),
            "crawl_quality_batch_limit": row.crawl_quality_batch_limit,
            "search_rerank_enabled": bool(row.search_rerank_enabled),
            "search_rerank_candidate_limit": row.search_rerank_candidate_limit,
            "incident_triage_enabled": bool(row.incident_triage_enabled),
            "incident_triage_event_limit": row.incident_triage_event_limit,
            "maintenance_enabled": bool(row.maintenance_enabled),
            "maintenance_model": row.maintenance_model,
            "maintenance_interval_days": row.maintenance_interval_days,
            "maintenance_min_candidates": row.maintenance_min_candidates,
            "maintenance_batch_size": row.maintenance_batch_size,
            "maintenance_threshold": self._render_threshold(
                row.maintenance_threshold_millis
            ),
            "maintenance_last_checked_at": row.maintenance_last_checked_at,
            "maintenance_last_started_at": row.maintenance_last_started_at,
        }

    @staticmethod
    def _values(row: JevRuntimeSettings) -> dict[str, object]:
        return {
            "enabled": bool(row.enabled),
            "endpoint": row.endpoint,
            "model": row.model,
            "api_key": row.api_key,
            "sample_limit": row.sample_limit,
            "question_batch_limit": row.question_batch_limit,
            "concurrency": row.concurrency,
            "retry_limit": row.retry_limit,
            "timeout_seconds": row.timeout_seconds,
            "evidence_threshold_millis": row.evidence_threshold_millis,
            "recommendation_threshold_millis": row.recommendation_threshold_millis,
            "duplicate_enabled": bool(row.duplicate_enabled),
            "duplicate_candidate_limit": row.duplicate_candidate_limit,
            "duplicate_corpus_limit": row.duplicate_corpus_limit,
            "crawl_quality_enabled": bool(row.crawl_quality_enabled),
            "crawl_quality_batch_limit": row.crawl_quality_batch_limit,
            "search_rerank_enabled": bool(row.search_rerank_enabled),
            "search_rerank_candidate_limit": row.search_rerank_candidate_limit,
            "incident_triage_enabled": bool(row.incident_triage_enabled),
            "incident_triage_event_limit": row.incident_triage_event_limit,
            "maintenance_enabled": bool(row.maintenance_enabled),
            "maintenance_model": row.maintenance_model,
            "maintenance_interval_days": row.maintenance_interval_days,
            "maintenance_min_candidates": row.maintenance_min_candidates,
            "maintenance_batch_size": row.maintenance_batch_size,
            "maintenance_threshold_millis": row.maintenance_threshold_millis,
            "maintenance_last_checked_at": row.maintenance_last_checked_at,
            "maintenance_last_started_at": row.maintenance_last_started_at,
        }

    @staticmethod
    def _threshold_millis(value: object, field_name: str) -> int:
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise JevSettingsValidationError(
                [
                    {
                        "loc": [field_name],
                        "msg": "Must be between 0 and 1",
                        "type": "value_error",
                    }
                ]
            ) from exc
        if decimal < 0 or decimal > 1:
            raise JevSettingsValidationError(
                [
                    {
                        "loc": [field_name],
                        "msg": "Must be between 0 and 1",
                        "type": "value_error",
                    }
                ]
            )
        return int(decimal * 1000)

    @staticmethod
    def _render_threshold(value: int) -> str:
        return f"{Decimal(value) / Decimal(1000):.3f}"

    @staticmethod
    def _mask_secret(value: str | None) -> str | None:
        if not value:
            return None
        if len(value) <= 8:
            return "***"
        return f"{value[:4]}...{value[-4:]}"

    @staticmethod
    def _validate(values: dict[str, object]) -> None:
        errors: list[dict[str, object]] = []
        parsed = urlparse(str(values["endpoint"]))
        is_local_http = parsed.scheme == "http" and parsed.hostname in {
            "127.0.0.1",
            "localhost",
            "::1",
        }
        if (parsed.scheme != "https" and not is_local_http) or not parsed.netloc:
            errors.append(
                {
                    "loc": ["endpoint"],
                    "msg": "Must be an HTTPS URL",
                    "type": "value_error",
                }
            )
        if not str(values["model"]).strip():
            errors.append(
                {"loc": ["model"], "msg": "Must not be blank", "type": "value_error"}
            )
        if not str(values["maintenance_model"]).strip():
            errors.append(
                {
                    "loc": ["maintenance_model"],
                    "msg": "Must not be blank",
                    "type": "value_error",
                }
            )
        bounds = {
            "sample_limit": (1, 10_000),
            "question_batch_limit": (1, 100),
            "concurrency": (1, 50),
            "retry_limit": (0, 10),
            "timeout_seconds": (1, 600),
            "duplicate_candidate_limit": (1, 10),
            "duplicate_corpus_limit": (2, 1_000),
            "crawl_quality_batch_limit": (1, 100),
            "search_rerank_candidate_limit": (1, 50),
            "incident_triage_event_limit": (1, 1_000),
            "maintenance_interval_days": (1, 3650),
            "maintenance_min_candidates": (1, 100_000),
            "maintenance_batch_size": (1, 10_000),
        }
        for field_name, (minimum, maximum) in bounds.items():
            value = values[field_name]
            if not isinstance(value, int) or not minimum <= value <= maximum:
                errors.append(
                    {
                        "loc": [field_name],
                        "msg": f"Must be between {minimum} and {maximum}",
                        "type": "value_error",
                    }
                )
        if errors:
            raise JevSettingsValidationError(errors)


__all__ = [
    "JevRuntimeSettingsService",
    "JevSettingsValidationError",
]
