from datetime import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, Integer, String

from app.database import Base


class ScraperPacingSettings(Base):
    """Persisted Job Detail pacing for one supported scraper source."""

    __tablename__ = "scraper_pacing_settings"
    __table_args__ = (
        CheckConstraint(
            "interval_min_seconds >= 0.1 AND interval_min_seconds <= 60",
            name="ck_scraper_pacing_interval_min",
        ),
        CheckConstraint(
            "interval_max_seconds >= 0.1 AND interval_max_seconds <= 60",
            name="ck_scraper_pacing_interval_max",
        ),
        CheckConstraint(
            "interval_min_seconds <= interval_max_seconds",
            name="ck_scraper_pacing_interval_order",
        ),
        CheckConstraint(
            "burst_size >= 1 AND burst_size <= 1000",
            name="ck_scraper_pacing_burst_size",
        ),
        CheckConstraint(
            "burst_pause_seconds >= 0 AND burst_pause_seconds <= 3600",
            name="ck_scraper_pacing_burst_pause",
        ),
    )

    source_site = Column(String(32), primary_key=True)
    interval_min_seconds = Column(Float, nullable=False)
    interval_max_seconds = Column(Float, nullable=False)
    burst_size = Column(Integer, nullable=False)
    burst_pause_seconds = Column(Float, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
