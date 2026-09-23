from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.job_intelligence.current_taxonomies import (
    CurrentTaxonomyReader,
)
from app.schemas.current_taxonomy import CurrentJobSkillStateSchema, CurrentTaxonomyTreeSchema


router = APIRouter(prefix="/job-intelligence", tags=["job-intelligence"])


@router.get("/skills/tree", response_model=CurrentTaxonomyTreeSchema)
def read_skill_tree(
    db: Session = Depends(get_db),
) -> CurrentTaxonomyTreeSchema:
    return CurrentTaxonomyTreeSchema.model_validate(
        CurrentTaxonomyReader(db).get_tree("skill")
    )


@router.get("/jobs/{job_id}/skills", response_model=CurrentJobSkillStateSchema)
def read_job_skills(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> CurrentJobSkillStateSchema:
    return CurrentJobSkillStateSchema.model_validate(
        CurrentTaxonomyReader(db).get_job_skills(job_id)
    )


__all__ = [
    "read_job_skills",
    "read_skill_tree",
    "router",
]
