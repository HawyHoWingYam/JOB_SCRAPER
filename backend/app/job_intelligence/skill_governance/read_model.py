from __future__ import annotations

import base64
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
import json
import math
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.job_intelligence.skill_governance.contracts import SkillGovernanceReadError
from app.job_intelligence.skill_governance.normalization import (
    normalize_exact_skill_key,
)
from app.models.governance import GovernanceRevision
from app.models.job import Job
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedJobSkillMention,
    GovernedSkill,
    GovernedSkillAlias,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
    SkillTaxonomyRelease,
)


_CANDIDATE_STATUSES = {
    "pending",
    "resolved_merged",
    "resolved_created",
    "resolved_generic",
    "rejected",
    "superseded",
}


@dataclass(frozen=True)
class SkillRevisionView:
    id: UUID
    release_key: str
    content_hash: str
    lock_version: int
    activated_at: datetime
    counts: Mapping[str, int]
    component_hashes: Mapping[str, str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "release_key": self.release_key,
            "content_hash": self.content_hash,
            "status": "active",
            "lock_version": self.lock_version,
            "activated_at": self.activated_at.isoformat(),
            "counts": dict(self.counts),
            "component_hashes": dict(self.component_hashes),
        }


@dataclass(frozen=True)
class GovernedSkillView:
    id: UUID
    revision_id: UUID
    category_id: UUID
    category_code: str
    category_name: str
    technology_id: UUID
    technology_code: str
    technology_name: str
    code: str
    name: str
    order: int
    origin: str
    aliases: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "revision_id": str(self.revision_id),
            "category": {
                "id": str(self.category_id),
                "code": self.category_code,
                "name": self.category_name,
            },
            "technology": {
                "id": str(self.technology_id),
                "code": self.technology_code,
                "name": self.technology_name,
            },
            "code": self.code,
            "name": self.name,
            "order": self.order,
            "origin": self.origin,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class SkillTechnologyView:
    id: UUID
    code: str
    name: str
    order: int
    skills: tuple[GovernedSkillView, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "order": self.order,
            "skills": [skill.to_payload() for skill in self.skills],
        }


@dataclass(frozen=True)
class SkillCategoryView:
    id: UUID
    code: str
    name: str
    order: int
    technologies: tuple[SkillTechnologyView, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "code": self.code,
            "name": self.name,
            "order": self.order,
            "technologies": [
                technology.to_payload() for technology in self.technologies
            ],
        }


@dataclass(frozen=True)
class SkillTreeView:
    revision: SkillRevisionView
    categories: tuple[SkillCategoryView, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "revision": self.revision.to_payload(),
            "categories": [category.to_payload() for category in self.categories],
        }


@dataclass(frozen=True)
class UnreviewedSkillMentionView:
    id: UUID
    raw_name: str
    normalized_key: str
    candidate_id: UUID
    candidate_version: int
    source: str
    confidence: float | None
    provenance: Mapping[str, Any]
    created_at: datetime
    updated_at: datetime
    label: str = "Unreviewed Skill Mention"

    @property
    def deep_link(self) -> str:
        return (
            f"/api/v1/job-intelligence/governance/skills/candidates/{self.candidate_id}"
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "label": self.label,
            "raw_name": self.raw_name,
            "normalized_key": self.normalized_key,
            "candidate_id": str(self.candidate_id),
            "candidate_version": self.candidate_version,
            "source": self.source,
            "confidence": self.confidence,
            "provenance": dict(self.provenance),
            "deep_link": self.deep_link,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class JobSkillStateView:
    job_id: UUID
    taxonomy_revision_id: UUID
    skills: tuple[GovernedSkillView, ...]
    unreviewed_skill_mentions: tuple[UnreviewedSkillMentionView, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "skills": [skill.to_payload() for skill in self.skills],
            "unreviewed_skill_mentions": [
                mention.to_payload() for mention in self.unreviewed_skill_mentions
            ],
        }


@dataclass(frozen=True)
class SkillRecommendationView:
    skill_id: UUID
    skill_code: str
    skill_name: str
    category_code: str
    category_name: str
    technology_code: str
    technology_name: str
    score: float
    reason: str
    advisory_only: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
            "skill_id": str(self.skill_id),
            "skill_code": self.skill_code,
            "skill_name": self.skill_name,
            "category_code": self.category_code,
            "category_name": self.category_name,
            "technology_code": self.technology_code,
            "technology_name": self.technology_name,
            "score": self.score,
            "reason": self.reason,
            "advisory_only": self.advisory_only,
        }


