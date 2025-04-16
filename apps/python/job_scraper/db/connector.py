"""Database connection and operations."""

import logging
import os
from typing import Dict, List, Optional

import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from job_scraper.models.job import Job

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Create base class for SQLAlchemy models
Base = declarative_base()


# Define the Jobs table
class JobModel(Base):
    """SQLAlchemy model for jobs table."""

    __tablename__ = "jobs"

    # Primary key with auto increment
    internal_id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    id = sa.Column(sa.Integer, nullable=False)

    # All other fields are nullable
    description = sa.Column(sa.Text, nullable=True)
    company_id = sa.Column(sa.Integer, nullable=True)
    company_name = sa.Column(sa.String(255), nullable=True)
    name = sa.Column(sa.String(255), nullable=True)  # Job title
    location = sa.Column(sa.String(255), nullable=True)
    work_type = sa.Column(sa.String(255), nullable=True)
    salary_description = sa.Column(sa.String(255), nullable=True)
    date_posted = sa.Column(sa.String(255), nullable=True)
    date_scraped = sa.Column(sa.String(255), nullable=True)
    source = sa.Column(sa.String(255), nullable=True)
    source_id = sa.Column(sa.Integer, nullable=True)
    other = sa.Column(sa.Text, nullable=True)
    remark = sa.Column(sa.Text, nullable=True)
    job_class = sa.Column(sa.String(255), nullable=True)
    job_subclass = sa.Column(sa.String(255), nullable=True)
    job_class_id = sa.Column(sa.Integer, nullable=True)
    job_subclass_id = sa.Column(sa.Integer, nullable=True)


