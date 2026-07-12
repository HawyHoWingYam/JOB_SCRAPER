from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from types import MappingProxyType
from typing import Any

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session, joinedload

from app.models.crawl_job_listing import CrawlJobListing
from app.models.job import Job
from app.repositories.company_repository import CompanyRepository
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.job_repository import JobRepository
from app.sources.contracts import (
    CanonicalScrapedJob,
    build_offertoday_canonical_job,
    build_offertoday_company_data,
    build_offertoday_job_data,
)
from app.sources.offertoday.detail_identity import (
    OfferTodayDetailFetchResult,
    OfferTodayDetailIdentity,
    OfferTodayIdentityAuthorityIndex,
    OfferTodayIdentityError,
    build_offertoday_identity_authority_index,
    resolve_offertoday_detail_identity,
    validate_offertoday_detail_identity,
)
from app.sources.offertoday.response_policy import OfferTodayResponseKind


_AUTO_REPAIR_BLOCKING_DETAIL_STATUSES = (
    "terminal_unavailable",
    "identity_conflict",
)


def _with_canonical_identity(
    payload: Mapping[str, Any],
    identity: OfferTodayDetailIdentity,
) -> dict[str, Any]:
    return {
        **deepcopy(dict(payload)),
        "job_id": identity.job_id,
        "encrypted_job_id": identity.encrypted_job_id,
        "encrypted_job_id_source": identity.encrypted_job_id_source,
    }


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
        crawl_job_listing_repository: CrawlJobListingRepository | None = None,
        crawl_job_repository: CrawlJobRepository | None = None,
    ) -> None:
        self.db = db
        self.company_repository = company_repository or CompanyRepository()
        self.job_repository = job_repository or JobRepository()
        self.crawl_job_listing_repository = crawl_job_listing_repository
        if self.crawl_job_listing_repository is None and db is not None:
            self.crawl_job_listing_repository = CrawlJobListingRepository()
        self.crawl_job_repository = crawl_job_repository
        if self.crawl_job_repository is None and db is not None:
            self.crawl_job_repository = CrawlJobRepository()
        self._cached_identity_authority_index: (
            OfferTodayIdentityAuthorityIndex | None
        ) = None
        self._cached_identity_error_by_job: Mapping[str, OfferTodayIdentityError] = (
            MappingProxyType({})
        )

    def list_candidate_jobs(self, *, limit: int | None = None) -> list[Job]:
        if self.db is None:
            return []

        query = (
            self.db.query(Job)
            .options(joinedload(Job.company))
            .filter(Job.source_site == "offertoday", Job.is_deleted.is_(False))
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
            .filter(Job.source_site == "offertoday", Job.is_deleted.is_(False))
            .filter(or_(Job.description.is_(None), Job.description == ""))
            .filter(
                ~exists().where(
                    and_(
                        CrawlJobListing.source_site == "offertoday",
                        CrawlJobListing.source_job_id == Job.source_job_id,
                        CrawlJobListing.detail_status.in_(
                            _AUTO_REPAIR_BLOCKING_DETAIL_STATUSES
                        ),
                    )
                )
            )
            .order_by(Job.updated_at.desc(), Job.created_at.desc())
        )
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def repair_job(self, job: Job) -> OfferTodayRepairResult:
        if self.db is None:
            raise ValueError("repair_job requires an active database session")

        listing = self.get_latest_completed_listing(
            job.source_job_id
        ) or self.get_latest_listing(job.source_job_id)
        identity = self.resolve_detail_identity(job, listing)
        detail_payload = getattr(listing, "detail_payload", None)
        listing_payload = getattr(listing, "listing_payload", None)
        repair_payload = (
            detail_payload
            if isinstance(detail_payload, Mapping)
            else listing_payload if isinstance(listing_payload, Mapping) else {}
        )
        canonical_detail = _with_canonical_identity(repair_payload, identity)
        canonical = self.build_canonical_job_snapshot(
            job,
            listing,
            detail_payload_override=canonical_detail,
            identity=identity,
        )
        return self._persist_canonical_job(job, canonical, listing)

    def repair_job_with_parsed_detail(
        self,
        job: Job,
        parsed_detail: dict[str, Any],
    ) -> OfferTodayRepairResult:
        if self.db is None:
            raise ValueError(
                "repair_job_with_parsed_detail requires an active database session"
            )

        listing = self.get_latest_listing(job.source_job_id)
        expected_identity = self.resolve_detail_identity(job, listing)
        validate_offertoday_detail_identity(expected_identity, parsed_detail)
        canonical_detail = _with_canonical_identity(parsed_detail, expected_identity)

        canonical = self.build_canonical_job_snapshot(
            job,
            listing,
            detail_payload_override=canonical_detail,
            identity=expected_identity,
        )
        repair_result = self._persist_canonical_job(job, canonical, listing)
        if listing is not None:
            listing.detail_payload = deepcopy(canonical_detail)
            listing.detail_status = "completed"
            listing.detail_error_message = None
            listing.detail_completed_at = datetime.now(UTC)
        return repair_result

    def repair_job_with_detail_result(
        self,
        job: Job,
        result: OfferTodayDetailFetchResult,
    ) -> OfferTodayRepairResult:
        if self.db is None:
            raise ValueError(
                "repair_job_with_detail_result requires an active database session"
            )

        listing = self.get_latest_listing(job.source_job_id)
        expected_identity = self.resolve_detail_identity(job, listing)
        if result.identity != expected_identity:
            raise OfferTodayIdentityError(
                "OfferToday detail result ownership mismatch: "
                f"expected jobId={expected_identity.job_id!r}, "
                f"encryptJobId={expected_identity.encrypted_job_id!r}, "
                f"source={expected_identity.encrypted_job_id_source!r}; "
                f"result jobId={result.identity.job_id!r}, "
                f"encryptJobId={result.identity.encrypted_job_id!r}, "
                f"source={result.identity.encrypted_job_id_source!r}"
            )

        if result.classification.kind is OfferTodayResponseKind.SUCCESS:
            if result.canonical_detail is None:
                raise ValueError(
                    "Successful OfferToday detail result has no canonical_detail"
                )
            if result.parsed_detail is None:
                raise ValueError(
                    "Successful OfferToday detail result has no parsed_detail"
                )

            validate_offertoday_detail_identity(
                expected_identity,
                result.parsed_detail,
            )
            canonical_detail = deepcopy(result.canonical_detail)

            canonical = self.build_canonical_job_snapshot(
                job,
                listing,
                detail_payload_override=canonical_detail,
                identity=expected_identity,
            )
            repair_result = self._persist_canonical_job(job, canonical, listing)
            if listing is not None:
                listing.detail_payload = deepcopy(canonical_detail)
                listing.detail_status = "completed"
                listing.detail_error_message = None
                listing.detail_completed_at = datetime.now(UTC)
            return repair_result

        detail_status = {
            OfferTodayResponseKind.TERMINAL_UNAVAILABLE: "terminal_unavailable",
            OfferTodayResponseKind.ID_MISMATCH: "identity_conflict",
        }.get(result.classification.kind, "failed")
        affected_listings = (
            self.get_listings_for_canonical_id(job.source_job_id)
            if detail_status in _AUTO_REPAIR_BLOCKING_DETAIL_STATUSES
            else ([listing] if listing is not None else [])
        )
        error_message = json.dumps(
            {
                "code": result.classification.code,
                "encrypted_job_id": result.identity.encrypted_job_id,
                "encrypted_job_id_source": (result.identity.encrypted_job_id_source),
                "job_id": result.identity.job_id,
                "kind": result.classification.kind.value,
                "message": result.classification.message,
                "retryable": result.classification.retryable,
                "stop_batch": result.classification.stop_batch,
            },
            sort_keys=True,
        )
        completed_at = datetime.now(UTC)
        for affected_listing in affected_listings:
            affected_listing.detail_payload = deepcopy(result.raw_response)
            affected_listing.detail_status = detail_status
            affected_listing.detail_error_message = error_message
            affected_listing.detail_completed_at = completed_at

        return OfferTodayRepairResult(
            action=result.classification.kind.value,
            description_repaired=False,
            company_reassigned=False,
            listing_attached=False,
        )

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
            description_repaired=not before_description
            and bool(str(repaired_job.description or "").strip()),
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

    def get_listings_for_canonical_id(
        self, source_job_id: str
    ) -> list[CrawlJobListing]:
        if self.db is None:
            return []

        return (
            self.db.query(CrawlJobListing)
            .filter(
                CrawlJobListing.source_site == "offertoday",
                CrawlJobListing.source_job_id == str(source_job_id or "").strip(),
            )
            .order_by(
                CrawlJobListing.created_at.asc(),
                CrawlJobListing.id.asc(),
            )
            .all()
        )

    def get_latest_completed_listing(
        self, source_job_id: str
    ) -> CrawlJobListing | None:
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

    def _identity_authority_index(self) -> OfferTodayIdentityAuthorityIndex:
        if self._cached_identity_authority_index is not None:
            return self._cached_identity_authority_index
        if self.db is None:
            raise ValueError(
                "identity authority audit requires an active database session"
            )
        if (
            self.crawl_job_listing_repository is None
            or self.crawl_job_repository is None
        ):
            raise RuntimeError("identity authority repositories are unavailable")

        identities: list[OfferTodayDetailIdentity] = []
        identity_error_by_job: dict[str, OfferTodayIdentityError] = {}

        def add_evidence(
            source_job_id: Any,
            payload: Mapping[str, Any],
        ) -> None:
            canonical_source_job_id = str(source_job_id or "").strip()
            try:
                identities.append(
                    resolve_offertoday_detail_identity(
                        source_job_id=canonical_source_job_id,
                        listing_payload=payload,
                    )
                )
            except OfferTodayIdentityError as exc:
                if canonical_source_job_id:
                    identity_error_by_job.setdefault(canonical_source_job_id, exc)

        for row in self.crawl_job_listing_repository.list_offertoday_identity_history(
            self.db
        ):
            listing_payload = getattr(row, "listing_payload", None)
            add_evidence(
                getattr(row, "source_job_id", None),
                dict(listing_payload) if isinstance(listing_payload, Mapping) else {},
            )
        observations = (
            self.crawl_job_repository.list_offertoday_listing_identity_observations(
                self.db
            )
        )
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            add_evidence(
                observation.get("source_job_id"),
                observation,
            )

        self._cached_identity_error_by_job = MappingProxyType(
            dict(identity_error_by_job)
        )
        self._cached_identity_authority_index = (
            build_offertoday_identity_authority_index(tuple(identities))
        )
        return self._cached_identity_authority_index

    def resolve_detail_identity(
        self,
        job: Job | Any,
        listing: CrawlJobListing | Any | None = None,
    ) -> OfferTodayDetailIdentity:
        listing_payload = getattr(listing, "listing_payload", None)
        listing_identity = resolve_offertoday_detail_identity(
            source_job_id=getattr(job, "source_job_id", None),
            listing_payload=(
                dict(listing_payload) if isinstance(listing_payload, Mapping) else {}
            ),
        )
        if self.db is None:
            return listing_identity

        index = self._identity_authority_index()
        identity_error = self._cached_identity_error_by_job.get(listing_identity.job_id)
        if identity_error is not None:
            raise identity_error
        conflict_reason = index.conflict_reason_by_job.get(listing_identity.job_id)
        if conflict_reason is not None:
            raise OfferTodayIdentityError(
                f"OfferToday repair identity conflict: {conflict_reason}",
                classification=conflict_reason,
            )
        return index.authoritative_identity_by_job.get(
            listing_identity.job_id,
            listing_identity,
        )

    def resolve_detail_identifiers(
        self,
        job: Job | Any,
        listing: CrawlJobListing | Any | None = None,
    ) -> tuple[str, str]:
        identity = self.resolve_detail_identity(job, listing)
        return identity.job_id, identity.encrypted_job_id

    def build_canonical_job_snapshot(
        self,
        job: Job | Any,
        listing: CrawlJobListing | Any | None = None,
        *,
        detail_payload_override: dict[str, Any] | None = None,
        identity: OfferTodayDetailIdentity | None = None,
    ) -> CanonicalScrapedJob:
        payload = {
            "source_site": "offertoday",
            "job_id": getattr(job, "source_job_id", None),
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

        return build_offertoday_canonical_job(payload, identity=identity)
