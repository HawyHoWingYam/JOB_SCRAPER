from __future__ import annotations

from collections.abc import Iterable
import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.job_intelligence.foundation import (
    DecisionCommand,
    DecisionEffect,
    DecisionResult,
    GovernanceUnitOfWork,
    OutboxEvent,
)
from app.job_intelligence.skill_governance.contracts import (
    SkillCreateTarget,
    decode_skill_create_target,
)
from app.job_intelligence.skill_governance.normalization import (
    normalize_exact_skill_key,
    normalize_skill_text,
)
from app.job_intelligence.skill_governance.projection import (
    rebuild_job_skill_projection,
)
from app.models.skill_governance import (
    GovernedJobSkillMention,
    GovernedSkill,
    GovernedSkillAlias,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
    SkillTaxonomyRelease,
)
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.utils.time import utc_now


_SKILL_CODE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


class SkillCandidateDecisionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class SkillCandidateDecisionAdapter:
    """Trusted-local adapter for human-only Skill Candidate decisions."""

    def __init__(
        self,
        db: Session,
        *,
        outbox_repository: EventOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.outbox_repository = outbox_repository or EventOutboxRepository()

    def decide(self, command: DecisionCommand) -> DecisionResult:
        transition = _SkillCandidateTransition()
        return GovernanceUnitOfWork(
            self.db,
            outbox_repository=self.outbox_repository,
        ).execute(command, transition)


class _SkillCandidateTransition:
    domain = "skill-governance"
    subject_type = "skill-candidate"

    def __init__(self) -> None:
        self._operator_skill_id: UUID | None = None
        self._operator_alias_ids: set[UUID] = set()

    def load_for_update(
        self,
        db: Session,
        subject_id: str,
    ) -> SkillCandidate | None:
        try:
            candidate_id = UUID(subject_id)
        except (TypeError, ValueError):
            return None
        return (
            db.query(SkillCandidate)
            .filter(SkillCandidate.id == candidate_id)
            .with_for_update()
            .one_or_none()
        )

    @staticmethod
    def version(subject: SkillCandidate) -> int:
        return subject.lock_version

    @staticmethod
    def snapshot(subject: SkillCandidate) -> dict[str, object]:
        return {
            "id": str(subject.id),
            "taxonomy_revision_id": str(subject.taxonomy_revision_id),
            "normalized_key": subject.normalized_key,
            "canonical_raw_name": subject.canonical_raw_name,
            "status": subject.status,
            "occurrence_count": subject.occurrence_count,
            "distinct_job_count": subject.distinct_job_count,
            "resolved_skill_id": (
                str(subject.resolved_skill_id)
                if subject.resolved_skill_id is not None
                else None
            ),
            "generic_tag": subject.generic_tag,
            "rejection_reason": subject.rejection_reason,
            "version": subject.lock_version,
        }

    def apply(
        self,
        db: Session,
        subject: SkillCandidate,
        command: DecisionCommand,
    ) -> DecisionEffect:
        if subject.status != "pending":
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_NOT_PENDING",
                "Only a pending Skill Candidate can be decided",
            )
        active = db.get(SkillTaxonomyActiveRevision, "skill-taxonomy")
        release = db.get(SkillTaxonomyRelease, subject.taxonomy_revision_id)
        if (
            active is None
            or active.revision_id != subject.taxonomy_revision_id
            or release is None
            or release.status != "ready"
            or release.content_hash != active.content_hash
        ):
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_REVISION_INACTIVE",
                "Skill Candidate decisions require its active ready taxonomy revision",
            )

        mentions = (
            db.query(GovernedJobSkillMention)
            .filter(
                GovernedJobSkillMention.candidate_id == subject.id,
                GovernedJobSkillMention.taxonomy_revision_id
                == subject.taxonomy_revision_id,
                GovernedJobSkillMention.resolution == "review_candidate",
                GovernedJobSkillMention.status == "active",
            )
            .order_by(
                GovernedJobSkillMention.job_id.asc(),
                GovernedJobSkillMention.id.asc(),
            )
            .with_for_update()
            .all()
        )
        now = utc_now()
        target_skill: GovernedSkill | None = None
        if command.action == "merge_existing":
            target_skill = self._merge_target(db, subject, command.target_id)
            self._ensure_operator_aliases(db, subject, target_skill, ())
            subject.status = "resolved_merged"
            subject.resolved_skill_id = target_skill.id
        elif command.action == "create_skill":
            target = self._decode_create_target(command.target_id)
            target_skill = self._create_skill(db, subject, target)
            subject.status = "resolved_created"
            subject.resolved_skill_id = target_skill.id
        elif command.action == "classify_generic":
            generic_tag = normalize_skill_text(command.target_id)
            if not generic_tag:
                raise SkillCandidateDecisionError(
                    "SKILL_CANDIDATE_GENERIC_TAG_REQUIRED",
                    "classify_generic requires a non-empty generic tag",
                )
            subject.status = "resolved_generic"
            subject.generic_tag = generic_tag
        elif command.action == "reject":
            reason = normalize_skill_text(command.note or command.target_id)
            if not reason:
                raise SkillCandidateDecisionError(
                    "SKILL_CANDIDATE_REJECTION_REASON_REQUIRED",
                    "reject requires a reason",
                )
            subject.status = "rejected"
            subject.rejection_reason = reason
        else:
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_DECISION_ACTION_INVALID",
                f"Unsupported Skill Candidate decision action {command.action!r}",
            )

        affected_job_ids = sorted({mention.job_id for mention in mentions}, key=str)
        for mention in mentions:
            mention.origin_candidate_id = subject.id
            mention.candidate_id = None
            mention.lock_version += 1
            if target_skill is not None:
                mention.resolution = "match_existing"
                mention.skill_id = target_skill.id
                mention.generic_tag = None
                mention.rejection_reason = None
            elif subject.status == "resolved_generic":
                mention.resolution = "generic_tag"
                mention.skill_id = None
                mention.generic_tag = subject.generic_tag
                mention.rejection_reason = None
            else:
                mention.resolution = "rejected"
                mention.skill_id = None
                mention.generic_tag = None
                mention.rejection_reason = subject.rejection_reason

        subject.occurrence_count = 0
        subject.distinct_job_count = 0
        subject.resolved_at = now
        subject.lock_version += 1
        db.flush()
        for job_id in affected_job_ids:
            rebuild_job_skill_projection(
                db,
                job_id=job_id,
                revision_id=subject.taxonomy_revision_id,
            )

        projection = {
            "candidate_id": str(subject.id),
            "taxonomy_revision_id": str(subject.taxonomy_revision_id),
            "status": subject.status,
            "skill_id": str(target_skill.id) if target_skill is not None else None,
            "generic_tag": subject.generic_tag,
            "rejection_reason": subject.rejection_reason,
            "affected_job_ids": [str(job_id) for job_id in affected_job_ids],
            "affected_mention_count": len(mentions),
            "version": subject.lock_version,
        }
        events: list[OutboxEvent] = [
            OutboxEvent(
                topic="skill-governance",
                aggregate_type="skill-candidate",
                aggregate_id=str(subject.id),
                event_type="skill.candidate_decided",
                source_service="skill-governance",
                payload={
                    **projection,
                    "invalidate": [
                        "skill-candidate-queue",
                        "skill-taxonomy-read-model",
                    ],
                },
            )
        ]
        for job_id in affected_job_ids:
            events.append(
                OutboxEvent(
                    topic="job-intelligence-projections",
                    aggregate_type="job",
                    aggregate_id=str(job_id),
                    event_type="job.skill_projection_changed",
                    source_service="skill-governance",
                    payload={
                        "job_id": str(job_id),
                        "taxonomy_revision_id": str(subject.taxonomy_revision_id),
                        "candidate_id": str(subject.id),
                        "decision": command.action,
                        "invalidate": [
                            "job-skill-read-model",
                            "job-search",
                            "job-recommendation",
                            "job-embedding",
                            "skill-analytics",
                        ],
                    },
                )
            )
        return DecisionEffect(
            subject=self.snapshot(subject),
            resulting_projection=projection,
            version=subject.lock_version,
            evidence_refs=tuple(
                {
                    "kind": "skill-mention",
                    "id": str(mention.id),
                    "job_id": str(mention.job_id),
                }
                for mention in mentions
            ),
            outbox_events=tuple(events),
        )

    def _merge_target(
        self,
        db: Session,
        subject: SkillCandidate,
        target_id: str | None,
    ) -> GovernedSkill:
        try:
            skill_id = UUID(str(target_id))
        except (TypeError, ValueError):
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_TARGET_REQUIRED",
                "merge_existing requires a governed Skill UUID",
            ) from None
        skill = (
            db.query(GovernedSkill)
            .filter(
                GovernedSkill.id == skill_id,
                GovernedSkill.revision_id == subject.taxonomy_revision_id,
                GovernedSkill.is_active.is_(True),
            )
            .with_for_update()
            .one_or_none()
        )
        if skill is None:
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_TARGET_INVALID",
                "merge_existing target must be active in the Candidate revision",
            )
        return skill

    @staticmethod
    def _decode_create_target(value: str | None) -> SkillCreateTarget:
        try:
            return decode_skill_create_target(value)
        except ValueError as exc:
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_CREATE_TARGET_INVALID",
                str(exc),
            ) from exc

    def _create_skill(
        self,
        db: Session,
        subject: SkillCandidate,
        target: SkillCreateTarget,
    ) -> GovernedSkill:
        category = db.scalar(
            select(GovernedSkillCategory).where(
                GovernedSkillCategory.revision_id == subject.taxonomy_revision_id,
                GovernedSkillCategory.code == target.category_code,
                GovernedSkillCategory.is_active.is_(True),
            )
        )
        technology = (
            db.query(GovernedSkillTechnology)
            .filter(
                GovernedSkillTechnology.revision_id == subject.taxonomy_revision_id,
                GovernedSkillTechnology.code == target.technology_code,
                GovernedSkillTechnology.is_active.is_(True),
            )
            .with_for_update()
            .one_or_none()
        )
        if (
            category is None
            or technology is None
            or technology.category_id != category.id
        ):
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_CREATE_PATH_INVALID",
                "create_skill requires an active Category/Technology path",
            )
        if not _SKILL_CODE.fullmatch(
            target.stable_code
        ) or not target.stable_code.startswith(f"{technology.code}."):
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_CREATE_CODE_INVALID",
                "create_skill stable code must be explicit beneath its Technology",
            )
        existing = db.scalar(
            select(GovernedSkill).where(
                GovernedSkill.revision_id == subject.taxonomy_revision_id,
                (
                    (GovernedSkill.code == target.stable_code)
                    | (
                        (GovernedSkill.technology_id == technology.id)
                        & (func.lower(GovernedSkill.name) == target.name.casefold())
                    )
                ),
            )
        )
        if existing is not None:
            raise SkillCandidateDecisionError(
                "SKILL_CANDIDATE_CREATE_CONFLICT",
                "create_skill code or Technology-local name already exists",
            )
        max_order = db.scalar(
            select(func.max(GovernedSkill.source_order)).where(
                GovernedSkill.technology_id == technology.id
            )
        )
        skill = GovernedSkill(
            revision_id=subject.taxonomy_revision_id,
            technology_id=technology.id,
            code=target.stable_code,
            name=normalize_skill_text(target.name),
            source_order=int(max_order or 0) + 1,
            origin="operator",
            is_active=True,
        )
        db.add(skill)
        db.flush()
        self._operator_skill_id = skill.id
        self._ensure_operator_aliases(
            db, subject, skill, (target.name, *target.aliases)
        )
        return skill

    def _ensure_operator_aliases(
        self,
        db: Session,
        subject: SkillCandidate,
        skill: GovernedSkill,
        aliases: Iterable[str],
    ) -> None:
        raw_values = {
            normalize_skill_text(value)
            for value in (
                subject.canonical_raw_name,
                *(subject.raw_variants or []),
                *aliases,
            )
            if normalize_skill_text(value)
        }
        values_by_key: dict[str, str] = {}
        for raw_value in sorted(
            raw_values, key=lambda value: (value.casefold(), value)
        ):
            values_by_key.setdefault(normalize_exact_skill_key(raw_value), raw_value)

        max_order = db.scalar(
            select(func.max(GovernedSkillAlias.source_order)).where(
                GovernedSkillAlias.skill_id == skill.id
            )
        )
        next_order = int(max_order or 0) + 1
        for normalized_key, raw_value in sorted(values_by_key.items()):
            existing = (
                db.query(GovernedSkillAlias)
                .filter(
                    GovernedSkillAlias.taxonomy_revision_id
                    == subject.taxonomy_revision_id,
                    GovernedSkillAlias.normalized_key == normalized_key,
                )
                .with_for_update()
                .one_or_none()
            )
            if existing is not None:
                if existing.skill_id != skill.id:
                    raise SkillCandidateDecisionError(
                        "SKILL_CANDIDATE_ALIAS_CONFLICT",
                        f"Reviewed alias {normalized_key!r} belongs to another Skill",
                    )
                continue
            alias = GovernedSkillAlias(
                taxonomy_revision_id=subject.taxonomy_revision_id,
                skill_id=skill.id,
                raw_alias=raw_value,
                normalized_key=normalized_key,
                source="operator",
                source_order=next_order,
            )
            next_order += 1
            db.add(alias)
            db.flush()
            self._operator_alias_ids.add(alias.id)

    def attach_audit_reference(
        self,
        db: Session,
        subject: SkillCandidate,
        audit_event_id: UUID,
    ) -> None:
        subject.decision_audit_id = audit_event_id
        if self._operator_skill_id is not None:
            skill = db.get(GovernedSkill, self._operator_skill_id)
            if skill is not None:
                skill.created_by_audit_id = audit_event_id
        for alias_id in self._operator_alias_ids:
            alias = db.get(GovernedSkillAlias, alias_id)
            if alias is not None:
                alias.created_by_audit_id = audit_event_id


__all__ = ["SkillCandidateDecisionAdapter", "SkillCandidateDecisionError"]
