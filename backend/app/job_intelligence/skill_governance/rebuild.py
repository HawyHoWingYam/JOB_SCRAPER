from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.job_intelligence.foundation import normalized_content_hash
from app.job_intelligence.skill_governance.normalization import (
    normalize_exact_skill_key,
    normalize_skill_lookup_key,
    normalize_skill_text,
)
from app.job_intelligence.skill_governance.read_model import SkillGovernanceReader
from app.models.job import Job
from app.models.skill_governance import (
    GovernedJobSkillMention,
    SkillCandidate,
    SkillTaxonomyRelease,
)


@dataclass(frozen=True)
class SkillGovernanceRebuildReport:
    active_revision_id: UUID
    rules_hash: str
    backfill_hash: str
    jobs_inspected: int
    terms_inspected: int
    outcomes: Mapping[str, int]
    affected_jobs: int
    no_preserved_evidence_jobs: int
    normalized_collisions: int
    jobs: tuple[Mapping[str, Any], ...]
    mode: str = "read-only"

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "active_revision_id": str(self.active_revision_id),
            "rules_hash": self.rules_hash,
            "backfill_hash": self.backfill_hash,
            "jobs_inspected": self.jobs_inspected,
            "terms_inspected": self.terms_inspected,
            "outcomes": dict(self.outcomes),
            "affected_jobs": self.affected_jobs,
            "no_preserved_evidence_jobs": self.no_preserved_evidence_jobs,
            "normalized_collisions": self.normalized_collisions,
            "jobs": [dict(item) for item in self.jobs],
        }


@dataclass(frozen=True)
class RecoveredSkillEvidence:
    job_id: UUID
    terms: tuple[object, ...]
    evidence_source: str | None
    evidence_hash: str | None

    @property
    def cursor(self) -> str:
        return str(self.job_id)

    @property
    def extraction_source(self) -> str:
        return {
            "ai_extraction.skills": "ai-extraction",
            "ai_enrichment.skills": "ai-enrichment",
            "skills": "legacy-skills",
        }.get(self.evidence_source or "", "skill-cutover-rebuild")


