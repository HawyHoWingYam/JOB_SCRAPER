from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.llm_client import get_llm_client
from app.ai.job_insight_extractor import get_job_insight_extractor
from app.ai.llm_client import get_llm_status
from app.job_intelligence.current_taxonomies.contracts import (
    CurrentJobSkillInput,
    ReplaceCurrentJobSkillsCommand,
)
from app.job_intelligence.current_taxonomies.enrichment import (
    CurrentTaxonomyEnrichment,
    normalize_exact_skill_key,
    normalize_skill_text,
)
from app.job_intelligence.current_taxonomies.store import CurrentTaxonomyStore
from app.job_intelligence.current_taxonomies.company_projection import (
    project_current_company_industry,
)
from app.job_intelligence.source_attributes import SourceJobAttributes
from app.models.company import Company
from app.models.current_taxonomy import (
    CurrentCompanyIndustryAssignment,
    CurrentJobSkillMention,
    CurrentJobTaxonomyAssignment,
    CurrentSkillCandidate,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.models.job import Job
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.services.classification_batch_runtime import ClassificationCandidate
from app.utils.time import utc_now


_RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "skill_curation_rules.json"
_CODE_PART = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SkillPlacementDecision:
    status: str
    category_code: str | None = None
    technology_code: str | None = None
    name: str | None = None
    aliases: tuple[str, ...] = ()


class SkillPlacementClassifier(Protocol):
    async def classify(
        self,
        *,
        candidate: CurrentSkillCandidate,
        paths: tuple[dict[str, str], ...],
    ) -> SkillPlacementDecision: ...


class LLMSkillPlacementClassifier:
    """Choose an existing Category/Technology path; never invent parent nodes."""

    async def classify(
        self,
        *,
        candidate: CurrentSkillCandidate,
        paths: tuple[dict[str, str], ...],
    ) -> SkillPlacementDecision:
        prompt = (
            "Classify one repeated technical Skill candidate. Return JSON only with "
            "status=create|generic|reject|uncertain, category_code, technology_code, "
            "name, aliases. For create, copy one exact Category/Technology pair from "
            "the supplied paths. If placement is not reliable, use uncertain. Never "
            "invent a parent or an Other/Unknown fallback.\n\n"
            f"Candidate: {candidate.canonical_raw_name}\n"
            f"Variants: {json.dumps(candidate.raw_variants or [], ensure_ascii=False)}\n"
            f"Distinct jobs: {candidate.distinct_job_count}\n"
            f"Existing paths: {json.dumps(paths, ensure_ascii=False)}"
        )
        payload = await get_llm_client("jobs").generate_json(prompt)
        status = str(payload.get("status") or "uncertain").strip().lower()
        if status not in {"create", "generic", "reject", "uncertain"}:
            status = "uncertain"
        raw_aliases = payload.get("aliases")
        aliases = tuple(
            normalize_skill_text(value)
            for value in raw_aliases
            if normalize_skill_text(value)
        ) if isinstance(raw_aliases, list) else ()
        return SkillPlacementDecision(
            status=status,
            category_code=_optional_text(payload.get("category_code")),
            technology_code=_optional_text(payload.get("technology_code")),
            name=_optional_text(payload.get("name")),
            aliases=aliases,
        )


class SkillClassificationAdapter:
    domain = "skill"

    def __init__(
        self,
        *,
        placement_classifier: SkillPlacementClassifier | None = None,
    ) -> None:
        self.placement_classifier = placement_classifier or LLMSkillPlacementClassifier()

    def select_candidates(
        self,
        db: Session,
        *,
        filters: dict[str, object],
        limit: int,
    ) -> tuple[ClassificationCandidate, ...]:
        del filters
        threshold = AIRuntimeSettingsService(
            db
        ).get_skill_auto_create_distinct_job_threshold()
        rows = tuple(
            db.scalars(
                select(CurrentSkillCandidate)
                .where(
                    CurrentSkillCandidate.resolved_skill_code.is_(None),
                    CurrentSkillCandidate.distinct_job_count >= threshold,
                )
                .order_by(
                    CurrentSkillCandidate.distinct_job_count.desc(),
                    CurrentSkillCandidate.first_seen_at,
                    CurrentSkillCandidate.id,
                )
                .limit(limit)
            )
        )
        return tuple(
            ClassificationCandidate(
                subject_id=str(row.id),
                subject_label=row.canonical_raw_name,
                payload={
                    "normalized_key": row.normalized_key,
                    "distinct_job_count": row.distinct_job_count,
                },
            )
            for row in rows
        )

    async def process_candidate(
        self,
        db: Session,
        candidate: ClassificationCandidate,
    ) -> None:
        candidate_id = UUID(candidate.subject_id)
        row = db.scalar(
            select(CurrentSkillCandidate)
            .where(CurrentSkillCandidate.id == candidate_id)
            .with_for_update()
        )
        if row is None:
            raise ValueError("Skill candidate was not found")
        if row.resolved_skill_code:
            return
        threshold = AIRuntimeSettingsService(
            db
        ).get_skill_auto_create_distinct_job_threshold()
        if row.distinct_job_count < threshold:
            raise ValueError("Skill candidate no longer meets the distinct Job threshold")

        existing_code = self._resolve_existing_code(db, row)
        if existing_code:
            self._resolve_mentions(db, row, resolution="match_existing", skill_code=existing_code)
            row.resolved_skill_code = existing_code
            self._finish_candidate(row)
            self._reproject_jobs(db, row.id)
            return

        local_disposition = _local_disposition(row.canonical_raw_name)
        if local_disposition == "generic":
            self._resolve_mentions(
                db,
                row,
                resolution="generic_tag",
                generic_tag=row.canonical_raw_name,
            )
            self._finish_candidate(row)
            self._reproject_jobs(db, row.id)
            return
        if local_disposition == "reject":
            self._resolve_mentions(
                db,
                row,
                resolution="rejected",
                rejection_reason="suppressed_generic_term",
            )
            self._finish_candidate(row)
            self._reproject_jobs(db, row.id)
            return

        paths = self._placement_paths(db)
        decision = await self.placement_classifier.classify(
            candidate=row,
            paths=paths,
        )
        if decision.status == "generic":
            self._resolve_mentions(
                db,
                row,
                resolution="generic_tag",
                generic_tag=row.canonical_raw_name,
            )
            self._finish_candidate(row)
            self._reproject_jobs(db, row.id)
            return
        if decision.status == "reject":
            self._resolve_mentions(
                db,
                row,
                resolution="rejected",
                rejection_reason="classifier_rejected",
            )
            self._finish_candidate(row)
            self._reproject_jobs(db, row.id)
            return
        if decision.status != "create":
            raise ValueError("Skill candidate placement is uncertain")

        skill_code = self._create_skill(db, row, decision)
        self._resolve_mentions(db, row, resolution="match_existing", skill_code=skill_code)
        row.resolved_skill_code = skill_code
        self._finish_candidate(row)
        self._reproject_jobs(db, row.id)

    def _resolve_existing_code(
        self,
        db: Session,
        candidate: CurrentSkillCandidate,
    ) -> str | None:
        exact = _exact_skill_codes(db)
        rules = _load_rules()
        alias_lookup = {
            normalize_exact_skill_key(key): normalize_exact_skill_key(value)
            for key, value in (rules.get("canonical_aliases") or {}).items()
        }
        values = (
            candidate.normalized_key,
            candidate.canonical_raw_name,
            *(candidate.raw_variants or []),
        )
        for value in values:
            key = normalize_exact_skill_key(value)
            canonical_key = alias_lookup.get(key, key)
            match = exact.get(canonical_key) or exact.get(key)
            if match:
                return match
        return None

    @staticmethod
    def _placement_paths(db: Session) -> tuple[dict[str, str], ...]:
        nodes = tuple(
            db.scalars(
                select(CurrentTaxonomyNodeRecord).where(
                    CurrentTaxonomyNodeRecord.taxonomy == "skill",
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                    CurrentTaxonomyNodeRecord.level.in_(("category", "technology")),
                )
            )
        )
        by_code = {node.code: node for node in nodes}
        return tuple(
            {
                "category_code": parent.code,
                "category_label": _node_label(parent),
                "technology_code": node.code,
                "technology_label": _node_label(node),
            }
            for node in sorted(nodes, key=lambda item: (item.sort_order, item.code))
            if node.level == "technology"
            and (parent := by_code.get(node.parent_code or "")) is not None
            and parent.level == "category"
        )

    @staticmethod
    def _create_skill(
        db: Session,
        candidate: CurrentSkillCandidate,
        decision: SkillPlacementDecision,
    ) -> str:
        category = db.get(
            CurrentTaxonomyNodeRecord,
            ("skill", decision.category_code),
        ) if decision.category_code else None
        technology = db.get(
            CurrentTaxonomyNodeRecord,
            ("skill", decision.technology_code),
        ) if decision.technology_code else None
        if (
            category is None
            or technology is None
            or not category.is_active
            or not technology.is_active
            or category.level != "category"
            or technology.level != "technology"
            or technology.parent_code != category.code
        ):
            raise ValueError("Skill candidate placement is uncertain")
        name = normalize_skill_text(decision.name or candidate.canonical_raw_name)
        slug = _CODE_PART.sub("_", normalize_exact_skill_key(name)).strip("_")
        if not name or not slug:
            raise ValueError("Skill candidate name cannot produce a stable code")
        code = f"{technology.code}.{slug}"
        if db.get(CurrentTaxonomyNodeRecord, ("skill", code)) is not None:
            raise ValueError("Skill candidate stable code conflicts with an existing node")
        max_order = db.scalar(
            select(func.max(CurrentTaxonomyNodeRecord.sort_order)).where(
                CurrentTaxonomyNodeRecord.taxonomy == "skill",
                CurrentTaxonomyNodeRecord.parent_code == technology.code,
            )
        )
        db.add(
            CurrentTaxonomyNodeRecord(
                taxonomy="skill",
                code=code,
                parent_code=technology.code,
                level="skill",
                labels={"en": name},
                sort_order=int(max_order or 0) + 1,
                is_assignable=True,
                is_active=True,
            )
        )
        db.flush()
        aliases = {
            normalize_skill_text(value)
            for value in (
                candidate.canonical_raw_name,
                *(candidate.raw_variants or []),
                *decision.aliases,
            )
            if normalize_skill_text(value)
            and normalize_exact_skill_key(value) != normalize_exact_skill_key(name)
        }
        for alias in sorted(aliases, key=str.casefold):
            db.add(
                CurrentTaxonomyAliasRecord(
                    taxonomy="skill",
                    node_code=code,
                    alias=alias,
                    normalized_alias=normalize_exact_skill_key(alias),
                )
            )
        db.flush()
        return code

    @staticmethod
    def _resolve_mentions(
        db: Session,
        candidate: CurrentSkillCandidate,
        *,
        resolution: str,
        skill_code: str | None = None,
        generic_tag: str | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        now = utc_now()
        mentions = tuple(
            db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.candidate_id == candidate.id,
                    CurrentJobSkillMention.resolution == "candidate",
                    CurrentJobSkillMention.status == "active",
                )
            )
        )
        for mention in mentions:
            mention.origin_candidate_id = candidate.id
            mention.candidate_id = None
            mention.resolution = resolution
            mention.skill_code = skill_code
            mention.generic_tag = generic_tag
            mention.rejection_reason = rejection_reason
            mention.updated_at = now
        db.flush()

    @staticmethod
    def _finish_candidate(candidate: CurrentSkillCandidate) -> None:
        candidate.occurrence_count = 0
        candidate.distinct_job_count = 0
        candidate.evidence_summary = {
            "active_mentions": 0,
            "distinct_jobs": 0,
            "automatic_processing": "resolved",
        }
        candidate.updated_at = utc_now()

    @staticmethod
    def _reproject_jobs(db: Session, candidate_id: UUID) -> None:
        job_ids = tuple(
            db.scalars(
                select(CurrentJobSkillMention.job_id)
                .where(CurrentJobSkillMention.origin_candidate_id == candidate_id)
                .distinct()
            )
        )
        store = CurrentTaxonomyStore(db)
        now = utc_now()
        for job_id in job_ids:
            mentions = tuple(
                db.scalars(
                    select(CurrentJobSkillMention).where(
                        CurrentJobSkillMention.job_id == job_id,
                        CurrentJobSkillMention.status == "active",
                        CurrentJobSkillMention.resolution == "match_existing",
                    )
                )
            )
            counts = Counter(
                mention.skill_code for mention in mentions if mention.skill_code
            )
            store.replace_job_skills(
                ReplaceCurrentJobSkillsCommand(
                    job_id=job_id,
                    skills=tuple(
                        CurrentJobSkillInput(
                            skill_code=code,
                            source="automatic-candidate-processing",
                            confidence=None,
                            provenance={"candidate_id": str(candidate_id)},
                            mention_count=count,
                            updated_at=now,
                        )
                        for code, count in sorted(counts.items())
                    ),
                )
            )


