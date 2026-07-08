from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.crawl_job_listing import CrawlJobListing
from app.models.job import Job
from app.repositories.company_repository import CompanyRepository
from app.repositories.job_repository import JobRepository
from app.sources.contracts import (
    CanonicalScrapedJob,
    build_offertoday_canonical_job,
    build_offertoday_company_data,
    build_offertoday_job_data,
)


@dataclass(frozen=True)
class OfferTodayRepairResult:
    action: str
    description_repaired: bool
    company_reassigned: bool
    listing_attached: bool


class OfferTodayJobRepairService:
    def __init__(
        self,
        db: Session | None,
        *,
        company_repository: CompanyRepository | None = None,
        job_repository: JobRepository | None = None,
    ) -> None:
        self.db = db
        self.company_repository = company_repository or CompanyRepository()
        self.job_repository = job_repository or JobRepository()

    def list_candidate_jobs(self, *, limit: int | None = None) -> list[Job]:
        if self.db is None:
            return []

        query = (
            self.db.query(Job)
            .options(joinedload(Job.company))
            .filter(Job.source_site == "offertoday", Job.is_deleted == False)
            .order_by(Job.updated_at.desc(), Job.created_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def is_degraded_job(self, job: Job | Any) -> bool:
        if getattr(job, "source_site", None) != "offertoday":
            return False
        return not str(getattr(job, "description", "") or "").strip()

    def iter_repair_candidates(self, *, limit: int | None = None) -> list[Job]:
        if self.db is None:
            return []

        query = (
            self.db.query(Job)
            .options(joinedload(Job.company))
            .filter(Job.source_site == "offertoday", Job.is_deleted == False)
            .filter(or_(Job.description.is_(None), Job.description == ""))
            .order_by(Job.updated_at.desc(), Job.created_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def repair_job(self, job: Job) -> OfferTodayRepairResult:
        if self.db is None:
            raise ValueError("repair_job requires an active database session")

        listing = self.get_latest_completed_listing(job.source_job_id) or self.get_latest_listing(
            job.source_job_id
        )
        canonical = self.build_canonical_job_snapshot(job, listing)
        return self._persist_canonical_job(job, canonical, listing)

    def repair_job_with_detail_payload(
        self,
        job: Job,
        detail_payload: dict[str, Any],
    ) -> OfferTodayRepairResult:
        if self.db is None:
            raise ValueError("repair_job_with_detail_payload requires an active database session")

        listing = self.get_latest_listing(job.source_job_id)
        if listing is not None:
            listing.detail_payload = dict(detail_payload)
            listing.detail_status = "completed"
            listing.detail_error_message = None
            listing.detail_completed_at = datetime.utcnow()

        canonical = self.build_canonical_job_snapshot(
            job,
            listing,
            detail_payload_override=detail_payload,
        )
        return self._persist_canonical_job(job, canonical, listing)

    def _persist_canonical_job(
        self,
        job: Job,
        canonical: CanonicalScrapedJob,
        listing: CrawlJobListing | Any | None,
    ) -> OfferTodayRepairResult:
        company_data = build_offertoday_company_data(canonical)
        company, _company_action = self.company_repository.upsert_company(
            self.db,
            company_data,
            auto_commit=False,
        )

        before_description = str(job.description or "").strip()
        before_company_id = job.company_id
        job_data = build_offertoday_job_data(canonical, company.id)
        if not job_data.get("description") and before_description:
            job_data["description"] = before_description
        if not job_data.get("posted_date") and job.posted_date:
            job_data["posted_date"] = job.posted_date

        repaired_job, action = self.job_repository.upsert_source_job(
            self.db,
            job_data,
            skip_existing=False,
            auto_commit=False,
        )

        listing_attached = False
        if listing is not None and listing.published_job_id != repaired_job.id:
            listing.published_job_id = repaired_job.id
            listing_attached = True

        return OfferTodayRepairResult(
            action=action,
            description_repaired=not before_description and bool(str(repaired_job.description or "").strip()),
            company_reassigned=before_company_id != repaired_job.company_id,
            listing_attached=listing_attached,
        )

    def get_latest_listing(self, source_job_id: str) -> CrawlJobListing | None:
        if self.db is None:
            return None

        return (
            self.db.query(CrawlJobListing)
            .filter(
                CrawlJobListing.source_site == "offertoday",
                CrawlJobListing.source_job_id == str(source_job_id or "").strip(),
            )
            .order_by(
                CrawlJobListing.updated_at.desc(),
                CrawlJobListing.created_at.desc(),
            )
            .first()
        )

    def get_latest_completed_listing(self, source_job_id: str) -> CrawlJobListing | None:
        if self.db is None:
            return None

        return (
            self.db.query(CrawlJobListing)
            .filter(
                CrawlJobListing.source_site == "offertoday",
                CrawlJobListing.source_job_id == str(source_job_id or "").strip(),
                CrawlJobListing.detail_status == "completed",
                CrawlJobListing.detail_payload.isnot(None),
            )
            .order_by(
                CrawlJobListing.detail_completed_at.desc().nullslast(),
                CrawlJobListing.updated_at.desc(),
                CrawlJobListing.created_at.desc(),
            )
            .first()
        )

    def build_canonical_job_snapshot(
        self,
        job: Job | Any,
        listing: CrawlJobListing | Any | None = None,
        *,
        detail_payload_override: dict[str, Any] | None = None,
    ) -> CanonicalScrapedJob:
        payload = {
            "source_site": "offertoday",
            "encrypted_job_id": str(getattr(job, "source_job_id", None) or getattr(job, "job_id", "") or "").strip(),
            "title": getattr(job, "title", "") or "",
            "description_html": getattr(job, "description", "") or "",
            "location": getattr(job, "location", "") or "",
            "salary_range": getattr(job, "salary_range", "") or "",
            "employment_type": getattr(job, "employment_type", "") or "",
            "posted_at": (
                getattr(job, "posted_date", None).isoformat()
                if getattr(job, "posted_date", None) is not None
                else ""
            ),
            "company_name": getattr(getattr(job, "company", None), "name", None),
            "raw_data": dict(getattr(job, "raw_data", None) or {}),
        }

        listing_payload = getattr(listing, "listing_payload", None)
        if isinstance(listing_payload, dict):
            payload.update(dict(listing_payload))

        detail_payload = detail_payload_override
        if detail_payload is None:
            detail_payload = getattr(listing, "detail_payload", None)
        if isinstance(detail_payload, dict):
            payload.update(dict(detail_payload))
        elif isinstance(getattr(job, "raw_data", None), dict):
            payload.update(dict(job.raw_data))

        return build_offertoday_canonical_job(payload)
