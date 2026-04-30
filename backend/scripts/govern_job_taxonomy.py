#!/usr/bin/env python3
"""Audit and backfill governed job taxonomy assignments."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from sqlalchemy import false, func
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.database import SessionLocal
from app.models import Job, JobCategory, JobDomain, JobSubcategory
from app.services.job_category_normalizer import JobCategoryNormalizer
from app.services.job_taxonomy_registry import get_job_taxonomy_registry


def _unmapped_jobs_query(db: Session):
    return (
        db.query(Job)
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.is_(None),
            Job.source_classification_id.isnot(None),
            Job.source_classification_id != "",
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
    )


def _known_source_classification_ids() -> tuple[str, ...]:
    registry = get_job_taxonomy_registry()
    return tuple(sorted(registry.mapping.keys()))


def _backfillable_jobs_query(db: Session):
    known_ids = _known_source_classification_ids()
    if not known_ids:
        return _unmapped_jobs_query(db).filter(false())
    return _unmapped_jobs_query(db).filter(Job.source_classification_id.in_(known_ids))


def _usage_timestamp():
    return func.coalesce(Job.ai_enriched_at, Job.created_at)


def audit_job_taxonomy(db: Session) -> dict[str, int]:
    jobs_total = (
        db.query(func.count(Job.id))
        .filter(Job.is_deleted.is_(False))
        .scalar()
        or 0
    )
    jobs_with_subcategory = (
        db.query(func.count(Job.id))
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
        )
        .scalar()
        or 0
    )
    jobs_without_subcategory = (
        db.query(func.count(Job.id))
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.is_(None),
        )
        .scalar()
        or 0
    )
    eligible_backfill_jobs = _backfillable_jobs_query(db).count()

    return {
        "jobs_total": int(jobs_total),
        "jobs_with_subcategory": int(jobs_with_subcategory),
        "jobs_without_subcategory": int(jobs_without_subcategory),
        "eligible_backfill_jobs": int(eligible_backfill_jobs),
    }


def backfill_unmapped_jobs(db: Session, *, execute: bool = False) -> int:
    normalizer = JobCategoryNormalizer(db)
    jobs = _backfillable_jobs_query(db).all()
    updated = 0

    try:
        for job in jobs:
            job.subcategory_id = normalizer.resolve_taxonomy_decision(
                {},
                source_classification_id=str(job.source_classification_id),
                source_classification_name=job.source_classification_name,
                source_subclassification_name=job.source_subclassification_name,
                conservative_mode=settings.job_classification_conservative_mode,
                cross_domain_min_confidence=settings.job_classification_cross_domain_min_confidence,
            )
            updated += 1

        rebuild_job_taxonomy_metrics(db)

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    return updated


def rebuild_job_taxonomy_metrics(db: Session) -> None:
    db.query(JobSubcategory).update(
        {
            JobSubcategory.usage_count: 0,
            JobSubcategory.distinct_job_count: 0,
            JobSubcategory.is_filter_visible: False,
            JobSubcategory.last_used_at: None,
        },
        synchronize_session=False,
    )
    db.query(JobCategory).update(
        {
            JobCategory.usage_count: 0,
            JobCategory.distinct_job_count: 0,
            JobCategory.is_filter_visible: False,
            JobCategory.last_used_at: None,
        },
        synchronize_session=False,
    )
    db.query(JobDomain).update(
        {
            JobDomain.usage_count: 0,
            JobDomain.distinct_job_count: 0,
            JobDomain.is_filter_visible: False,
            JobDomain.last_used_at: None,
        },
        synchronize_session=False,
    )
    db.flush()

    subcategory_counts = (
        db.query(
            Job.subcategory_id.label("subcategory_id"),
            func.count(Job.id).label("usage_count"),
            func.count(func.distinct(Job.id)).label("distinct_job_count"),
            func.max(_usage_timestamp()).label("last_used_at"),
        )
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
        )
        .group_by(Job.subcategory_id)
        .all()
    )
    for row in subcategory_counts:
        subcategory = db.query(JobSubcategory).filter_by(id=row.subcategory_id).first()
        if subcategory is None:
            continue
        subcategory.usage_count = int(row.usage_count or 0)
        subcategory.distinct_job_count = int(row.distinct_job_count or 0)
        subcategory.last_used_at = row.last_used_at
        subcategory.is_filter_visible = (
            subcategory.distinct_job_count >= settings.filter_job_l3_min_jobs
        )

    category_counts = (
        db.query(
            JobCategory.id.label("category_id"),
            func.count(Job.id).label("usage_count"),
            func.count(func.distinct(Job.id)).label("distinct_job_count"),
            func.max(_usage_timestamp()).label("last_used_at"),
        )
        .join(JobSubcategory, JobSubcategory.category_id == JobCategory.id)
        .join(Job, Job.subcategory_id == JobSubcategory.id)
        .filter(Job.is_deleted.is_(False))
        .group_by(JobCategory.id)
        .all()
    )
    for row in category_counts:
        category = db.query(JobCategory).filter_by(id=row.category_id).first()
        if category is None:
            continue
        category.usage_count = int(row.usage_count or 0)
        category.distinct_job_count = int(row.distinct_job_count or 0)
        category.last_used_at = row.last_used_at
        category.is_filter_visible = (
            category.distinct_job_count >= settings.filter_job_l2_min_jobs
        )

    domain_counts = (
        db.query(
            JobDomain.id.label("domain_id"),
            func.count(Job.id).label("usage_count"),
            func.count(func.distinct(Job.id)).label("distinct_job_count"),
            func.max(_usage_timestamp()).label("last_used_at"),
        )
        .join(JobCategory, JobCategory.domain_id == JobDomain.id)
        .join(JobSubcategory, JobSubcategory.category_id == JobCategory.id)
        .join(Job, Job.subcategory_id == JobSubcategory.id)
        .filter(Job.is_deleted.is_(False))
        .group_by(JobDomain.id)
        .all()
    )
    for row in domain_counts:
        domain = db.query(JobDomain).filter_by(id=row.domain_id).first()
        if domain is None:
            continue
        domain.usage_count = int(row.usage_count or 0)
        domain.distinct_job_count = int(row.distinct_job_count or 0)
        domain.last_used_at = row.last_used_at
        domain.is_filter_visible = (
            domain.distinct_job_count >= settings.filter_job_l1_min_jobs
        )

    db.flush()


def apply_job_taxonomy_governance(db: Session, *, execute: bool = False) -> dict[str, Any]:
    snapshot = audit_job_taxonomy(db)
    updated = backfill_unmapped_jobs(db, execute=execute)
    snapshot["jobs_backfilled"] = int(updated)
    snapshot["dry_run"] = not execute
    return snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("audit", help="Read-only unmapped job taxonomy audit")

    apply_parser = subparsers.add_parser("apply", help="Backfill missing job taxonomy")
    mode = apply_parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Persist job taxonomy backfill")
    mode.add_argument("--dry-run", action="store_true", help="Simulate without committing")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "audit":
            report = audit_job_taxonomy(db)
        else:
            report = apply_job_taxonomy_governance(
                db,
                execute=bool(args.execute),
            )
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
