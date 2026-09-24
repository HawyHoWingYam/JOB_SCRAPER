from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.enrichment import (
    normalize_exact_skill_key,
    normalize_skill_text,
)
from app.job_intelligence.foundation import normalized_content_hash
from app.models.current_taxonomy import (
    CurrentTaxonomyAliasRecord,
    CurrentTaxonomyNodeRecord,
)
from app.services.jev_evaluation import (
    PreparedSkillOptions,
    SkillOption,
    prepare_skill_options,
    rank_prepared_skill_options,
)
from app.services.jev_online_skill_classification import (
    OnlineSkillCandidate,
    OnlineSkillCase,
    OnlineSkillOption,
)


ONLINE_SKILL_RUBRIC_VERSION = "jev-online-skill-v1"


@dataclass
class OnlineSkillCaseBuildContext:
    """Request-scoped taxonomy materialization and deterministic rank cache."""

    db: Session
    options: tuple[SkillOption, ...] | None = None
    prepared_options: PreparedSkillOptions | None = None
    exact_codes: dict[str, str] | None = None
    display_names: dict[str, str] | None = None
    taxonomy_snapshot_sha256: str | None = None
    ranked_codes: dict[tuple[str, int], tuple[str, ...]] = field(default_factory=dict)

    def ensure_loaded(self) -> None:
        if self.options is not None:
            return
        nodes = tuple(
            self.db.scalars(
                select(CurrentTaxonomyNodeRecord)
                .where(
                    CurrentTaxonomyNodeRecord.taxonomy == "skill",
                    CurrentTaxonomyNodeRecord.is_active.is_(True),
                    CurrentTaxonomyNodeRecord.is_assignable.is_(True),
                )
                .order_by(CurrentTaxonomyNodeRecord.code)
            )
        )
        active_codes = {node.code for node in nodes}
        aliases = tuple(
            self.db.scalars(
                select(CurrentTaxonomyAliasRecord)
                .where(
                    CurrentTaxonomyAliasRecord.taxonomy == "skill",
                    CurrentTaxonomyAliasRecord.node_code.in_(active_codes),
                )
                .order_by(
                    CurrentTaxonomyAliasRecord.node_code,
                    CurrentTaxonomyAliasRecord.alias,
                )
            )
        )
        aliases_by_code: dict[str, list[str]] = defaultdict(list)
        for alias in aliases:
            aliases_by_code[alias.node_code].append(alias.alias)
        self.options = tuple(
            SkillOption(
                code=node.code,
                labels=dict(node.labels),
                aliases=tuple(aliases_by_code[node.code]),
            )
            for node in nodes
        )
        self.prepared_options = prepare_skill_options(self.options)
        self.exact_codes = {}
        for option in self.options:
            for value in (option.code, *option.labels.values(), *option.aliases):
                key = normalize_exact_skill_key(value)
                if key:
                    self.exact_codes.setdefault(key, option.code)
        self.display_names = {
            option.code: next(
                (
                    option.labels[key]
                    for key in ("en", "en_HK", "zh_HK", "zh")
                    if option.labels.get(key)
                ),
                option.code,
            )
            for option in self.options
        }
        taxonomy_snapshot = {
            "nodes": [
                {
                    "code": node.code,
                    "labels": dict(node.labels),
                    "level": node.level,
                    "parent_code": node.parent_code,
                    "is_assignable": bool(node.is_assignable),
                }
                for node in nodes
            ],
            "aliases": [
                {
                    "node_code": alias.node_code,
                    "alias": alias.alias,
                    "normalized_alias": alias.normalized_alias,
                }
                for alias in aliases
            ],
        }
        self.taxonomy_snapshot_sha256 = normalized_content_hash(taxonomy_snapshot)

    def rank_codes(self, raw_name: str, *, limit: int) -> tuple[str, ...]:
        self.ensure_loaded()
        cache_key = (normalize_exact_skill_key(raw_name), limit)
        if cache_key not in self.ranked_codes:
            ranked = rank_prepared_skill_options(
                raw_name,
                self.prepared_options or (),
                limit=limit,
            )
            self.ranked_codes[cache_key] = tuple(str(row["code"]) for row in ranked)
        return self.ranked_codes[cache_key]


def build_online_skill_case(
    db: Session,
    *,
    job_id: UUID,
    source_site: str,
    title: str,
    evidence_text: str,
    extracted_skills: Sequence[object],
    option_limit: int = 5,
    context: OnlineSkillCaseBuildContext | None = None,
) -> OnlineSkillCase | None:
    if option_limit < 1:
        raise ValueError("online Skill option limit must be positive")
    if not any(
        normalize_skill_text(value.get("name") if isinstance(value, dict) else value)
        for value in extracted_skills
    ):
        return None
    build_context = context or OnlineSkillCaseBuildContext(db)
    build_context.ensure_loaded()
    exact_codes = build_context.exact_codes or {}
    display_names = build_context.display_names or {}

    candidates: list[OnlineSkillCandidate] = []
    seen: set[str] = set()
    for value in extracted_skills:
        payload = value if isinstance(value, dict) else {"name": value}
        raw_name = normalize_skill_text(payload.get("name"))
        normalized_key = normalize_exact_skill_key(raw_name)
        if not raw_name or not normalized_key or normalized_key in seen:
            continue
        seen.add(normalized_key)
        ranked_codes = build_context.rank_codes(raw_name, limit=option_limit)
        hinted_code = exact_codes.get(
            normalize_exact_skill_key(payload.get("existing_skill"))
        )
        candidate_codes = []
        for code in (hinted_code, *ranked_codes):
            if code and code not in candidate_codes:
                candidate_codes.append(code)
            if len(candidate_codes) >= option_limit:
                break
        candidates.append(
            OnlineSkillCandidate(
                raw_name=raw_name,
                evidence=(
                    normalize_skill_text(payload.get("evidence"))
                    or "No dedicated evidence span was extracted; inspect the Job text."
                ),
                options=tuple(
                    OnlineSkillOption(code=code, label=display_names[code])
                    for code in candidate_codes
                ),
            )
        )
    if not candidates:
        return None

    return OnlineSkillCase(
        job_id=str(job_id),
        source_site=source_site,
        title=title,
        evidence_text=evidence_text,
        candidates=tuple(candidates),
        taxonomy_snapshot_sha256=build_context.taxonomy_snapshot_sha256 or "",
        rubric_version=ONLINE_SKILL_RUBRIC_VERSION,
    )


__all__ = [
    "ONLINE_SKILL_RUBRIC_VERSION",
    "OnlineSkillCaseBuildContext",
    "build_online_skill_case",
]
