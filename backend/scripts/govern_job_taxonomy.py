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


def _current_job_taxonomy_path(
    normalizer: JobCategoryNormalizer,
    subcategory_id,
) -> tuple[str, str, str] | None:
    if subcategory_id is None:
        return None
    hierarchy = normalizer.get_category_hierarchy(subcategory_id)
    if not hierarchy:
        return None
    domain = hierarchy.get("domain")
    category = hierarchy.get("category")
    subcategory = hierarchy.get("subcategory")
    if not (domain and category and subcategory):
        return None
    return (domain, category, subcategory)


def _governed_job_paths() -> set[tuple[str, str, str]]:
    registry = get_job_taxonomy_registry()
    paths: set[tuple[str, str, str]] = set()
    for domain in registry.taxonomy.get("domains", []):
        domain_name = domain.get("name")
        if not domain_name:
            continue
        for category in domain.get("categories", []):
            category_name = category.get("name")
            if not category_name:
                continue
            for subcategory_name in category.get("subcategories", []):
                if not subcategory_name:
                    continue
                paths.add((domain_name, category_name, subcategory_name))
    return paths


def _off_taxonomy_jobs(db: Session, normalizer: JobCategoryNormalizer):
    governed_paths = _governed_job_paths()
    known_ids = _known_source_classification_ids()
    if not known_ids:
        return []

    jobs = (
        db.query(Job)
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
            Job.source_classification_id.in_(known_ids),
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
        .all()
    )

    candidates = []
    for job in jobs:
        current_path = _current_job_taxonomy_path(normalizer, job.subcategory_id)
        if current_path is None:
            continue
        if current_path not in governed_paths:
            candidates.append(job)
    return candidates


def _base_default_jobs(db: Session, normalizer: JobCategoryNormalizer):
    registry = get_job_taxonomy_registry()
    known_ids = _known_source_classification_ids()
    if not known_ids:
        return []

    jobs = (
        db.query(Job)
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
            Job.source_classification_id.in_(known_ids),
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
        .all()
    )

    candidates = []
    for job in jobs:
        current_path = _current_job_taxonomy_path(normalizer, job.subcategory_id)
        if current_path is None:
            continue
        try:
            base_default_path = registry.get_base_default_path(str(job.source_classification_id))
        except ValueError:
            continue
        if current_path == base_default_path:
            candidates.append(job)
    return candidates


def _generic_leaf_jobs(db: Session, normalizer: JobCategoryNormalizer):
    known_ids = _known_source_classification_ids()
    if not known_ids:
        return []

    jobs = (
        db.query(Job)
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
            Job.source_classification_id.in_(known_ids),
        )
        .order_by(Job.created_at.asc(), Job.id.asc())
        .all()
    )

    candidates = []
    for job in jobs:
        current_path = _current_job_taxonomy_path(normalizer, job.subcategory_id)
        if current_path is None:
            continue
        _, category_name, subcategory_name = current_path
        if category_name == "General" or subcategory_name == "General":
            candidates.append(job)
    return candidates


