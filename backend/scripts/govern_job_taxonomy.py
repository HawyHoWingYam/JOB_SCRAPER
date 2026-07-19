#!/usr/bin/env python3
"""Inspect preserved legacy Job taxonomy links without changing them."""

from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import func
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal  # noqa: E402
from app.models import Job  # noqa: E402


def audit_job_taxonomy(db: Session) -> dict[str, int | str]:
    """Report legacy comparison evidence; this script is no longer a writer."""
    jobs_total = (
        db.query(func.count(Job.id)).filter(Job.is_deleted.is_(False)).scalar() or 0
    )
    legacy_assigned_jobs = (
        db.query(func.count(Job.id))
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
        )
        .scalar()
        or 0
    )
    legacy_unassigned_jobs = (
        db.query(func.count(Job.id))
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.is_(None),
        )
        .scalar()
        or 0
    )
    return {
        "authority": "legacy-comparison-evidence",
        "writer_status": "retired",
        "jobs_total": int(jobs_total),
        "legacy_assigned_jobs": int(legacy_assigned_jobs),
        "legacy_unassigned_jobs": int(legacy_unassigned_jobs),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "audit",
        help="Read-only audit of preserved legacy taxonomy comparison evidence",
    )
    return parser


def main() -> int:
    build_parser().parse_args()
    db = SessionLocal()
    try:
        report = audit_job_taxonomy(db)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