class JobTaxonomyClassificationAdapter:
    domain = "job_taxonomy"

    def select_candidates(
        self,
        db: Session,
        *,
        filters: dict[str, object],
        limit: int,
    ) -> tuple[ClassificationCandidate, ...]:
        query = (
            select(Job)
            .outerjoin(
                CurrentJobTaxonomyAssignment,
                CurrentJobTaxonomyAssignment.job_id == Job.id,
            )
            .where(
                Job.is_deleted.is_(False),
                CurrentJobTaxonomyAssignment.job_id.is_(None),
            )
        )
        source_sites = _string_filter(filters.get("source_sites"))
        if source_sites:
            query = query.where(Job.source_site.in_(source_sites))
        rows = tuple(db.scalars(query.order_by(Job.created_at, Job.id).limit(limit)))
        return tuple(
            ClassificationCandidate(
                subject_id=str(job.id),
                subject_label=job.title,
                payload={"source_site": job.source_site},
            )
            for job in rows
        )

    async def process_candidate(
        self,
        db: Session,
        candidate: ClassificationCandidate,
    ) -> None:
        job = db.get(Job, UUID(candidate.subject_id))
        if job is None or job.is_deleted:
            raise ValueError("Job is unavailable for taxonomy classification")
        current = CurrentTaxonomyEnrichment(db)
        evidence = SourceJobAttributes(db).get(job.id)
        context = current.build_job_context(evidence)
        insight = await get_job_insight_extractor().extract_taxonomy(
            title=job.title,
            description=job.description or "",
            taxonomy_candidates=context.prompt_payload,
        )
        llm_status = get_llm_status("jobs")
        provenance = {
            key: value
            for key, value in {
                "provider": llm_status.get("active_provider"),
                "name": llm_status.get("active_model"),
                "version": llm_status.get("model_version"),
            }.items()
            if isinstance(value, str) and value.strip()
        }
        result = current.assign_job_from_classification(
            job_id=job.id,
            evidence=evidence,
            classification=insight.get("classification"),
            context=context,
            model_provenance=provenance,
        )
        if result["state"] != "assigned":
            raise ValueError(
                "Job taxonomy classifier did not choose a reliable current code"
            )