class DatabaseConnector:
    """Database connection and operations."""

    def __init__(self):
        """Initialize database connection."""
        db_uri = os.getenv(
            "DATABASE_URL", "postgresql://postgres:admin@localhost:5432/job_scraper"
        )

        self.engine = sa.create_engine(db_uri)
        self.Session = sessionmaker(bind=self.engine)

        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)
        logger.info("Database connected and tables created if not exist")

    def save_jobs(self, jobs: List[Job]) -> int:
        """Save jobs to database.

        Args:
            jobs: List of Job objects to save

        Returns:
            Number of jobs saved
        """
        session = self.Session()
        saved_count = 0

        try:
            for job in jobs:
                # Convert Pydantic model to SQLAlchemy model
                job_model = self._convert_to_model(job)

                # For new jobs (no ID), just add them
                if job.id is None:
                    session.add(job_model)
                else:
                    # For existing jobs, update them
                    existing_job = (
                        session.query(JobModel).filter(JobModel.id == job.id).first()
                    )

                    if existing_job:
                        # Update existing job
                        for key, value in job_model.__dict__.items():
                            if key != "_sa_instance_state" and key != "id":
                                setattr(existing_job, key, value)
                    else:
                        # If ID doesn't exist, add as new
                        session.add(job_model)

                saved_count += 1

            session.commit()
            logger.info(f"Saved {saved_count} jobs to database")
            return saved_count

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error saving jobs to database: {e}")
            return 0

        finally:
            session.close()

    def get_jobs(self, filters: Optional[Dict] = None, limit: int = 100) -> List[Dict]:
        """Get jobs from database with optional filters.

        Args:
            filters: Dictionary of filter criteria
            limit: Maximum number of jobs to return

        Returns:
            List of jobs as dictionaries
        """
        session = self.Session()

        try:
            query = session.query(JobModel)

            # Apply filters if provided
            if filters:
                if "query" in filters:
                    search_term = f"%{filters['query']}%"
                    query = query.filter(
                        sa.or_(
                            JobModel.name.ilike(search_term),
                            JobModel.description.ilike(search_term),
                        )
                    )

                if "location" in filters:
                    location_term = f"%{filters['location']}%"
                    query = query.filter(JobModel.location.ilike(location_term))

                if "company" in filters:
                    company_term = f"%{filters['company']}%"
                    query = query.filter(JobModel.company_name.ilike(company_term))

                if "source" in filters:
                    query = query.filter(JobModel.source == filters["source"])

                if "job_class" in filters:
                    query = query.filter(JobModel.job_class == filters["job_class"])

            # Apply limit and get results
            jobs = query.order_by(JobModel.date_scraped.desc()).limit(limit).all()

            # Convert SQLAlchemy models to dictionaries
            return [self._convert_to_dict(job) for job in jobs]

        except SQLAlchemyError as e:
            logger.error(f"Error getting jobs from database: {e}")
            return []

        finally:
            session.close()

    def get_jobs_by_internal_id_range(self, start_id: int, end_id: int) -> List[str]:
        """Get job IDs for a range of internal IDs.

        Args:
            start_id: Starting internal ID
            end_id: Ending internal ID

        Returns:
            List of job IDs
        """
        session = self.Session()
        try:
            jobs = (
                session.query(JobModel.id)
                .filter(JobModel.internal_id.between(start_id, end_id))
                .all()
            )
            return [job[0] for job in jobs]  # Extract IDs from result tuples

        except SQLAlchemyError as e:
            logger.error(f"Error getting jobs from database: {e}")
            return []

        finally:
            session.close()


    def get_jobs_with_null_description(self, limit: int = 10) -> List[int]:
        """Get IDs of jobs with null descriptions.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job IDs
        """
        session = self.Session()
        try:
            jobs = (
                session.query(JobModel.id)
                .filter(sa.or_(JobModel.description.is_(None), JobModel.description == ""))
                .limit(limit)
                .all()
            )

            return [job[0] for job in jobs]

        except SQLAlchemyError as e:
            logger.error(f"Error getting jobs with null descriptions: {e}")
            return []

        finally:
            session.close()

    def _convert_to_model(self, job: Job) -> JobModel:
        """Convert Pydantic Job model to SQLAlchemy JobModel.

        Args:
            job: Pydantic Job object

        Returns:
            SQLAlchemy JobModel
        """
        job_model = JobModel(
            id=job.id,
            description=job.description,
            company_name=job.company_name,
            name=job.name,
            location=job.location,
            work_type=job.work_type,
            salary_description=job.salary_description,
            date_posted=job.date_posted,
            date_scraped=job.date_scraped,
            source=job.source,
            other=job.other,
            remark=job.remark,
            job_class=job.job_class,
            job_subclass=job.job_subclass,
        )

        # Only set ID if it exists (for updates)
        # if job.id is not None:
        #     job_model.id = job.id

        return job_model

    def _convert_to_dict(self, job_model: JobModel) -> Dict:
        """Convert SQLAlchemy JobModel to dictionary.

        Args:
            job_model: SQLAlchemy JobModel

        Returns:
            Job as dictionary
        """
        return {
            "internal_id": job_model.internal_id,
            "id": job_model.id,
            "description": job_model.description,
            "company_name": job_model.company_name,
            "name": job_model.name,
            "location": job_model.location,
            "work_type": job_model.work_type,
            "salary_description": job_model.salary_description,
            "date_posted": job_model.date_posted,
            "date_scraped": job_model.date_scraped,
            "source": job_model.source,
            "other": job_model.other,
            "remark": job_model.remark,
            "job_class": job_model.job_class,
            "job_subclass": job_model.job_subclass,
        }

    def update_job_description(self, job_id: str, description: str) -> bool:
        """Update the description for a specific job.

        Args:
            job_id: Job ID to update
            description: New job description

        Returns:
            True if successful, False otherwise
        """
        session = self.Session()

        try:
            # Find the job by ID
            job = session.query(JobModel).filter(JobModel.id == job_id).first()

            if not job:
                logger.error(f"Job with ID {job_id} not found")
                return False

            # Update the description
            job.description = description

            # Commit the changes
            session.commit()
            logger.info(f"Updated description for job ID {job_id}")
            return True

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error updating job description: {e}")
            return False

        finally:
            session.close()
