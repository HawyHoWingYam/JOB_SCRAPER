from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.system_one import ChoiceAnswer
from app.job_intelligence.current_taxonomies.enrichment import (
    normalize_exact_skill_key,
)
from app.job_intelligence.foundation import normalized_content_hash
from app.models.current_taxonomy import (
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.models.jev import JevRuntimeSettings, JevSkillMaintenanceBatch
from app.services.classification_domain_adapters import (
    SkillClassificationAdapter,
    SkillPlacementDecision,
)
from app.services.jev_evaluation import SkillOption, rank_skill_options
from app.services.jev_budget import JevBudgetExhaustedError
from app.services.jev_run_service import JevRunService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.utils.time import as_utc, utc_now


_CHOICE = TypeAdapter(ChoiceAnswer)
MAINTENANCE_RUBRIC_VERSION = "jev-skill-maintenance-v1"


@dataclass(frozen=True)
class MaintenanceEligibility:
    enabled: bool
    due: bool
    eligible_count: int
    minimum_count: int
    can_start: bool
    reason: str | None


class JevSkillMaintenanceService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def eligibility(self, *, manual: bool = False) -> MaintenanceEligibility:
        settings = JevRuntimeSettingsService(self.db).get_or_create()
        eligible_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(CurrentSkillCandidate)
                .where(
                    CurrentSkillCandidate.resolved_skill_code.is_(None),
                    CurrentSkillCandidate.distinct_job_count > 0,
                )
            )
            or 0
        )
        now = utc_now()
        due = manual or settings.maintenance_last_checked_at is None
        if not due:
            due = as_utc(settings.maintenance_last_checked_at) <= now - timedelta(
                days=settings.maintenance_interval_days
            )
        if not settings.maintenance_enabled:
            reason = "maintenance_disabled"
        elif not due:
            reason = "not_due"
        elif eligible_count < settings.maintenance_min_candidates:
            reason = "insufficient_candidates"
        else:
            reason = None
        return MaintenanceEligibility(
            enabled=bool(settings.maintenance_enabled),
            due=due,
            eligible_count=eligible_count,
            minimum_count=settings.maintenance_min_candidates,
            can_start=reason is None,
            reason=reason,
        )

    def start(
        self, *, trigger: str
    ) -> tuple[MaintenanceEligibility, JevSkillMaintenanceBatch | None]:
        if trigger not in {"manual", "scheduled"}:
            raise ValueError("unknown maintenance trigger")
        initial_settings = JevRuntimeSettingsService(self.db).get_or_create()
        settings = (
            self.db.scalar(
                select(JevRuntimeSettings)
                .where(JevRuntimeSettings.id == initial_settings.id)
                .with_for_update()
            )
            or initial_settings
        )
        eligibility = self.eligibility(manual=trigger == "manual")
        settings.maintenance_last_checked_at = utc_now()
        if not eligibility.can_start:
            self.db.flush()
            return eligibility, None
        active_batch = self.db.scalar(
            select(JevSkillMaintenanceBatch)
            .where(JevSkillMaintenanceBatch.status.in_(("pending", "running")))
            .order_by(JevSkillMaintenanceBatch.created_at)
            .limit(1)
        )
        if active_batch is not None:
            self.db.flush()
            return (
                MaintenanceEligibility(
                    enabled=eligibility.enabled,
                    due=eligibility.due,
                    eligible_count=eligibility.eligible_count,
                    minimum_count=eligibility.minimum_count,
                    can_start=False,
                    reason="maintenance_in_progress",
                ),
                None,
            )

        candidates = tuple(
            self.db.scalars(
                select(CurrentSkillCandidate)
                .where(
                    CurrentSkillCandidate.resolved_skill_code.is_(None),
                    CurrentSkillCandidate.distinct_job_count > 0,
                )
                .order_by(
                    CurrentSkillCandidate.distinct_job_count.desc(),
                    CurrentSkillCandidate.first_seen_at,
                    CurrentSkillCandidate.id,
                )
                .limit(settings.maintenance_batch_size)
            )
        )
        taxonomy, options, technologies = self._taxonomy()
        batch = JevSkillMaintenanceBatch(
            status="pending",
            trigger=trigger,
            eligible_count=eligibility.eligible_count,
            candidate_ids=[str(candidate.id) for candidate in candidates],
            settings_snapshot={
                "model": settings.maintenance_model,
                "allowance_microdollars": settings.maintenance_allowance_microdollars,
                "interval_days": settings.maintenance_interval_days,
                "minimum_candidates": settings.maintenance_min_candidates,
                "batch_size": settings.maintenance_batch_size,
                "threshold_millis": settings.maintenance_threshold_millis,
            },
            taxonomy_snapshot_sha256=normalized_content_hash(taxonomy),
            proposals=[],
            applied_changes=[],
        )
        self.db.add(batch)
        self.db.flush()
        state, questions = self._request(candidates, options, technologies)
        run = JevRunService(self.db).start(
            purpose=f"taxonomy_maintenance:{batch.id}",
            rubric_version=MAINTENANCE_RUBRIC_VERSION,
            profile="maintenance",
            items=[
                {
                    "subject_id": batch.id,
                    "evidence_refs": [batch.taxonomy_snapshot_sha256],
                    "payload": {"state": state, "questions": questions},
                }
            ],
        )
        batch.jev_run_id = run.id
        settings.maintenance_last_started_at = utc_now()
        self.db.flush()
        return eligibility, batch

    async def execute(self, batch_id: str, *, evaluator) -> JevSkillMaintenanceBatch:
        batch = self._require(batch_id)
        if batch.status in {"ready_for_approval", "applied", "unavailable"}:
            return batch
        if not batch.jev_run_id:
            raise ValueError("maintenance batch has no Jev run")
        batch.status = "running"
        batch.started_at = batch.started_at or utc_now()
        try:
            item = await JevRunService(self.db).execute_next(
                batch.jev_run_id,
                evaluator=evaluator,
            )
        except JevBudgetExhaustedError:
            batch.status = "unavailable"
            batch.error_code = "jev_allowance_exhausted"
            batch.receipt = {
                "status": "unavailable",
                "error_code": batch.error_code,
            }
            batch.completed_at = utc_now()
            self.db.flush()
            return batch
        if item is None:
            raise ValueError("maintenance run has no executable item")
        if item.status != "completed":
            batch.status = "unavailable"
            batch.error_code = item.error_code or "jev_unavailable"
            batch.receipt = {
                "status": "unavailable",
                "error_code": batch.error_code,
            }
            batch.completed_at = utc_now()
            self.db.flush()
            return batch

        candidates = {
            str(candidate.id): candidate
            for candidate in self.db.scalars(
                select(CurrentSkillCandidate).where(
                    CurrentSkillCandidate.id.in_(
                        [UUID(value) for value in batch.candidate_ids]
                    )
                )
            )
        }
        answers = item.result.get("answers") or {}
        batch.receipt = dict(item.result or {})
        requested_questions = item.payload.get("questions") or {}
        threshold = int(batch.settings_snapshot["threshold_millis"]) / 1000
        proposals: list[dict[str, object]] = []
        applied: list[dict[str, object]] = []
        adapter = SkillClassificationAdapter()
        for index, candidate_id in enumerate(batch.candidate_ids):
            candidate = candidates.get(candidate_id)
            if candidate is None or candidate.resolved_skill_code:
                proposals.append(
                    {"candidate_id": candidate_id, "action": "stale", "held": True}
                )
                continue
            action = self._answer(answers, f"candidate_{index:03d}_action")
            action_name = f"candidate_{index:03d}_action"
            allowed_actions = set(
                (requested_questions.get(action_name) or {}).get("criteria") or {}
            )
            if action is None or action.choice not in allowed_actions:
                proposals.append(
                    {"candidate_id": candidate_id, "action": "invalid", "held": True}
                )
                continue
            choice = action.choice
            base = {
                "candidate_id": candidate_id,
                "candidate_name": candidate.canonical_raw_name,
                "action": choice,
                "confidence": action.confidence,
                "probabilities": dict(action.probabilities),
            }
            if action.confidence < threshold or choice == "insufficient":
                proposals.append({**base, "held": True, "reason": "below_threshold"})
            elif choice == "propose_new":
                parent = self._answer(answers, f"candidate_{index:03d}_parent")
                parent_name = f"candidate_{index:03d}_parent"
                allowed_parents = set(
                    (requested_questions.get(parent_name) or {}).get("criteria") or {}
                )
                proposals.append(
                    {
                        **base,
                        "held": True,
                        "technology_code": (
                            parent.choice
                            if parent and parent.choice in allowed_parents
                            else None
                        ),
                        "parent_confidence": (
                            parent.confidence
                            if parent and parent.choice in allowed_parents
                            else None
                        ),
                        "reason": "new_skill_requires_aggregate_approval",
                    }
                )
            elif choice in {"generic", "reject"}:
                adapter.apply_operator_decision(
                    self.db,
                    candidate.id,
                    action=choice,
                    generic_tag="jev_maintenance_generic"
                    if choice == "generic"
                    else None,
                    rejection_reason="jev_maintenance_rejected"
                    if choice == "reject"
                    else None,
                )
                applied.append({**base, "held": False})
            else:
                adapter.apply_operator_decision(
                    self.db,
                    candidate.id,
                    action="match_existing",
                    skill_code=choice,
                )
                self._add_alias(candidate.canonical_raw_name, choice)
                applied.append({**base, "held": False, "skill_code": choice})
        batch.proposals = proposals
        batch.applied_changes = applied
        batch.auto_applied_count = len(applied)
        batch.held_for_approval_count = len(proposals)
        batch.status = "ready_for_approval" if proposals else "applied"
        batch.completed_at = utc_now()
        self.db.flush()
        return batch

    def approve(self, batch_id: str) -> JevSkillMaintenanceBatch:
        batch = self._require(batch_id)
        if batch.status != "ready_for_approval":
            raise ValueError("maintenance batch is not awaiting approval")
        adapter = SkillClassificationAdapter()
        remaining: list[dict[str, object]] = []
        applied = list(batch.applied_changes or [])
        for proposal in batch.proposals or []:
            if proposal.get("action") != "propose_new":
                remaining.append(proposal)
                continue
            technology_code = str(proposal.get("technology_code") or "")
            technology = self.db.get(
                CurrentTaxonomyNodeRecord,
                ("skill", technology_code),
            )
            candidate = self.db.get(
                CurrentSkillCandidate,
                UUID(str(proposal["candidate_id"])),
            )
            if (
                candidate is None
                or technology is None
                or technology.level != "technology"
                or not technology.is_active
                or not proposal.get("parent_confidence")
            ):
                remaining.append(proposal)
                continue
            code = adapter.apply_operator_decision(
                self.db,
                candidate.id,
                action="create",
                decision=SkillPlacementDecision(
                    status="create",
                    category_code=technology.parent_code,
                    technology_code=technology.code,
                    name=candidate.canonical_raw_name,
                    aliases=tuple(candidate.raw_variants or []),
                ),
            )
            applied.append({**proposal, "held": False, "skill_code": code})
        batch.proposals = remaining
        batch.applied_changes = applied
        batch.held_for_approval_count = len(remaining)
        batch.status = "applied" if not remaining else "ready_for_approval"
        batch.approved_at = utc_now()
        self.db.flush()
        return batch

    def latest(self) -> JevSkillMaintenanceBatch | None:
        return self.db.scalar(
            select(JevSkillMaintenanceBatch)
            .order_by(
                JevSkillMaintenanceBatch.created_at.desc(),
                JevSkillMaintenanceBatch.id.desc(),
            )
            .limit(1)
        )

    def pending(self) -> JevSkillMaintenanceBatch | None:
        """Return durable work that was created but not yet dispatched."""
        return self.db.scalar(
            select(JevSkillMaintenanceBatch)
            .where(JevSkillMaintenanceBatch.status == "pending")
            .order_by(
                JevSkillMaintenanceBatch.created_at,
                JevSkillMaintenanceBatch.id,
            )
            .limit(1)
        )

    def mark_unavailable(
        self,
        batch_id: str,
        *,
        error_code: str,
    ) -> JevSkillMaintenanceBatch:
        """Terminate work that cannot safely reach the provider."""
        batch = self._require(batch_id)
        if batch.status not in {"pending", "running"}:
            return batch
        if batch.jev_run_id:
            run = JevRunService(self.db).get(batch.jev_run_id)
            if run.status == "pending":
                JevRunService(self.db).request_stop(run.id)
        batch.status = "unavailable"
        batch.error_code = error_code
        batch.receipt = {"status": "unavailable", "error_code": error_code}
        batch.completed_at = utc_now()
        self.db.flush()
        return batch

    def _taxonomy(self):
        nodes = tuple(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord)
                .where(
                    CurrentTaxonomyNodeRecord.taxonomy == "skill",
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                )
                .order_by(CurrentTaxonomyNodeRecord.code)
            )
        )
        aliases = tuple(
            self.db.scalars(
                select(CurrentTaxonomyAliasRecord)
                .where(CurrentTaxonomyAliasRecord.taxonomy == "skill")
                .order_by(
                    CurrentTaxonomyAliasRecord.node_code,
                    CurrentTaxonomyAliasRecord.alias,
                )
            )
        )
        alias_by_code: dict[str, list[str]] = {}
        for alias in aliases:
            alias_by_code.setdefault(alias.node_code, []).append(alias.alias)
        options = tuple(
            SkillOption(
                code=node.code,
                labels=dict(node.labels),
                aliases=tuple(alias_by_code.get(node.code, [])),
            )
            for node in nodes
            if node.level == "skill" and node.is_assignable
        )
        technologies = tuple(node for node in nodes if node.level == "technology")
        taxonomy = {
            "nodes": [
                {
                    "code": node.code,
                    "parent_code": node.parent_code,
                    "level": node.level,
                    "labels": node.labels,
                    "is_assignable": node.is_assignable,
                }
                for node in nodes
            ],
            "aliases": [
                {"node_code": alias.node_code, "alias": alias.alias}
                for alias in aliases
            ],
        }
        return taxonomy, options, technologies

    @staticmethod
    def _request(candidates, options, technologies):
        state_candidates = []
        questions = {}
        for index, candidate in enumerate(candidates):
            ranked = rank_skill_options(
                candidate.canonical_raw_name,
                options,
                limit=5,
            )
            action_criteria = {
                str(option["code"]): f"Map to existing Skill {option['name']}."
                for option in ranked
            }
            action_criteria.update(
                {
                    "generic": "Treat as a generic capability.",
                    "reject": "Reject as noise or not a useful Skill.",
                    "propose_new": "Propose a new governed Skill leaf.",
                    "insufficient": "Keep unresolved due to insufficient evidence.",
                }
            )
            questions[f"candidate_{index:03d}_action"] = {
                "type": "choice",
                "instructions": "Choose the safest taxonomy maintenance outcome.",
                "criteria": action_criteria,
            }
            questions[f"candidate_{index:03d}_parent"] = {
                "type": "choice",
                "instructions": "If proposing a new Skill, choose its Technology parent.",
                "criteria": {
                    node.code: str((node.labels or {}).get("en") or node.code)
                    for node in technologies
                },
            }
            state_candidates.append(
                {
                    "candidate_id": str(candidate.id),
                    "name": candidate.canonical_raw_name,
                    "variants": list(candidate.raw_variants or []),
                    "occurrence_count": candidate.occurrence_count,
                    "distinct_job_count": candidate.distinct_job_count,
                    "ranked_existing_options": ranked,
                }
            )
        return {"candidates": state_candidates}, questions

    @staticmethod
    def _answer(answers, name: str) -> ChoiceAnswer | None:
        value = answers.get(name)
        if not isinstance(value, dict):
            return None
        try:
            return _CHOICE.validate_python(value)
        except ValueError:
            return None

    def _add_alias(self, alias: str, skill_code: str) -> None:
        normalized = normalize_exact_skill_key(alias)
        if not normalized:
            return
        existing = tuple(
            self.db.scalars(
                select(CurrentTaxonomyAliasRecord).where(
                    CurrentTaxonomyAliasRecord.taxonomy == "skill",
                    CurrentTaxonomyAliasRecord.normalized_alias == normalized,
                )
            )
        )
        if existing:
            return
        self.db.add(
            CurrentTaxonomyAliasRecord(
                taxonomy="skill",
                node_code=skill_code,
                alias=alias,
                normalized_alias=normalized,
            )
        )
        self.db.flush()

    def _require(self, batch_id: str) -> JevSkillMaintenanceBatch:
        batch = self.db.get(JevSkillMaintenanceBatch, batch_id)
        if batch is None:
            raise ValueError("maintenance batch does not exist")
        return batch


__all__ = [
    "JevSkillMaintenanceService",
    "MAINTENANCE_RUBRIC_VERSION",
    "MaintenanceEligibility",
]
