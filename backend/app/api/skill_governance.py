from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.job_intelligence.foundation import (
    AuditQuery,
    AuditReader,
    DecisionCommand,
    GovernanceError,
)
from app.job_intelligence.skill_governance import (
    SkillCandidateDecisionAdapter,
    SkillCandidateDecisionError,
    SkillCandidateQuery,
    SkillCreateTarget,
    SkillGovernanceReadError,
    SkillGovernanceReader,
    encode_skill_create_target,
)
from app.schemas.job_intelligence import GovernanceAuditPageSchema
from app.schemas.skill_governance import (
    JobSkillStateSchema,
    SkillCandidateDecisionRequestSchema,
    SkillCandidateDecisionResultSchema,
    SkillCandidatePageSchema,
    SkillCandidateSchema,
    SkillRecommendationSchema,
    SkillRevisionSchema,
    SkillSearchSchema,
    SkillTreeSchema,
)


router = APIRouter(prefix="/job-intelligence", tags=["job-intelligence"])


def _read_error(exc: SkillGovernanceReadError) -> HTTPException:
    if exc.code in {
        "SKILL_TAXONOMY_NOT_ACTIVE",
        "SKILL_JOB_NOT_FOUND",
        "SKILL_CANDIDATE_NOT_FOUND",
    }:
        status_code = 404
    elif exc.code in {
        "SKILL_TAXONOMY_ACTIVE_REVISION_INVALID",
        "SKILL_CANDIDATE_RESOLUTION_INVALID",
    }:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail=exc.to_detail())


def _decision_error(
    exc: GovernanceError | SkillCandidateDecisionError,
) -> HTTPException:
    if isinstance(exc, GovernanceError):
        detail = exc.to_detail()
        code = exc.code
    else:
        detail = exc.to_detail()
        code = exc.code
    if code == "GOVERNANCE_DECISION_SUBJECT_NOT_FOUND":
        status_code = 404
    elif code in {
        "GOVERNANCE_DECISION_STALE_VERSION",
        "GOVERNANCE_IDEMPOTENCY_CONFLICT",
        "SKILL_CANDIDATE_NOT_PENDING",
        "SKILL_CANDIDATE_REVISION_INACTIVE",
        "SKILL_CANDIDATE_CREATE_CONFLICT",
        "SKILL_CANDIDATE_ALIAS_CONFLICT",
    }:
        status_code = 409
    else:
        status_code = 422
    return HTTPException(status_code=status_code, detail=detail)


@router.get("/skills/revision", response_model=SkillRevisionSchema)
def read_skill_revision(db: Session = Depends(get_db)) -> SkillRevisionSchema:
    try:
        payload = SkillGovernanceReader(db).get_active_revision().to_payload()
    except SkillGovernanceReadError as exc:
        raise _read_error(exc) from exc
    return SkillRevisionSchema.model_validate(payload)


@router.get("/skills/tree", response_model=SkillTreeSchema)
def read_skill_tree(db: Session = Depends(get_db)) -> SkillTreeSchema:
    try:
        payload = SkillGovernanceReader(db).get_tree().to_payload()
    except SkillGovernanceReadError as exc:
        raise _read_error(exc) from exc
    return SkillTreeSchema.model_validate(payload)


