from pydantic import BaseModel, Field


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
