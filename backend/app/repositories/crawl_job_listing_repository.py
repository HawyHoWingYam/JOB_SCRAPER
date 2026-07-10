from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, aliased

from app.crawl_phases import DEFAULT_DETAIL_RETRY_STATUSES, resolve_detail_statuses
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.utils.time import utc_now


class CrawlJobListingRepository:
    """Repository for listing-stage staging rows and detail execution state."""

    OFFERTODAY_STAGING_LOCK_KEY = "job_scraper:offertoday:staging"

    def acquire_offertoday_staging_lock(self, db: Session) -> None:
        """Serialize OfferToday identity checks and inserts within this transaction."""

        try:
            bind = db.get_bind()
        except (AttributeError, TypeError):
            bind = getattr(db, "bind", None)
        dialect_name = str(getattr(getattr(bind, "dialect", None), "name", ""))
        if dialect_name != "postgresql":
            return

        db.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(self.OFFERTODAY_STAGING_LOCK_KEY)
                )
            )
        )

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

    def list_source_job_ids_for_crawl_job(
        self,
        db: Session,
        *,
        crawl_job_id,
        source_site: str | None = None,
    ) -> set[str]:
        query = db.query(CrawlJobListing.source_job_id).filter(
            CrawlJobListing.crawl_job_id == crawl_job_id,
        )
        if source_site:
            query = query.filter(
                CrawlJobListing.source_site == str(source_site).strip().lower(),
            )
        rows = query.all()
        return {str(source_job_id).strip() for (source_job_id,) in rows if str(source_job_id).strip()}

    def list_existing_source_job_ids(
        self,
        db: Session,
        *,
        source_site: str,
        source_job_ids: Iterable[str],
        exclude_crawl_job_id=None,
    ) -> set[str]:
        normalized_source_site = str(source_site).strip().lower()
        normalized_source_job_ids = [
            str(source_job_id).strip()
            for source_job_id in source_job_ids
            if str(source_job_id).strip()
        ]
        if not normalized_source_job_ids:
            return set()

        query = (
            db.query(CrawlJobListing.source_job_id)
            .filter(CrawlJobListing.source_site == normalized_source_site)
            .filter(CrawlJobListing.source_job_id.in_(normalized_source_job_ids))
        )
        if exclude_crawl_job_id is not None:
            query = query.filter(CrawlJobListing.crawl_job_id != exclude_crawl_job_id)

        rows = query.distinct().all()
        return {
            str(source_job_id).strip()
            for (source_job_id,) in rows
            if str(source_job_id).strip()
        }

    def get_max_listing_rank_for_crawl_job(
        self,
        db: Session,
        *,
        crawl_job_id,
        source_site: str | None = None,
    ) -> int:
        query = db.query(func.max(CrawlJobListing.listing_rank)).filter(
            CrawlJobListing.crawl_job_id == crawl_job_id,
        )
        if source_site:
            query = query.filter(
                CrawlJobListing.source_site == str(source_site).strip().lower(),
            )
        value = query.scalar()
        return int(value or 0)

    def list_detail_candidates(
        self,
        db: Session,
        *,
        source_site: str,
        source_listing_crawl_job_id=None,
        category_ids: Iterable[str | int] | None = None,
        statuses: Iterable[str] | None = None,
        source_job_ids: Iterable[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CrawlJobListing]:
        normalized_source_site = str(source_site).strip().lower()
        query = db.query(CrawlJobListing).filter(
            CrawlJobListing.source_site == normalized_source_site,
        )
        normalized_source_job_ids: list[str] | None = None
        if source_job_ids is not None:
            normalized_source_job_ids = [
                str(source_job_id).strip()
                for source_job_id in source_job_ids
                if str(source_job_id).strip()
            ]
            if not normalized_source_job_ids:
                return []
            query = query.filter(
                CrawlJobListing.source_job_id.in_(normalized_source_job_ids)
            )
        normalized_statuses = resolve_detail_statuses(
            crawl_phase="detail",
            detail_statuses=statuses,
        )
        query = query.filter(CrawlJobListing.detail_status.in_(normalized_statuses))
        if normalized_source_job_ids is None:
            if source_listing_crawl_job_id is not None:
                query = query.filter(
                    CrawlJobListing.crawl_job_id == source_listing_crawl_job_id
                )

            normalized_category_ids = [
                str(category_id).strip()
                for category_id in (category_ids or [])
                if str(category_id).strip()
            ]
            if normalized_category_ids:
                query = query.filter(
                    CrawlJobListing.source_classification_id.in_(
                        normalized_category_ids
                    )
                )

        if normalized_source_site == "offertoday":
            historical_blocker = aliased(CrawlJobListing)
            blocking_sibling_exists = (
                select(historical_blocker.id)
                .where(
                    historical_blocker.source_site == CrawlJobListing.source_site,
                    historical_blocker.source_job_id
                    == CrawlJobListing.source_job_id,
                    historical_blocker.detail_status.in_(
                        ("terminal_unavailable", "identity_conflict")
                    ),
                )
                .correlate(CrawlJobListing)
                .exists()
            )
            query = query.filter(~blocking_sibling_exists)

        query = query.order_by(
            case(
                (CrawlJobListing.detail_status == "manual_action_required", 0),
                (CrawlJobListing.detail_status == "failed", 1),
                (CrawlJobListing.detail_status == "pending", 2),
                else_=3,
            ),
            CrawlJobListing.listing_rank.asc().nullslast(),
            CrawlJobListing.created_at.asc(),
        )
        query = query.offset(max(int(offset or 0), 0))
        if limit is not None:
            query = query.limit(max(int(limit), 0))
        return query.all()

    def list_offertoday_identity_history(
        self,
        db: Session,
    ) -> list[CrawlJobListing]:
        """Return OfferToday staging identity evidence in deterministic creation order."""

        return (
            db.query(CrawlJobListing)
            .filter(CrawlJobListing.source_site == "offertoday")
            .order_by(CrawlJobListing.created_at.asc(), CrawlJobListing.id.asc())
            .all()
        )

    def defer_identity_conflicts(
        self,
        db: Session,
        *,
        source_site: str,
        source_job_ids: Iterable[str],
        statuses: Iterable[str] = DEFAULT_DETAIL_RETRY_STATUSES,
        error_message: str,
        auto_commit: bool = True,
    ) -> int:
        normalized_source_job_ids = [
            str(source_job_id).strip()
            for source_job_id in source_job_ids
            if str(source_job_id).strip()
        ]
        normalized_statuses = [
            str(status).strip().lower() for status in statuses if str(status).strip()
        ]
        if not normalized_source_job_ids or not normalized_statuses:
            return 0

        rows = (
            db.query(CrawlJobListing)
            .filter(
                CrawlJobListing.source_site == str(source_site).strip().lower(),
                CrawlJobListing.source_job_id.in_(normalized_source_job_ids),
                CrawlJobListing.detail_status.in_(normalized_statuses),
            )
            .all()
        )
        for listing in rows:
            listing.detail_status = "identity_conflict"
            listing.detail_error_message = error_message

        if auto_commit:
            db.commit()
        else:
            db.flush()
        return len(rows)

    def list_listing_batches(
        self,
        db: Session,
        *,
        source_site: str | None = None,
        category_id: str | None = None,
        detail_status: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        effective_limit = int(limit or 20)
        normalized_source_site = str(source_site).strip().lower() if source_site else None
        normalized_category_id = str(category_id).strip() if category_id else None
        normalized_detail_status = str(detail_status).strip().lower() if detail_status else None

        latest_listing_at = func.max(CrawlJobListing.created_at).label("latest_listing_at")
        grouped_query = db.query(CrawlJobListing.crawl_job_id, latest_listing_at)
        if normalized_source_site:
            grouped_query = grouped_query.filter(CrawlJobListing.source_site == normalized_source_site)
        if normalized_category_id:
            grouped_query = grouped_query.filter(CrawlJobListing.source_classification_id == normalized_category_id)
        if normalized_detail_status:
            grouped_query = grouped_query.filter(CrawlJobListing.detail_status == normalized_detail_status)

        grouped_rows = (
            grouped_query.group_by(CrawlJobListing.crawl_job_id)
            .order_by(latest_listing_at.desc(), CrawlJobListing.crawl_job_id.desc())
            .limit(effective_limit)
            .all()
        )

        crawl_job_ids = [crawl_job_id for crawl_job_id, _latest_listing_at in grouped_rows]
        if not crawl_job_ids:
            return []

        crawl_jobs_by_id = {
            crawl_job.id: crawl_job
            for crawl_job in db.query(CrawlJob).filter(CrawlJob.id.in_(crawl_job_ids)).all()
        }

        counts_query = db.query(
            CrawlJobListing.crawl_job_id,
            CrawlJobListing.detail_status,
            func.count(CrawlJobListing.id),
        ).filter(CrawlJobListing.crawl_job_id.in_(crawl_job_ids))
        if normalized_source_site:
            counts_query = counts_query.filter(CrawlJobListing.source_site == normalized_source_site)
        if normalized_category_id:
            counts_query = counts_query.filter(CrawlJobListing.source_classification_id == normalized_category_id)

        status_counts_by_job_id: dict[Any, dict[str, int]] = {}
        for crawl_job_id, status, count in counts_query.group_by(
            CrawlJobListing.crawl_job_id,
            CrawlJobListing.detail_status,
        ).all():
            status_counts_by_job_id.setdefault(crawl_job_id, {})[str(status)] = int(count)

        category_ids_by_job_id: dict[Any, list[str]] = {}
        jobs_needing_category_lookup: list[Any] = []
        for crawl_job_id in crawl_job_ids:
            crawl_job = crawl_jobs_by_id.get(crawl_job_id)
            if crawl_job is None:
                continue
            request_payload = crawl_job.request_payload if isinstance(crawl_job.request_payload, dict) else {}
            if not normalized_category_id and not list(request_payload.get("category_ids") or []):
                jobs_needing_category_lookup.append(crawl_job_id)

        if jobs_needing_category_lookup:
            category_query = (
                db.query(CrawlJobListing.crawl_job_id, CrawlJobListing.source_classification_id)
                .filter(CrawlJobListing.crawl_job_id.in_(jobs_needing_category_lookup))
                .filter(CrawlJobListing.source_classification_id.isnot(None))
            )
            if normalized_source_site:
                category_query = category_query.filter(CrawlJobListing.source_site == normalized_source_site)

            for crawl_job_id, source_classification_id in (
                category_query.group_by(
                    CrawlJobListing.crawl_job_id,
                    CrawlJobListing.source_classification_id,
                )
                .order_by(
                    CrawlJobListing.crawl_job_id.asc(),
                    CrawlJobListing.source_classification_id.asc(),
                )
                .all()
            ):
                category_ids_by_job_id.setdefault(crawl_job_id, []).append(str(source_classification_id))

        batches: list[dict[str, Any]] = []
        for crawl_job_id, _latest_listing_at in grouped_rows:
            crawl_job = crawl_jobs_by_id.get(crawl_job_id)
            if crawl_job is None:
                continue

            request_payload = crawl_job.request_payload if isinstance(crawl_job.request_payload, dict) else {}
            status_counts = status_counts_by_job_id.get(crawl_job.id, {})
            listings_staged = sum(status_counts.values())
            if listings_staged == 0:
                continue

            payload_category_ids = list(request_payload.get("category_ids") or [])
            if normalized_category_id:
                category_ids = [normalized_category_id]
            elif payload_category_ids:
                category_ids = payload_category_ids
            else:
                category_ids = category_ids_by_job_id.get(crawl_job.id, [])

            batches.append(
                {
                    "crawl_job_id": str(crawl_job.id),
                    "source_site": crawl_job.source_site,
                    "status": crawl_job.status,
                    "category_ids": category_ids,
                    "queued_at": crawl_job.queued_at.isoformat() if crawl_job.queued_at else None,
                    "completed_at": crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
                    "listings_staged": listings_staged,
                    "detail_pending": status_counts.get("pending", 0),
                    "detail_running": status_counts.get("running", 0),
                    "detail_completed": status_counts.get("completed", 0),
                    "detail_failed": status_counts.get("failed", 0),
                    "detail_manual_action_required": status_counts.get("manual_action_required", 0),
                    "detail_terminal_unavailable": status_counts.get(
                        "terminal_unavailable", 0
                    ),
                    "detail_identity_conflict": status_counts.get(
                        "identity_conflict", 0
                    ),
                }
            )

        return batches

    def summarize_detail_status_counts(
        self,
        db: Session,
    ) -> dict[str, int]:
        rows = (
            db.query(CrawlJobListing.detail_status, func.count(CrawlJobListing.id))
            .group_by(CrawlJobListing.detail_status)
            .all()
        )
        return {str(status): int(count) for status, count in rows}

    def count_detail_statuses(
        self,
        db: Session,
        *,
        source_site: str | None = None,
        source_listing_crawl_job_id=None,
        category_ids: Iterable[str | int] | None = None,
    ) -> dict[str, int]:
        query = db.query(
            CrawlJobListing.detail_status,
            func.count(CrawlJobListing.id),
        )

        normalized_source_site = str(source_site).strip().lower() if source_site else None
        if normalized_source_site:
            query = query.filter(CrawlJobListing.source_site == normalized_source_site)
        if source_listing_crawl_job_id is not None:
            query = query.filter(CrawlJobListing.crawl_job_id == source_listing_crawl_job_id)

        normalized_category_ids = [str(category_id).strip() for category_id in (category_ids or []) if str(category_id).strip()]
        if normalized_category_ids:
            query = query.filter(CrawlJobListing.source_classification_id.in_(normalized_category_ids))

        rows = query.group_by(CrawlJobListing.detail_status).all()
        return {str(status): int(count) for status, count in rows}

    def count_detail_statuses_for_detail_crawl_job(
        self,
        db: Session,
        *,
        detail_crawl_job_id,
        source_site: str | None = None,
    ) -> dict[str, int]:
        query = db.query(
            CrawlJobListing.detail_status,
            func.count(CrawlJobListing.id),
        ).filter(CrawlJobListing.last_detail_crawl_job_id == detail_crawl_job_id)

        normalized_source_site = str(source_site).strip().lower() if source_site else None
        if normalized_source_site:
            query = query.filter(CrawlJobListing.source_site == normalized_source_site)

        rows = query.group_by(CrawlJobListing.detail_status).all()
        return {str(status): int(count) for status, count in rows}

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

    def mark_detail_identity_conflict(
        self,
        db: Session,
        *,
        listing_id,
        detail_crawl_job_id,
        error_message: str,
        auto_commit: bool = True,
    ) -> CrawlJobListing:
        listing = (
            db.query(CrawlJobListing)
            .filter(CrawlJobListing.id == listing_id)
            .one()
        )
        timestamp = utc_now()
        listing.detail_status = "identity_conflict"
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