class CompanyIndustryClassificationAdapter:
    domain = "company_industry"

    def select_candidates(
        self,
        db: Session,
        *,
        filters: dict[str, object],
        limit: int,
    ) -> tuple[ClassificationCandidate, ...]:
        query = (
            select(Company)
            .outerjoin(
                CurrentCompanyIndustryAssignment,
                CurrentCompanyIndustryAssignment.company_id == Company.id,
            )
            .where(
                Company.is_deleted.is_(False),
                CurrentCompanyIndustryAssignment.company_id.is_(None),
            )
        )
        source_sites = _string_filter(filters.get("source_sites"))
        if source_sites:
            query = query.where(Company.source_site.in_(source_sites))
        rows = tuple(
            db.scalars(query.order_by(Company.created_at, Company.id).limit(limit))
        )
        return tuple(
            ClassificationCandidate(
                subject_id=str(company.id),
                subject_label=company.name,
                payload={"source_site": company.source_site},
            )
            for company in rows
        )

    async def process_candidate(
        self,
        db: Session,
        candidate: ClassificationCandidate,
    ) -> None:
        company_id = UUID(candidate.subject_id)
        company = db.get(Company, company_id)
        if company is None or company.is_deleted:
            raise ValueError("Company is unavailable for industry classification")
        jobs = tuple(
            db.scalars(
                select(Job)
                .where(Job.company_id == company_id, Job.is_deleted.is_(False))
                .order_by(Job.created_at.desc(), Job.id.desc())
            )
        )
        for job in jobs:
            result = project_current_company_industry(db, company_id, job)
            if result is not None and result.state == "assigned":
                return
        raise ValueError("Company has no mapped source-industry evidence")


