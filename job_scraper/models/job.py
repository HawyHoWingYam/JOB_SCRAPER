"""Job data model."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Company(BaseModel):
    """Company information model."""

    id: Optional[int] = None
    name: str
    # industry_id: Optional[int] = None
    industry: Optional[str] = None
    # location: Optional[str] = None


class Job(BaseModel):
    """Job listing model."""

    # ID will be None for new jobs (auto-increment in DB)
    internal_id: Optional[int] = None
    id: str
    # Basic job info
    name: Optional[str] = None  # Job title
    description: Optional[str] = None
    company_name: Optional[str] = None
    location: Optional[str] = None
    work_type: Optional[str] = None
    salary_description: Optional[str] = None
    date_posted: Optional[str] = None
    date_scraped: Optional[str] = Field(
        default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    )
    source: Optional[str] = None  # e.g., "Indeed", "LinkedIn"
    # Additional information
    job_class: Optional[str] = None
    job_subclass: Optional[str] = None
    other: Optional[str] = None
    remark: Optional[str] = None
    # Fields to ignore for now
    company_id: Optional[int] = None
    source_id: Optional[int] = None
    job_class_id: Optional[int] = None
    job_subclass_id: Optional[int] = None

    class Config:
        """Pydantic model configuration."""

        json_encoders = {datetime: lambda v: v.isoformat()}
