from __future__ import annotations

from sqlalchemy.orm import Session

from app.job_intelligence.product_read_model import JobIntelligenceProductReadModel
from app.models.job import Job
from app.schemas.job import JobDetailSchema, JobSchema


_JOB_DETAIL_SCALAR_FIELDS = (
    "original_job_url",
    "ai_enriched_at",
    "experience_min_years",
    "experience_max_years",
    "experience_level",
    "experience_summary",
    "experience_evidence",
    "expiry_date",
    "is_expired",
)


def compose_current_job_detail(db: Session, job: Job) -> JobDetailSchema:
    """Compose Job Detail without touching retired governed ORM relationships."""

    is_manual = str(job.source_site or "").strip().lower() == "manual"
    manual_evidence = job.manual_evidence if is_manual else None
    is_stale = bool(
        manual_evidence is not None
        and manual_evidence.enriched_evidence_hash is not None
        and manual_evidence.enriched_evidence_hash != manual_evidence.evidence_hash
    )
    if is_stale:
        freshness = "stale"
    elif job.ai_enriched_at is not None:
        freshness = "current"
    else:
        freshness = "not_enriched"

    if is_manual and not str(job.description or "").strip():
        eligibility = "needs_job_description"
    elif is_stale:
        eligibility = "stale"
    elif job.ai_enriched_at is not None:
        eligibility = "current"
    else:
        eligibility = "pending"

    payload = JobSchema.model_validate(job).model_dump(mode="python")
    payload.update(
        {field: getattr(job, field, None) for field in _JOB_DETAIL_SCALAR_FIELDS}
    )
    payload.update(
        {
            "company_name": job.company.name if job.company is not None else None,
            "company_ai_description": (
                job.company.ai_description if job.company is not None else None
            ),
            "company_website": (
                job.company.website if job.company is not None else None
            ),
            "origin": "manual_entry" if is_manual else str(job.source_site),
            "manual_editable": is_manual,
            "enrichment_eligibility": eligibility,
            "job_intelligence_freshness": freshness,
        }
    )
    payload.update(
        JobIntelligenceProductReadModel(db)
        .get_job_detail(job_id=job.id, company_id=job.company_id)
        .to_payload()
    )
    return JobDetailSchema.model_validate(payload)


__all__ = ["compose_current_job_detail"]