class SkillGovernanceRebuildInspector:
    """Compare preserved extraction evidence with one pinned active Skill release."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def inspect(
        self,
        job_ids: Iterable[UUID] | None = None,
    ) -> SkillGovernanceRebuildReport:
        reader = SkillGovernanceReader(self.db)
        revision = reader.get_active_revision()
        release = self.db.get(SkillTaxonomyRelease, revision.id)
        assert release is not None
        tree = reader.get_tree()
        alias_outcomes: dict[str, dict[str, str]] = {}
        skill_by_id: dict[UUID, dict[str, str]] = {}
        for category in tree.categories:
            for technology in category.technologies:
                for skill in technology.skills:
                    outcome = {
                        "skill_id": str(skill.id),
                        "skill_code": skill.code,
                        "skill_name": skill.name,
                    }
                    skill_by_id[skill.id] = outcome
                    for alias in (skill.name, *skill.aliases):
                        alias_outcomes[normalize_exact_skill_key(alias)] = outcome

        requested_ids = tuple(dict.fromkeys(job_ids or ()))
        statement = select(Job)
        if requested_ids:
            statement = statement.where(Job.id.in_(requested_ids))
        jobs = self.db.scalars(statement.order_by(Job.id.asc())).all()
        rules = dict(release.rules_document or {})
        generic = {
            normalize_skill_lookup_key(value): normalize_skill_text(value)
            for value in rules.get("generic_terms") or []
        }
        suppressed = {
            normalize_skill_lookup_key(value)
            for value in rules.get("suppressed_review_terms") or []
        }
        review_only = {
            normalize_skill_lookup_key(value)
            for value in rules.get("review_only_terms") or []
        }

        outcome_counts: Counter[str] = Counter(
            {
                "match_existing": 0,
                "review_candidate": 0,
                "generic_tag": 0,
                "rejected": 0,
            }
        )
        job_payloads: list[Mapping[str, Any]] = []
        affected_jobs = 0
        no_evidence = 0
        collisions = 0
        terms_inspected = 0
        for job in jobs:
            raw_terms, evidence_source = _preserved_terms(job.raw_data)
            current = {
                mention.normalized_key: mention.resolution
                for mention in self.db.scalars(
                    select(GovernedJobSkillMention).where(
                        GovernedJobSkillMention.job_id == job.id,
                        GovernedJobSkillMention.taxonomy_revision_id == revision.id,
                        GovernedJobSkillMention.status == "active",
                    )
                ).all()
            }
            if not raw_terms:
                no_evidence += 1
                job_payloads.append(
                    {
                        "job_id": str(job.id),
                        "evidence_source": None,
                        "evidence_hash": None,
                        "terms": [],
                        "difference_count": 0,
                    }
                )
                continue

            seen: set[str] = set()
            proposed_terms: list[dict[str, Any]] = []
            difference_count = 0
            for raw_term in raw_terms:
                payload = _coerce_term(raw_term)
                raw_name = normalize_skill_text(payload.get("name"))
                normalized_key = normalize_exact_skill_key(raw_name)
                if not raw_name or not normalized_key:
                    continue
                if normalized_key in seen:
                    collisions += 1
                    continue
                seen.add(normalized_key)
                proposed = self._classify(
                    revision_id=revision.id,
                    raw_name=raw_name,
                    normalized_key=normalized_key,
                    kind=str(payload.get("kind") or "technical"),
                    alias_outcomes=alias_outcomes,
                    skill_by_id=skill_by_id,
                    generic=generic,
                    suppressed=suppressed,
                    review_only=review_only,
                )
                terms_inspected += 1
                outcome_counts[proposed["resolution"]] += 1
                differs = current.get(normalized_key) != proposed["resolution"]
                difference_count += int(differs)
                proposed_terms.append(
                    {
                        "raw_name": raw_name,
                        "normalized_key": normalized_key,
                        **proposed,
                        "current_resolution": current.get(normalized_key),
                        "differs": differs,
                    }
                )
            affected_jobs += int(difference_count > 0)
            job_payloads.append(
                {
                    "job_id": str(job.id),
                    "evidence_source": evidence_source,
                    "evidence_hash": normalized_content_hash(raw_terms),
                    "terms": proposed_terms,
                    "difference_count": difference_count,
                }
            )

        return SkillGovernanceRebuildReport(
            active_revision_id=revision.id,
            rules_hash=release.rules_hash,
            backfill_hash=release.backfill_hash,
            jobs_inspected=len(jobs),
            terms_inspected=terms_inspected,
            outcomes={
                key: outcome_counts[key]
                for key in (
                    "match_existing",
                    "review_candidate",
                    "generic_tag",
                    "rejected",
                )
            },
            affected_jobs=affected_jobs,
            no_preserved_evidence_jobs=no_evidence,
            normalized_collisions=collisions,
            jobs=tuple(job_payloads),
        )

    def recover(
        self,
        job_ids: Iterable[UUID] | None = None,
    ) -> tuple[RecoveredSkillEvidence, ...]:
        """Expose preserved extraction terms through a read-only rebuild port."""

        requested_ids = tuple(dict.fromkeys(job_ids or ()))
        statement = select(Job)
        if job_ids is not None:
            statement = statement.where(Job.id.in_(requested_ids))
        jobs = self.db.scalars(statement.order_by(Job.id.asc())).all()
        recovered: list[RecoveredSkillEvidence] = []
        for job in jobs:
            raw_terms, evidence_source = _preserved_terms(job.raw_data)
            recovered.append(
                RecoveredSkillEvidence(
                    job_id=job.id,
                    terms=tuple(raw_terms),
                    evidence_source=evidence_source,
                    evidence_hash=(
                        normalized_content_hash(raw_terms) if raw_terms else None
                    ),
                )
            )
        return tuple(recovered)

    def _classify(
        self,
        *,
        revision_id: UUID,
        raw_name: str,
        normalized_key: str,
        kind: str,
        alias_outcomes: Mapping[str, Mapping[str, str]],
        skill_by_id: Mapping[UUID, Mapping[str, str]],
        generic: Mapping[str, str],
        suppressed: set[str],
        review_only: set[str],
    ) -> dict[str, Any]:
        alias = alias_outcomes.get(normalized_key)
        if alias is not None:
            return {"resolution": "match_existing", **dict(alias)}
        candidate = self.db.scalar(
            select(SkillCandidate).where(
                SkillCandidate.taxonomy_revision_id == revision_id,
                SkillCandidate.normalized_key == normalized_key,
            )
        )
        if candidate is not None and candidate.status != "pending":
            if candidate.status in {"resolved_merged", "resolved_created"}:
                skill = skill_by_id.get(candidate.resolved_skill_id)
                if skill is not None:
                    return {"resolution": "match_existing", **dict(skill)}
            if candidate.status == "resolved_generic":
                return {
                    "resolution": "generic_tag",
                    "generic_tag": candidate.generic_tag,
                }
            return {
                "resolution": "rejected",
                "rejection_reason": candidate.rejection_reason or "candidate_rejected",
            }
        lookup_key = normalize_skill_lookup_key(raw_name)
        if lookup_key in generic:
            return {"resolution": "generic_tag", "generic_tag": generic[lookup_key]}
        if lookup_key in suppressed:
            return {
                "resolution": "rejected",
                "rejection_reason": "suppressed_review_term",
            }
        if lookup_key in review_only or kind.casefold() == "technical":
            return {"resolution": "review_candidate"}
        return {"resolution": "generic_tag", "generic_tag": raw_name}


def _preserved_terms(raw_data: object) -> tuple[list[object], str | None]:
    if not isinstance(raw_data, Mapping):
        return [], None
    paths = (
        ("ai_extraction", "skills"),
        ("ai_enrichment", "skills"),
        ("skills",),
    )
    for path in paths:
        value: object = raw_data
        for key in path:
            if not isinstance(value, Mapping):
                value = None
                break
            value = value.get(key)
        if isinstance(value, list):
            return list(value), ".".join(path)
    return [], None


def _coerce_term(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        payload = dict(value)
        payload["name"] = (
            payload.get("normalized_name")
            or payload.get("name")
            or payload.get("skill")
            or payload.get("raw_name")
            or ""
        )
        return payload
    return {"name": str(value or ""), "kind": "technical"}


__all__ = [
    "RecoveredSkillEvidence",
    "SkillGovernanceRebuildInspector",
    "SkillGovernanceRebuildReport",
]
