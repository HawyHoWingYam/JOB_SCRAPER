"""Crawl run model — maps product crawl runs to Scrapyd job IDs."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class CrawlRun(Base):
    """Persistent projection of a product crawl run onto Scrapyd job state.

    Each CrawlRun represents one end-to-end crawl execution for a source site,
    tracking the Scrapyd job ID(s) and the run-level progress visible to the
    frontend. This is the authoritative source of truth for product-facing
    crawl state — Scrapyd's own state is treated as ephemeral.
    """

    __tablename__ = "crawl_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crawl_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_site = Column(String(50), nullable=False, index=True)
    scrapyd_project = Column(String(100), nullable=False, default="job_scraper_spiders")
    scrapyd_spider = Column(String(100), nullable=False)
    scrapyd_job_id = Column(String(100), nullable=True, index=True)
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # pending | running | completed | failed | cancelled

    # Progress counters (updated by pipelines / projection service)
    pages_processed = Column(Integer, nullable=False, default=0)
    listings_staged = Column(Integer, nullable=False, default=0)
    details_completed = Column(Integer, nullable=False, default=0)
    details_failed = Column(Integer, nullable=False, default=0)

    # Request payload snapshot (serialised)
    request_payload = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Optional FK back to the product crawl_job
    crawl_job = relationship("CrawlJob", back_populates="crawl_runs", lazy="selectin")

    __table_args__ = (
        {"extend_existing": True},
    )
