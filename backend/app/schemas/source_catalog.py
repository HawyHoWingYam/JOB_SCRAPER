from __future__ import annotations

from pydantic import BaseModel, Field


class CatalogActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=255)


class CatalogPublishRequest(CatalogActorRequest):
    review_token: str = Field(min_length=20, max_length=512)
