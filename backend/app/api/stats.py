"""
Statistics API Endpoints

Provides aggregated data for dashboard charts.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc, func, literal
from collections import defaultdict
from typing import Any, Dict, List

from app.database import get_db
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.skill_governance import (
    GovernedJobSkill,
    GovernedSkill,
    GovernedSkillCategory,
    GovernedSkillTechnology,
    SkillTaxonomyActiveRevision,
)
from app.services.enrichment_run_service import EnrichmentRunService
from app.schemas.stats import (
    DashboardCategoryStatsSchema,
    DashboardCategoryItemSchema,
    DashboardFallbackBucketSchema,
    DashboardOtherSpecificCategoriesSchema,
    DashboardCategorySourceBreakdownSchema,
)

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


def get_skill_dashboard_bucket(skill_name: str, category_name: str) -> str | None:
    """Map a skill + its category to a stable dashboard presentation bucket.

    Fully dynamic approach — only two hard rules:

    1. ``Other`` category (unclassified skills) → ``None`` (suppressed from dashboard).
    2. ``DevOps`` skills are sub-bucketed by keyword match to avoid lumping cloud
       infra, networking, and security into one chart.

    Every other category is returned verbatim, so taxonomy changes propagate
    to the dashboard automatically without any mapping table.
    """
    category = str(category_name or "")
    name = str(skill_name or "").lower()

    # Unclassified — never show on dashboard
    if category == "Other":
        return None

    # DevOps: sub-bucket by keyword match
    if category == "DevOps":
        if any(
            token in name
            for token in (
                "azure",
                "aws",
                "kubernetes",
                "docker",
                "ci/cd",
                "microsoft 365",
                "jenkins",
                "github actions",
            )
        ):
            return "Platform & Cloud"
        if any(
            token in name
            for token in (
                "linux",
                "windows server",
                "windows",
                "network",
                "vpn",
                "active directory",
                "unix",
                "vmware",
            )
        ):
            return "Systems & Network"
        if any(
            token in name
            for token in (
                "firewall",
                "cybersecurity",
                "security",
                "identity",
            )
        ):
            return "Security & Identity"
        return "Infrastructure"

    # Everything else: pass through dynamically
    return category


@router.get("/overview")
async def get_overview(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get dashboard overview statistics."""
    queue_counts = EnrichmentRunService(db).get_job_queue_counts()

    return {
        "total_jobs": queue_counts["total_jobs"],
        "enriched_jobs": queue_counts["enriched_jobs"],
        "eligible_enriched_jobs": queue_counts["eligible_enriched_jobs"],
        "ai_eligible_jobs": queue_counts["ai_eligible_jobs"],
        "ineligible_jobs": queue_counts["ineligible_jobs"],
        "pending_enrichment": queue_counts["pending_jobs"],
    }


@router.get("/skills")
async def get_skill_stats(
    limit: int = 20,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get top skills by frequency using governed canonical skill mentions."""
    query = (
        db.query(
            GovernedSkill.name,
            GovernedSkillCategory.name.label("category"),
            func.count(func.distinct(GovernedJobSkill.job_id)).label("count"),
        )
        .join(
            GovernedSkillTechnology,
            (GovernedSkill.technology_id == GovernedSkillTechnology.id)
            & (GovernedSkill.revision_id == GovernedSkillTechnology.revision_id),
        )
        .join(
            GovernedSkillCategory,
            (GovernedSkillTechnology.category_id == GovernedSkillCategory.id)
            & (
                GovernedSkillTechnology.revision_id == GovernedSkillCategory.revision_id
            ),
        )
        .join(
            GovernedJobSkill,
            (GovernedJobSkill.skill_id == GovernedSkill.id)
            & (GovernedJobSkill.taxonomy_revision_id == GovernedSkill.revision_id),
        )
        .join(
            SkillTaxonomyActiveRevision,
            (SkillTaxonomyActiveRevision.singleton_key == "skill-taxonomy")
            & (
                SkillTaxonomyActiveRevision.revision_id
                == GovernedJobSkill.taxonomy_revision_id
            ),
        )
        .filter(
            GovernedSkill.is_active.is_(True),
            GovernedSkillTechnology.is_active.is_(True),
            GovernedSkillCategory.is_active.is_(True),
        )
        .group_by(GovernedSkill.id, GovernedSkill.name, GovernedSkillCategory.name)
    )

    if category:
        query = query.filter(GovernedSkillCategory.name == category)

    results = query.order_by(desc("count")).limit(limit).all()

    return {
        "skills": [
            {
                "name": r.name,
                "category": r.category,
                "count": r.count,
                "dashboard_bucket": get_skill_dashboard_bucket(r.name, r.category),
            }
            for r in results
        ]
    }


@router.get("/categories")
async def get_category_stats(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Get job distribution by canonical job taxonomy path."""
    category_label = (
        JobDomain.name
        + literal(" / ")
        + JobCategory.name
        + literal(" / ")
        + JobSubcategory.name
    ).label("category")

    results = (
        db.query(category_label, func.count(Job.id).label("count"))
        .outerjoin(
            JobSubcategory,
            Job.subcategory_id == JobSubcategory.id,
        )
        .outerjoin(
            JobCategory,
            JobSubcategory.category_id == JobCategory.id,
        )
        .outerjoin(
            JobDomain,
            JobCategory.domain_id == JobDomain.id,
        )
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
            category_label.isnot(None),
            category_label != "",
        )
        .group_by(category_label)
        .order_by(desc("count"))
        .all()
    )

    return [{"category": cat, "count": count} for cat, count in results]


