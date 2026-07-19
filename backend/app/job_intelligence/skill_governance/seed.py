from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from app.job_intelligence.foundation import SeedIssue, normalized_content_hash
from app.job_intelligence.skill_governance.normalization import (
    normalize_exact_skill_key,
    normalize_skill_lookup_key,
)


DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
SKILL_TAXONOMY_PATH = DATA_DIRECTORY / "skill_taxonomy.json"
SKILL_RULES_PATH = DATA_DIRECTORY / "skill_curation_rules.json"
SKILL_BACKFILL_PATH = DATA_DIRECTORY / "skill_backfill_curations.json"
_CODE = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Skill seed document must be an object: {path}")
    return payload


def load_skill_seed_bundle(
    *,
    taxonomy_path: str | Path | None = None,
    rules_path: str | Path | None = None,
    backfill_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the three committed Skill governance documents as one revision input."""

    return {
        "taxonomy": _load_json(
            Path(taxonomy_path) if taxonomy_path else SKILL_TAXONOMY_PATH
        ),
        "rules": _load_json(Path(rules_path) if rules_path else SKILL_RULES_PATH),
        "backfill": _load_json(
            Path(backfill_path) if backfill_path else SKILL_BACKFILL_PATH
        ),
    }


def skill_seed_content_hash(bundle: Mapping[str, Any]) -> str:
    return normalized_content_hash(
        {
            "taxonomy": bundle.get("taxonomy"),
            "rules": bundle.get("rules"),
            "backfill": bundle.get("backfill"),
        }
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _quoted_path(prefix: str, key: object) -> str:
    escaped = str(key).replace("\\", "\\\\").replace("'", "\\'")
    return f"{prefix}['{escaped}']"


def validate_taxonomy_structure(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    taxonomy = _mapping(document.get("taxonomy"))
    categories = _sequence(taxonomy.get("categories"))
    expected_counts = _mapping(taxonomy.get("expected_counts"))
    counts = {"categories": len(categories), "technologies": 0, "skills": 0}
    seen_codes: dict[str, dict[str, str]] = {
        "category": {},
        "technology": {},
        "skill": {},
    }

    for category_index, raw_category in enumerate(categories):
        category = _mapping(raw_category)
        category_path = f"$.taxonomy.categories[{category_index}]"
        category_code = str(category.get("code") or "").strip()
        category_name = str(category.get("name") or "").strip()
        yield from _validate_node(
            kind="category",
            code=category_code,
            name=category_name,
            order=category.get("order"),
            is_active=category.get("is_active"),
            retired_at=category.get("retired_at"),
            expected_order=category_index,
            path=category_path,
            seen_codes=seen_codes,
        )
        if normalize_skill_lookup_key(category_name) in {"other", "general"}:
            yield SeedIssue(
                json_path=f"{category_path}.name",
                code="skill_taxonomy_fallback_forbidden",
                message="Governed Skill taxonomy cannot contain Other or General categories",
                related_id=category_code or None,
            )
        technologies = _sequence(category.get("technologies"))
        counts["technologies"] += len(technologies)
        for technology_index, raw_technology in enumerate(technologies):
            technology = _mapping(raw_technology)
            technology_path = f"{category_path}.technologies[{technology_index}]"
            technology_code = str(technology.get("code") or "").strip()
            technology_name = str(technology.get("name") or "").strip()
            yield from _validate_node(
                kind="technology",
                code=technology_code,
                name=technology_name,
                order=technology.get("order"),
                is_active=technology.get("is_active"),
                retired_at=technology.get("retired_at"),
                expected_order=technology_index,
                path=technology_path,
                seen_codes=seen_codes,
            )
            if normalize_skill_lookup_key(technology_name) in {"other", "general"}:
                yield SeedIssue(
                    json_path=f"{technology_path}.name",
                    code="skill_taxonomy_fallback_forbidden",
                    message="Governed Skill taxonomy cannot contain Other or General technologies",
                    related_id=technology_code or None,
                )

            skills = _sequence(technology.get("skills"))
            counts["skills"] += len(skills)
            for skill_index, raw_skill in enumerate(skills):
                skill = _mapping(raw_skill)
                skill_path = f"{technology_path}.skills[{skill_index}]"
                yield from _validate_node(
                    kind="skill",
                    code=str(skill.get("code") or "").strip(),
                    name=str(skill.get("name") or "").strip(),
                    order=skill.get("order"),
                    is_active=skill.get("is_active"),
                    retired_at=skill.get("retired_at"),
                    expected_order=skill_index,
                    path=skill_path,
                    seen_codes=seen_codes,
                )

    for count_name, actual in counts.items():
        expected = expected_counts.get(count_name)
        if not isinstance(expected, int) or expected != actual:
            yield SeedIssue(
                json_path=f"$.taxonomy.expected_counts.{count_name}",
                code="skill_taxonomy_count_mismatch",
                message=f"Expected {expected!r} {count_name}, materialized {actual}",
                related_id=count_name,
            )


def validate_bundle_identity(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    taxonomy = _mapping(document.get("taxonomy"))
    release_key = str(taxonomy.get("release_key") or "").strip()
    if taxonomy.get("schema_version") != 1:
        yield SeedIssue(
            json_path="$.taxonomy.schema_version",
            code="skill_seed_schema_invalid",
            message="Skill taxonomy schema_version must be 1",
        )
    if not release_key:
        yield SeedIssue(
            json_path="$.taxonomy.release_key",
            code="skill_seed_release_missing",
            message="Skill taxonomy release_key is required",
        )
    for document_name in ("rules", "backfill"):
        child = _mapping(document.get(document_name))
        if child.get("schema_version") != 1:
            yield SeedIssue(
                json_path=f"$.{document_name}.schema_version",
                code="skill_seed_schema_invalid",
                message=f"Skill {document_name} schema_version must be 1",
            )
        pinned_release = str(child.get("taxonomy_release_key") or "").strip()
        if pinned_release != release_key:
            yield SeedIssue(
                json_path=f"$.{document_name}.taxonomy_release_key",
                code="skill_seed_release_mismatch",
                message=f"Skill {document_name} must pin taxonomy release {release_key}",
                related_id=pinned_release or None,
            )


def _validate_node(
    *,
    kind: str,
    code: str,
    name: str,
    order: object,
    is_active: object,
    retired_at: object,
    expected_order: int,
    path: str,
    seen_codes: dict[str, dict[str, str]],
) -> Iterable[SeedIssue]:
    if not name:
        yield SeedIssue(
            json_path=f"{path}.name",
            code="skill_taxonomy_name_missing",
            message=f"Skill {kind} name is required",
        )
    if not _CODE.fullmatch(code):
        yield SeedIssue(
            json_path=f"{path}.code",
            code="skill_taxonomy_code_invalid",
            message=f"Skill {kind} code must be an explicit stable lowercase code",
            related_id=code or None,
        )
    elif code in seen_codes[kind]:
        yield SeedIssue(
            json_path=f"{path}.code",
            code="skill_taxonomy_code_duplicate",
            message=f"Skill {kind} code is already used at {seen_codes[kind][code]}",
            related_id=code,
        )
    else:
        seen_codes[kind][code] = path
    if order != expected_order:
        yield SeedIssue(
            json_path=f"{path}.order",
            code="skill_taxonomy_order_invalid",
            message=f"Skill {kind} order must be the explicit zero-based source order",
            related_id=code or None,
        )
    retired_timestamp: datetime | None = None
    if retired_at is not None:
        try:
            retired_timestamp = datetime.fromisoformat(
                str(retired_at).replace("Z", "+00:00")
            )
        except ValueError:
            retired_timestamp = None
    if (
        not isinstance(is_active, bool)
        or (is_active and retired_at is not None)
        or (
            is_active is False
            and (retired_timestamp is None or retired_timestamp.tzinfo is None)
        )
    ):
        yield SeedIssue(
            json_path=f"{path}.is_active",
            code="skill_taxonomy_retirement_invalid",
            message=(
                f"Skill {kind} must be active without retired_at or retired with a "
                "timezone-aware retired_at"
            ),
            related_id=code or None,
        )


def _taxonomy_index(
    document: Mapping[str, Any],
) -> tuple[
    dict[str, tuple[str, str, str, str]],
    set[tuple[str, str, str]],
    list[tuple[str, str, str]],
]:
    taxonomy = _mapping(document.get("taxonomy"))
    by_name: dict[str, tuple[str, str, str, str]] = {}
    paths: set[tuple[str, str, str]] = set()
    names_and_aliases: list[tuple[str, str, str]] = []
    for category_index, raw_category in enumerate(
        _sequence(taxonomy.get("categories"))
    ):
        category = _mapping(raw_category)
        category_name = str(category.get("name") or "").strip()
        for technology_index, raw_technology in enumerate(
            _sequence(category.get("technologies"))
        ):
            technology = _mapping(raw_technology)
            technology_name = str(technology.get("name") or "").strip()
            for skill_index, raw_skill in enumerate(
                _sequence(technology.get("skills"))
            ):
                skill = _mapping(raw_skill)
                skill_name = str(skill.get("name") or "").strip()
                skill_code = str(skill.get("code") or "").strip()
                skill_path = (
                    f"$.taxonomy.categories[{category_index}]"
                    f".technologies[{technology_index}].skills[{skill_index}]"
                )
                by_name[skill_name] = (
                    category_name,
                    technology_name,
                    skill_code,
                    skill_path,
                )
                paths.add((category_name, technology_name, skill_name))
                names_and_aliases.append((skill_name, skill_code, f"{skill_path}.name"))
                for alias_index, alias in enumerate(_sequence(skill.get("aliases"))):
                    names_and_aliases.append(
                        (str(alias), skill_code, f"{skill_path}.aliases[{alias_index}]")
                    )
    return by_name, paths, names_and_aliases


def validate_aliases(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    by_name, _, names_and_aliases = _taxonomy_index(document)
    rules = _mapping(document.get("rules"))
    canonical_aliases = _mapping(rules.get("canonical_aliases"))
    resolved_aliases = list(names_and_aliases)

    for raw_alias, raw_target in canonical_aliases.items():
        alias = str(raw_alias)
        target = str(raw_target)
        target_node = by_name.get(target)
        alias_path = _quoted_path("$.rules.canonical_aliases", alias)
        if target_node is None:
            yield SeedIssue(
                json_path=alias_path,
                code="skill_alias_target_missing",
                message=f"Canonical alias target does not exist: {target}",
                related_id=target,
            )
            continue
        resolved_aliases.append((alias, target_node[2], alias_path))

    targets_by_key: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for alias, skill_code, path in resolved_aliases:
        key = normalize_exact_skill_key(alias)
        if not key:
            yield SeedIssue(
                json_path=path,
                code="skill_alias_key_invalid",
                message="Skill name or alias has an empty deterministic normalized key",
                related_id=skill_code or None,
            )
            continue
        targets_by_key[key][skill_code].append(path)

    for key, targets in targets_by_key.items():
        if len(targets) <= 1:
            continue
        paths = sorted(
            path for target_paths in targets.values() for path in target_paths
        )
        yield SeedIssue(
            json_path=paths[-1],
            code="skill_alias_collision",
            message=f"Normalized alias {key!r} resolves to multiple governed Skills",
            related_id=key,
        )


def validate_rule_sets(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    rules = _mapping(document.get("rules"))
    sets: dict[str, dict[str, list[int]]] = {}
    for field in ("generic_terms", "review_only_terms", "suppressed_review_terms"):
        normalized: dict[str, list[int]] = defaultdict(list)
        for index, value in enumerate(_sequence(rules.get(field))):
            key = normalize_skill_lookup_key(value)
            if key:
                normalized[key].append(index)
            else:
                yield SeedIssue(
                    json_path=f"$.rules.{field}[{index}]",
                    code="skill_rule_key_invalid",
                    message="Skill curation rule has an empty deterministic normalized key",
                )
        sets[field] = normalized

    fields = tuple(sets)
    for index, left in enumerate(fields):
        for right in fields[index + 1 :]:
            for key in sorted(set(sets[left]) & set(sets[right])):
                right_index = sets[right][key][0]
                yield SeedIssue(
                    json_path=f"$.rules.{right}[{right_index}]",
                    code="skill_rule_overlap",
                    message=f"Normalized rule {key!r} appears in both {left} and {right}",
                    related_id=key,
                )


def validate_backfill(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    _, paths, _ = _taxonomy_index(document)
    backfill = _mapping(document.get("backfill"))
    entries = _mapping(backfill.get("entries"))
    seen_keys: dict[str, str] = {}
    for raw_key, raw_entry in entries.items():
        key = normalize_exact_skill_key(raw_key)
        entry_path = _quoted_path("$.backfill.entries", raw_key)
        if not key:
            yield SeedIssue(
                json_path=entry_path,
                code="skill_backfill_key_invalid",
                message="Backfill curation key must normalize deterministically",
            )
        elif key in seen_keys:
            yield SeedIssue(
                json_path=entry_path,
                code="skill_backfill_key_collision",
                message=f"Backfill key collides with {seen_keys[key]}",
                related_id=key,
            )
        else:
            seen_keys[key] = str(raw_key)

        entry = _mapping(raw_entry)
        action = str(entry.get("action") or "").strip()
        if action not in {"merge", "generic", "review"}:
            yield SeedIssue(
                json_path=f"{entry_path}.action",
                code="skill_backfill_action_invalid",
                message=f"Unsupported Skill backfill action: {action!r}",
                related_id=key or None,
            )
            continue
        if action == "merge":
            target = _mapping(entry.get("target"))
            target_path = (
                str(target.get("category") or ""),
                str(target.get("technology") or ""),
                str(target.get("skill") or ""),
            )
            if target_path not in paths:
                yield SeedIssue(
                    json_path=f"{entry_path}.target",
                    code="skill_backfill_target_missing",
                    message="Backfill merge target is not an exact governed Skill path",
                    related_id=" / ".join(target_path),
                )


SKILL_SEED_RULES = (
    validate_bundle_identity,
    validate_taxonomy_structure,
    validate_aliases,
    validate_rule_sets,
    validate_backfill,
)
