from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata
from typing import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.contracts import (
    AssignCurrentJobTaxonomyCommand,
    CurrentJobSkillInput,
    JobTaxonomyBreadcrumb,
    ReplaceCurrentJobSkillsCommand,
)
from app.job_intelligence.current_taxonomies.store import CurrentTaxonomyStore
from app.job_intelligence.foundation import normalized_content_hash
from app.job_intelligence.source_attributes import SourceJobAttributesView
from app.models.current_taxonomy import (
    CurrentJobSkillMention,
    CurrentSkillCandidate,
    CurrentSourceTaxonomyMapping,
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.utils.time import utc_now


_DASHES = ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212")


def normalize_skill_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    for dash in _DASHES:
        text = text.replace(dash, "-")
    return re.sub(r"\s+", " ", text)


def normalize_exact_skill_key(value: object) -> str:
    text = normalize_skill_text(value).casefold()
    text = re.sub(r"[^a-z0-9+#./\-\s]+", " ", text)
    text = re.sub(r"\s*([+#./-])\s*", r"\1", text)
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or normalize_skill_text(value).casefold()


def _display_label(labels: Mapping[str, object]) -> str:
    for key in ("en", "en_HK", "zh_HK", "zh"):
        value = str(labels.get(key) or "").strip()
        if value:
            return value
    return next(
        (str(value).strip() for value in labels.values() if str(value).strip()),
        "",
    )


@dataclass(frozen=True)
class CurrentJobClassifierContext:
    prompt_payload: dict[str, object]
    allowed_codes: frozenset[str]
    breadcrumbs: dict[str, JobTaxonomyBreadcrumb]
    mapping_refs_by_code: dict[str, tuple[dict[str, str], ...]]


class CurrentTaxonomyEnrichment:
    """Build AI prompt context and persist revision-free enrichment results."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.store = CurrentTaxonomyStore(db)

    def build_job_context(
        self,
        evidence: SourceJobAttributesView,
    ) -> CurrentJobClassifierContext:
        nodes = tuple(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord)
                .where(
                    CurrentTaxonomyNodeRecord.taxonomy == "job",
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                )
                .order_by(
                    CurrentTaxonomyNodeRecord.sort_order,
                    CurrentTaxonomyNodeRecord.code,
                )
            )
        )
        by_code = {node.code: node for node in nodes}
        assignable = {
            node.code: node for node in nodes if bool(node.is_assignable)
        }
        source_keys = tuple(
            dict.fromkeys(
                node.source_classification_id
                for path in evidence.source_classification_paths
                for node in path.nodes
            )
        )
        mapping_rows = tuple(
            self.db.scalars(
                select(CurrentSourceTaxonomyMapping)
                .join(
                    CurrentTaxonomyNodeRecord,
                    (
                        CurrentTaxonomyNodeRecord.taxonomy
                        == CurrentSourceTaxonomyMapping.taxonomy
                    )
                    & (
                        CurrentTaxonomyNodeRecord.code
                        == CurrentSourceTaxonomyMapping.target_code
                    ),
                )
                .where(
                    CurrentSourceTaxonomyMapping.taxonomy == "job",
                    CurrentSourceTaxonomyMapping.source_site == evidence.source_site,
                    CurrentSourceTaxonomyMapping.source_key.in_(source_keys),
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                    CurrentTaxonomyNodeRecord.is_assignable.is_(True),
                )
                .order_by(
                    CurrentSourceTaxonomyMapping.target_code,
                    CurrentSourceTaxonomyMapping.source_key,
                )
            )
        ) if source_keys else ()

        target_codes = tuple(
            dict.fromkeys(row.target_code for row in mapping_rows)
        ) or tuple(assignable)
        breadcrumbs = {
            code: self._job_breadcrumb(assignable[code], by_code)
            for code in target_codes
        }
        refs_by_code: dict[str, list[dict[str, str]]] = {}
        for row in mapping_rows:
            refs_by_code.setdefault(row.target_code, []).append(
                {
                    "source_site": row.source_site,
                    "source_key": row.source_key,
                    "target_code": row.target_code,
                }
            )
        mapping_refs = {
            code: tuple(refs_by_code.get(code, ())) for code in target_codes
        }
        targets = [
            {
                "code": code,
                "label": _display_label(assignable[code].labels),
                "breadcrumb": " / ".join(
                    str(breadcrumbs[code][level]["label"])
                    for level in ("domain", "category", "subcategory")
                ),
            }
            for code in target_codes
        ]
        return CurrentJobClassifierContext(
            prompt_payload={
                "authority": "current-job-taxonomy",
                "source_classification_paths": [
                    {
                        "source_order": path.source_order,
                        "nodes": [
                            {
                                "id": node.source_classification_id,
                                "label": node.label,
                            }
                            for node in path.nodes
                        ],
                    }
                    for path in evidence.source_classification_paths
                ],
                "canonical_targets": targets,
            },
            allowed_codes=frozenset(target_codes),
            breadcrumbs=breadcrumbs,
            mapping_refs_by_code=mapping_refs,
        )

    def assign_job_from_classification(
        self,
        *,
        job_id: UUID,
        evidence: SourceJobAttributesView,
        classification: object,
        context: CurrentJobClassifierContext,
        model_provenance: dict[str, object] | None,
    ) -> dict[str, object]:
        payload = classification if isinstance(classification, dict) else {}
        target = str(payload.get("target_code") or "").strip()
        if payload.get("decision") != "select_existing" or target not in context.allowed_codes:
            return {
                "state": "unassigned",
                "assignment": None,
                "reason": "classifier_did_not_select_current_code",
            }
        captured_at = utc_now()
        mapping_refs = context.mapping_refs_by_code.get(target, ())
        source_refs = tuple(
            {
                "kind": "source-classification-path",
                "source_site": evidence.source_site,
                "source_order": path.source_order,
                "source_classification_ids": [
                    node.source_classification_id for node in path.nodes
                ],
            }
            for path in evidence.source_classification_paths
        )
        self.store.assign_job(
            AssignCurrentJobTaxonomyCommand(
                job_id=job_id,
                taxonomy_code=target,
                method="constrained_ai",
                evidence_hash=normalized_content_hash(
                    {
                        "source_evidence_hash": evidence.evidence_hash,
                        "classification": payload,
                    }
                ),
                source_evidence_refs=source_refs,
                mapping_ids=tuple(mapping_refs),
                model_provenance=model_provenance,
                breadcrumb=context.breadcrumbs[target],
                captured_at=captured_at,
            )
        )
        return {
            "state": "assigned",
            "assignment": {
                "taxonomy_code": target,
                "method": "constrained_ai",
                "breadcrumb": context.breadcrumbs[target],
                "model_provenance": model_provenance,
            },
            "reason": None,
        }

    def build_skill_prompt(self, *, role_mode: str) -> dict[str, object]:
        nodes = tuple(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord)
                .where(
                    CurrentTaxonomyNodeRecord.taxonomy == "skill",
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                )
                .order_by(
                    CurrentTaxonomyNodeRecord.sort_order,
                    CurrentTaxonomyNodeRecord.code,
                )
            )
        )
        values_by_level: dict[str, list[str]] = {
            "category": [],
            "technology": [],
            "skill": [],
        }
        for node in nodes:
            if node.level in values_by_level:
                values_by_level[node.level].append(_display_label(node.labels))
        return {
            "existing_categories": values_by_level["category"],
            "existing_technologies": values_by_level["technology"],
            "existing_skills": values_by_level["skill"],
            "review_only_terms": [],
            "suppressed_review_terms": [],
            "role_mode": role_mode,
        }

    def replace_job_skills(
        self,
        *,
        job_id: UUID,
        extracted_skills: Sequence[object],
        confidence: float | None,
        provenance: dict[str, object],
    ) -> dict[str, object]:
        now = utc_now()
        existing_mentions = tuple(
            self.db.scalars(
                select(CurrentJobSkillMention).where(
                    CurrentJobSkillMention.job_id == job_id,
                    CurrentJobSkillMention.status == "active",
                )
            )
        )
        touched_candidate_ids = {
            mention.candidate_id
            for mention in existing_mentions
            if mention.candidate_id is not None
        }
        for mention in existing_mentions:
            mention.status = "superseded"
            mention.superseded_at = now
            mention.updated_at = now
        self.db.flush()

        exact_skills = self._exact_skill_codes()
        seen_keys: set[str] = set()
        matched_codes: list[str] = []
        mention_payloads: list[dict[str, object]] = []
        for value in extracted_skills:
            payload = value if isinstance(value, dict) else {"name": value}
            raw_name = normalize_skill_text(payload.get("name"))
            normalized_key = normalize_exact_skill_key(raw_name)
            if not raw_name or not normalized_key or normalized_key in seen_keys:
                continue
            seen_keys.add(normalized_key)
            existing_key = normalize_exact_skill_key(payload.get("existing_skill"))
            skill_code = exact_skills.get(existing_key) or exact_skills.get(normalized_key)
            kind = str(payload.get("kind") or "technical").strip().lower()
            resolution = str(payload.get("resolution") or "").strip().lower()
            candidate_id = None
            generic_tag = None
            rejection_reason = None
            if skill_code is not None and kind not in {"generic", "reject"}:
                mention_resolution = "match_existing"
                matched_codes.append(skill_code)
            elif kind == "generic" or resolution == "drop":
                mention_resolution = "generic_tag"
                generic_tag = raw_name
                skill_code = None
            elif kind == "reject":
                mention_resolution = "rejected"
                rejection_reason = "model_rejected"
                skill_code = None
            else:
                mention_resolution = "candidate"
                skill_code = None
                candidate = self._upsert_candidate(
                    normalized_key=normalized_key,
                    raw_name=raw_name,
                    now=now,
                )
                candidate_id = candidate.id
                touched_candidate_ids.add(candidate.id)

            evidence_hash = normalized_content_hash(
                {
                    "job_id": str(job_id),
                    "skill": payload,
                    "provenance": provenance,
                }
            )
            mention = CurrentJobSkillMention(
                job_id=job_id,
                taxonomy="skill",
                raw_name=raw_name,
                normalized_key=normalized_key,
                resolution=mention_resolution,
                status="active",
                skill_code=skill_code,
                candidate_id=candidate_id,
                origin_candidate_id=None,
                generic_tag=generic_tag,
                rejection_reason=rejection_reason,
                source="ai-extraction",
                confidence=confidence,
                provenance=dict(provenance),
                evidence_hash=evidence_hash,
                created_at=now,
                updated_at=now,
                superseded_at=None,
            )
            self.db.add(mention)
            mention_payloads.append(
                {
                    "normalized_key": normalized_key,
                    "resolution": mention_resolution,
                    "skill_code": skill_code,
                    "candidate_id": str(candidate_id) if candidate_id else None,
                }
            )
        self.db.flush()

        counts = Counter(matched_codes)
        self.store.replace_job_skills(
            ReplaceCurrentJobSkillsCommand(
                job_id=job_id,
                skills=tuple(
                    CurrentJobSkillInput(
                        skill_code=code,
                        source="ai-extraction",
                        confidence=confidence,
                        provenance=dict(provenance),
                        mention_count=count,
                        updated_at=now,
                    )
                    for code, count in sorted(counts.items())
                ),
            )
        )
        self._refresh_candidate_metrics(touched_candidate_ids, now=now)
        return {
            "skills": [
                {"skill_code": code, "mention_count": count}
                for code, count in sorted(counts.items())
            ],
            "mentions": mention_payloads,
        }

    def _exact_skill_codes(self) -> dict[str, str]:
        nodes = tuple(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord).where(
                    CurrentTaxonomyNodeRecord.taxonomy == "skill",
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                    CurrentTaxonomyNodeRecord.is_assignable.is_(True),
                )
            )
        )
        exact: dict[str, str] = {}
        for node in sorted(nodes, key=lambda item: item.code):
            for value in (node.code, *node.labels.values()):
                key = normalize_exact_skill_key(value)
                if key:
                    exact.setdefault(key, node.code)
        aliases = self.db.scalars(
            select(CurrentTaxonomyAliasRecord)
            .where(CurrentTaxonomyAliasRecord.taxonomy == "skill")
            .order_by(
                CurrentTaxonomyAliasRecord.node_code,
                CurrentTaxonomyAliasRecord.alias,
            )
        )
        for alias in aliases:
            key = normalize_exact_skill_key(alias.normalized_alias or alias.alias)
            if key:
                exact.setdefault(key, alias.node_code)
        return exact

    def _upsert_candidate(
        self,
        *,
        normalized_key: str,
        raw_name: str,
        now,
    ) -> CurrentSkillCandidate:
        candidate = self.db.scalar(
            select(CurrentSkillCandidate).where(
                CurrentSkillCandidate.normalized_key == normalized_key
            )
        )
        if candidate is None:
            candidate = CurrentSkillCandidate(
                taxonomy="skill",
                normalized_key=normalized_key,
                canonical_raw_name=raw_name,
                raw_variants=[raw_name],
                occurrence_count=0,
                distinct_job_count=0,
                evidence_summary={},
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
            self.db.add(candidate)
            self.db.flush()
            return candidate
        variants = {
            normalize_skill_text(value)
            for value in (candidate.raw_variants or [])
            if normalize_skill_text(value)
        }
        variants.add(raw_name)
        candidate.raw_variants = sorted(variants, key=str.casefold)
        candidate.last_seen_at = now
        candidate.updated_at = now
        return candidate

    def _refresh_candidate_metrics(
        self,
        candidate_ids: set[UUID],
        *,
        now,
    ) -> None:
        for candidate_id in candidate_ids:
            occurrence_count, distinct_job_count = self.db.execute(
                select(
                    func.count(CurrentJobSkillMention.id),
                    func.count(func.distinct(CurrentJobSkillMention.job_id)),
                ).where(
                    CurrentJobSkillMention.candidate_id == candidate_id,
                    CurrentJobSkillMention.resolution == "candidate",
                    CurrentJobSkillMention.status == "active",
                )
            ).one()
            candidate = self.db.get(CurrentSkillCandidate, candidate_id)
            if candidate is None:
                continue
            candidate.occurrence_count = int(occurrence_count or 0)
            candidate.distinct_job_count = int(distinct_job_count or 0)
            candidate.evidence_summary = {
                "active_mentions": candidate.occurrence_count,
                "distinct_jobs": candidate.distinct_job_count,
            }
            candidate.updated_at = now
        self.db.flush()

    @staticmethod
    def _job_breadcrumb(
        leaf: CurrentTaxonomyNodeRecord,
        by_code: dict[str, CurrentTaxonomyNodeRecord],
    ) -> JobTaxonomyBreadcrumb:
        chain: list[CurrentTaxonomyNodeRecord] = []
        cursor: CurrentTaxonomyNodeRecord | None = leaf
        visited: set[str] = set()
        while cursor is not None and cursor.code not in visited:
            visited.add(cursor.code)
            chain.append(cursor)
            cursor = by_code.get(cursor.parent_code) if cursor.parent_code else None
        levels = {node.level: node for node in reversed(chain)}
        return {
            level: {
                "code": levels[level].code,
                "label": _display_label(levels[level].labels),
            }
            for level in ("domain", "category", "subcategory")
        }


__all__ = [
    "CurrentJobClassifierContext",
    "CurrentTaxonomyEnrichment",
    "normalize_exact_skill_key",
    "normalize_skill_text",
]
