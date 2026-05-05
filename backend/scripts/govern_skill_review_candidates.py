#!/usr/bin/env python3
"""Promote curated skill review candidates into canonical skills or generic tags."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.models import Job, JobSkillMention, SkillReviewCandidate
from app.repositories.job_skill_repository import JobSkillRepository
from app.services.skill_recommendation_service import SkillRecommendationService
from app.services.skill_normalizer import SkillNormalizer
from scripts.govern_skill_history import (
    _ensure_target_skill,
    load_backfill_curations,
    normalize_lookup_key,
    rebuild_skill_taxonomy_metrics,
)


def audit_review_candidates(
    db: Session,
    *,
    min_occurrence_count: int | None = None,
    curation_path: str | Path | None = None,
) -> dict[str, Any]:
    curations = load_backfill_curations(curation_path)
    threshold = int(min_occurrence_count or 1)
    candidates = (
        db.query(SkillReviewCandidate)
        .filter(
            SkillReviewCandidate.status == "pending",
            SkillReviewCandidate.occurrence_count >= threshold,
        )
        .order_by(
            SkillReviewCandidate.occurrence_count.desc(),
            SkillReviewCandidate.normalized_name.asc(),
        )
        .all()
    )
    recommendation_service = SkillRecommendationService(db)
    cluster_ids = recommendation_service.cluster_candidates(candidates)

    entries = []
    summary = {"merge": 0, "generic": 0, "review": 0}
    for candidate in candidates:
        key = normalize_lookup_key(candidate.normalized_name or candidate.raw_name)
        curation = dict(curations["entries"].get(key) or {})
        action = str(curation.get("action") or "review").strip()
        entry = {
            "action": action,
            "review_candidate": {
                "id": str(candidate.id),
                "raw_name": candidate.raw_name,
                "normalized_name": candidate.normalized_name,
                "occurrence_count": int(candidate.occurrence_count or 0),
            },
            "cluster_id": cluster_ids.get(candidate.normalized_name, normalize_lookup_key(candidate.normalized_name or candidate.raw_name)),
            "recommendations": recommendation_service.recommend_for_candidate(candidate),
        }
        if action == "merge":
            entry["target"] = dict(curation.get("target") or {})
        elif action == "generic":
            entry["generic_tag"] = str(curation.get("generic_tag") or candidate.raw_name).strip()
        elif curation.get("note"):
            entry["note"] = str(curation["note"])

        entries.append(entry)
        summary[action] += 1

    return {
        "minimum_occurrence_count": threshold,
        "curation_path": curations["path"],
        "entries": entries,
        "summary": summary,
    }


def _apply_merge(db: Session, candidate: SkillReviewCandidate, target: dict[str, Any]) -> None:
    target_skill = _ensure_target_skill(db, target)
    repo = JobSkillRepository()
    mentions = (
        db.query(JobSkillMention)
        .filter(
            JobSkillMention.review_candidate_id == candidate.id,
            JobSkillMention.resolution == "review_candidate",
        )
        .all()
    )
    for mention in mentions:
        repo.create_job_skill(
            db,
            job_id=mention.job_id,
            skill_id=target_skill.id,
            source=mention.source or "ai",
            confidence=mention.confidence,
        )
        mention.resolution = "match_existing"
        mention.skill_id = target_skill.id
        mention.review_candidate_id = None
        mention.generic_tag = None
        mention.normalized_name = target_skill.name

    candidate.status = "resolved"
    candidate.occurrence_count = 0


def _apply_generic(db: Session, candidate: SkillReviewCandidate, generic_tag: str) -> None:
    mentions = (
        db.query(JobSkillMention)
        .filter(
            JobSkillMention.review_candidate_id == candidate.id,
            JobSkillMention.resolution == "review_candidate",
        )
        .all()
    )
    for mention in mentions:
        mention.resolution = "generic_tag"
        mention.skill_id = None
        mention.review_candidate_id = None
        mention.generic_tag = generic_tag
        mention.normalized_name = generic_tag

    candidate.status = "resolved"
    candidate.occurrence_count = 0


def _backfill_candidate_suggestions(
    candidate: SkillReviewCandidate,
    *,
    db: Session,
    normalizer: SkillNormalizer,
) -> None:
    if candidate.suggested_category and candidate.suggested_technology:
        return

    context_counts: Counter[tuple[str, str]] = Counter()
    job_ids = [
        job_id
        for (job_id,) in (
            db.query(JobSkillMention.job_id)
            .filter(
                JobSkillMention.review_candidate_id == candidate.id,
                JobSkillMention.resolution == "review_candidate",
            )
            .all()
        )
    ]
    if candidate.first_seen_job_id is not None:
        job_ids.append(candidate.first_seen_job_id)
    if candidate.last_seen_job_id is not None:
        job_ids.append(candidate.last_seen_job_id)

    unique_job_ids = list(dict.fromkeys(job_ids))
    if unique_job_ids:
        jobs = db.query(Job).filter(Job.id.in_(unique_job_ids)).all()
        for job in jobs:
            category_hint, technology_hint = normalizer.infer_taxonomy_hints(
                candidate.raw_name or candidate.normalized_name or "",
                description=job.description or "",
                source_subclassification_name=job.source_subclassification_name,
            )
            if category_hint and technology_hint:
                context_counts[(category_hint, technology_hint)] += 1

    if context_counts:
        category_hint, technology_hint = context_counts.most_common(1)[0][0]
    else:
        category_hint, technology_hint = normalizer.infer_taxonomy_hints(
            candidate.raw_name or candidate.normalized_name or ""
        )

    if category_hint and not candidate.suggested_category:
        candidate.suggested_category = category_hint
    if technology_hint and not candidate.suggested_technology:
        candidate.suggested_technology = technology_hint


def apply_review_candidate_governance(
    db: Session,
    *,
    min_occurrence_count: int | None = None,
    curation_path: str | Path | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    report = audit_review_candidates(
        db,
        min_occurrence_count=min_occurrence_count,
        curation_path=curation_path,
    )

    processed = {"merge": 0, "generic": 0, "review": 0}
    normalizer = SkillNormalizer(db)
    try:
        for entry in report["entries"]:
            action = entry["action"]
            candidate_id = uuid.UUID(entry["review_candidate"]["id"])
            candidate = db.query(SkillReviewCandidate).filter_by(
                id=candidate_id
            ).one()
            _backfill_candidate_suggestions(candidate, db=db, normalizer=normalizer)
            if action == "merge":
                _apply_merge(db, candidate, entry["target"])
            elif action == "generic":
                _apply_generic(db, candidate, str(entry["generic_tag"]))
            else:
                processed["review"] += 1
                continue
            processed[action] += 1

        rebuild_skill_taxonomy_metrics(db)

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    report["processed"] = processed
    report["dry_run"] = not execute
    return report


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "minimum_occurrence_count": report.get("minimum_occurrence_count"),
        "curation_path": report.get("curation_path"),
        "summary": report.get("summary"),
        "processed": report.get("processed"),
        "dry_run": report.get("dry_run"),
        "entry_count": len(report.get("entries") or []),
    }
    return {key: value for key, value in summary.items() if value is not None}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="Read-only review candidate audit")
    audit_parser.add_argument("--min-occurrence-count", type=int, default=1)
    audit_parser.add_argument("--curation-path", type=str, default=None)
    audit_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary fields instead of the full entry list",
    )

    apply_parser = subparsers.add_parser("apply", help="Apply review candidate governance")
    apply_parser.add_argument("--min-occurrence-count", type=int, default=1)
    apply_parser.add_argument("--curation-path", type=str, default=None)
    apply_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary fields instead of the full entry list",
    )
    mode = apply_parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Persist review candidate governance")
    mode.add_argument("--dry-run", action="store_true", help="Simulate without committing")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "audit":
            report = audit_review_candidates(
                db,
                min_occurrence_count=args.min_occurrence_count,
                curation_path=args.curation_path,
            )
        else:
            report = apply_review_candidate_governance(
                db,
                min_occurrence_count=args.min_occurrence_count,
                curation_path=args.curation_path,
                execute=bool(args.execute),
            )
        payload = _summarize_report(report) if bool(args.summary_only) else report
        print(json.dumps(payload, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
