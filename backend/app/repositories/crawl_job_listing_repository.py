from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from app.crawl_phases import resolve_crawl_phase
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.utils.time import utc_now


class CrawlJobListingRepository:
    """Repository for listing-stage staging rows and detail execution state."""

    def get_by_source_key(
        self,
        db: Session,
        *,
        crawl_job_id,
        source_site: str,
        source_job_id: str,
    ) -> CrawlJobListing | None:
        return (
            db.query(CrawlJobListing)
            .filter(
                CrawlJobListing.crawl_job_id == crawl_job_id,
                CrawlJobListing.source_site == str(source_site).strip().lower(),
                CrawlJobListing.source_job_id == str(source_job_id).strip(),
            )
            .first()
        )

    def upsert_listing(
        self,
        db: Session,
        *,
        crawl_job_id,
        source_site: str,
        source_job_id: str,
        source_url: str,
        source_classification_id: str | None,
        source_classification_name: str | None,
        listing_page: int | None,
        listing_rank: int | None,
        listing_payload: dict[str, Any],
        auto_commit: bool = True,
    ) -> tuple[CrawlJobListing, str]:
        normalized_source_site = str(source_site).strip().lower()
        normalized_source_job_id = str(source_job_id).strip()
        existing = self.get_by_source_key(
            db,
            crawl_job_id=crawl_job_id,
            source_site=normalized_source_site,
            source_job_id=normalized_source_job_id,
        )
        if existing is None:
            listing = CrawlJobListing(
                crawl_job_id=crawl_job_id,
                source_site=normalized_source_site,
                source_job_id=normalized_source_job_id,
                source_url=source_url,
                source_classification_id=source_classification_id,
                source_classification_name=source_classification_name,
                listing_page=listing_page,
                listing_rank=listing_rank,
                listing_payload=dict(listing_payload or {}),
            )
            db.add(listing)
            if auto_commit:
                db.commit()
                db.refresh(listing)
            else:
                db.flush()
            return listing, "created"

        existing.source_url = source_url
        existing.source_classification_id = source_classification_id
        existing.source_classification_name = source_classification_name
        existing.listing_page = listing_page
        existing.listing_rank = listing_rank
        existing.listing_payload = dict(listing_payload or {})
        if auto_commit:
            db.commit()
            db.refresh(existing)
        else:
            db.flush()
        return existing, "updated"

    def list_detail_candidates(
        self,
        db: Session,
        *,
        source_site: str,
        source_listing_crawl_job_id=None,
        category_ids: Iterable[str | int] | None = None,
        statuses: Iterable[str] = ("pending",),
        limit: int = 100,
    ) -> list[CrawlJobListing]:
        query = db.query(CrawlJobListing).filter(
            CrawlJobListing.source_site == str(source_site).strip().lower(),
        )
        normalized_statuses = [str(status).strip().lower() for status in statuses if str(status).strip()]
        if normalized_statuses:
            query = query.filter(CrawlJobListing.detail_status.in_(normalized_statuses))
        if source_listing_crawl_job_id is not None:
            query = query.filter(CrawlJobListing.crawl_job_id == source_listing_crawl_job_id)

        normalized_category_ids = [str(category_id).strip() for category_id in (category_ids or []) if str(category_id).strip()]
        if normalized_category_ids:
            query = query.filter(CrawlJobListing.source_classification_id.in_(normalized_category_ids))

        return (
            query.order_by(
                case(
                    (CrawlJobListing.detail_status == "manual_action_required", 0),
                    else_=1,
                ),
                CrawlJobListing.listing_rank.asc().nullslast(),
                CrawlJobListing.created_at.asc(),
            )
            .limit(limit)
            .all()
        )

    def list_listing_batches(
        self,
        db: Session,
        *,
        source_site: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = db.query(CrawlJob).order_by(desc(CrawlJob.queued_at), desc(CrawlJob.created_at))
        if source_site:
            query = query.filter(CrawlJob.source_site == str(source_site).strip().lower())

        batches: list[dict[str, Any]] = []
        for crawl_job in query.limit(max(int(limit or 20) * 5, int(limit or 20))).all():
            request_payload = crawl_job.request_payload if isinstance(crawl_job.request_payload, dict) else {}
            if resolve_crawl_phase(request_payload.get("crawl_phase")) != "listing":
                continue

            status_counts = {
                str(status): int(count)
                for status, count in (
                    db.query(CrawlJobListing.detail_status, func.count(CrawlJobListing.id))
                    .filter(CrawlJobListing.crawl_job_id == crawl_job.id)
                    .group_by(CrawlJobListing.detail_status)
                    .all()
                )
            }
            listings_staged = sum(status_counts.values())
            if listings_staged == 0:
                continue

            batches.append(
                {
                    "crawl_job_id": str(crawl_job.id),
                    "source_site": crawl_job.source_site,
                    "status": crawl_job.status,
                    "category_ids": list(request_payload.get("category_ids") or []),
                    "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
                    "completed_at": crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
                    "listings_staged": listings_staged,
                    "detail_pending": status_counts.get("pending", 0),
                    "detail_running": status_counts.get("running", 0),
                    "detail_completed": status_counts.get("completed", 0),
                    "detail_failed": status_counts.get("failed", 0),
                    "detail_manual_action_required": status_counts.get("manual_action_required", 0),
                }
            )
            if len(batches) >= int(limit or 20):
                break

        return batches

    def mark_detail_running(
        self,
        db: Session,
        *,
        listing_id,
        detail_crawl_job_id,
        auto_commit: bool = True,
    ) -> CrawlJobListing:
        listing = db.query(CrawlJobListing).filter(CrawlJobListing.id == listing_id).one()
        listing.detail_status = "running"
        listing.detail_attempts = int(listing.detail_attempts or 0) + 1
        listing.last_detail_crawl_job_id = detail_crawl_job_id
        listing.detail_started_at = utc_now()
        listing.detail_completed_at = None
        listing.detail_error_message = None
        if auto_commit:
            db.commit()
            db.refresh(listing)
        else:
            db.flush()
        return listing

    def mark_detail_completed(
        self,
        db: Session,
        *,
        listing_id,
        detail_crawl_job_id,
        detail_payload: dict[str, Any] | None = None,
        published_job_id=None,
        auto_commit: bool = True,
    ) -> CrawlJobListing:
        listing = db.query(CrawlJobListing).filter(CrawlJobListing.id == listing_id).one()
        timestamp = utc_now()
        listing.detail_status = "completed"
        listing.last_detail_crawl_job_id = detail_crawl_job_id
        listing.published_job_id = published_job_id
        if detail_payload is not None:
            listing.detail_payload = dict(detail_payload)
        listing.detail_started_at = listing.detail_started_at or timestamp
        listing.detail_completed_at = timestamp
        listing.detail_error_message = None
        if auto_commit:
            db.commit()
            db.refresh(listing)
        else:
            db.flush()
        return listing

    def attach_published_job(
        self,
        db: Session,
        *,
        listing_id,
        published_job_id,
        auto_commit: bool = True,
    ) -> CrawlJobListing:
        listing = db.query(CrawlJobListing).filter(CrawlJobListing.id == listing_id).one()
        listing.published_job_id = published_job_id
        if auto_commit:
            db.commit()
            db.refresh(listing)
        else:
            db.flush()
        return listing

    def mark_detail_failed(
        self,
        db: Session,
        *,
        listing_id,
        detail_crawl_job_id,
        error_message: str,
        auto_commit: bool = True,
    ) -> CrawlJobListing:
        listing = db.query(CrawlJobListing).filter(CrawlJobListing.id == listing_id).one()
        timestamp = utc_now()
        listing.detail_status = "failed"
        listing.last_detail_crawl_job_id = detail_crawl_job_id
        listing.detail_started_at = listing.detail_started_at or timestamp
        listing.detail_completed_at = timestamp
        listing.detail_error_message = error_message
        if auto_commit:
            db.commit()
            db.refresh(listing)
        else:
            db.flush()
        return listing

    def mark_detail_manual_action_required(
        self,
        db: Session,
        *,
        listing_id,
        detail_crawl_job_id,
        error_message: str,
        auto_commit: bool = True,
    ) -> CrawlJobListing:
        listing = db.query(CrawlJobListing).filter(CrawlJobListing.id == listing_id).one()
        timestamp = utc_now()
        listing.detail_status = "manual_action_required"
        listing.last_detail_crawl_job_id = detail_crawl_job_id
        listing.detail_started_at = listing.detail_started_at or timestamp
        listing.detail_completed_at = timestamp
        listing.detail_error_message = error_message
        if auto_commit:
            db.commit()
            db.refresh(listing)
        else:
            db.flush()
        return listing
