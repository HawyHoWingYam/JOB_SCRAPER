#!/usr/bin/env python3
"""Read-only audit of legacy Skill review candidates and recommendations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal  # noqa: E402
from app.models import SkillReviewCandidate  # noqa: E402
from app.services.skill_recommendation_service import (  # noqa: E402
    SkillRecommendationService,
)
from app.services.skill_normalizer import normalize_exact_skill_key  # noqa: E402
from scripts.govern_skill_history import load_backfill_curations  # noqa: E402


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
        key = normalize_exact_skill_key(candidate.normalized_name or candidate.raw_name)
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
            "cluster_id": cluster_ids.get(
                candidate.normalized_name,
                normalize_exact_skill_key(
                    candidate.normalized_name or candidate.raw_name
                ),
            ),
            "recommendations": recommendation_service.recommend_for_candidate(
                candidate
            ),
        }
        if action == "merge":
            entry["target"] = dict(curation.get("target") or {})
        elif action == "generic":
            entry["generic_tag"] = str(
                curation.get("generic_tag") or candidate.raw_name
            ).strip()
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


def _summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "minimum_occurrence_count": report.get("minimum_occurrence_count"),
        "curation_path": report.get("curation_path"),
        "summary": report.get("summary"),
        "entry_count": len(report.get("entries") or []),
    }
    return {key: value for key, value in summary.items() if value is not None}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser(
        "audit", help="Read-only review candidate audit"
    )
    audit_parser.add_argument("--min-occurrence-count", type=int, default=1)
    audit_parser.add_argument("--curation-path", type=str, default=None)
    audit_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary fields instead of the full entry list",
    )

    apply_parser = subparsers.add_parser(
        "apply",
        help="Retired mutation path; always fails closed",
    )
    apply_parser.add_argument("--min-occurrence-count", type=int, default=1)
    apply_parser.add_argument("--curation-path", type=str, default=None)
    apply_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary fields instead of the full entry list",
    )
    mode = apply_parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true", help="Persist review candidate governance"
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="Simulate without committing"
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "apply":
        parser.error(
            "legacy Skill Candidate mutation is retired; use the governed "
            "Skill Candidate decision API or the read-only audit command"
        )

    db = SessionLocal()
    try:
        report = audit_review_candidates(
            db,
            min_occurrence_count=args.min_occurrence_count,
            curation_path=args.curation_path,
        )
        payload = _summarize_report(report) if bool(args.summary_only) else report
        print(json.dumps(payload, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
