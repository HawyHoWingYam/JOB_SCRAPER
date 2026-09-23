"""Seed the initial Skill taxonomy and reconcile deterministic evidence."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.job_intelligence.current_taxonomies.transforms import transform_skill_taxonomy
from app.job_intelligence.current_taxonomies.store import CurrentTaxonomyStore
from app.models.current_taxonomy import CurrentTaxonomyNodeRecord
from app.models.current_taxonomy import CurrentTaxonomyAliasRecord
from app.services.classification_domain_adapters import SkillClassificationAdapter


SKILL_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "data" / "skill_taxonomy.json"


def synchronize_initial_skill_taxonomy(db: Session) -> dict[str, int | bool]:
    """Install the bundled baseline without overwriting operator-owned nodes.

    An empty taxonomy is seeded normally. On later starts, only missing
    manifest nodes and aliases are added; existing nodes (including operator
    additions and decisions) are left untouched. This makes taxonomy coverage
    upgrades restartable without a destructive schema/data cutover.
    """

    payload = json.loads(SKILL_TAXONOMY_PATH.read_text(encoding="utf-8"))
    snapshot = transform_skill_taxonomy(payload)

    existing_count = db.scalar(
        select(CurrentTaxonomyNodeRecord.code)
        .where(CurrentTaxonomyNodeRecord.taxonomy == "skill")
        .limit(1)
    )
    if existing_count is None:
        CurrentTaxonomyStore(db).synchronize(snapshot)
        return {
            "seeded": True,
            "nodes": len(snapshot.nodes),
            "aliases": len(snapshot.aliases),
        }

    existing_nodes = {
        row.code: row
        for row in db.scalars(
            select(CurrentTaxonomyNodeRecord).where(
                CurrentTaxonomyNodeRecord.taxonomy == "skill"
            )
        )
    }
    added_nodes = 0
    for node in snapshot.nodes:
        if node.code in existing_nodes:
            continue
        db.add(
            CurrentTaxonomyNodeRecord(
                taxonomy=node.taxonomy,
                code=node.code,
                parent_code=node.parent_code,
                level=node.level,
                labels=dict(node.labels),
                sort_order=node.order,
                is_assignable=node.is_assignable,
                is_active=node.is_active,
            )
        )
        db.flush()
        existing_nodes[node.code] = db.get(
            CurrentTaxonomyNodeRecord, ("skill", node.code)
        )
        added_nodes += 1

    existing_aliases = {
        (row.node_code, row.alias)
        for row in db.scalars(
            select(CurrentTaxonomyAliasRecord).where(
                CurrentTaxonomyAliasRecord.taxonomy == "skill"
            )
        )
    }
    added_aliases = 0
    for alias in snapshot.aliases:
        if (alias.node_code, alias.alias) in existing_aliases:
            continue
        db.add(
            CurrentTaxonomyAliasRecord(
                taxonomy=alias.taxonomy,
                node_code=alias.node_code,
                alias=alias.alias,
                normalized_alias=alias.normalized_alias,
            )
        )
        existing_aliases.add((alias.node_code, alias.alias))
        added_aliases += 1
    db.flush()
    return {
        "seeded": False,
        "nodes": added_nodes,
        "aliases": added_aliases,
    }


def reconcile_deterministic_skill_candidates(db: Session) -> int:
    """Resolve known names and local dispositions after taxonomy initialization."""

    return SkillClassificationAdapter().reconcile_deterministic_candidates(db)


__all__ = [
    "SKILL_TAXONOMY_PATH",
    "reconcile_deterministic_skill_candidates",
    "synchronize_initial_skill_taxonomy",
]
