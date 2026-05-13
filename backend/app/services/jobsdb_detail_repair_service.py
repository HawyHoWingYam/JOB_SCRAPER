from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Job
from app.utils.data_mapper import parse_listing_date, parse_salary_range


class JobsDBDetailRepairService:
    def __init__(self, db: Session):
        self.db = db

    def list_candidate_jobs(self, *, limit: int = 100) -> list[Job]:
        return (
            self.db.query(Job)
            .filter(Job.source_site == "jobsdb", Job.is_deleted == False)
            .order_by(Job.updated_at.desc(), Job.created_at.desc())
            .limit(limit)
            .all()
        )

    def is_degraded_job(self, job: Job) -> bool:
        if getattr(job, "source_site", None) != "jobsdb":
            return False

        description = str(job.description or "").strip()
        if not description:
            return True
        if len(description) < 250:
            return True
        if not str(job.source_subclassification_name or "").strip():
            return True
        return False

    def apply_parsed_detail(self, job: Job, parsed_detail: dict) -> None:
        description = parsed_detail.get("description_html") or parsed_detail.get("abstract")
        salary_range = parsed_detail.get("salary")
        salary_min, salary_max, salary_currency = parse_salary_range(salary_range)
        posted_date = parse_listing_date(parsed_detail.get("listing_date"))

        if description:
            job.description = description
        if parsed_detail.get("title"):
            job.title = parsed_detail["title"]
        job.source_classification_id = parsed_detail.get("classification_id")
        job.source_classification_name = parsed_detail.get("classification")
        job.source_subclassification_id = parsed_detail.get("subclassification_id")
        job.source_subclassification_name = parsed_detail.get("subclassification")
        job.location = parsed_detail.get("location")
        job.employment_type = parsed_detail.get("work_type")
        job.salary_range = salary_range
        job.salary_min = salary_min
        job.salary_max = salary_max
        job.salary_currency = salary_currency
        job.posted_date = posted_date

        existing_raw = dict(job.raw_data or {})
        existing_raw.update(parsed_detail)
        job.raw_data = existing_raw
        job.updated_at = datetime.utcnow()

    def iter_repair_candidates(self, *, limit: int = 100) -> list[Job]:
        return [job for job in self.list_candidate_jobs(limit=limit) if self.is_degraded_job(job)]