def _ict_title_heuristic_path(job: Job) -> tuple[str, str, str] | None:
    text = f"{job.title or ''} {job.description or ''}".lower()

    if any(token in text for token in ["ux designer", "ui designer", "product designer", "graphic designer", "design system", "interaction design"]):
        return (
            "Information & Communication Technology",
            "Product & Quality",
            "UI/UX Design",
        )

    if any(token in text for token in ["project manager", "project coordinator", "project officer", "project executive", "program manager", "programme manager", "digital transformation"]):
        return (
            "Information & Communication Technology",
            "Product & Quality",
            "Project Management",
        )

    if any(token in text for token in ["product manager", "product owner", "product specialist"]):
        return (
            "Information & Communication Technology",
            "Product & Quality",
            "Product Management",
        )

    if any(token in text for token in ["quality assurance", "qa ", "qa/", " qa", "tester", "testing"]):
        return (
            "Information & Communication Technology",
            "Product & Quality",
            "QA Testing",
        )

    if any(token in text for token in ["technical writer", "documentation", "content designer"]):
        return (
            "Information & Communication Technology",
            "Product & Quality",
            "Technical Documentation",
        )

    if any(token in text for token in ["application security", "devsecops"]):
        return (
            "Information & Communication Technology",
            "Cybersecurity",
            "Application Security",
        )

    if any(token in text for token in ["risk", "governance", "grc", "compliance", "audit"]):
        return (
            "Information & Communication Technology",
            "Cybersecurity",
            "Governance Risk & Compliance",
        )

    if any(token in text for token in ["security", "cyber", "soc", "threat", "vulnerability"]):
        return (
            "Information & Communication Technology",
            "Cybersecurity",
            "Security Operations",
        )

    if any(token in text for token in ["data engineer", "etl", "data warehouse", "warehouse"]):
        return (
            "Information & Communication Technology",
            "Data & Analytics",
            "Data Engineering",
        )

    if any(token in text for token in ["business analyst", "system analyst", "systems analyst", "data analyst", "analytics", "business intelligence", "bi analyst"]):
        return (
            "Information & Communication Technology",
            "Data & Analytics",
            "Data Analysis",
        )

    if any(token in text for token in ["solution architect", "technology architect", "data architect", "enterprise architect", "architect"]):
        return (
            "Information & Communication Technology",
            "Infrastructure & Support",
            "Solutions Architecture",
        )

    if any(token in text for token in ["consultant", "pre-sales", "presales", "solution consultant", "sales engineer", "business partner"]):
        return (
            "Information & Communication Technology",
            "Infrastructure & Support",
            "Solutions Consulting",
        )

    if any(token in text for token in ["it manager", "technology manager", "digital solutions manager", "innovation & solution manager", "head of artificial intelligence", "head of ai", "manager, it", "assistant manager, it"]):
        return (
            "Information & Communication Technology",
            "Infrastructure & Support",
            "Technology Management",
        )

    if any(token in text for token in ["help desk", "desktop support"]):
        return (
            "Information & Communication Technology",
            "Infrastructure & Support",
            "Help Desk Support",
        )

    if any(token in text for token in ["application support", "systems support"]):
        return (
            "Information & Communication Technology",
            "Infrastructure & Support",
            "Application Support",
        )

    if any(token in text for token in ["network", "telecom", "telecommunications"]):
        return (
            "Information & Communication Technology",
            "Infrastructure & Support",
            "Network Engineering",
        )

    if any(token in text for token in ["system administrator", "systems administrator", "infrastructure", "platform engineer", "windows server", "linux administrator"]):
        return (
            "Information & Communication Technology",
            "Infrastructure & Support",
            "Systems Administration",
        )

    return None


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
    try:
        updated = _backfill_unmapped_jobs_in_session(db)
        rebuild_job_taxonomy_metrics(db)

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    return updated


def _backfill_unmapped_jobs_in_session(db: Session) -> int:
    normalizer = JobCategoryNormalizer(db)
    jobs = _backfillable_jobs_query(db).all()
    updated = 0

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

    return updated


def refine_base_default_jobs(db: Session, *, execute: bool = False) -> int:
    try:
        updated = _refine_base_default_jobs_in_session(db)
        rebuild_job_taxonomy_metrics(db)

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    return updated


def _refine_base_default_jobs_in_session(db: Session) -> int:
    normalizer = JobCategoryNormalizer(db)
    jobs = _generic_leaf_jobs(db, normalizer)
    updated = 0

    for job in jobs:
        current_path = _current_job_taxonomy_path(normalizer, job.subcategory_id)
        resolved_subcategory_id = normalizer.resolve_taxonomy_decision(
            {},
            source_classification_id=str(job.source_classification_id),
            source_classification_name=job.source_classification_name,
            source_subclassification_name=job.source_subclassification_name,
            conservative_mode=settings.job_classification_conservative_mode,
            cross_domain_min_confidence=settings.job_classification_cross_domain_min_confidence,
        )
        if resolved_subcategory_id == job.subcategory_id and current_path is not None:
            heuristic_path = _ict_title_heuristic_path(job)
            if heuristic_path is not None:
                resolved_subcategory_id = normalizer._get_or_create_path(
                    heuristic_path[0],
                    heuristic_path[1],
                    heuristic_path[2],
                    allow_create=True,
                )
        if resolved_subcategory_id == job.subcategory_id:
            continue
        job.subcategory_id = resolved_subcategory_id
        updated += 1

    return updated


