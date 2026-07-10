from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from datetime import datetime
from typing import Any

from app.sources.offertoday.detail_identity import read_offertoday_identity_evidence
from app.utils.data_mapper import parse_listing_date, parse_salary_range
from app.utils.source_identity import (
    build_compat_company_id,
    build_compat_job_id,
    derive_source_company_id_from_raw_data,
)


def _normalize_salary_range(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    if isinstance(value, dict):
        for key in ("label", "display", "text"):
            label = value.get(key)
            if isinstance(label, str) and label.strip():
                return label.strip()
    return None


def _join_work_types(values: Any) -> str | None:
    if not isinstance(values, list):
        return None
    normalized = [str(value).strip() for value in values if str(value).strip()]
    if not normalized:
        return None
    return ", ".join(normalized)


def _build_listing_description(teaser: Any, bullet_points: Any) -> str | None:
    teaser_text = (
        str(teaser).strip() if isinstance(teaser, str) and teaser.strip() else ""
    )
    bullets = [
        str(point).strip() for point in (bullet_points or []) if str(point).strip()
    ]
    if teaser_text and bullets:
        return teaser_text + "\n\nHighlights:\n- " + "\n- ".join(bullets)
    if teaser_text:
        return teaser_text
    if bullets:
        return "Highlights:\n- " + "\n- ".join(bullets)
    return None


@dataclass(frozen=True)
class CanonicalScrapedJob:
    source_site: str
    source_job_id: str
    source_url: str
    title: str
    description: str | None
    company_name: str | None
    location: str | None
    salary_range: str | None
    employment_type: str | None
    source_classification_id: str | int | None
    source_classification_name: str | None
    source_subclassification_id: str | int | None
    source_subclassification_name: str | None
    posted_date: str | None
    raw_data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_jobsdb_canonical_job(
    parsed_job: dict[str, Any],
    *,
    source_url: str,
) -> CanonicalScrapedJob:
    source_job_id = str(parsed_job.get("jobsdb_id") or "").strip()
    return CanonicalScrapedJob(
        source_site="jobsdb",
        source_job_id=source_job_id,
        source_url=source_url,
        title=parsed_job.get("title") or "",
        description=parsed_job.get("description_html") or parsed_job.get("abstract"),
        company_name=parsed_job.get("advertiser_name"),
        location=parsed_job.get("location"),
        salary_range=_normalize_salary_range(parsed_job.get("salary")),
        employment_type=parsed_job.get("work_type"),
        source_classification_id=parsed_job.get("classification_id"),
        source_classification_name=parsed_job.get("classification"),
        source_subclassification_id=parsed_job.get("subclassification_id"),
        source_subclassification_name=parsed_job.get("subclassification"),
        posted_date=parsed_job.get("listing_date"),
        raw_data=dict(parsed_job),
    )


def build_jobsdb_listing_canonical_job(
    parsed_job: dict[str, Any],
    *,
    source_url: str,
) -> CanonicalScrapedJob:
    source_job_id = str(parsed_job.get("external_id") or "").strip()
    return CanonicalScrapedJob(
        source_site="jobsdb",
        source_job_id=source_job_id,
        source_url=source_url,
        title=parsed_job.get("title") or "",
        description=_build_listing_description(
            parsed_job.get("teaser"),
            parsed_job.get("bullet_points"),
        ),
        company_name=parsed_job.get("company_name"),
        location=parsed_job.get("location"),
        salary_range=_normalize_salary_range(parsed_job.get("salary_label")),
        employment_type=_join_work_types(parsed_job.get("work_types")),
        source_classification_id=parsed_job.get("classification_id"),
        source_classification_name=parsed_job.get("classification_name"),
        source_subclassification_id=parsed_job.get("subclassification_id"),
        source_subclassification_name=parsed_job.get("subclassification"),
        posted_date=parsed_job.get("listing_date"),
        raw_data=dict(parsed_job),
    )


def build_offertoday_canonical_job(parsed_job: dict[str, Any]) -> CanonicalScrapedJob:
    """Build a CanonicalScrapedJob from an OfferToday parsed job dict.

    Supports both listing and detail response formats.
    Takes the union of all fields and uses whichever is available.
    """
    from app.sources.offertoday.parsers import build_offertoday_job_url

    raw_job_id = read_offertoday_identity_evidence(
        parsed_job,
        field_names=("job_id", "jobId"),
        raw_field_name="jobId",
        evidence_name="jobId",
    )
    encrypted_id = read_offertoday_identity_evidence(
        parsed_job,
        field_names=("encrypted_job_id", "encryptJobId"),
        raw_field_name="encryptJobId",
        evidence_name="encryptJobId",
    )

    # Extract classification from job_functions (available in listing + detail)
    job_functions = (
        parsed_job.get("job_functions") or parsed_job.get("jobFunctions") or []
    )
    source_classification_id = None
    source_classification_name = None
    source_subclassification_id = None
    source_subclassification_name = None
    if job_functions and isinstance(job_functions, list) and len(job_functions) > 0:
        jf = job_functions[0]
        raw_code = str(jf.get("code") or "")
        source_classification_id = f"offertoday:{raw_code}" if raw_code else None
        source_classification_name = str(jf.get("name") or "")
        children = jf.get("children") or []
        if children and isinstance(children, list) and len(children) > 0:
            child = children[0]
            source_subclassification_id = (
                f"offertoday:{str(child.get('code') or '')}"
                if child.get("code")
                else None
            )
            source_subclassification_name = str(child.get("name") or "")

    return CanonicalScrapedJob(
        source_site="offertoday",
        source_job_id=raw_job_id,
        source_url=build_offertoday_job_url(encrypted_id),
        title=parsed_job.get("title") or parsed_job.get("jobName") or "",
        description=(
            parsed_job.get("description_html")
            or parsed_job.get("description_text")
            or parsed_job.get("jobDesc")
            or parsed_job.get("abstract")
        ),
        company_name=(
            parsed_job.get("company_name")
            or parsed_job.get("companyName")
            or parsed_job.get("brandName")
        ),
        location=(
            parsed_job.get("location")
            or parsed_job.get("locationDesc")
            or parsed_job.get("level3_location")
        ),
        salary_range=parsed_job.get("salary_range") or parsed_job.get("salaryDesc"),
        employment_type=(
            parsed_job.get("employment_type")
            or parsed_job.get("jobTypeDesc")
            or parsed_job.get("employ_type")
        ),
        source_classification_id=source_classification_id or None,
        source_classification_name=source_classification_name or None,
        source_subclassification_id=source_subclassification_id or None,
        source_subclassification_name=source_subclassification_name or None,
        posted_date=(
            parsed_job.get("posted_desc")
            or parsed_job.get("postDateDesc")
            or parsed_job.get("posted_at")
        ),
        raw_data=dict(parsed_job),
    )


def build_offertoday_company_data(
    canonical_job: CanonicalScrapedJob,
) -> dict[str, Any]:
    source_company_id = derive_source_company_id_from_raw_data(
        canonical_job.source_site,
        canonical_job.raw_data,
    )
    company_name = str(canonical_job.company_name or "").strip()
    if not source_company_id:
        source_company_id = _derive_fallback_source_company_id(
            source_site=canonical_job.source_site,
            company_name=company_name,
        )

    return {
        "source_site": canonical_job.source_site,
        "source_company_id": source_company_id,
        "company_id": build_compat_company_id(
            canonical_job.source_site, source_company_id
        ),
        "name": company_name,
        "industry": canonical_job.raw_data.get("company_industry"),
        "location": canonical_job.location,
        "extra_data": {
            "source_url": canonical_job.source_url,
            "raw_data": canonical_job.raw_data,
            "source_identity": (
                "fallback_company_name"
                if str(source_company_id).startswith("fallback:name:")
                else "source_company_id"
            ),
        },
    }


def build_offertoday_job_data(
    canonical_job: CanonicalScrapedJob,
    company_id: Any,
) -> dict[str, Any]:
    salary_range = _normalize_salary_range(canonical_job.salary_range)
    salary_min, salary_max, salary_currency = parse_salary_range(
        salary_range if isinstance(salary_range, str) else None
    )
    posted_date = _parse_optional_datetime(canonical_job.posted_date)

    return {
        "job_id": build_compat_job_id(
            canonical_job.source_site, canonical_job.source_job_id
        ),
        "source_site": canonical_job.source_site,
        "source_job_id": canonical_job.source_job_id,
        "company_id": company_id,
        "title": canonical_job.title,
        "description": canonical_job.description,
        "salary_range": salary_range,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": salary_currency,
        "location": canonical_job.location,
        "employment_type": canonical_job.employment_type,
        "source_classification_id": canonical_job.source_classification_id,
        "source_classification_name": canonical_job.source_classification_name,
        "source_subclassification_id": canonical_job.source_subclassification_id,
        "source_subclassification_name": canonical_job.source_subclassification_name,
        "posted_date": posted_date,
        "raw_data": canonical_job.raw_data,
    }


def _derive_fallback_source_company_id(*, source_site: str, company_name: str) -> str:
    normalized_company_name = " ".join(str(company_name or "").strip().lower().split())
    digest = hashlib.sha1(
        f"{source_site}:{normalized_company_name}".encode("utf-8")
    ).hexdigest()[:16]
    return f"fallback:name:{digest}"


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        parsed = parse_listing_date(value)
        if parsed is not None:
            return parsed
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def build_ctgoodjobs_canonical_job(parsed_job: dict[str, Any]) -> CanonicalScrapedJob:
    raw_job_id = str(parsed_job.get("job_id") or "").strip()
    source_job_id = raw_job_id.removeprefix("ctgoodjobs:")
    return CanonicalScrapedJob(
        source_site="ctgoodjobs",
        source_job_id=source_job_id,
        source_url=parsed_job.get("url")
        or f"https://jobs.ctgoodjobs.hk/job/{source_job_id}",
        title=parsed_job.get("title") or "",
        description=parsed_job.get("description_html")
        or parsed_job.get("description_text"),
        company_name=parsed_job.get("company_name"),
        location=parsed_job.get("location"),
        salary_range=parsed_job.get("salary_range"),
        employment_type=parsed_job.get("employment_type"),
        source_classification_id=parsed_job.get("source_classification_id"),
        source_classification_name=parsed_job.get("source_classification_name"),
        source_subclassification_id=parsed_job.get("source_subclassification_id"),
        source_subclassification_name=parsed_job.get("source_subclassification_name"),
        posted_date=parsed_job.get("posted_date"),
        raw_data=dict(parsed_job),
    )
