from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class CompanyCreateSchema(BaseModel):
    """Schema for creating a new company."""

    company_id: str
    name: str
    industry: Optional[str] = None
    location: Optional[str] = None
    ai_description: Optional[str] = None


class CompanySchema(CompanyCreateSchema):
    """Schema for company response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