def _load_rules() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as stream:
        payload = json.load(stream)
    return payload if isinstance(payload, dict) else {}


def _local_disposition(value: str) -> str | None:
    key = _loose_key(value)
    rules = _load_rules()
    generic = {_loose_key(item) for item in rules.get("generic_terms") or []}
    suppressed = {
        _loose_key(item) for item in rules.get("suppressed_review_terms") or []
    }
    if key in generic:
        return "generic"
    if key in suppressed:
        return "reject"
    return None


def _exact_skill_codes(db: Session) -> dict[str, str]:
    exact: dict[str, str] = {}
    nodes = tuple(
        db.scalars(
            select(CurrentTaxonomyNodeRecord).where(
                CurrentTaxonomyNodeRecord.taxonomy == "skill",
                CurrentTaxonomyNodeRecord.level == "skill",
                CurrentTaxonomyNodeRecord.is_active.is_(True),
                CurrentTaxonomyNodeRecord.is_assignable.is_(True),
            )
        )
    )
    for node in sorted(nodes, key=lambda item: item.code):
        for value in (node.code, *node.labels.values()):
            key = normalize_exact_skill_key(value)
            if key:
                exact.setdefault(key, node.code)
    aliases = db.scalars(
        select(CurrentTaxonomyAliasRecord)
        .where(CurrentTaxonomyAliasRecord.taxonomy == "skill")
        .order_by(CurrentTaxonomyAliasRecord.node_code, CurrentTaxonomyAliasRecord.alias)
    )
    for alias in aliases:
        key = normalize_exact_skill_key(alias.normalized_alias or alias.alias)
        if key:
            exact.setdefault(key, alias.node_code)
    return exact


def _node_label(node: CurrentTaxonomyNodeRecord) -> str:
    labels = node.labels if isinstance(node.labels, dict) else {}
    return str(labels.get("en") or next(iter(labels.values()), node.code))


def _loose_key(value: object) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).split())


def _optional_text(value: object) -> str | None:
    text = normalize_skill_text(value)
    return text or None


def _string_filter(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        dict.fromkeys(
            str(item).strip().lower()
            for item in value
            if str(item).strip()
        )
    )


__all__ = [
    "CompanyIndustryClassificationAdapter",
    "JobTaxonomyClassificationAdapter",
    "LLMSkillPlacementClassifier",
    "SkillClassificationAdapter",
    "SkillPlacementClassifier",
    "SkillPlacementDecision",
]
