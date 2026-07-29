from __future__ import annotations

from collections import Counter
import re
import unicodedata
from typing import Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.contracts import (
    CurrentJobSkillInput,
    ReplaceCurrentJobSkillsCommand,
)
from app.job_intelligence.current_taxonomies.store import CurrentTaxonomyStore
from app.job_intelligence.current_taxonomies.skill_curation import (
    resolve_skill_curation,
)
from app.job_intelligence.foundation import normalized_content_hash
from app.models.current_taxonomy import (
    CurrentJobSkillMention,
    CurrentSkillCandidate,
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


class CurrentSkillEnrichment:
    """Build Skill prompt context and persist governed Skill evidence."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.store = CurrentTaxonomyStore(db)

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
            local_disposition = resolve_skill_curation(raw_name)
            kind = str(payload.get("kind") or "technical").strip().lower()
            resolution = str(payload.get("resolution") or "").strip().lower()
            candidate_id = None
            generic_tag = None
            rejection_reason = None
            if skill_code is not None and kind not in {"generic", "reject"}:
                mention_resolution = "match_existing"
                matched_codes.append(skill_code)
            elif local_disposition is not None and local_disposition.kind == "generic":
                mention_resolution = "generic_tag"
                generic_tag = local_disposition.generic_tag
                skill_code = None
            elif local_disposition is not None and local_disposition.kind == "reject":
                mention_resolution = "rejected"
                rejection_reason = local_disposition.rejection_reason
                skill_code = None
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

__all__ = [
    "CurrentSkillEnrichment",
    "normalize_exact_skill_key",
    "normalize_skill_text",
]