@router.get("/skills/search", response_model=SkillSearchSchema)
def search_governed_skills(
    q: str | None = None,
    category_code: str | None = None,
    technology_code: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SkillSearchSchema:
    try:
        skills = SkillGovernanceReader(db).search_skills(
            q,
            category_code=category_code,
            technology_code=technology_code,
            limit=limit,
        )
    except SkillGovernanceReadError as exc:
        raise _read_error(exc) from exc
    return SkillSearchSchema.model_validate(
        {"skills": [skill.to_payload() for skill in skills]}
    )


@router.get("/jobs/{job_id}/skills", response_model=JobSkillStateSchema)
def read_job_skills(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> JobSkillStateSchema:
    try:
        payload = SkillGovernanceReader(db).get_job_state(job_id).to_payload()
    except SkillGovernanceReadError as exc:
        raise _read_error(exc) from exc
    return JobSkillStateSchema.model_validate(payload)


@router.get(
    "/governance/skills/candidates",
    response_model=SkillCandidatePageSchema,
)
def list_skill_candidates(
    status: list[str] | None = Query(default=None),
    search: str | None = None,
    cursor: str | None = None,
    page: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SkillCandidatePageSchema:
    try:
        page = SkillGovernanceReader(db).list_candidates(
            SkillCandidateQuery(
                statuses=tuple(status) if status is not None else ("pending",),
                search=search,
                cursor=cursor,
                page=page,
                limit=limit,
            )
        )
    except SkillGovernanceReadError as exc:
        raise _read_error(exc) from exc
    return SkillCandidatePageSchema.model_validate(page.to_payload())


@router.get(
    "/governance/skills/candidates/{candidate_id}",
    response_model=SkillCandidateSchema,
)
def read_skill_candidate(
    candidate_id: UUID,
    db: Session = Depends(get_db),
) -> SkillCandidateSchema:
    try:
        payload = SkillGovernanceReader(db).get_candidate(candidate_id).to_payload()
    except SkillGovernanceReadError as exc:
        raise _read_error(exc) from exc
    return SkillCandidateSchema.model_validate(payload)


@router.get(
    "/governance/skills/candidates/{candidate_id}/recommendations",
    response_model=list[SkillRecommendationSchema],
)
def recommend_skill_candidate(
    candidate_id: UUID,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[SkillRecommendationSchema]:
    try:
        recommendations = SkillGovernanceReader(db).recommend(
            candidate_id,
            limit=limit,
        )
    except SkillGovernanceReadError as exc:
        raise _read_error(exc) from exc
    return [
        SkillRecommendationSchema.model_validate(recommendation.to_payload())
        for recommendation in recommendations
    ]


@router.post(
    "/governance/skills/candidates/{candidate_id}/decision",
    response_model=SkillCandidateDecisionResultSchema,
)
def decide_skill_candidate(
    candidate_id: UUID,
    request: SkillCandidateDecisionRequestSchema,
    db: Session = Depends(get_db),
) -> SkillCandidateDecisionResultSchema:
    target_id: str | None = None
    note = request.note
    if request.action == "merge_existing":
        target_id = (
            str(request.target_skill_id)
            if request.target_skill_id is not None
            else None
        )
    elif request.action == "create_skill" and request.create_target is not None:
        target_id = encode_skill_create_target(
            SkillCreateTarget(
                category_code=request.create_target.category_code,
                technology_code=request.create_target.technology_code,
                stable_code=request.create_target.stable_code,
                name=request.create_target.name,
                aliases=tuple(request.create_target.aliases),
            )
        )
    elif request.action == "classify_generic":
        target_id = request.generic_tag
    elif request.action == "reject":
        note = request.rejection_reason or request.note

    command = DecisionCommand(
        subject_id=str(candidate_id),
        action=request.action,
        target_id=target_id,
        expected_version=request.expected_version,
        idempotency_key=request.idempotency_key,
        confirmed=request.confirmed,
        note=note,
        correlation_id=request.correlation_id,
    )
    try:
        result = SkillCandidateDecisionAdapter(db).decide(command)
    except (GovernanceError, SkillCandidateDecisionError) as exc:
        raise _decision_error(exc) from exc
    return SkillCandidateDecisionResultSchema.model_validate(
        {**result.to_payload(), "replayed": result.replayed}
    )


@router.get(
    "/governance/skills/audit-events",
    response_model=GovernanceAuditPageSchema,
)
def list_skill_audit_events(
    subject_id: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> GovernanceAuditPageSchema:
    try:
        page = AuditReader(db).list(
            AuditQuery(
                domain="skill-governance",
                subject_type="skill-candidate",
                subject_id=subject_id,
                cursor=cursor,
                limit=limit,
            )
        )
    except ValueError as exc:
        raise _read_error(
            SkillGovernanceReadError(
                "SKILL_AUDIT_CURSOR_INVALID",
                str(exc),
            )
        ) from exc
    return GovernanceAuditPageSchema.from_contract(page)


__all__ = ["router"]
