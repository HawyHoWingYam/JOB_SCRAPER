from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


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


def build_ctgoodjobs_canonical_job(parsed_job: dict[str, Any]) -> CanonicalScrapedJob:
    raw_job_id = str(parsed_job.get("job_id") or "").strip()
    source_job_id = raw_job_id.removeprefix("ctgoodjobs:")
    return CanonicalScrapedJob(
        source_site="ctgoodjobs",
        source_job_id=source_job_id,
        source_url=parsed_job.get("url") or f"https://jobs.ctgoodjobs.hk/job/{source_job_id}",
        title=parsed_job.get("title") or "",
        description=parsed_job.get("description_html") or parsed_job.get("description_text"),
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
