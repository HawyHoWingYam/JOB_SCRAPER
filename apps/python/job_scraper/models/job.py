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
    description: str
    url: str  # Original job posting URL
    
    # Company information
    company: Company
    
    # Location and work type
    location: str
    remote: bool = False
    work_type: Optional[str] = None  # Full-time, Part-time, Contract, etc.
    
    # Compensation
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_period: Optional[str] = None  # yearly, monthly, hourly
    
    # Dates
    date_posted: Optional[datetime] = None
    date_scraped: datetime = Field(default_factory=datetime.utcnow)
    
    # Source information
    source: str  # e.g., "Indeed", "LinkedIn"
    source_id: str  # Original ID from the source
    
    # Additional information
    skills: List[str] = []
    experience_level: Optional[str] = None
    education_level: Optional[str] = None
    benefits: List[str] = []
    
    # Raw data
    raw_data: Optional[Dict] = None
    
    class Config:
        """Pydantic model configuration."""
        
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }