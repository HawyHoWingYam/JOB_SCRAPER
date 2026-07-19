from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.job_intelligence.foundation import normalized_content_hash
from app.job_intelligence.skill_governance.contracts import (
    SkillExtractionContext,
    SkillExtractionResult,
    SkillGovernanceReadError,
    SkillMentionProjection,
)
from app.job_intelligence.skill_governance.normalization import (
    normalize_exact_skill_key,
    normalize_skill_lookup_key,
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


@dataclass(frozen=True)
class _Resolution:
    resolution: str
    skill: GovernedSkill | None = None
    candidate: SkillCandidate | None = None
    generic_tag: str | None = None
    rejection_reason: str | None = None


class SkillGovernance:
    """Worker-safe deterministic Skill extraction and governed projection Module."""

    def __init__(
        self,
        db: Session,
        *,
        outbox_repository: EventOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.outbox_repository = outbox_repository or EventOutboxRepository()

    def extract(
        self,
        job_id: UUID,
        extracted_terms: Sequence[object],
        context: SkillExtractionContext | None = None,
    ) -> SkillExtractionResult:
        context = context or SkillExtractionContext()
        active, release = self._active_release()
        rules = dict(release.rules_document or {})
        changed = False
        projections: list[SkillMentionProjection] = []
        seen_keys: set[str] = set()
        affected_candidate_ids: set[UUID] = set()

        for raw_term in extracted_terms:
            payload = self._coerce_term(raw_term)
            raw_name = normalize_skill_text(payload.get("name"))
            normalized_key = normalize_exact_skill_key(raw_name)
            if not raw_name or not normalized_key or normalized_key in seen_keys:
                continue
            seen_keys.add(normalized_key)

            resolution = self._resolve(
                revision_id=active.revision_id,
                raw_name=raw_name,
                normalized_key=normalized_key,
                payload=payload,
                rules=rules,
                context=context,
            )
            mention, mention_changed, prior_candidate_id = self._upsert_mention(
                job_id=job_id,
                revision_id=active.revision_id,
                raw_name=raw_name,
                normalized_key=normalized_key,
                resolution=resolution,
                context=context,
            )
            changed = changed or mention_changed
            if prior_candidate_id is not None:
                affected_candidate_ids.add(prior_candidate_id)
            if resolution.candidate is not None:
                affected_candidate_ids.add(resolution.candidate.id)
            projections.append(self._mention_projection(mention, resolution.skill))

        stale_mentions = (
            self.db.query(GovernedJobSkillMention)
            .filter(
                GovernedJobSkillMention.job_id == job_id,
                GovernedJobSkillMention.taxonomy_revision_id == active.revision_id,
                GovernedJobSkillMention.source == context.source,
                GovernedJobSkillMention.status == "active",
            )
            .with_for_update()
            .all()
        )
        now = utc_now()
        for mention in stale_mentions:
            if mention.normalized_key in seen_keys:
                continue
            if mention.candidate_id is not None:
                affected_candidate_ids.add(mention.candidate_id)
            mention.status = "superseded"
            mention.superseded_at = now
            mention.lock_version += 1
            changed = True
        self.db.flush()

        for candidate_id in sorted(affected_candidate_ids, key=str):
            self._recompute_candidate_metrics(candidate_id)
        projection_changed = self._rebuild_job_projection(
            job_id=job_id,
            revision_id=active.revision_id,
        )
        changed = changed or projection_changed

        if changed:
            self.outbox_repository.enqueue(
                self.db,
                topic="job-intelligence-projections",
                aggregate_type="job",
                aggregate_id=str(job_id),
                event_type="job.skill_projection_changed",
                source_service="skill-governance",
                payload={
                    "job_id": str(job_id),
                    "taxonomy_revision_id": str(active.revision_id),
                    "mention_ids": [str(item.id) for item in projections],
                    "candidate_ids": sorted(
                        (str(candidate_id) for candidate_id in affected_candidate_ids)
                    ),
                },
                auto_commit=False,
            )

        return SkillExtractionResult(
            job_id=job_id,
            taxonomy_revision_id=active.revision_id,
            mentions=tuple(projections),
            changed=changed,
        )

    def _active_release(
        self,
    ) -> tuple[SkillTaxonomyActiveRevision, SkillTaxonomyRelease]:
        active = self.db.get(SkillTaxonomyActiveRevision, "skill-taxonomy")
        if active is None:
            raise SkillGovernanceReadError(
                "SKILL_TAXONOMY_NOT_ACTIVE",
                "No governed Skill taxonomy revision is active",
            )
        release = self.db.get(SkillTaxonomyRelease, active.revision_id)
        if (
            release is None
            or release.status != "ready"
            or release.content_hash != active.content_hash
        ):
            raise SkillGovernanceReadError(
                "SKILL_TAXONOMY_ACTIVE_REVISION_INVALID",
                "The active governed Skill taxonomy revision is inconsistent",
            )
        return active, release

    @staticmethod
    def _coerce_term(raw_term: object) -> dict[str, Any]:
        if isinstance(raw_term, Mapping):
            payload = dict(raw_term)
            payload["name"] = (
                payload.get("normalized_name")
                or payload.get("name")
                or payload.get("skill")
                or payload.get("raw_name")
                or ""
            )
            return payload
        return {"name": str(raw_term or ""), "kind": "technical"}

    def _resolve(
        self,
        *,
        revision_id: UUID,
        raw_name: str,
        normalized_key: str,
        payload: Mapping[str, Any],
        rules: Mapping[str, Any],
        context: SkillExtractionContext,
    ) -> _Resolution:
        skill = self._exact_skill(revision_id, normalized_key)
        if skill is not None:
            return _Resolution("match_existing", skill=skill)

        prior = (
            self.db.query(SkillCandidate)
            .filter(
                SkillCandidate.taxonomy_revision_id == revision_id,
                SkillCandidate.normalized_key == normalized_key,
            )
            .with_for_update()
            .one_or_none()
        )
        if prior is not None and prior.status != "pending":
            return self._resolved_candidate(prior)

        lookup_key = normalize_skill_lookup_key(raw_name)
        generic_by_key = {
            normalize_skill_lookup_key(value): normalize_skill_text(value)
            for value in rules.get("generic_terms") or []
        }
        review_only = {
            normalize_skill_lookup_key(value)
            for value in rules.get("review_only_terms") or []
        }
        suppressed = {
            normalize_skill_lookup_key(value)
            for value in rules.get("suppressed_review_terms") or []
        }
        if lookup_key in generic_by_key:
            return _Resolution("generic_tag", generic_tag=generic_by_key[lookup_key])
        if lookup_key in suppressed:
            return _Resolution(
                "rejected",
                rejection_reason="suppressed_review_term",
            )

        kind = str(payload.get("kind") or "technical").strip().casefold()
        if (
            lookup_key in review_only
            or kind == "technical"
            or self._looks_technical(
                raw_name,
                payload,
                rules,
            )
        ):
            candidate = prior or self._register_candidate(
                revision_id=revision_id,
                raw_name=raw_name,
                normalized_key=normalized_key,
                payload=payload,
                context=context,
            )
            return _Resolution("review_candidate", candidate=candidate)
        return _Resolution("generic_tag", generic_tag=raw_name)

    @staticmethod
    def _looks_technical(
        raw_name: str,
        payload: Mapping[str, Any],
        rules: Mapping[str, Any],
    ) -> bool:
        if str(payload.get("resolution") or "").strip().casefold() in {
            "match_existing",
            "create_new",
            "unresolved",
        }:
            return True
        lowered = raw_name.casefold()
        return any(
            str(keyword).casefold() in lowered
            for keyword in rules.get("technical_hint_keywords") or []
        )

    def _exact_skill(
        self, revision_id: UUID, normalized_key: str
    ) -> GovernedSkill | None:
        return self.db.scalar(
            select(GovernedSkill)
            .join(
                GovernedSkillAlias,
                GovernedSkillAlias.skill_id == GovernedSkill.id,
            )
            .join(
                GovernedSkillTechnology,
                GovernedSkillTechnology.id == GovernedSkill.technology_id,
            )
            .join(
                GovernedSkillCategory,
                GovernedSkillCategory.id == GovernedSkillTechnology.category_id,
            )
            .where(
                GovernedSkillAlias.taxonomy_revision_id == revision_id,
                GovernedSkillAlias.normalized_key == normalized_key,
                GovernedSkill.revision_id == revision_id,
                GovernedSkill.is_active.is_(True),
                GovernedSkillTechnology.is_active.is_(True),
                GovernedSkillCategory.is_active.is_(True),
            )
        )

    def _resolved_candidate(self, candidate: SkillCandidate) -> _Resolution:
        if candidate.status in {"resolved_merged", "resolved_created"}:
            skill = self.db.get(GovernedSkill, candidate.resolved_skill_id)
            if skill is None or not skill.is_active:
                raise SkillGovernanceReadError(
                    "SKILL_CANDIDATE_RESOLUTION_INVALID",
                    "Resolved Skill Candidate points to an unavailable Skill",
                )
            return _Resolution("match_existing", skill=skill, candidate=candidate)
        if candidate.status == "resolved_generic":
            return _Resolution(
                "generic_tag",
                candidate=candidate,
                generic_tag=candidate.generic_tag,
            )
        return _Resolution(
            "rejected",
            candidate=candidate,
            rejection_reason=candidate.rejection_reason or "candidate_rejected",
        )

    def _register_candidate(
        self,
        *,
        revision_id: UUID,
        raw_name: str,
        normalized_key: str,
        payload: Mapping[str, Any],
        context: SkillExtractionContext,
    ) -> SkillCandidate:
        now = utc_now()
        candidate_id = uuid4()
        values = {
            "id": candidate_id,
            "taxonomy_revision_id": revision_id,
            "normalized_key": normalized_key,
            "canonical_raw_name": raw_name,
            "raw_variants": [raw_name],
            "status": "pending",
            "suggested_category_code": payload.get("category_code")
            or payload.get("category"),
            "suggested_technology_code": payload.get("technology_code")
            or payload.get("technology"),
            "occurrence_count": 0,
            "distinct_job_count": 0,
            "evidence_summary": {"sources": [context.source]},
            "recommendations": [],
            "lock_version": 1,
            "first_seen_at": now,
            "last_seen_at": now,
            "created_at": now,
            "updated_at": now,
        }
        if self.db.get_bind().dialect.name == "postgresql":
            inserted_id = self.db.scalar(
                postgresql_insert(SkillCandidate)
                .values(**values)
                .on_conflict_do_nothing(
                    index_elements=["taxonomy_revision_id", "normalized_key"]
                )
                .returning(SkillCandidate.id)
            )
            if inserted_id is not None:
                candidate_id = inserted_id
        else:
            try:
                with self.db.begin_nested():
                    self.db.add(SkillCandidate(**values))
                    self.db.flush()
            except IntegrityError:
                pass

        candidate = (
            self.db.query(SkillCandidate)
            .filter(
                SkillCandidate.taxonomy_revision_id == revision_id,
                SkillCandidate.normalized_key == normalized_key,
            )
            .with_for_update()
            .one()
        )
        variants = sorted(
            {
                normalize_skill_text(value)
                for value in [*(candidate.raw_variants or []), raw_name]
                if normalize_skill_text(value)
            },
            key=lambda value: (value.casefold(), value),
        )
        candidate.raw_variants = variants
        candidate.canonical_raw_name = variants[0]
        candidate.last_seen_at = now
        if payload.get("category_code") or payload.get("category"):
            candidate.suggested_category_code = str(
                payload.get("category_code") or payload.get("category")
            )
        if payload.get("technology_code") or payload.get("technology"):
            candidate.suggested_technology_code = str(
                payload.get("technology_code") or payload.get("technology")
            )
        summary = dict(candidate.evidence_summary or {})
        summary["sources"] = sorted({*(summary.get("sources") or []), context.source})
        candidate.evidence_summary = summary
        self.db.flush()
        return candidate

    def _upsert_mention(
        self,
        *,
        job_id: UUID,
        revision_id: UUID,
        raw_name: str,
        normalized_key: str,
        resolution: _Resolution,
        context: SkillExtractionContext,
    ) -> tuple[GovernedJobSkillMention, bool, UUID | None]:
        candidate_id = (
            resolution.candidate.id
            if resolution.resolution == "review_candidate" and resolution.candidate
            else None
        )
        origin_candidate_id = resolution.candidate.id if resolution.candidate else None
        values = {
            "job_id": job_id,
            "taxonomy_revision_id": revision_id,
            "raw_name": raw_name,
            "normalized_key": normalized_key,
            "resolution": resolution.resolution,
            "status": "active",
            "skill_id": resolution.skill.id if resolution.skill else None,
            "candidate_id": candidate_id,
            "origin_candidate_id": origin_candidate_id,
            "generic_tag": resolution.generic_tag,
            "rejection_reason": resolution.rejection_reason,
            "source": context.source,
            "confidence": context.confidence,
            "provenance": dict(context.provenance),
        }
        values["evidence_hash"] = normalized_content_hash(values)
        mention = (
            self.db.query(GovernedJobSkillMention)
            .filter(
                GovernedJobSkillMention.job_id == job_id,
                GovernedJobSkillMention.taxonomy_revision_id == revision_id,
                GovernedJobSkillMention.normalized_key == normalized_key,
                GovernedJobSkillMention.status == "active",
            )
            .with_for_update()
            .one_or_none()
        )
        if mention is None:
            mention_id = uuid4()
            now = utc_now()
            if self.db.get_bind().dialect.name == "postgresql":
                inserted_id = self.db.scalar(
                    postgresql_insert(GovernedJobSkillMention)
                    .values(
                        id=mention_id,
                        **values,
                        lock_version=1,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            "job_id",
                            "taxonomy_revision_id",
                            "normalized_key",
                        ],
                        index_where=(GovernedJobSkillMention.status == "active"),
                    )
                    .returning(GovernedJobSkillMention.id)
                )
                if inserted_id is not None:
                    mention_id = inserted_id
            else:
                try:
                    with self.db.begin_nested():
                        self.db.add(
                            GovernedJobSkillMention(
                                id=mention_id,
                                **values,
                                lock_version=1,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        self.db.flush()
                except IntegrityError:
                    pass
            mention = (
                self.db.query(GovernedJobSkillMention)
                .filter(
                    GovernedJobSkillMention.job_id == job_id,
                    GovernedJobSkillMention.taxonomy_revision_id == revision_id,
                    GovernedJobSkillMention.normalized_key == normalized_key,
                    GovernedJobSkillMention.status == "active",
                )
                .with_for_update()
                .one()
            )
            return mention, True, None

        prior_candidate_id = mention.candidate_id
        comparable_fields = (
            "raw_name",
            "resolution",
            "skill_id",
            "candidate_id",
            "generic_tag",
            "rejection_reason",
            "source",
            "confidence",
            "provenance",
            "evidence_hash",
        )
        desired_origin = mention.origin_candidate_id or origin_candidate_id
        same = all(
            getattr(mention, field) == values[field] for field in comparable_fields
        )
        same = same and mention.origin_candidate_id == desired_origin
        if same:
            return mention, False, prior_candidate_id
        for field, value in values.items():
            setattr(mention, field, value)
        mention.origin_candidate_id = desired_origin
        mention.lock_version += 1
        self.db.flush()
        return mention, True, prior_candidate_id

    def _recompute_candidate_metrics(self, candidate_id: UUID) -> None:
        candidate = (
            self.db.query(SkillCandidate)
            .filter(SkillCandidate.id == candidate_id)
            .with_for_update()
            .one_or_none()
        )
        if candidate is None or candidate.status != "pending":
            return
        mentions = (
            self.db.query(GovernedJobSkillMention)
            .filter(
                GovernedJobSkillMention.candidate_id == candidate_id,
                GovernedJobSkillMention.resolution == "review_candidate",
                GovernedJobSkillMention.status == "active",
            )
            .order_by(
                GovernedJobSkillMention.created_at.asc(),
                GovernedJobSkillMention.id.asc(),
            )
            .all()
        )
        candidate.occurrence_count = len(mentions)
        candidate.distinct_job_count = len({mention.job_id for mention in mentions})
        candidate.raw_variants = sorted(
            {mention.raw_name for mention in mentions},
            key=lambda value: (value.casefold(), value),
        )
        if mentions:
            candidate.first_seen_at = mentions[0].created_at
            candidate.last_seen_at = max(mention.updated_at for mention in mentions)
        summary = dict(candidate.evidence_summary or {})
        summary.update(
            {
                "sources": sorted({mention.source for mention in mentions}),
                "job_ids": sorted(str(mention.job_id) for mention in mentions),
            }
        )
        candidate.evidence_summary = summary
        self.db.flush()

    def _rebuild_job_projection(self, *, job_id: UUID, revision_id: UUID) -> bool:
        return rebuild_job_skill_projection(
            self.db,
            job_id=job_id,
            revision_id=revision_id,
        )

    def _mention_projection(
        self,
        mention: GovernedJobSkillMention,
        skill: GovernedSkill | None,
    ) -> SkillMentionProjection:
        if skill is None and mention.skill_id is not None:
            skill = self.db.get(GovernedSkill, mention.skill_id)
        return SkillMentionProjection(
            id=mention.id,
            raw_name=mention.raw_name,
            normalized_key=mention.normalized_key,
            resolution=mention.resolution,
            skill_id=mention.skill_id,
            skill_code=skill.code if skill is not None else None,
            skill_name=skill.name if skill is not None else None,
            candidate_id=mention.candidate_id,
            generic_tag=mention.generic_tag,
            rejection_reason=mention.rejection_reason,
        )
