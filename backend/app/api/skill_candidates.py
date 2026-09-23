from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.job_intelligence.current_taxonomies.enrichment import normalize_exact_skill_key
from app.models.current_taxonomy import (
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.models.job import Job
from app.models.jev import JevOnlineSkillClassification
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.services.jev_evaluator_factory import build_jev_evaluator
from app.services.jev_run_service import JevRunConfigurationError, JevRunService
from app.services.jev_skill_maintenance import JevSkillMaintenanceService
from app.services.classification_domain_adapters import (
    SkillClassificationAdapter,
    SkillPlacementDecision,
)


router = APIRouter(
    prefix="/job-intelligence/skill-candidates", tags=["skill-candidates"]
)


class SkillCandidateDecisionRequest(BaseModel):
    action: Literal["match_existing", "create", "generic", "reject"]
    skill_code: str | None = None
    category_code: str | None = None
    technology_code: str | None = None
    name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    generic_tag: str | None = None
    rejection_reason: str | None = None
    decision_note: str | None = Field(default=None, max_length=500)


def _serialize(
    candidate: CurrentSkillCandidate,
    *,
    recommendations: list[dict[str, object]],
    evidence: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "id": str(candidate.id),
        "canonical_raw_name": candidate.canonical_raw_name,
        "normalized_key": candidate.normalized_key,
        "raw_variants": list(candidate.raw_variants or []),
        "occurrence_count": candidate.occurrence_count,
        "distinct_job_count": candidate.distinct_job_count,
        "evidence_summary": dict(candidate.evidence_summary or {}),
        "first_seen_at": candidate.first_seen_at,
        "last_seen_at": candidate.last_seen_at,
        "recommendations": recommendations,
        "evidence": evidence,
    }


def _serialize_maintenance(batch) -> dict[str, object] | None:
    if batch is None:
        return None
    return {
        "id": batch.id,
        "jev_run_id": batch.jev_run_id,
        "status": batch.status,
        "trigger": batch.trigger,
        "eligible_count": batch.eligible_count,
        "candidate_ids": list(batch.candidate_ids or []),
        "settings_snapshot": dict(batch.settings_snapshot or {}),
        "taxonomy_snapshot_sha256": batch.taxonomy_snapshot_sha256,
        "proposals": list(batch.proposals or []),
        "applied_changes": list(batch.applied_changes or []),
        "receipt": dict(batch.receipt or {}),
        "auto_applied_count": batch.auto_applied_count,
        "held_for_approval_count": batch.held_for_approval_count,
        "error_code": batch.error_code,
        "created_at": batch.created_at,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "approved_at": batch.approved_at,
    }


def _similarity(left: str, right: str) -> float:
    left_key = normalize_exact_skill_key(left)
    right_key = normalize_exact_skill_key(right)
    if not left_key or not right_key:
        return 0.0
    if left_key == right_key:
        return 1.0
    left_tokens = set(left_key.split())
    right_tokens = set(right_key.split())
    shared = left_tokens & right_tokens
    if shared:
        smaller_coverage = len(shared) / min(len(left_tokens), len(right_tokens))
        if smaller_coverage >= 0.75:
            jaccard = len(shared) / len(left_tokens | right_tokens)
            return 0.75 + (0.25 * jaccard)
    if min(len(left_key), len(right_key)) >= 3 and (
        left_key in right_key or right_key in left_key
    ):
        return 0.8 + (
            0.2
            * min(len(left_key), len(right_key))
            / max(len(left_key), len(right_key))
        )
    ratio = SequenceMatcher(None, left_key, right_key).ratio()
    return ratio if ratio >= 0.82 else 0.0


def _candidate_recommendations(
    db: Session,
    candidates: tuple[CurrentSkillCandidate, ...],
    *,
    limit: int,
) -> dict[UUID, list[dict[str, object]]]:
    nodes = tuple(
        db.scalars(
            select(CurrentTaxonomyNodeRecord).where(
                CurrentTaxonomyNodeRecord.taxonomy == "skill",
                CurrentTaxonomyNodeRecord.is_active.is_(True),
            )
        )
    )
    by_code = {node.code: node for node in nodes}
    aliases: dict[str, list[str]] = defaultdict(list)
    for alias in db.scalars(
        select(CurrentTaxonomyAliasRecord).where(
            CurrentTaxonomyAliasRecord.taxonomy == "skill"
        )
    ):
        aliases[alias.node_code].append(alias.alias)
    skills = tuple(
        node for node in nodes if node.level == "skill" and node.is_assignable
    )
    results: dict[UUID, list[dict[str, object]]] = {}
    for candidate in candidates:
        needle = normalize_exact_skill_key(candidate.canonical_raw_name)
        ranked: list[tuple[float, str, CurrentTaxonomyNodeRecord]] = []
        for node in skills:
            label = str((node.labels or {}).get("en") or node.code)
            values = (
                (label, "名称相似"),
                *((value, "Alias 相似") for value in aliases[node.code]),
            )
            score, reason = max(
                (
                    _similarity(needle, value),
                    match_reason,
                )
                for value, match_reason in values
            )
            if score > 0:
                ranked.append((score, reason, node))
        recommendations = []
        for score, reason, node in sorted(
            ranked, key=lambda item: (-item[0], item[2].code)
        )[:limit]:
            technology = by_code.get(node.parent_code or "")
            category = by_code.get(technology.parent_code or "") if technology else None
            recommendations.append(
                {
                    "code": node.code,
                    "name": str((node.labels or {}).get("en") or node.code),
                    "technology": str(
                        (technology.labels or {}).get("en") or technology.code
                    )
                    if technology
                    else None,
                    "category": str((category.labels or {}).get("en") or category.code)
                    if category
                    else None,
                    "score": round(score, 3),
                    "reason": reason,
                }
            )
        results[candidate.id] = recommendations
    return results


def _candidate_evidence(
    db: Session,
    candidate_ids: tuple[UUID, ...],
    *,
    limit: int,
) -> dict[UUID, list[dict[str, object]]]:
    grouped: dict[UUID, list[dict[str, object]]] = defaultdict(list)
    seen: dict[UUID, set[UUID]] = defaultdict(set)
    if not candidate_ids:
        return grouped
    rows = list(
        db.execute(
            select(
                CurrentJobSkillMention,
                Job.id,
                Job.title,
                Job.source_site,
                Job.description,
            )
            .join(Job, Job.id == CurrentJobSkillMention.job_id)
            .where(
                CurrentJobSkillMention.candidate_id.in_(candidate_ids),
                CurrentJobSkillMention.status == "active",
                CurrentJobSkillMention.resolution == "candidate",
            )
            .order_by(
                CurrentJobSkillMention.candidate_id, Job.created_at.desc(), Job.id
            )
        )
    )
    job_ids = tuple({job_id for _mention, job_id, *_rest in rows})
    latest_by_job: dict[UUID, JevOnlineSkillClassification] = {}
    if job_ids:
        classifications = db.scalars(
            select(JevOnlineSkillClassification)
            .where(JevOnlineSkillClassification.job_id.in_(job_ids))
            .order_by(
                JevOnlineSkillClassification.job_id,
                JevOnlineSkillClassification.created_at.desc(),
                JevOnlineSkillClassification.id.desc(),
            )
        )
        for classification in classifications:
            latest_by_job.setdefault(classification.job_id, classification)
    for mention, job_id, title, source_site, description in rows:
        candidate_id = mention.candidate_id
        if (
            candidate_id is None
            or job_id in seen[candidate_id]
            or len(grouped[candidate_id]) >= limit
        ):
            continue
        seen[candidate_id].add(job_id)
        classification = latest_by_job.get(job_id)
        jev_decision = None
        if classification is not None:
            jev_decision = next(
                (
                    decision
                    for decision in (classification.decisions or [])
                    if normalize_exact_skill_key(decision.get("raw_name"))
                    == mention.normalized_key
                ),
                None,
            )
        receipt = classification.receipt if classification is not None else None
        grouped[candidate_id].append(
            {
                "job_id": str(job_id),
                "title": title,
                "source_site": source_site,
                "evidence_excerpt": _evidence_excerpt(
                    classification,
                    normalized_key=mention.normalized_key,
                    fallback=description,
                ),
                "mention_confidence": mention.confidence,
                "jev": (
                    {
                        "classification_id": classification.id,
                        "run_id": classification.jev_run_id,
                        "status": classification.status,
                        "error_code": classification.error_code,
                        "decision": jev_decision,
                        "request_id": (receipt or {}).get("request_id"),
                        "provider": (receipt or {}).get("provider"),
                        "model": (receipt or {}).get("model"),
                        "usage": (receipt or {}).get("usage"),
                    }
                    if classification is not None
                    else None
                ),
            }
        )
    return grouped


def _evidence_excerpt(
    classification: JevOnlineSkillClassification | None,
    *,
    normalized_key: str,
    fallback: object,
) -> str | None:
    if classification is not None:
        for candidate in (classification.evidence_snapshot or {}).get("candidates", []):
            if normalize_exact_skill_key(candidate.get("raw_name")) == normalized_key:
                evidence = str(candidate.get("evidence") or "").strip()
                if evidence:
                    return evidence[:600]
    text = str(fallback or "").strip()
    return text[:600] or None


@router.get("")
def list_skill_candidates(
    ready_only: bool = Query(default=True),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    settings_service = AIRuntimeSettingsService(db)
    threshold = settings_service.get_skill_auto_create_distinct_job_threshold()
    recommendation_limit = settings_service.get_skill_candidate_recommendation_limit()
    evidence_limit = settings_service.get_skill_candidate_evidence_limit()
    query = select(CurrentSkillCandidate).where(
        CurrentSkillCandidate.resolved_skill_code.is_(None)
    )
    if ready_only:
        query = query.where(CurrentSkillCandidate.distinct_job_count >= threshold)
    total_count = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    candidates = tuple(
        db.scalars(
            query.order_by(
                CurrentSkillCandidate.distinct_job_count.desc(),
                CurrentSkillCandidate.first_seen_at,
                CurrentSkillCandidate.id,
            )
            .offset(offset)
            .limit(limit)
        )
    )
    candidate_ids = tuple(candidate.id for candidate in candidates)
    recommendations = _candidate_recommendations(
        db, candidates, limit=recommendation_limit
    )
    evidence = _candidate_evidence(db, candidate_ids, limit=evidence_limit)
    return {
        "threshold": threshold,
        "recommendation_limit": recommendation_limit,
        "evidence_limit": evidence_limit,
        "ready_only": ready_only,
        "total_count": int(total_count),
        "offset": offset,
        "limit": limit,
        "items": [
            _serialize(
                candidate,
                recommendations=recommendations.get(candidate.id, []),
                evidence=evidence.get(candidate.id, []),
            )
            for candidate in candidates
        ],
    }


@router.post("/{candidate_id}/decision")
def decide_skill_candidate(
    candidate_id: UUID,
    request: SkillCandidateDecisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    generic_reasons = {
        "general_capability",
        "responsibility",
        "job_attribute",
        "not_a_skill",
    }
    rejection_reasons = {"noise", "parse_error", "too_specific", "inappropriate"}
    if request.action == "generic" and request.generic_tag not in generic_reasons:
        raise HTTPException(
            status_code=400, detail="A valid generic reason is required"
        )
    if request.action == "reject" and request.rejection_reason not in rejection_reasons:
        raise HTTPException(
            status_code=400, detail="A valid rejection reason is required"
        )
    generic_tag = request.generic_tag
    rejection_reason = request.rejection_reason
    if request.decision_note:
        if generic_tag:
            generic_tag = f"{generic_tag}: {request.decision_note.strip()}"
        if rejection_reason:
            rejection_reason = f"{rejection_reason}: {request.decision_note.strip()}"
    decision = None
    if request.action == "create":
        decision = SkillPlacementDecision(
            status="create",
            category_code=request.category_code,
            technology_code=request.technology_code,
            name=request.name,
            aliases=tuple(request.aliases),
        )
    try:
        resolved_code = SkillClassificationAdapter().apply_operator_decision(
            db,
            candidate_id,
            action=request.action,
            skill_code=request.skill_code,
            decision=decision,
            generic_tag=generic_tag,
            rejection_reason=rejection_reason,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        message = str(exc)
        status_code = 404 if "not found" in message.casefold() else 400
        raise HTTPException(status_code=status_code, detail=message) from exc
    return {"candidate_id": str(candidate_id), "resolved_skill_code": resolved_code}


@router.get("/maintenance/status")
def skill_maintenance_status(db: Session = Depends(get_db)) -> dict[str, object]:
    service = JevSkillMaintenanceService(db)
    eligibility = service.eligibility()
    return {
        "eligibility": {
            "enabled": eligibility.enabled,
            "due": eligibility.due,
            "eligible_count": eligibility.eligible_count,
            "minimum_count": eligibility.minimum_count,
            "can_start": eligibility.can_start,
            "reason": eligibility.reason,
        },
        "latest_batch": _serialize_maintenance(service.latest()),
    }


@router.post("/maintenance/run-now")
async def run_skill_maintenance_now(
    db: Session = Depends(get_db),
) -> dict[str, object]:
    service = JevSkillMaintenanceService(db)
    evaluator = None
    batch = None
    try:
        eligibility, batch = service.start(trigger="manual")
        db.commit()
        if batch is None:
            return {
                "dispatched": False,
                "reason": eligibility.reason,
                "eligible_count": eligibility.eligible_count,
                "minimum_count": eligibility.minimum_count,
                "batch": None,
            }
        run = JevRunService(db).get(batch.jev_run_id)
        evaluator = build_jev_evaluator(db, run)
        batch = await service.execute(batch.id, evaluator=evaluator)
        db.commit()
        return {
            "dispatched": True,
            "reason": None,
            "eligible_count": eligibility.eligible_count,
            "minimum_count": eligibility.minimum_count,
            "batch": _serialize_maintenance(batch),
        }
    except JevRunConfigurationError as exc:
        db.rollback()
        if batch is not None:
            batch = service.mark_unavailable(
                batch.id,
                error_code="configuration_error",
            )
            db.commit()
            return {
                "dispatched": False,
                "reason": "configuration_error",
                "eligible_count": eligibility.eligible_count,
                "minimum_count": eligibility.minimum_count,
                "batch": _serialize_maintenance(batch),
            }
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        close = getattr(evaluator, "aclose", None)
        if close is not None:
            await close()


@router.post("/maintenance/{batch_id}/approve")
def approve_skill_maintenance(
    batch_id: str,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        batch = JevSkillMaintenanceService(db).approve(batch_id)
        db.commit()
        return _serialize_maintenance(batch)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["router"]
