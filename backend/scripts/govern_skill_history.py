#!/usr/bin/env python3
"""Audit and clean historical polluted skills under Other / General."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.database import SessionLocal
from app.models import (
    Job,
    JobSkill,
    JobSkillMention,
    Skill,
    SkillCategory,
    SkillReviewCandidate,
    SkillTechnology,
)
from app.repositories.job_skill_mention_repository import JobSkillMentionRepository
from app.services.skill_normalizer import SkillNormalizer


def _data_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "app" / "data" / filename


def normalize_lookup_key(value: str) -> str:
    text_value = str(value or "").strip()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text_value = text_value.replace(dash, "-")
    text_value = re.sub(r"\s+", " ", text_value).lower().strip()
    text_value = re.sub(r"[^a-z0-9]+", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def _looks_phrase_like(value: str) -> bool:
    return len(normalize_lookup_key(value).split()) >= 4


def load_backfill_curations(path: str | Path | None = None) -> dict[str, Any]:
    curation_path = Path(path) if path is not None else _data_path("skill_backfill_curations.json")
    payload = json.loads(curation_path.read_text())
    entries = payload.get("entries") or {}
    normalized_entries: dict[str, dict[str, Any]] = {}

    for raw_key, config in entries.items():
        action = str((config or {}).get("action") or "").strip()
        if action not in {"merge", "generic", "review"}:
            raise ValueError(f"Unsupported curation action for '{raw_key}': {action}")
        normalized_entries[normalize_lookup_key(raw_key)] = dict(config)

    return {
        "path": str(curation_path),
        "minimum_distinct_jobs": int(payload.get("minimum_distinct_jobs") or 100),
        "entries": normalized_entries,
    }


def _resolved_threshold(curations: dict[str, Any], min_distinct_jobs: int | None) -> int:
    if min_distinct_jobs is not None:
        return int(min_distinct_jobs)
    return int(curations["minimum_distinct_jobs"])


def _polluted_skill_rows_query(*, min_distinct_jobs: int | None = None, exact_distinct_jobs: int | None = None) -> str:
    having_clauses = []
    if min_distinct_jobs is not None:
        having_clauses.append("COUNT(DISTINCT js.job_id) >= :min_distinct_jobs")
    if exact_distinct_jobs is not None:
        having_clauses.append("COUNT(DISTINCT js.job_id) = :exact_distinct_jobs")
    having_sql = ""
    if having_clauses:
        having_sql = "\n            HAVING " + " AND ".join(having_clauses)

    return f"""
            SELECT
                s.id AS skill_id,
                s.name AS skill_name,
                sc.name AS category_name,
                st.name AS technology_name,
                COUNT(js.job_id) AS job_links,
                COUNT(DISTINCT js.job_id) AS distinct_jobs
            FROM skills s
            JOIN skill_technologies st ON st.id = s.technology_id
            JOIN skill_categories sc ON sc.id = st.category_id
            LEFT JOIN job_skills js ON js.skill_id = s.id
            WHERE lower(sc.name) = 'other'
              AND lower(st.name) = 'general'
            GROUP BY s.id, s.name, sc.name, st.name{having_sql}
            ORDER BY COUNT(DISTINCT js.job_id) DESC, COUNT(js.job_id) DESC, s.name ASC
            """


def _query_polluted_skill_rows(
    db: Session,
    *,
    min_distinct_jobs: int | None = None,
    exact_distinct_jobs: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, int] = {}
    if min_distinct_jobs is not None:
        params["min_distinct_jobs"] = min_distinct_jobs
    if exact_distinct_jobs is not None:
        params["exact_distinct_jobs"] = exact_distinct_jobs

    result = db.execute(
        text(
            _polluted_skill_rows_query(
                min_distinct_jobs=min_distinct_jobs,
                exact_distinct_jobs=exact_distinct_jobs,
            )
        ),
        params,
    )
    return [dict(row) for row in result.mappings()]


def _raw_polluted_skill_rows(db: Session, *, min_distinct_jobs: int) -> list[dict[str, Any]]:
    rows = _query_polluted_skill_rows(db, min_distinct_jobs=min_distinct_jobs)

    if min_distinct_jobs > 1:
        seen_skill_ids = {str(row["skill_id"]) for row in rows}
        for row in _query_polluted_skill_rows(db, exact_distinct_jobs=1):
            if str(row["skill_id"]) in seen_skill_ids:
                continue
            if not _looks_phrase_like(str(row["skill_name"] or "")):
                continue
            rows.append(row)

    rows.sort(
        key=lambda row: (
            -int(row["distinct_jobs"] or 0),
            -int(row["job_links"] or 0),
            str(row["skill_name"] or ""),
        )
    )
    return rows


def _classify_skill_row(
    row: dict[str, Any],
    curations: dict[str, Any],
) -> dict[str, Any]:
    source_name = row["skill_name"]
    normalized_name = normalize_lookup_key(source_name)
    curation = dict(curations["entries"].get(normalized_name) or {})

    if not curation and int(row["distinct_jobs"] or 0) <= 1 and _looks_phrase_like(source_name):
        curation = {"action": "review", "note": "Phrase-like one-off skill mention"}

    action = str(curation.get("action") or "review").strip()

    entry: dict[str, Any] = {
        "action": action,
        "source_skill": {
            "id": str(row["skill_id"]),
            "name": source_name,
            "normalized_name": normalized_name,
            "category": row["category_name"],
            "technology": row["technology_name"],
            "job_links": int(row["job_links"] or 0),
            "distinct_jobs": int(row["distinct_jobs"] or 0),
        },
    }

    if action == "merge":
        entry["target"] = dict(curation.get("target") or {})
    elif action == "generic":
        entry["generic_tag"] = str(curation.get("generic_tag") or source_name).strip()
    elif action == "review" and curation.get("note"):
        entry["note"] = str(curation["note"])

    return entry


def audit_skill_history(
    db: Session,
    *,
    min_distinct_jobs: int | None = None,
    curation_path: str | Path | None = None,
) -> dict[str, Any]:
    curations = load_backfill_curations(curation_path)
    threshold = _resolved_threshold(curations, min_distinct_jobs)
    entries = [
        _classify_skill_row(row, curations)
        for row in _raw_polluted_skill_rows(db, min_distinct_jobs=threshold)
    ]

    summary = {
        "merge": {"skill_count": 0, "affected_distinct_jobs": 0, "affected_job_links": 0},
        "generic": {"skill_count": 0, "affected_distinct_jobs": 0, "affected_job_links": 0},
        "review": {"skill_count": 0, "affected_distinct_jobs": 0, "affected_job_links": 0},
    }

    for entry in entries:
        bucket = summary[entry["action"]]
        bucket["skill_count"] += 1
        bucket["affected_distinct_jobs"] += entry["source_skill"]["distinct_jobs"]
        bucket["affected_job_links"] += entry["source_skill"]["job_links"]

    return {
        "minimum_distinct_jobs": threshold,
        "curation_path": curations["path"],
        "entries": entries,
        "summary": summary,
    }


def _require_governance_schema(db: Session) -> None:
    inspector = inspect(db.bind)
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    missing = []

    if "ai_generic_tags" not in job_columns:
        missing.append("jobs.ai_generic_tags")
    if not inspector.has_table("skill_review_candidates"):
        missing.append("skill_review_candidates")
    if not inspector.has_table("job_skill_mentions"):
        missing.append("job_skill_mentions")

    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(
            "Historical governance apply requires Alembic revision 20260501_103000 "
            f"before execution. Missing: {missing_text}"
        )


def _find_polluted_skill(db: Session, skill_name: str) -> Skill:
    skill = (
        db.query(Skill)
        .join(SkillTechnology, Skill.technology_id == SkillTechnology.id)
        .join(SkillCategory, SkillTechnology.category_id == SkillCategory.id)
        .filter(
            Skill.name == skill_name,
            SkillCategory.name == "Other",
            SkillTechnology.name == "General",
        )
        .one()
    )
    return skill


def _ensure_skill_category(db: Session, name: str) -> SkillCategory:
    category = db.query(SkillCategory).filter_by(name=name).first()
    if category is None:
        category = SkillCategory(
            name=name,
            created_by="seed",
            is_auto_created=False,
            is_filter_visible=False,
            usage_count=0,
            distinct_job_count=0,
        )
        db.add(category)
        db.flush()
    return category


def _ensure_skill_technology(db: Session, *, category_name: str, technology_name: str) -> SkillTechnology:
    category = _ensure_skill_category(db, category_name)
    technology = (
        db.query(SkillTechnology)
        .filter_by(category_id=category.id, name=technology_name)
        .first()
    )
    if technology is None:
        technology = SkillTechnology(
            category_id=category.id,
            name=technology_name,
            created_by="seed",
            is_auto_created=False,
            is_filter_visible=False,
            usage_count=0,
            distinct_job_count=0,
        )
        db.add(technology)
        db.flush()
    return technology


def _merge_aliases(existing: list[str] | None, incoming: list[str] | None) -> list[str] | None:
    aliases = list(existing or [])
    for value in incoming or []:
        alias = str(value).strip()
        if alias and alias not in aliases:
            aliases.append(alias)
    return aliases or None


def _ensure_target_skill(db: Session, target: dict[str, Any]) -> Skill:
    technology = _ensure_skill_technology(
        db,
        category_name=str(target["category"]),
        technology_name=str(target["technology"]),
    )
    skill = db.query(Skill).filter_by(technology_id=technology.id, name=target["skill"]).first()
    if skill is None:
        skill = Skill(
            technology_id=technology.id,
            name=str(target["skill"]),
            aliases=_merge_aliases(None, target.get("aliases")),
            created_by="seed",
            is_auto_created=False,
            is_filter_visible=False,
            usage_count=0,
            distinct_job_count=0,
        )
        db.add(skill)
        db.flush()
        return skill

    aliases = _merge_aliases(skill.aliases, target.get("aliases"))
    if aliases != skill.aliases:
        skill.aliases = aliases
        db.flush()
    return skill


def _delete_skill_if_unlinked(db: Session, skill: Skill) -> None:
    remaining = db.query(JobSkill).filter(JobSkill.skill_id == skill.id).count()
    if remaining == 0:
        db.delete(skill)
        db.flush()


def _merge_job_skill_links(db: Session, *, source_skill: Skill, target_skill: Skill) -> None:
    links = (
        db.query(JobSkill)
        .filter(JobSkill.skill_id == source_skill.id)
        .order_by(JobSkill.created_at.asc(), JobSkill.job_id.asc())
        .all()
    )
    for link in links:
        existing_target = (
            db.query(JobSkill)
            .filter(
                JobSkill.job_id == link.job_id,
                JobSkill.skill_id == target_skill.id,
            )
            .first()
        )
        if existing_target is not None:
            db.delete(link)
            continue

        replacement = JobSkill(
            job_id=link.job_id,
            skill_id=target_skill.id,
            source=link.source,
            confidence=link.confidence,
            created_at=link.created_at,
        )
        db.add(replacement)
        db.flush()
        db.delete(link)

    db.flush()
    _delete_skill_if_unlinked(db, source_skill)


def _coerce_generic_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        if isinstance(parsed, str) and parsed.strip():
            return [parsed.strip()]
    return []


def _append_generic_tag(job: Job, generic_tag: str, *, normalizer: SkillNormalizer) -> None:
    merged: list[str] = []
    seen = set()

    for value in _coerce_generic_tags(job.ai_generic_tags) + [generic_tag]:
        raw_tag = str(value or "").strip()
        if not raw_tag:
            continue
        tag = normalizer.canonicalize_generic_tag(raw_tag) or raw_tag
        normalized_tag = normalizer.normalize_generic_tag_key(tag)
        if not normalized_tag or normalized_tag in seen:
            continue
        seen.add(normalized_tag)
        merged.append(tag)

    job.ai_generic_tags = merged or None


def _route_generic_links_to_job_tags(db: Session, *, source_skill: Skill, generic_tag: str) -> None:
    normalizer = SkillNormalizer(db)
    links = db.query(JobSkill).filter(JobSkill.skill_id == source_skill.id).all()
    for link in links:
        job = db.query(Job).filter(Job.id == link.job_id).one()
        _append_generic_tag(job, generic_tag, normalizer=normalizer)
        db.delete(link)

    db.flush()
    _delete_skill_if_unlinked(db, source_skill)


def _ensure_review_candidate_mention(
    db: Session,
    *,
    mention_repo: JobSkillMentionRepository,
    candidate: SkillReviewCandidate,
    source_skill: Skill,
    job_id: Any,
) -> None:
    mention = (
        db.query(JobSkillMention)
        .filter(
            JobSkillMention.job_id == job_id,
            JobSkillMention.review_candidate_id == candidate.id,
            JobSkillMention.resolution == "review_candidate",
        )
        .first()
    )
    if mention is None:
        mention_repo.create_mention(
            db,
            job_id=job_id,
            raw_name=source_skill.name,
            normalized_name=candidate.normalized_name,
            resolution="review_candidate",
            review_candidate_id=candidate.id,
        )
        return

    mention.raw_name = source_skill.name
    mention.normalized_name = candidate.normalized_name


def _register_review_candidate_links(db: Session, *, source_skill: Skill) -> None:
    normalizer = SkillNormalizer(db)
    mention_repo = JobSkillMentionRepository()
    affected_candidate_ids = set()
    links = (
        db.query(JobSkill)
        .filter(JobSkill.skill_id == source_skill.id)
        .order_by(JobSkill.created_at.asc(), JobSkill.job_id.asc())
        .all()
    )
    for link in links:
        candidate = normalizer.register_review_candidate(
            raw_name=source_skill.name,
            normalized_name=source_skill.name,
            job_id=link.job_id,
        )
        affected_candidate_ids.add(candidate.id)
        _ensure_review_candidate_mention(
            db,
            mention_repo=mention_repo,
            candidate=candidate,
            source_skill=source_skill,
            job_id=link.job_id,
        )
        db.delete(link)

    db.flush()
    for candidate_id in affected_candidate_ids:
        candidate = db.query(SkillReviewCandidate).filter_by(id=candidate_id).first()
        if candidate is None:
            continue
        candidate.occurrence_count = mention_repo.count_jobs_for_review_candidate(
            db, candidate_id
        )
    db.flush()
    _delete_skill_if_unlinked(db, source_skill)


def rebuild_skill_taxonomy_metrics(db: Session) -> None:
    db.query(Skill).update(
        {
            Skill.usage_count: 0,
            Skill.distinct_job_count: 0,
            Skill.is_filter_visible: False,
            Skill.last_used_at: None,
        },
        synchronize_session=False,
    )
    db.query(SkillTechnology).update(
        {
            SkillTechnology.usage_count: 0,
            SkillTechnology.distinct_job_count: 0,
            SkillTechnology.is_filter_visible: False,
            SkillTechnology.last_used_at: None,
        },
        synchronize_session=False,
    )
    db.query(SkillCategory).update(
        {
            SkillCategory.usage_count: 0,
            SkillCategory.distinct_job_count: 0,
            SkillCategory.is_filter_visible: False,
            SkillCategory.last_used_at: None,
        },
        synchronize_session=False,
    )
    db.flush()

    skill_counts = (
        db.query(
            JobSkill.skill_id.label("skill_id"),
            func.count().label("usage_count"),
            func.count(func.distinct(JobSkill.job_id)).label("distinct_job_count"),
            func.max(JobSkill.created_at).label("last_used_at"),
        )
        .group_by(JobSkill.skill_id)
        .all()
    )
    for row in skill_counts:
        skill = db.query(Skill).filter_by(id=row.skill_id).first()
        if skill is None:
            continue
        skill.usage_count = int(row.usage_count or 0)
        skill.distinct_job_count = int(row.distinct_job_count or 0)
        skill.last_used_at = row.last_used_at
        skill.is_filter_visible = skill.distinct_job_count >= settings.filter_skill_l3_min_jobs

    technology_counts = (
        db.query(
            SkillTechnology.id.label("technology_id"),
            func.count(JobSkill.job_id).label("usage_count"),
            func.count(func.distinct(JobSkill.job_id)).label("distinct_job_count"),
            func.max(JobSkill.created_at).label("last_used_at"),
        )
        .join(Skill, Skill.technology_id == SkillTechnology.id)
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .group_by(SkillTechnology.id)
        .all()
    )
    for row in technology_counts:
        technology = db.query(SkillTechnology).filter_by(id=row.technology_id).first()
        if technology is None:
            continue
        technology.usage_count = int(row.usage_count or 0)
        technology.distinct_job_count = int(row.distinct_job_count or 0)
        technology.last_used_at = row.last_used_at
        technology.is_filter_visible = (
            technology.distinct_job_count >= settings.filter_skill_l2_min_jobs
        )

    category_counts = (
        db.query(
            SkillCategory.id.label("category_id"),
            func.count(JobSkill.job_id).label("usage_count"),
            func.count(func.distinct(JobSkill.job_id)).label("distinct_job_count"),
            func.max(JobSkill.created_at).label("last_used_at"),
        )
        .join(SkillTechnology, SkillTechnology.category_id == SkillCategory.id)
        .join(Skill, Skill.technology_id == SkillTechnology.id)
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .group_by(SkillCategory.id)
        .all()
    )
    for row in category_counts:
        category = db.query(SkillCategory).filter_by(id=row.category_id).first()
        if category is None:
            continue
        category.usage_count = int(row.usage_count or 0)
        category.distinct_job_count = int(row.distinct_job_count or 0)
        category.last_used_at = row.last_used_at
        category.is_filter_visible = (
            category.distinct_job_count >= settings.filter_skill_l1_min_jobs
        )

    db.flush()


def apply_skill_history_governance(
    db: Session,
    *,
    min_distinct_jobs: int | None = None,
    curation_path: str | Path | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    _require_governance_schema(db)
    report = audit_skill_history(
        db,
        min_distinct_jobs=min_distinct_jobs,
        curation_path=curation_path,
    )

    processed = {"merge": 0, "generic": 0, "review": 0}

    try:
        for entry in report["entries"]:
            source_skill = _find_polluted_skill(db, entry["source_skill"]["name"])
            action = entry["action"]

            if action == "merge":
                target_skill = _ensure_target_skill(db, entry["target"])
                _merge_job_skill_links(db, source_skill=source_skill, target_skill=target_skill)
            elif action == "generic":
                _route_generic_links_to_job_tags(
                    db,
                    source_skill=source_skill,
                    generic_tag=str(entry["generic_tag"]),
                )
            else:
                _register_review_candidate_links(db, source_skill=source_skill)

            processed[action] += 1

        rebuild_skill_taxonomy_metrics(db)

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    report["dry_run"] = not execute
    report["processed"] = processed
    return report


def _write_report_if_requested(report: dict[str, Any], output_path: str | None) -> None:
    if not output_path:
        return
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Read-only polluted skill audit")
    audit_parser.add_argument("--min-distinct-jobs", type=int, default=None)
    audit_parser.add_argument("--curation-path", type=str, default=None)
    audit_parser.add_argument("--output", type=str, default=None)

    apply_parser = subparsers.add_parser("apply", help="Apply curated historical cleanup")
    apply_parser.add_argument("--min-distinct-jobs", type=int, default=None)
    apply_parser.add_argument("--curation-path", type=str, default=None)
    apply_parser.add_argument("--output", type=str, default=None)
    mode = apply_parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Persist historical cleanup")
    mode.add_argument("--dry-run", action="store_true", help="Simulate without committing")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "audit":
            report = audit_skill_history(
                db,
                min_distinct_jobs=args.min_distinct_jobs,
                curation_path=args.curation_path,
            )
        else:
            report = apply_skill_history_governance(
                db,
                min_distinct_jobs=args.min_distinct_jobs,
                curation_path=args.curation_path,
                execute=bool(args.execute),
            )
        _write_report_if_requested(report, getattr(args, "output", None))
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
