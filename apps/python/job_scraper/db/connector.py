"""Database connection and operations."""

import logging
import os
from typing import Dict, List, Optional

import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from ..models.job import Job

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Create base class for SQLAlchemy models
Base = declarative_base()


# Define the Jobs table
class JobModel(Base):
    """SQLAlchemy model for jobs table."""

    __tablename__ = "jobs"

    id = sa.Column(sa.String, primary_key=True)
    title = sa.Column(sa.String, nullable=False)
    description = sa.Column(sa.Text, nullable=True)
    url = sa.Column(sa.String, nullable=False)

    company_name = sa.Column(sa.String, nullable=False)
    company_website = sa.Column(sa.String, nullable=True)
    company_logo_url = sa.Column(sa.String, nullable=True)

    location = sa.Column(sa.String, nullable=False)
    remote = sa.Column(sa.Boolean, default=False)
    work_type = sa.Column(sa.String, nullable=True)

    salary_min = sa.Column(sa.Float, nullable=True)
    salary_max = sa.Column(sa.Float, nullable=True)
    salary_currency = sa.Column(sa.String, nullable=True)
    salary_period = sa.Column(sa.String, nullable=True)

    date_posted = sa.Column(sa.DateTime, nullable=True)
    date_scraped = sa.Column(sa.DateTime, nullable=False)

    source = sa.Column(sa.String, nullable=False)
    source_id = sa.Column(sa.String, nullable=False)

    skills = sa.Column(sa.JSON, nullable=True)
    experience_level = sa.Column(sa.String, nullable=True)
    education_level = sa.Column(sa.String, nullable=True)
    benefits = sa.Column(sa.JSON, nullable=True)

    raw_data = sa.Column(sa.JSON, nullable=True)


class DatabaseConnector:
    """Database connection and operations."""

    def __init__(self):
        """Initialize database connection."""
        db_uri = os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/job_scraper"
        )

        self.engine = sa.create_engine(db_uri)
        self.Session = sessionmaker(bind=self.engine)

        # Create tables if they don't exist
        Base.metadata.create_all(self.engine)

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

                # Check if job already exists
                existing_job = (
                    session.query(JobModel)
                    .filter(
                        JobModel.source == job.source,
                        JobModel.source_id == job.source_id,
                    )
                    .first()
                )

                if existing_job:
                    # Update existing job
                    for key, value in job_model.__dict__.items():
                        if key != "_sa_instance_state" and key != "id":
                            setattr(existing_job, key, value)
                else:
                    # Add new job
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
                            JobModel.title.ilike(search_term),
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

                if "remote" in filters:
                    query = query.filter(JobModel.remote == filters["remote"])

            # Apply limit and get results
            jobs = query.order_by(JobModel.date_scraped.desc()).limit(limit).all()

            # Convert SQLAlchemy models to dictionaries
            return [self._convert_to_dict(job) for job in jobs]

        except SQLAlchemyError as e:
            logger.error(f"Error getting jobs from database: {e}")
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
        return JobModel(
            id=f"{job.source}_{job.source_id}",
            title=job.title,
            description=job.description,
            url=job.url,
            company_name=job.company.name,
            company_website=job.company.website,
            company_logo_url=job.company.logo_url,
            location=job.location,
            remote=job.remote,
            work_type=job.work_type,
            salary_min=job.salary_min,
            salary_max=job.salary_max,
            salary_currency=job.salary_currency,
            salary_period=job.salary_period,
            date_posted=job.date_posted,
            date_scraped=job.date_scraped,
            source=job.source,
            source_id=job.source_id,
            skills=job.skills,
            experience_level=job.experience_level,
            education_level=job.education_level,
            benefits=job.benefits,
            raw_data=job.raw_data,
        )

    def _convert_to_dict(self, job_model: JobModel) -> Dict:
        """Convert SQLAlchemy JobModel to dictionary.

        Args:
            job_model: SQLAlchemy JobModel

        Returns:
            Job as dictionary
        """
        return {
            "id": job_model.id,
            "title": job_model.title,
            "description": job_model.description,
            "url": job_model.url,
            "company": {
                "name": job_model.company_name,
                "website": job_model.company_website,
                "logo_url": job_model.company_logo_url,
            },
            "location": job_model.location,
            "remote": job_model.remote,
            "work_type": job_model.work_type,
            "salary": {
                "min": job_model.salary_min,
                "max": job_model.salary_max,
                "currency": job_model.salary_currency,
                "period": job_model.salary_period,
            },
            "date_posted": (
                job_model.date_posted.isoformat() if job_model.date_posted else None
            ),
            "date_scraped": (
                job_model.date_scraped.isoformat() if job_model.date_scraped else None
            ),
            "source": job_model.source,
            "source_id": job_model.source_id,
            "skills": job_model.skills,
            "experience_level": job_model.experience_level,
            "education_level": job_model.education_level,
            "benefits": job_model.benefits,
        }
