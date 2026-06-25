from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID


class CompanyCreateSchema(BaseModel):
    """Schema for creating a new company.

    When creating via the UI, ``company_id`` can be omitted; the server
    auto-generates one (``manual:<uuid>``).  The ``name`` field is always
    required.
    """

    company_id: Optional[str] = None
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
