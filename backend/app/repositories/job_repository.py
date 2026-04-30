"""
Job Repository - Data access layer for Job entities.

Handles job lookup, creation, updates, and upsert logic.
"""

import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from app.models.job import Job

logger = logging.getLogger(__name__)


class JobRepository:
    """Repository for Job database operations."""

    def upsert_job(
        self,
        db: Session,
        job_data: Dict[str, Any],
        skip_existing: bool = False,
        auto_commit: bool = True,
    ) -> tuple[Job, str]:
        """
        Create or update job (upsert pattern).

        Args:
            db: SQLAlchemy session
            job_data: Job data dict
            skip_existing: If True, skip existing jobs instead of updating

        Returns:
            (Job, action: str) - Job instance and action taken: "created", "updated", or "skipped"
        """
        existing = self.get_job_by_job_id(db, job_data["job_id"])

        if existing:
            if skip_existing:
                return existing, "skipped"
            return self.update_job(db, existing.id, job_data, auto_commit=auto_commit), "updated"
        else:
            return self.create_job(db, job_data, auto_commit=auto_commit), "created"

    def get_existing_job_ids(self, db: Session, job_ids: List[str]) -> set[str]:
        """
        Batch query which job_ids already exist in database.

        Args:
            db: SQLAlchemy session
            job_ids: List of job_ids to check

        Returns:
            Set of existing job_ids
        """
        try:
            results = db.query(Job.job_id).filter(
                Job.job_id.in_(job_ids),
                Job.is_deleted == False
            ).all()
            return {row.job_id for row in results}
        except Exception as e:
            logger.error(f"Error querying existing job_ids: {e}")
            return set()

    def get_job_by_job_id(self, db: Session, job_id: str) -> Optional[Job]:
        """
        Get job by external job_id (JobsDB ID).

        Args:
            db: SQLAlchemy session
            job_id: External job identifier from JobsDB

        Returns:
            Job instance or None if not found
        """
        try:
            return (
                db.query(Job)
                .filter(Job.job_id == job_id, Job.is_deleted == False)
                .first()
            )
        except Exception as e:
            logger.error(f"Error querying job by job_id {job_id}: {e}")
            return None

    def create_job(
        self, db: Session, job_data: Dict[str, Any], auto_commit: bool = True
    ) -> Job:
        """
        Create a new job.

        Args:
            db: SQLAlchemy session
            job_data: Job data dict

        Returns:
            Created Job instance

        Raises:
            IntegrityError: If job with same job_id already exists
        """
        try:
            job = Job(
                job_id=job_data.get("job_id"),
                source_site=job_data.get("source_site") or "jobsdb",
                company_id=job_data.get("company_id"),
                title=job_data.get("title"),
                description=job_data.get("description"),
                source_classification_id=job_data.get("source_classification_id"),
                source_classification_name=job_data.get("source_classification_name"),
                source_subclassification_id=job_data.get("source_subclassification_id"),
                source_subclassification_name=job_data.get("source_subclassification_name"),
                experience_min_years=job_data.get("experience_min_years"),
                experience_max_years=job_data.get("experience_max_years"),
                salary_range=job_data.get("salary_range"),
                salary_min=job_data.get("salary_min"),
                salary_max=job_data.get("salary_max"),
                salary_currency=job_data.get("salary_currency"),
                location=job_data.get("location"),
                employment_type=job_data.get("employment_type"),
                ai_category=job_data.get("ai_category"),
                ai_summary=job_data.get("ai_summary"),
                posted_date=job_data.get("posted_date"),
                raw_data=job_data.get("raw_data"),
            )
            db.add(job)
            if auto_commit:
                db.commit()
            else:
                db.flush()
            db.refresh(job)
            logger.debug(f"Created job: {job.title} (id: {job.job_id})")
            return job
        except IntegrityError as e:
            if auto_commit:
                db.rollback()
            else:
                raise
            logger.warning(f"Integrity error creating job {job_data.get('job_id')}: {e}")
            # Try to find existing job
            existing = self.get_job_by_job_id(db, job_data["job_id"])
            if existing:
                return existing
            raise
        except Exception as e:
            if auto_commit:
                db.rollback()
            logger.error(f"Error creating job: {e}")
            raise

    def update_job(
        self,
        db: Session,
        job_id: UUID,
        job_data: Dict[str, Any],
        auto_commit: bool = True,
    ) -> Job:
        """
        Update an existing job.

        Args:
            db: SQLAlchemy session
            job_id: Job UUID (primary key)
            job_data: Job data dict with fields to update

        Returns:
            Updated Job instance
        """
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job:
                raise ValueError(f"Job not found: {job_id}")

            # Update fields
            for key, value in job_data.items():
                if hasattr(job, key) and key not in ["id", "job_id", "created_at"]:
                    setattr(job, key, value)

            if auto_commit:
                db.commit()
            else:
                db.flush()
            db.refresh(job)
            logger.debug(f"Updated job: {job.title} (id: {job.job_id})")
            return job
        except Exception as e:
            if auto_commit:
                db.rollback()
            logger.error(f"Error updating job {job_id}: {e}")
            raise
