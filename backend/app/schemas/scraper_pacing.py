from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DetailPacingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_min_seconds: float = Field(ge=0.1, le=60)
    interval_max_seconds: float = Field(ge=0.1, le=60)
    burst_size: int = Field(ge=1, le=1000)
    burst_pause_seconds: float = Field(ge=0, le=3600)

    @model_validator(mode="after")
    def validate_interval_order(self) -> "DetailPacingConfig":
        if self.interval_min_seconds > self.interval_max_seconds:
            raise ValueError("interval_min_seconds must be <= interval_max_seconds")
        return self


class ScraperPacingSettingsUpdate(DetailPacingConfig):
    pass


class ScraperPacingSettingsResponse(DetailPacingConfig):
    source_site: str


class ScraperPacingSettingsListResponse(BaseModel):
    items: list[ScraperPacingSettingsResponse]
    active_detail_task_count: int = Field(ge=0)