@router.get("/categories/dashboard", response_model=DashboardCategoryStatsSchema)
async def get_dashboard_category_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get dashboard-oriented category stats with explicit fallback diagnostics."""
    category_label = (
        JobDomain.name
        + literal(" / ")
        + JobCategory.name
        + literal(" / ")
        + JobSubcategory.name
    ).label("category")

    results = (
        db.query(
            category_label,
            JobDomain.name.label("domain_name"),
            JobCategory.name.label("category_name"),
            JobSubcategory.name.label("subcategory_name"),
            Job.source_site.label("source_site"),
            Job.source_subclassification_name.label("source_subclassification_name"),
            func.count(Job.id).label("count"),
        )
        .outerjoin(
            JobSubcategory,
            Job.subcategory_id == JobSubcategory.id,
        )
        .outerjoin(
            JobCategory,
            JobSubcategory.category_id == JobCategory.id,
        )
        .outerjoin(
            JobDomain,
            JobCategory.domain_id == JobDomain.id,
        )
        .filter(
            Job.is_deleted.is_(False),
            Job.subcategory_id.isnot(None),
            category_label.isnot(None),
            category_label != "",
        )
        .group_by(
            category_label,
            JobDomain.name,
            JobCategory.name,
            JobSubcategory.name,
            Job.source_site,
            Job.source_subclassification_name,
        )
        .all()
    )

    grouped_specific: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "path": "",
            "label": "",
        }
    )
    fallback_counts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "path": "",
            "label": "",
            "source_breakdown": defaultdict(int),
        }
    )

    for row in results:
        path = row.category or ""
        count = int(row.count or 0)
        category_name = row.category_name or ""
        subcategory_name = row.subcategory_name or ""
        is_fallback = category_name == "General" or subcategory_name == "General"

        if is_fallback:
            fallback_entry = fallback_counts[path]
            fallback_entry["count"] += count
            fallback_entry["path"] = path
            fallback_entry["label"] = f"{category_name} / {subcategory_name}"
            source_key = (row.source_site, row.source_subclassification_name)
            fallback_entry["source_breakdown"][source_key] += count
            continue

        specific_entry = grouped_specific[path]
        specific_entry["count"] += count
        specific_entry["path"] = path
        specific_entry["label"] = subcategory_name

    specific_items = sorted(
        grouped_specific.values(),
        key=lambda item: (-item["count"], item["label"], item["path"]),
    )
    fallback_items = sorted(
        fallback_counts.values(),
        key=lambda item: (-item["count"], item["label"], item["path"]),
    )

    specific_total = sum(item["count"] for item in specific_items)
    fallback_total = sum(item["count"] for item in fallback_items)
    categorized_total = specific_total + fallback_total
    visible_specific_items = specific_items[:6]
    other_specific_count = sum(item["count"] for item in specific_items[6:])
    other_specific_bucket_count = max(len(specific_items) - 6, 0)

    top_specific_categories = [
        DashboardCategoryItemSchema(
            path=item["path"],
            label=item["label"],
            count=item["count"],
            share_of_specific=round((item["count"] / specific_total) * 100)
            if specific_total
            else 0,
        ).model_dump(mode="json")
        for item in visible_specific_items
    ]

    fallback_buckets = [
        DashboardFallbackBucketSchema(
            path=item["path"],
            label=item["label"],
            count=item["count"],
            share_of_categorized=round((item["count"] / categorized_total) * 100)
            if categorized_total
            else 0,
            source_breakdown=[
                DashboardCategorySourceBreakdownSchema(
                    source_site=source_site,
                    source_subclassification_name=source_subclassification_name,
                    count=count,
                ).model_dump(mode="json")
                for (source_site, source_subclassification_name), count in sorted(
                    item["source_breakdown"].items(),
                    key=lambda entry: (
                        -entry[1],
                        str(entry[0][0] or ""),
                        entry[0][1] is None,
                        str(entry[0][1] or ""),
                    ),
                )
            ],
        ).model_dump(mode="json")
        for item in fallback_items
    ]

    return {
        "categorized_total": categorized_total,
        "specific_total": specific_total,
        "fallback_total": fallback_total,
        "top_specific_categories": top_specific_categories,
        "other_specific_categories": DashboardOtherSpecificCategoriesSchema(
            count=other_specific_count,
            bucket_count=other_specific_bucket_count,
            share_of_specific=round((other_specific_count / specific_total) * 100)
            if specific_total
            else 0,
        ).model_dump(mode="json"),
        "fallback_buckets": fallback_buckets,
    }
