from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base
from app.utils.time import utc_now


class CrawlJobListing(Base):
    """Durable staging row for listing-phase crawl results."""

    __tablename__ = "crawl_job_listings"
    __table_args__ = (
        UniqueConstraint(
            "crawl_job_id",
            "source_site",
            "source_job_id",
            name="uq_crawl_job_listings_job_source_key",
        ),
        Index(
            "ix_crawl_job_listings_source_status_rank_created",
            "source_site",
            "detail_status",
            "listing_rank",
            "created_at",
        ),
        Index(
            "ix_crawl_job_listings_job_status",
            "crawl_job_id",
            "detail_status",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    crawl_job_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    source_site = Column(String(32), nullable=False, index=True)
    source_job_id = Column(String(255), nullable=False, index=True)
    source_url = Column(String(1024), nullable=False)
    source_classification_id = Column(String(50), nullable=True, index=True)
    source_classification_name = Column(String(255), nullable=True)
    listing_page = Column(Integer, nullable=True)
    listing_rank = Column(Integer, nullable=True)
    listing_payload = Column(JSON, nullable=False)
    detail_payload = Column(JSON, nullable=True)
    detail_status = Column(String(32), nullable=False, default="pending", index=True)
    detail_attempts = Column(Integer, nullable=False, default=0)
    last_detail_crawl_job_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    published_job_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    detail_error_message = Column(Text, nullable=True)
    detail_started_at = Column(DateTime(timezone=True), nullable=True)
    detail_completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    crawl_job = relationship(
        "CrawlJob",
        primaryjoin="foreign(CrawlJobListing.crawl_job_id) == CrawlJob.id",
        viewonly=True,
    )
