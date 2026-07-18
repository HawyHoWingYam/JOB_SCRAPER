"""
Job Repository - Data access layer for Job entities.

Handles job lookup, creation, updates, and upsert logic.
"""

import logging
from datetime import UTC, datetime
import json
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID

from app.models.job import Job
from app.utils.source_identity import normalize_source_site

logger = logging.getLogger(__name__)

_LEGACY_SOURCE_ATTRIBUTE_FIELDS = frozenset(
    {
        "employment_type",
        "source_classification_id",
        "source_classification_name",
        "source_subclassification_id",
        "source_subclassification_name",
    }
)


class JobRepository:
    """Repository for Job database operations."""

    def upsert_source_job(
        self,
        db: Session,
        job_data: Dict[str, Any],
        skip_existing: bool = False,
        auto_commit: bool = True,
    ) -> tuple[Job, str]:
        forbidden_fields = sorted(
            _LEGACY_SOURCE_ATTRIBUTE_FIELDS.intersection(job_data)
        )
        if forbidden_fields:
            raise ValueError(
                "source-aware upsert cannot write legacy Source Job Attribute "
                f"fields: {', '.join(forbidden_fields)}"
            )
        source_site = normalize_source_site(job_data.get("source_site"))
        source_job_id = str(job_data.get("source_job_id") or "").strip()
        if not source_job_id:
            raise ValueError("source_job_id is required for source-aware upsert")

        normalized_data = dict(job_data)
        normalized_data["source_site"] = source_site
        normalized_data["source_job_id"] = source_job_id
        existing = self.get_job_by_source_key(
            db,
            source_site=source_site,
            source_job_id=source_job_id,
        )
        if existing is None:
            return (
                self._create_source_job(
                    db,
                    normalized_data,
                    auto_commit=auto_commit,
                ),
                "created",
            )
        if skip_existing:
            return existing, "skipped"

        changed = False
        for key, value in normalized_data.items():
            if not hasattr(existing, key) or key in {"id", "created_at"}:
                continue
            if not self._values_equal(getattr(existing, key), value):
                setattr(existing, key, value)
                changed = True

        if not changed:
            return existing, "skipped"

        if auto_commit:
            db.commit()
            db.refresh(existing)
        else:
            db.flush()
        return existing, "updated"

    def upsert_job(
        self,
        db: Session,
        job_data: Dict[str, Any],
        skip_existing: bool = False,
        auto_commit: bool = True,
    ) -> tuple[Job, str]:
        """Reject the retired generic writer; collected Jobs use source identity."""
        raise ValueError("generic Job writes are retired; use upsert_source_job")

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
                Job.is_deleted.is_(False),
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
                .filter(Job.job_id == job_id, Job.is_deleted.is_(False))
                .first()
            )
        except Exception as e:
            logger.error(f"Error querying job by job_id {job_id}: {e}")
            return None

    def get_job_by_source_key(
        self,
        db: Session,
        *,
        source_site: str,
        source_job_id: str,
    ) -> Optional[Job]:
        try:
            return (
                db.query(Job)
                .filter(
                    Job.source_site == normalize_source_site(source_site),
                    Job.source_job_id == str(source_job_id).strip(),
                    Job.is_deleted.is_(False),
                )
                .first()
            )
        except Exception as e:
            logger.error(
                "Error querying job by source key %s/%s: %s",
                source_site,
                source_job_id,
                e,
            )
            return None

    def list_existing_jobs_by_source_ids(
        self,
        db: Session,
        *,
        source_site: str,
        source_job_ids: List[str],
        raise_on_error: bool = False,
    ) -> dict[str, Job]:
        normalized_source_site = normalize_source_site(source_site)
        normalized_source_job_ids = [str(source_job_id).strip() for source_job_id in source_job_ids if str(source_job_id).strip()]
        if not normalized_source_job_ids:
            return {}

        try:
            rows = (
                db.query(Job)
                .filter(
                    Job.source_site == normalized_source_site,
                    Job.source_job_id.in_(normalized_source_job_ids),
                    Job.is_deleted.is_(False),
                )
                .all()
            )
            return {str(job.source_job_id).strip(): job for job in rows if str(job.source_job_id).strip()}
        except Exception as e:
            logger.error(
                "Error querying jobs by source ids for source_site=%s: %s",
                normalized_source_site,
                e,
            )
            if raise_on_error:
                raise
            return {}

    def create_job(
        self, db: Session, job_data: Dict[str, Any], auto_commit: bool = True
    ) -> Job:
        """Reject the retired generic writer; collected Jobs use source identity."""
        raise ValueError("generic Job writes are retired; use upsert_source_job")

    def _create_source_job(
        self, db: Session, job_data: Dict[str, Any], auto_commit: bool = True
    ) -> Job:
        """
        Create a Job after ``upsert_source_job`` validates source-owned fields.

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
                source_job_id=job_data.get("source_job_id"),
                company_id=job_data.get("company_id"),
                title=job_data.get("title"),
                description=job_data.get("description"),
                experience_min_years=job_data.get("experience_min_years"),
                experience_max_years=job_data.get("experience_max_years"),
                salary_range=job_data.get("salary_range"),
                salary_min=job_data.get("salary_min"),
                salary_max=job_data.get("salary_max"),
                salary_currency=job_data.get("salary_currency"),
                location=job_data.get("location"),
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
        forbidden_fields = sorted(
            _LEGACY_SOURCE_ATTRIBUTE_FIELDS.intersection(job_data)
        )
        if forbidden_fields:
            raise ValueError(
                "generic Job update cannot write legacy Source Job Attribute "
                f"fields: {', '.join(forbidden_fields)}"
            )
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

    def _values_equal(self, left, right) -> bool:
        return self._normalize_comparable_value(left) == self._normalize_comparable_value(right)

    def _normalize_comparable_value(self, value):
        if isinstance(value, datetime):
            return self._normalize_datetime(value)
        if isinstance(value, (dict, list)):
            return json.dumps(value, sort_keys=True)
        if isinstance(value, str):
            normalized = value.strip()
            try:
                parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
                return self._normalize_datetime(parsed)
            except ValueError:
                return normalized
        return value

    def _normalize_datetime(self, value: datetime) -> str:
        normalized = value
        if normalized.tzinfo is not None:
            normalized = normalized.astimezone(UTC).replace(tzinfo=None)
        return normalized.isoformat()
