from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.job_intelligence.current_taxonomies.contracts import (
    CurrentTaxonomyAlias,
    CurrentTaxonomyNode,
    CurrentTaxonomySnapshot,
)
from app.job_intelligence.current_taxonomies.normalization import (
    normalize_skill_lookup_key,
)


def _objects(value: object, *, field: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field} must be an array of objects")
    return tuple(value)


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def transform_skill_taxonomy(seed: Mapping[str, Any]) -> CurrentTaxonomySnapshot:
    nodes: list[CurrentTaxonomyNode] = []
    aliases: list[CurrentTaxonomyAlias] = []
    for category in _objects(seed.get("categories"), field="categories"):
        category_code = _required_text(category.get("code"), field="category.code")
        nodes.append(
            CurrentTaxonomyNode(
                taxonomy="skill",
                code=category_code,
                parent_code=None,
                level="category",
                labels={"en": _required_text(category.get("name"), field="category.name")},
                order=int(category["order"]),
                is_assignable=False,
                is_active=bool(category.get("is_active", True)),
            )
        )
        for technology in _objects(
            category.get("technologies"), field="category.technologies"
        ):
            technology_code = _required_text(
                technology.get("code"), field="technology.code"
            )
            nodes.append(
                CurrentTaxonomyNode(
                    taxonomy="skill",
                    code=technology_code,
                    parent_code=category_code,
                    level="technology",
                    labels={
                        "en": _required_text(
                            technology.get("name"), field="technology.name"
                        )
                    },
                    order=int(technology["order"]),
                    is_assignable=False,
                    is_active=bool(technology.get("is_active", True)),
                )
            )
            for skill in _objects(technology.get("skills"), field="technology.skills"):
                skill_code = _required_text(skill.get("code"), field="skill.code")
                nodes.append(
                    CurrentTaxonomyNode(
                        taxonomy="skill",
                        code=skill_code,
                        parent_code=technology_code,
                        level="skill",
                        labels={"en": _required_text(skill.get("name"), field="skill.name")},
                        order=int(skill["order"]),
                        is_assignable=True,
                        is_active=bool(skill.get("is_active", True)),
                    )
                )
                for alias in skill.get("aliases") or ():
                    alias_text = _required_text(alias, field="skill.alias")
                    aliases.append(
                        CurrentTaxonomyAlias(
                            taxonomy="skill",
                            node_code=skill_code,
                            alias=alias_text,
                            normalized_alias=normalize_skill_lookup_key(alias_text),
                        )
                    )
    snapshot = CurrentTaxonomySnapshot(
        taxonomy="skill",
        nodes=tuple(nodes),
        aliases=tuple(aliases),
    )
    return _validated_snapshot(snapshot)


def _validated_snapshot(snapshot: CurrentTaxonomySnapshot) -> CurrentTaxonomySnapshot:
    by_code: dict[str, CurrentTaxonomyNode] = {}
    for node in snapshot.nodes:
        if node.code in by_code:
            raise ValueError(f"Duplicate current taxonomy code {node.code!r}")
        if node.parent_code is not None and node.parent_code not in by_code:
            raise ValueError(
                f"Current taxonomy parent {node.parent_code!r} must precede {node.code!r}"
            )
        by_code[node.code] = node
    if any(alias.node_code not in by_code for alias in snapshot.aliases):
        raise ValueError("Current taxonomy alias points to an unknown node")
    return snapshot
