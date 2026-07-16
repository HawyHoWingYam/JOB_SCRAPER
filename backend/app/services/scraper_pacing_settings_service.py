from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.crawl_modes import normalize_source_site
from app.models.scraper_pacing_settings import ScraperPacingSettings
from app.schemas.scraper_pacing import DetailPacingConfig

logger = logging.getLogger(__name__)

SUPPORTED_PACING_SOURCES = ("jobsdb", "ctgoodjobs", "offertoday")
DEFAULT_DETAIL_PACING = DetailPacingConfig(
    interval_min_seconds=1.0,
    interval_max_seconds=3.0,
    burst_size=20,
    burst_pause_seconds=30.0,
)


@dataclass(frozen=True, slots=True)
class ResolvedDetailPacing:
    interval_min_seconds: float
    interval_max_seconds: float
    burst_size: int
    burst_pause_seconds: float

    def to_payload(self) -> dict[str, float | int]:
        return {
            "interval_min_seconds": self.interval_min_seconds,
            "interval_max_seconds": self.interval_max_seconds,
            "burst_size": self.burst_size,
            "burst_pause_seconds": self.burst_pause_seconds,
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "ResolvedDetailPacing":
        config = DetailPacingConfig.model_validate(payload)
        return cls(**config.model_dump())


class ScraperPacingSettingsService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def normalize_supported_source(source_site: str) -> str:
        normalized = normalize_source_site(source_site)
        if normalized not in SUPPORTED_PACING_SOURCES:
            raise ValueError(f"Unsupported scraper pacing source: {source_site}")
        return normalized

    def list_settings(self) -> list[ScraperPacingSettings]:
        rows: dict[str, ScraperPacingSettings] = {
            str(row.source_site): row
            for row in self.db.query(ScraperPacingSettings)
            .filter(ScraperPacingSettings.source_site.in_(SUPPORTED_PACING_SOURCES))
            .all()
        }
        return [self._get_or_create(source, rows.get(source)) for source in SUPPORTED_PACING_SOURCES]

    def resolve(
        self,
        source_site: str,
        *,
        for_update: bool = False,
    ) -> ResolvedDetailPacing:
        source = self.normalize_supported_source(source_site)
        query = self.db.query(ScraperPacingSettings).filter(
            ScraperPacingSettings.source_site == source
        )
        if for_update:
            query = query.with_for_update()
        row = query.one_or_none()
        if row is None:
            logger.warning("SCRAPER_PACING_DEFAULT_FALLBACK source=%s", source)
            return ResolvedDetailPacing.from_payload(DEFAULT_DETAIL_PACING.model_dump())
        return self._resolved_from_row(row)

    def update(self, source_site: str, payload: dict[str, Any]) -> ScraperPacingSettings:
        source = self.normalize_supported_source(source_site)
        config = DetailPacingConfig.model_validate(payload)
        row = (
            self.db.query(ScraperPacingSettings)
            .filter(ScraperPacingSettings.source_site == source)
            .with_for_update()
            .one_or_none()
        )
        row = self._get_or_create(source, row)
        for field, value in config.model_dump().items():
            setattr(row, field, value)
        self.db.flush()
        return row

    def reset(self, source_site: str) -> ScraperPacingSettings:
        return self.update(source_site, DEFAULT_DETAIL_PACING.model_dump())

    def _get_or_create(
        self,
        source: str,
        row: ScraperPacingSettings | None,
    ) -> ScraperPacingSettings:
        if row is not None:
            return row
        row = ScraperPacingSettings(
            source_site=source,
            **DEFAULT_DETAIL_PACING.model_dump(),
        )
        self.db.add(row)
        self.db.flush()
        return row

    @staticmethod
    def _resolved_from_row(row: ScraperPacingSettings) -> ResolvedDetailPacing:
        return ResolvedDetailPacing.from_payload(
            {
                "interval_min_seconds": row.interval_min_seconds,
                "interval_max_seconds": row.interval_max_seconds,
                "burst_size": row.burst_size,
                "burst_pause_seconds": row.burst_pause_seconds,
            }
        )


def serialize_scraper_pacing_row(row: ScraperPacingSettings) -> dict[str, Any]:
    return {
        "source_site": row.source_site,
        "interval_min_seconds": float(row.interval_min_seconds),
        "interval_max_seconds": float(row.interval_max_seconds),
        "burst_size": int(row.burst_size),
        "burst_pause_seconds": float(row.burst_pause_seconds),
    }
