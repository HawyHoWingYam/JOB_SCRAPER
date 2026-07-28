from pydantic import BaseModel, Field


class DashboardCategoryItemSchema(BaseModel):
    code: str
    path: str
    label: str
    count: int
    share_of_assigned: int


class DashboardOtherCategoriesSchema(BaseModel):
    count: int = 0
    bucket_count: int = 0
    share_of_assigned: int = 0
    items: list[DashboardCategoryItemSchema] = Field(default_factory=list)


class DashboardCategoryStatsSchema(BaseModel):
    population_total: int
    assigned_total: int
    unassigned_total: int
    assignment_coverage: int
    classification_ready_unassigned_total: int
    top_categories: list[DashboardCategoryItemSchema] = Field(default_factory=list)
    other_categories: DashboardOtherCategoriesSchema


class DashboardSkillItemSchema(BaseModel):
    code: str
    name: str
    category: str
    count: int
    prevalence: int
    dashboard_bucket: str | None = None


class DashboardSkillCandidateBacklogSchema(BaseModel):
    unresolved_candidate_total: int
    affected_job_total: int
    ready_candidate_total: int
    ready_threshold: int


class DashboardSkillStatsSchema(BaseModel):
    processed_total: int
    matched_job_total: int
    match_coverage: int
    candidate_backlog: DashboardSkillCandidateBacklogSchema
    skills: list[DashboardSkillItemSchema] = Field(default_factory=list)