def reconcile_off_taxonomy_jobs(db: Session, *, execute: bool = False) -> int:
    try:
        updated = _reconcile_off_taxonomy_jobs_in_session(db)
        rebuild_job_taxonomy_metrics(db)

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    return updated


def _reconcile_off_taxonomy_jobs_in_session(db: Session) -> int:
    normalizer = JobCategoryNormalizer(db)
    jobs = _off_taxonomy_jobs(db, normalizer)
    updated = 0

    for job in jobs:
        current_subcategory_id = job.subcategory_id
        resolved_subcategory_id = normalizer.resolve_taxonomy_decision(
            {},
            source_classification_id=str(job.source_classification_id),
            source_classification_name=job.source_classification_name,
            source_subclassification_name=job.source_subclassification_name,
            conservative_mode=settings.job_classification_conservative_mode,
            cross_domain_min_confidence=settings.job_classification_cross_domain_min_confidence,
        )
        if resolved_subcategory_id == current_subcategory_id:
            heuristic_path = _ict_title_heuristic_path(job)
            if heuristic_path is not None:
                resolved_subcategory_id = normalizer._get_or_create_path(
                    heuristic_path[0],
                    heuristic_path[1],
                    heuristic_path[2],
                    allow_create=True,
                )
        if resolved_subcategory_id == current_subcategory_id:
            continue
        job.subcategory_id = resolved_subcategory_id
        updated += 1

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


def prune_unused_taxonomy_nodes(db: Session, *, execute: bool = False) -> dict[str, int]:
    try:
        result = _prune_unused_taxonomy_nodes_in_session(db)
        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    return result


def _prune_unused_taxonomy_nodes_in_session(db: Session) -> dict[str, int]:
    deleted = {
        "subcategories_deleted": 0,
        "categories_deleted": 0,
        "domains_deleted": 0,
    }

    unused_subcategories = (
        db.query(JobSubcategory)
        .filter(JobSubcategory.distinct_job_count == 0)
        .order_by(JobSubcategory.id.asc())
        .all()
    )
    for subcategory in unused_subcategories:
        db.delete(subcategory)
        deleted["subcategories_deleted"] += 1
    db.flush()

    empty_categories = (
        db.query(JobCategory)
        .outerjoin(JobSubcategory, JobSubcategory.category_id == JobCategory.id)
        .group_by(JobCategory.id)
        .having(func.count(JobSubcategory.id) == 0)
        .order_by(JobCategory.id.asc())
        .all()
    )
    for category in empty_categories:
        db.delete(category)
        deleted["categories_deleted"] += 1
    db.flush()

    empty_domains = (
        db.query(JobDomain)
        .outerjoin(JobCategory, JobCategory.domain_id == JobDomain.id)
        .group_by(JobDomain.id)
        .having(func.count(JobCategory.id) == 0)
        .order_by(JobDomain.id.asc())
        .all()
    )
    for domain in empty_domains:
        db.delete(domain)
        deleted["domains_deleted"] += 1
    db.flush()

    return deleted


def apply_job_taxonomy_governance(db: Session, *, execute: bool = False) -> dict[str, Any]:
    snapshot = audit_job_taxonomy(db)
    try:
        updated = _backfill_unmapped_jobs_in_session(db)
        refined = _refine_base_default_jobs_in_session(db)
        reconciled = _reconcile_off_taxonomy_jobs_in_session(db)
        rebuild_job_taxonomy_metrics(db)

        if execute:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise

    snapshot["jobs_backfilled"] = int(updated)
    snapshot["jobs_refined_from_default"] = int(refined)
    snapshot["jobs_reconciled_off_taxonomy"] = int(reconciled)
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

    prune_parser = subparsers.add_parser("prune", help="Delete unused taxonomy scaffold nodes")
    prune_mode = prune_parser.add_mutually_exclusive_group()
    prune_mode.add_argument("--execute", action="store_true", help="Persist unused-node pruning")
    prune_mode.add_argument("--dry-run", action="store_true", help="Simulate unused-node pruning")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        if args.command == "audit":
            report = audit_job_taxonomy(db)
        elif args.command == "apply":
            report = apply_job_taxonomy_governance(
                db,
                execute=bool(args.execute),
            )
        else:
            report = prune_unused_taxonomy_nodes(
                db,
                execute=bool(args.execute),
            )
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
