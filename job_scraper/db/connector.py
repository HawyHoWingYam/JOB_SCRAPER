"""Database connection and operations."""

import logging
import os
from typing import Dict, List, Optional
import psycopg2 
import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
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
    def __init__(self):
        """Initialize database connection."""
        try:
            # Get database connection string from environment variables or use default
            db_host = os.environ.get("DB_HOST", "localhost")
            db_name = os.environ.get("DB_NAME", "job_scraper")
            db_user = os.environ.get("DB_USER", "postgres")
            db_password = os.environ.get("DB_PASSWORD", "admin")
            db_port = os.environ.get("DB_PORT", "5432")
            
            # Create SQLAlchemy engine
            self.engine = create_engine(
                f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
            )
            
            # Create session factory - this was missing
            self.Session = sessionmaker(bind=self.engine)
            
            # Create a raw connection for other operations
            self.connection = self.engine.raw_connection()
            
            logger.info("Database connection established successfully")
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            self.connection = None
            self.engine = None
            self.Session = None
            raise
           
    def save_jobs(self, jobs: List[Job]) -> int:
        """Save jobs to database."""
        if not self.Session:
            logger.error("Cannot save jobs: No database session available")
            return 0
            
        session = self.Session()
        try:
            saved_count = 0
            for job in jobs:
                # Convert to SQLAlchemy model
                job_model = self._convert_to_model(job)
                session.add(job_model)
                saved_count += 1
                
            session.commit()
            return saved_count
        except Exception as e:
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
                .filter(JobModel.id.between(start_id, end_id))
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
                .filter(
                    sa.or_(
                        # JobModel.description.is_(None),
                        # JobModel.description == "",
                        # JobModel.description == "N/A",
                        # JobModel.description == "Error: Scrape Failed",
                    )
                )
                .order_by(JobModel.internal_id.desc())  # Descending order by ID
                .limit(limit)
                .all()
            )

            return [job[0] for job in jobs]

        except SQLAlchemyError as e:
            logger.error(f"Error getting jobs with null descriptions: {e}")
            return []

        finally:
            session.close()

    def get_all_job_classes(self):
        """Get all job classes from the database.

        Returns:
            list: A list of job class objects with id and name attributes
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT id, name FROM job_class")
                job_classes = cursor.fetchall()

                # Convert to objects with id and name attributes
                class JobClass:
                    def __init__(self, id, name):
                        self.id = id
                        self.name = name

                return [JobClass(row[0], row[1]) for row in job_classes]
        except Exception as e:
            logger.error(f"Error fetching job classes: {e}")
            return []

    def get_all_source_platforms(self):
        """Get all source platforms from the database.

        Returns:
            list: A list of platform objects with id and name attributes
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT id, name FROM source_platform")
                platforms = cursor.fetchall()

                # Convert to objects with id and name attributes
                class SourcePlatform:
                    def __init__(self, id, name):
                        self.id = id
                        self.name = name

                return [SourcePlatform(row[0], row[1]) for row in platforms]
        except Exception as e:
            logger.error(f"Error fetching source platforms: {e}")
            return []

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
            # logger.info(f"Updated description for job ID {job_id}")
            return True

        except SQLAlchemyError as e:
            session.rollback()
            logger.error(f"Error updating job description: {e}")
            return False

        finally:
            session.close()
