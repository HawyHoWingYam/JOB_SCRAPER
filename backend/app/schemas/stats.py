from pydantic import BaseModel, Field


class DashboardSkillItemSchema(BaseModel):
    code: str
    name: str
    category: str
    count: int
    prevalence: int
    dashboard_bucket: str | None = None


class DashboardSkillStatsSchema(BaseModel):
    processed_total: int
    matched_job_total: int
    match_coverage: int
    skills: list[DashboardSkillItemSchema] = Field(default_factory=list)
