#!/usr/bin/env python3
"""Synchronize taxonomy data files into the database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import (
    JobCategory,
    JobDomain,
    JobSubcategory,
    Skill,
    SkillCategory,
    SkillTechnology,
)


def data_path(filename: str) -> Path:
    """Resolve taxonomy data files relative to the backend app/data directory."""
    return Path(__file__).resolve().parents[1] / "app" / "data" / filename


def _load_taxonomy(filename: str) -> dict[str, Any]:
    with data_path(filename).open() as handle:
        return json.load(handle)


def _coerce_aliases(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(alias).strip() for alias in value if str(alias).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        if isinstance(parsed, list):
            return [str(alias).strip() for alias in parsed if str(alias).strip()]
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
    return []


def _serialize_aliases_for_db(db, aliases: list[str] | None):
    normalized = _coerce_aliases(aliases)
    if not normalized:
        return None
    dialect_name = getattr(getattr(db.bind, "dialect", None), "name", "")
    if dialect_name == "sqlite":
        return json.dumps(normalized)
    return normalized


def _merge_aliases(existing: Any, incoming: Any) -> list[str] | None:
    aliases = list(_coerce_aliases(existing))
    for value in _coerce_aliases(incoming):
        if value not in aliases:
            aliases.append(value)
    return aliases or None


def _promote_seed_fields(node) -> bool:
    changed = False
    if getattr(node, "created_by", None) != "seed":
        node.created_by = "seed"
        changed = True
    if getattr(node, "is_auto_created", None) is not False:
        node.is_auto_created = False
        changed = True
    return changed


def sync_skills(db, data: dict[str, Any], *, execute: bool = False) -> dict[str, int]:
    report = {
        "categories_created": 0,
        "categories_promoted": 0,
        "technologies_created": 0,
        "technologies_promoted": 0,
        "skills_created": 0,
        "skills_promoted": 0,
        "skill_aliases_updated": 0,
    }

    try:
        for cat_data in data.get("categories", []):
            category = db.query(SkillCategory).filter_by(name=cat_data["name"]).first()
            if category is None:
                category = SkillCategory(
                    name=cat_data["name"],
                    created_by="seed",
                    is_auto_created=False,
                )
                db.add(category)
                db.flush()
                report["categories_created"] += 1
            elif _promote_seed_fields(category):
                report["categories_promoted"] += 1

            for tech_data in cat_data.get("technologies", []):
                technology = (
                    db.query(SkillTechnology)
                    .filter_by(category_id=category.id, name=tech_data["name"])
                    .first()
                )
                if technology is None:
                    technology = SkillTechnology(
                        category_id=category.id,
                        name=tech_data["name"],
                        created_by="seed",
                        is_auto_created=False,
                    )
                    db.add(technology)
                    db.flush()
                    report["technologies_created"] += 1
                elif _promote_seed_fields(technology):
                    report["technologies_promoted"] += 1

                for skill_data in tech_data.get("skills", []):
                    skill = (
                        db.query(Skill)
                        .filter_by(technology_id=technology.id, name=skill_data["name"])
                        .first()
                    )
                    if skill is None:
                        skill = Skill(
                            technology_id=technology.id,
                            name=skill_data["name"],
                            aliases=_serialize_aliases_for_db(db, skill_data.get("aliases")),
                            created_by="seed",
                            is_auto_created=False,
                        )
                        db.add(skill)
                        db.flush()
                        report["skills_created"] += 1
                        continue

                    if _promote_seed_fields(skill):
                        report["skills_promoted"] += 1

                    merged_aliases = _merge_aliases(skill.aliases, skill_data.get("aliases"))
                    serialized_aliases = _serialize_aliases_for_db(db, merged_aliases)
                    if serialized_aliases != skill.aliases:
                        skill.aliases = serialized_aliases
                        report["skill_aliases_updated"] += 1

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    return report


def sync_job_categories(db, data: dict[str, Any], *, execute: bool = False) -> dict[str, int]:
    report = {
        "domains_created": 0,
        "domains_promoted": 0,
        "categories_created": 0,
        "categories_promoted": 0,
        "subcategories_created": 0,
        "subcategories_promoted": 0,
    }

    try:
        for domain_data in data.get("domains", []):
            domain = db.query(JobDomain).filter_by(name=domain_data["name"]).first()
            if domain is None:
                domain = JobDomain(
                    name=domain_data["name"],
                    created_by="seed",
                    is_auto_created=False,
                )
                db.add(domain)
                db.flush()
                report["domains_created"] += 1
            elif _promote_seed_fields(domain):
                report["domains_promoted"] += 1

            for cat_data in domain_data.get("categories", []):
                category = (
                    db.query(JobCategory)
                    .filter_by(domain_id=domain.id, name=cat_data["name"])
                    .first()
                )
                if category is None:
                    category = JobCategory(
                        domain_id=domain.id,
                        name=cat_data["name"],
                        created_by="seed",
                        is_auto_created=False,
                    )
                    db.add(category)
                    db.flush()
                    report["categories_created"] += 1
                elif _promote_seed_fields(category):
                    report["categories_promoted"] += 1

                for subcat_name in cat_data.get("subcategories", []):
                    subcategory = (
                        db.query(JobSubcategory)
                        .filter_by(category_id=category.id, name=subcat_name)
                        .first()
                    )
                    if subcategory is None:
                        subcategory = JobSubcategory(
                            category_id=category.id,
                            name=subcat_name,
                            created_by="seed",
                            is_auto_created=False,
                        )
                        db.add(subcategory)
                        db.flush()
                        report["subcategories_created"] += 1
                    elif _promote_seed_fields(subcategory):
                        report["subcategories_promoted"] += 1

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Persist taxonomy sync")
    mode.add_argument("--dry-run", action="store_true", help="Simulate without committing")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--skills-only", action="store_true", help="Sync only skill taxonomy")
    target.add_argument("--jobs-only", action="store_true", help="Sync only job taxonomy")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        reports: dict[str, dict[str, int]] = {}
        execute = bool(args.execute)

        if not args.jobs_only:
            reports["skills"] = sync_skills(
                db,
                _load_taxonomy("skill_taxonomy.json"),
                execute=execute,
            )

        if not args.skills_only:
            reports["jobs"] = sync_job_categories(
                db,
                _load_taxonomy("job_category_taxonomy.json"),
                execute=execute,
            )

        print(json.dumps(reports, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
