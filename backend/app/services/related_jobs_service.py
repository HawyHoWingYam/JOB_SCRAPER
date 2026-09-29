from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.job import Job
from app.models.related_jobs_snapshot import (
    JobRelatedJobsSnapshot,
    JobRelatedJobsSnapshotItem,
)
from app.services.job_recommendation_service import JobRecommendationService
from app.utils.time import utc_now


class RelatedJobsService:
    """Persist and read the current provider-neutral Related Jobs result."""

    MAX_RESULTS = 5

    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_snapshot(
        self,
        *,
        source_job_id: UUID,
        source_evidence_hash: str,
        model_provenance: dict[str, object],
        selections: Sequence[dict[str, object]],
    ) -> None:
        if len(selections) > self.MAX_RESULTS:
            raise ValueError(
                f"Related Jobs snapshot supports at most {self.MAX_RESULTS} items"
            )
        snapshot = self.db.get(JobRelatedJobsSnapshot, source_job_id)
        now = utc_now()
        if snapshot is None:
            snapshot = JobRelatedJobsSnapshot(
                source_job_id=source_job_id,
                source_evidence_hash=source_evidence_hash,
                model_provenance=dict(model_provenance),
                completed_at=now,
                updated_at=now,
            )
            self.db.add(snapshot)
            self.db.flush()
        else:
            snapshot.source_evidence_hash = source_evidence_hash
            snapshot.model_provenance = dict(model_provenance)
            snapshot.completed_at = now
            snapshot.updated_at = now
            self.db.execute(
                delete(JobRelatedJobsSnapshotItem).where(
                    JobRelatedJobsSnapshotItem.source_job_id == source_job_id
                )
            )
            self.db.flush()

        for position, selection in enumerate(selections):
            target_job_id = UUID(str(selection.get("job_id") or ""))
            reason = str(selection.get("reason") or "").strip()
            if not reason:
                raise ValueError("Related Jobs snapshot reason is required")
            self.db.add(
                JobRelatedJobsSnapshotItem(
                    source_job_id=source_job_id,
                    target_job_id=target_job_id,
                    position=position,
                    reason=reason,
                )
            )
        self.db.flush()

    def recommend_for_job(self, job_id: UUID, *, limit: int = 5) -> dict[str, Any]:
        rows = tuple(
            self.db.execute(
                select(JobRelatedJobsSnapshotItem, Job, Company)
                .join(Job, Job.id == JobRelatedJobsSnapshotItem.target_job_id)
                .join(Company, Company.id == Job.company_id)
                .where(
                    JobRelatedJobsSnapshotItem.source_job_id == job_id,
                    Job.is_deleted.is_(False),
                )
                .order_by(JobRelatedJobsSnapshotItem.position)
                .limit(min(max(limit, 0), self.MAX_RESULTS))
            )
        )
        if rows:
            return {
                "result_source": "ai_ranked",
                "recommendations": [
                    {
                        "id": job.id,
                        "job_id": job.job_id,
                        "title": job.title,
                        "company_name": company.name,
                        "location": job.location,
                        "posted_date": job.posted_date.isoformat()
                        if job.posted_date
                        else None,
                        "reason": item.reason,
                    }
                    for item, job, company in rows
                ],
            }
        return {
            "result_source": "similarity",
            "recommendations": JobRecommendationService(self.db).recommend_for_job(
                job_id, limit=limit
            ),
        }


__all__ = ["RelatedJobsService"]