@dataclass(frozen=True)
class SkillCandidateView:
    id: UUID
    taxonomy_revision_id: UUID
    normalized_key: str
    canonical_raw_name: str
    raw_variants: tuple[str, ...]
    status: str
    suggested_category_code: str | None
    suggested_technology_code: str | None
    occurrence_count: int
    affected_job_count: int
    evidence_summary: Mapping[str, Any]
    recommendations: tuple[SkillRecommendationView, ...]
    version: int
    decision_audit_id: UUID | None
    resolved_skill_id: UUID | None
    generic_tag: str | None
    rejection_reason: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    @property
    def deep_link(self) -> str:
        return f"/api/v1/job-intelligence/governance/skills/candidates/{self.id}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "normalized_key": self.normalized_key,
            "canonical_raw_name": self.canonical_raw_name,
            "raw_variants": list(self.raw_variants),
            "status": self.status,
            "suggested_category_code": self.suggested_category_code,
            "suggested_technology_code": self.suggested_technology_code,
            "occurrence_count": self.occurrence_count,
            "affected_job_count": self.affected_job_count,
            "evidence_summary": dict(self.evidence_summary),
            "recommendations": [item.to_payload() for item in self.recommendations],
            "version": self.version,
            "decision_audit_id": (
                str(self.decision_audit_id)
                if self.decision_audit_id is not None
                else None
            ),
            "resolved_skill_id": (
                str(self.resolved_skill_id)
                if self.resolved_skill_id is not None
                else None
            ),
            "generic_tag": self.generic_tag,
            "rejection_reason": self.rejection_reason,
            "deep_link": self.deep_link,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


@dataclass(frozen=True)
class SkillCandidateQuery:
    statuses: tuple[str, ...] = ("pending",)
    search: str | None = None
    cursor: str | None = None
    page: int | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not self.statuses or not set(self.statuses) <= _CANDIDATE_STATUSES:
            raise SkillGovernanceReadError(
                "SKILL_CANDIDATE_STATUS_INVALID",
                "Skill Candidate status filter is invalid",
            )
        if not 1 <= self.limit <= 200:
            raise SkillGovernanceReadError(
                "SKILL_CANDIDATE_LIMIT_INVALID",
                "Skill Candidate page limit must be between 1 and 200",
            )
        if self.page is not None and self.page < 1:
            raise SkillGovernanceReadError(
                "SKILL_CANDIDATE_PAGE_INVALID",
                "Skill Candidate page must be at least 1",
            )


@dataclass(frozen=True)
class SkillCandidatePage:
    items: tuple[SkillCandidateView, ...]
    next_cursor: str | None
    total: int
    page: int | None = None
    limit: int | None = None
    offset: int | None = None
    page_count: int | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "items": [item.to_payload() for item in self.items],
            "next_cursor": self.next_cursor,
            "total": self.total,
        }
        if self.page is not None:
            payload.update(
                page=self.page,
                limit=self.limit,
                offset=self.offset,
                page_count=self.page_count,
            )
        return payload


