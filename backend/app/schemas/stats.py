from typing import Optional

from pydantic import BaseModel, Field


class DashboardCategorySourceBreakdownSchema(BaseModel):
    source_site: Optional[str] = None
    source_subclassification_name: Optional[str] = None
    count: int


class DashboardCategoryItemSchema(BaseModel):
    path: str
    label: str
    count: int
    share_of_specific: int


class DashboardFallbackBucketSchema(BaseModel):
    path: str
    label: str
    count: int
    share_of_categorized: int
    source_breakdown: list[DashboardCategorySourceBreakdownSchema] = Field(default_factory=list)


class DashboardOtherSpecificCategoriesSchema(BaseModel):
    count: int = 0
    bucket_count: int = 0
    share_of_specific: int = 0


class DashboardCategoryStatsSchema(BaseModel):
    categorized_total: int
    specific_total: int
    fallback_total: int
    top_specific_categories: list[DashboardCategoryItemSchema] = Field(default_factory=list)
    other_specific_categories: DashboardOtherSpecificCategoriesSchema
    fallback_buckets: list[DashboardFallbackBucketSchema] = Field(default_factory=list)
