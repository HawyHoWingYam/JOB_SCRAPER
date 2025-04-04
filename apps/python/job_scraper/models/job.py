"""Job data model."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Company(BaseModel):
    """Company information model."""

    name: str
    website: Optional[str] = None
    logo_url: Optional[str] = None
    location: Optional[str] = None


class Job(BaseModel):
    """Job listing model."""

    # Core information
    id: str  # Unique identifier from source
    title: str
    job_class: Optional[str] = None
    job_subclass: Optional[str] = None
    description: Optional[str]
    url: Optional[str] = None  # Original job posting URL

    # Company information
    company: Company

    # Location and work type
    location: Optional[str] = None
    remote: bool = False
    work_type: Optional[str] = None  # Full-time, Part-time, Contract, etc.

    # Compensation
    salary_description: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_period: Optional[str] = None  # yearly, monthly, hourly

    # Dates
    date_posted: Optional[str] = None
    date_scraped: Optional[str] = Field(default_factory=datetime.utcnow)

    # Source information
    source: Optional[str] =None  # e.g., "Indeed", "LinkedIn"
    source_id: Optional[str] =None  # Original ID from the source

    # Additional information
    skills: List[str] = []
    experience_level: Optional[str] = None
    education_level: Optional[str] = None
    benefits: List[str] = []

    # Raw data
    raw_data: Optional[str] = None

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat()}