def _encode_cursor(candidate: SkillCandidate) -> str:
    raw = json.dumps(
        {"last_seen_at": candidate.last_seen_at.isoformat(), "id": str(candidate.id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return datetime.fromisoformat(payload["last_seen_at"]), UUID(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SkillGovernanceReadError(
            "SKILL_CANDIDATE_CURSOR_INVALID",
            "Invalid Skill Candidate cursor",
        ) from exc


class SkillGovernanceReader:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _active(
        self,
    ) -> tuple[SkillTaxonomyActiveRevision, SkillTaxonomyRelease, GovernanceRevision]:
        active = self.db.get(SkillTaxonomyActiveRevision, "skill-taxonomy")
        if active is None:
            raise SkillGovernanceReadError(
                "SKILL_TAXONOMY_NOT_ACTIVE",
                "No governed Skill taxonomy revision is active",
            )
        release = self.db.get(SkillTaxonomyRelease, active.revision_id)
        governance = self.db.get(GovernanceRevision, active.revision_id)
        if (
            release is None
            or governance is None
            or release.status != "ready"
            or release.content_hash != active.content_hash
            or governance.domain != "skill-taxonomy"
            or governance.content_hash != active.content_hash
        ):
            raise SkillGovernanceReadError(
                "SKILL_TAXONOMY_ACTIVE_REVISION_INVALID",
                "The active governed Skill taxonomy revision is inconsistent",
            )
        return active, release, governance

    def get_active_revision(self) -> SkillRevisionView:
        active, release, governance = self._active()
        return SkillRevisionView(
            id=active.revision_id,
            release_key=governance.release_key,
            content_hash=active.content_hash,
            lock_version=active.lock_version,
            activated_at=active.activated_at,
            counts={
                "categories": release.materialized_category_count,
                "technologies": release.materialized_technology_count,
                "skills": release.materialized_skill_count,
            },
            component_hashes={
                "taxonomy": release.taxonomy_hash,
                "rules": release.rules_hash,
                "backfill": release.backfill_hash,
            },
        )

    def get_tree(self) -> SkillTreeView:
        revision = self.get_active_revision()
        categories = self.db.scalars(
            select(GovernedSkillCategory)
            .where(
                GovernedSkillCategory.revision_id == revision.id,
                GovernedSkillCategory.is_active.is_(True),
            )
            .order_by(
                GovernedSkillCategory.source_order.asc(),
                GovernedSkillCategory.code.asc(),
            )
        ).all()
        technologies = self.db.scalars(
            select(GovernedSkillTechnology)
            .where(
                GovernedSkillTechnology.revision_id == revision.id,
                GovernedSkillTechnology.is_active.is_(True),
            )
            .order_by(
                GovernedSkillTechnology.category_id.asc(),
                GovernedSkillTechnology.source_order.asc(),
                GovernedSkillTechnology.code.asc(),
            )
        ).all()
        skills = self.db.scalars(
            select(GovernedSkill)
            .where(
                GovernedSkill.revision_id == revision.id,
                GovernedSkill.is_active.is_(True),
            )
            .order_by(
                GovernedSkill.technology_id.asc(),
                GovernedSkill.source_order.asc(),
                GovernedSkill.code.asc(),
            )
        ).all()
        aliases = self.db.scalars(
            select(GovernedSkillAlias)
            .where(GovernedSkillAlias.taxonomy_revision_id == revision.id)
            .order_by(
                GovernedSkillAlias.skill_id.asc(),
                GovernedSkillAlias.source_order.asc(),
                GovernedSkillAlias.normalized_key.asc(),
            )
        ).all()
        aliases_by_skill: dict[UUID, list[str]] = defaultdict(list)
        for alias in aliases:
            aliases_by_skill[alias.skill_id].append(alias.raw_alias)
        category_by_id = {category.id: category for category in categories}
        technologies_by_category: dict[
            UUID, list[GovernedSkillTechnology]
        ] = defaultdict(list)
        for technology in technologies:
            technologies_by_category[technology.category_id].append(technology)
        skills_by_technology: dict[UUID, list[GovernedSkill]] = defaultdict(list)
        for skill in skills:
            skills_by_technology[skill.technology_id].append(skill)

        return SkillTreeView(
            revision=revision,
            categories=tuple(
                SkillCategoryView(
                    id=category.id,
                    code=category.code,
                    name=category.name,
                    order=category.source_order,
                    technologies=tuple(
                        SkillTechnologyView(
                            id=technology.id,
                            code=technology.code,
                            name=technology.name,
                            order=technology.source_order,
                            skills=tuple(
                                self._skill_view(
                                    skill,
                                    technology,
                                    category_by_id[technology.category_id],
                                    tuple(aliases_by_skill[skill.id]),
                                )
                                for skill in skills_by_technology[technology.id]
                            ),
                        )
                        for technology in technologies_by_category[category.id]
                    ),
                )
                for category in categories
            ),
        )

    def search_skills(
        self,
        query: str | None = None,
        *,
        category_code: str | None = None,
        technology_code: str | None = None,
        limit: int = 100,
    ) -> tuple[GovernedSkillView, ...]:
        if not 1 <= limit <= 200:
            raise SkillGovernanceReadError(
                "SKILL_SEARCH_LIMIT_INVALID",
                "Governed Skill search limit must be between 1 and 200",
            )
        normalized_query = normalize_exact_skill_key(query or "")
        result: list[GovernedSkillView] = []
        for category in self.get_tree().categories:
            if category_code is not None and category.code != category_code:
                continue
            for technology in category.technologies:
                if technology_code is not None and technology.code != technology_code:
                    continue
                for skill in technology.skills:
                    keys = {
                        normalize_exact_skill_key(skill.name),
                        *(normalize_exact_skill_key(alias) for alias in skill.aliases),
                    }
                    if normalized_query and not any(
                        normalized_query in key for key in keys
                    ):
                        continue
                    result.append(skill)
                    if len(result) == limit:
                        return tuple(result)
        return tuple(result)

    def get_prompt_candidate_slice(
        self,
        title: str,
        *,
        description: str = "",
        source_subclassification_name: str | None = None,
        limit: int = 10,
        role_mode: str | None = None,
    ) -> dict[str, Any]:
        """Return governed prompt context only; it cannot execute a decision."""

        if not 1 <= limit <= 50:
            raise SkillGovernanceReadError(
                "SKILL_PROMPT_SLICE_LIMIT_INVALID",
                "Skill prompt slice limit must be between 1 and 50",
            )
        tree = self.get_tree()
        _active, release, _governance = self._active()
        haystack = normalize_exact_skill_key(
            " ".join(
                (
                    title or "",
                    description or "",
                    source_subclassification_name or "",
                )
            )
        )
        all_skills = [
            skill
            for category in tree.categories
            for technology in category.technologies
            for skill in technology.skills
        ]
        ranked_skills = sorted(
            all_skills,
            key=lambda skill: (
                -max(
                    (
                        SequenceMatcher(
                            None,
                            haystack,
                            normalize_exact_skill_key(alias),
                        ).ratio()
                        for alias in (skill.name, *skill.aliases)
                    ),
                    default=0.0,
                ),
                skill.code,
            ),
        )
        selected = ranked_skills[:limit]
        first = selected[0] if selected else None
        rules = dict(release.rules_document or {})

        def terms_in_context(field: str) -> list[str]:
            return [
                str(term)
                for term in rules.get(field) or []
                if normalize_exact_skill_key(term) in haystack
            ][:limit]

        return {
            "taxonomy_revision_id": str(tree.revision.id),
            "category_hint": first.category_name if first is not None else None,
            "technology_hint": first.technology_name if first is not None else None,
            "existing_categories": [
                category.name for category in tree.categories[:limit]
            ],
            "existing_technologies": list(
                dict.fromkeys(skill.technology_name for skill in selected)
            )[:limit],
            "existing_skills": [skill.name for skill in selected],
            "review_only_terms": terms_in_context("review_only_terms"),
            "suppressed_review_terms": terms_in_context("suppressed_review_terms"),
            "role_mode": role_mode or "technical_heavy",
            "role_mode_guidance": (
                "Recommendations are advisory; emit evidence only and never create or merge Skills."
            ),
        }

    def get_job_state(self, job_id: UUID) -> JobSkillStateView:
        revision = self.get_active_revision()
        if self.db.get(Job, job_id) is None:
            raise SkillGovernanceReadError(
                "SKILL_JOB_NOT_FOUND",
                "Job was not found",
            )
        projection_rows = self.db.execute(
            select(
                GovernedJobSkill,
                GovernedSkill,
                GovernedSkillTechnology,
                GovernedSkillCategory,
            )
            .join(
                GovernedSkill,
                and_(
                    GovernedSkill.id == GovernedJobSkill.skill_id,
                    GovernedSkill.revision_id == GovernedJobSkill.taxonomy_revision_id,
                ),
            )
            .join(
                GovernedSkillTechnology,
                and_(
                    GovernedSkillTechnology.id == GovernedSkill.technology_id,
                    GovernedSkillTechnology.revision_id == GovernedSkill.revision_id,
                ),
            )
            .join(
                GovernedSkillCategory,
                and_(
                    GovernedSkillCategory.id == GovernedSkillTechnology.category_id,
                    GovernedSkillCategory.revision_id
                    == GovernedSkillTechnology.revision_id,
                ),
            )
            .where(
                GovernedJobSkill.job_id == job_id,
                GovernedJobSkill.taxonomy_revision_id == revision.id,
                GovernedSkill.is_active.is_(True),
                GovernedSkillTechnology.is_active.is_(True),
                GovernedSkillCategory.is_active.is_(True),
            )
            .order_by(
                GovernedSkillCategory.source_order.asc(),
                GovernedSkillTechnology.source_order.asc(),
                GovernedSkill.source_order.asc(),
                GovernedSkill.code.asc(),
            )
        ).all()
        skill_ids = [skill.id for _, skill, _, _ in projection_rows]
        alias_values: dict[UUID, list[str]] = defaultdict(list)
        if skill_ids:
            for skill_id, raw_alias in self.db.execute(
                select(
                    GovernedSkillAlias.skill_id,
                    GovernedSkillAlias.raw_alias,
                )
                .where(
                    GovernedSkillAlias.skill_id.in_(skill_ids),
                    GovernedSkillAlias.taxonomy_revision_id == revision.id,
                )
                .order_by(
                    GovernedSkillAlias.skill_id.asc(),
                    GovernedSkillAlias.source_order.asc(),
                )
            ).all():
                alias_values[skill_id].append(raw_alias)
        aliases_by_skill = {
            skill_id: tuple(values) for skill_id, values in alias_values.items()
        }
        mentions = self.db.execute(
            select(GovernedJobSkillMention, SkillCandidate)
            .join(
                SkillCandidate,
                and_(
                    SkillCandidate.id == GovernedJobSkillMention.candidate_id,
                    SkillCandidate.taxonomy_revision_id
                    == GovernedJobSkillMention.taxonomy_revision_id,
                ),
            )
            .where(
                GovernedJobSkillMention.job_id == job_id,
                GovernedJobSkillMention.taxonomy_revision_id == revision.id,
                GovernedJobSkillMention.status == "active",
                GovernedJobSkillMention.resolution == "review_candidate",
                SkillCandidate.status == "pending",
            )
            .order_by(
                GovernedJobSkillMention.created_at.asc(),
                GovernedJobSkillMention.id.asc(),
            )
        ).all()
        return JobSkillStateView(
            job_id=job_id,
            taxonomy_revision_id=revision.id,
            skills=tuple(
                self._skill_view(
                    skill,
                    technology,
                    category,
                    aliases_by_skill.get(skill.id, ()),
                )
                for _, skill, technology, category in projection_rows
            ),
            unreviewed_skill_mentions=tuple(
                UnreviewedSkillMentionView(
                    id=mention.id,
                    raw_name=mention.raw_name,
                    normalized_key=mention.normalized_key,
                    candidate_id=candidate.id,
                    candidate_version=candidate.lock_version,
                    source=mention.source,
                    confidence=mention.confidence,
                    provenance=dict(mention.provenance),
                    created_at=mention.created_at,
                    updated_at=mention.updated_at,
                )
                for mention, candidate in mentions
            ),
        )

    def list_candidates(self, query: SkillCandidateQuery) -> SkillCandidatePage:
        revision = self.get_active_revision()
        filters = [
            SkillCandidate.taxonomy_revision_id == revision.id,
            SkillCandidate.status.in_(query.statuses),
        ]
        if query.search and query.search.strip():
            pattern = f"%{query.search.strip()}%"
            filters.append(
                or_(
                    SkillCandidate.normalized_key.ilike(pattern),
                    SkillCandidate.canonical_raw_name.ilike(pattern),
                )
            )
        total = int(
            self.db.scalar(
                select(func.count()).select_from(SkillCandidate).where(*filters)
            )
            or 0
        )
        statement = select(SkillCandidate).where(*filters)
        if query.page is not None:
            offset = (query.page - 1) * query.limit
            page_rows = self.db.scalars(
                statement.order_by(
                    SkillCandidate.last_seen_at.desc(),
                    SkillCandidate.id.desc(),
                )
                .offset(offset)
                .limit(query.limit)
            ).all()
            recommendation_rows = (
                self._recommendation_rows(revision.id) if page_rows else []
            )
            return SkillCandidatePage(
                items=tuple(
                    self._candidate_view(
                        row,
                        recommendations=self._recommend_candidate(
                            row,
                            recommendation_rows,
                            limit=5,
                        ),
                    )
                    for row in page_rows
                ),
                next_cursor=None,
                total=total,
                page=query.page,
                limit=query.limit,
                offset=offset,
                page_count=max(1, math.ceil(total / query.limit)),
            )
        if query.cursor is not None:
            last_seen_at, candidate_id = _decode_cursor(query.cursor)
            statement = statement.where(
                or_(
                    SkillCandidate.last_seen_at < last_seen_at,
                    and_(
                        SkillCandidate.last_seen_at == last_seen_at,
                        SkillCandidate.id < candidate_id,
                    ),
                )
            )
        rows = self.db.scalars(
            statement.order_by(
                SkillCandidate.last_seen_at.desc(),
                SkillCandidate.id.desc(),
            ).limit(query.limit + 1)
        ).all()
        page_rows = rows[: query.limit]
        recommendation_rows = (
            self._recommendation_rows(revision.id) if page_rows else []
        )
        return SkillCandidatePage(
            items=tuple(
                self._candidate_view(
                    row,
                    recommendations=self._recommend_candidate(
                        row,
                        recommendation_rows,
                        limit=5,
                    ),
                )
                for row in page_rows
            ),
            next_cursor=(
                _encode_cursor(page_rows[-1])
                if len(rows) > query.limit and page_rows
                else None
            ),
            total=total,
        )

    def get_candidate(self, candidate_id: UUID) -> SkillCandidateView:
        revision = self.get_active_revision()
        candidate = self.db.scalar(
            select(SkillCandidate).where(
                SkillCandidate.id == candidate_id,
                SkillCandidate.taxonomy_revision_id == revision.id,
            )
        )
        if candidate is None:
            raise SkillGovernanceReadError(
                "SKILL_CANDIDATE_NOT_FOUND",
                "Skill Candidate was not found in the active revision",
            )
        return self._candidate_view(
            candidate,
            recommendations=self._recommend_candidate(
                candidate,
                self._recommendation_rows(revision.id),
                limit=5,
            ),
        )

    def recommend(
        self,
        candidate_id: UUID,
        *,
        limit: int = 10,
    ) -> tuple[SkillRecommendationView, ...]:
        if not 1 <= limit <= 50:
            raise SkillGovernanceReadError(
                "SKILL_RECOMMENDATION_LIMIT_INVALID",
                "Skill recommendation limit must be between 1 and 50",
            )
        revision = self.get_active_revision()
        candidate = self.db.scalar(
            select(SkillCandidate).where(
                SkillCandidate.id == candidate_id,
                SkillCandidate.taxonomy_revision_id == revision.id,
            )
        )
        if candidate is None:
            raise SkillGovernanceReadError(
                "SKILL_CANDIDATE_NOT_FOUND",
                "Skill Candidate was not found in the active revision",
            )
        return self._recommend_candidate(
            candidate,
            self._recommendation_rows(revision.id),
            limit=limit,
        )

    def _recommendation_rows(
        self,
        revision_id: UUID,
    ) -> list[
        tuple[
            GovernedSkill,
            GovernedSkillAlias,
            GovernedSkillTechnology,
            GovernedSkillCategory,
        ]
    ]:
        statement = (
            select(
                GovernedSkill,
                GovernedSkillAlias,
                GovernedSkillTechnology,
                GovernedSkillCategory,
            )
            .join(
                GovernedSkillAlias,
                and_(
                    GovernedSkillAlias.skill_id == GovernedSkill.id,
                    GovernedSkillAlias.taxonomy_revision_id
                    == GovernedSkill.revision_id,
                ),
            )
            .join(
                GovernedSkillTechnology,
                and_(
                    GovernedSkillTechnology.id == GovernedSkill.technology_id,
                    GovernedSkillTechnology.revision_id == GovernedSkill.revision_id,
                ),
            )
            .join(
                GovernedSkillCategory,
                and_(
                    GovernedSkillCategory.id == GovernedSkillTechnology.category_id,
                    GovernedSkillCategory.revision_id
                    == GovernedSkillTechnology.revision_id,
                ),
            )
            .where(
                GovernedSkill.revision_id == revision_id,
                GovernedSkill.is_active.is_(True),
                GovernedSkillTechnology.is_active.is_(True),
                GovernedSkillCategory.is_active.is_(True),
            )
        )
        return list(self.db.execute(statement).tuples().all())

    @staticmethod
    def _recommend_candidate(
        candidate: SkillCandidate,
        rows: list[
            tuple[
                GovernedSkill,
                GovernedSkillAlias,
                GovernedSkillTechnology,
                GovernedSkillCategory,
            ]
        ],
        *,
        limit: int,
    ) -> tuple[SkillRecommendationView, ...]:
        best: dict[UUID, SkillRecommendationView] = {}
        candidate_key = normalize_exact_skill_key(candidate.normalized_key)
        for skill, alias, technology, category in rows:
            score = round(
                SequenceMatcher(None, candidate_key, alias.normalized_key).ratio(),
                6,
            )
            recommendation = SkillRecommendationView(
                skill_id=skill.id,
                skill_code=skill.code,
                skill_name=skill.name,
                category_code=category.code,
                category_name=category.name,
                technology_code=technology.code,
                technology_name=technology.name,
                score=score,
                reason="normalized_similarity",
            )
            current = best.get(skill.id)
            if current is None or recommendation.score > current.score:
                best[skill.id] = recommendation
        return tuple(
            sorted(
                best.values(),
                key=lambda item: (
                    -item.score,
                    item.skill_code,
                    item.skill_name,
                    str(item.skill_id),
                ),
            )[:limit]
        )

    def _candidate_view(
        self,
        candidate: SkillCandidate,
        *,
        recommendations: tuple[SkillRecommendationView, ...],
    ) -> SkillCandidateView:
        return SkillCandidateView(
            id=candidate.id,
            taxonomy_revision_id=candidate.taxonomy_revision_id,
            normalized_key=candidate.normalized_key,
            canonical_raw_name=candidate.canonical_raw_name,
            raw_variants=tuple(candidate.raw_variants or ()),
            status=candidate.status,
            suggested_category_code=candidate.suggested_category_code,
            suggested_technology_code=candidate.suggested_technology_code,
            occurrence_count=candidate.occurrence_count,
            affected_job_count=candidate.distinct_job_count,
            evidence_summary=dict(candidate.evidence_summary or {}),
            recommendations=recommendations,
            version=candidate.lock_version,
            decision_audit_id=candidate.decision_audit_id,
            resolved_skill_id=candidate.resolved_skill_id,
            generic_tag=candidate.generic_tag,
            rejection_reason=candidate.rejection_reason,
            first_seen_at=candidate.first_seen_at,
            last_seen_at=candidate.last_seen_at,
            created_at=candidate.created_at,
            updated_at=candidate.updated_at,
            resolved_at=candidate.resolved_at,
        )

    @staticmethod
    def _skill_view(
        skill: GovernedSkill,
        technology: GovernedSkillTechnology,
        category: GovernedSkillCategory,
        aliases: tuple[str, ...],
    ) -> GovernedSkillView:
        return GovernedSkillView(
            id=skill.id,
            revision_id=skill.revision_id,
            category_id=category.id,
            category_code=category.code,
            category_name=category.name,
            technology_id=technology.id,
            technology_code=technology.code,
            technology_name=technology.name,
            code=skill.code,
            name=skill.name,
            order=skill.source_order,
            origin=skill.origin,
            aliases=aliases,
        )


__all__ = [
    "GovernedSkillView",
    "JobSkillStateView",
    "SkillCandidatePage",
    "SkillCandidateQuery",
    "SkillCandidateView",
    "SkillCategoryView",
    "SkillGovernanceReader",
    "SkillRecommendationView",
    "SkillRevisionView",
    "SkillTechnologyView",
    "SkillTreeView",
    "UnreviewedSkillMentionView",
]
