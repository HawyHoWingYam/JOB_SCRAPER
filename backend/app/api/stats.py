"""
Statistics API Endpoints

Provides aggregated data for dashboard charts.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc, func, literal
from typing import Any, Dict, List

from app.database import get_db
from app.models.job import Job
from app.models.job_category import JobCategory
from app.models.job_domain import JobDomain
from app.models.job_subcategory import JobSubcategory
from app.models.canonical_job_taxonomy import (
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveRevision,
    JobTaxonomyAssignment,
)
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
    DashboardOtherSpecificCategoriesSchema,
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
    """Return current accepted Canonical Job Taxonomy assignment counts."""
    active_revision_id = (
        db.query(CanonicalJobTaxonomyActiveRevision.revision_id)
        .filter(
            CanonicalJobTaxonomyActiveRevision.singleton_key
            == "canonical-job-taxonomy"
        )
        .scalar()
    )
    results = []
    if active_revision_id is not None:
        results = (
            db.query(
                CanonicalJobDomain.label.label("domain_label"),
                CanonicalJobCategory.label.label("category_label"),
                CanonicalJobSubcategory.label.label("subcategory_label"),
                func.count(Job.id).label("count"),
            )
            .join(JobTaxonomyAssignment, JobTaxonomyAssignment.job_id == Job.id)
            .join(
                CanonicalJobSubcategory,
                and_(
                    CanonicalJobSubcategory.id
                    == JobTaxonomyAssignment.subcategory_id,
                    CanonicalJobSubcategory.revision_id
                    == JobTaxonomyAssignment.taxonomy_revision_id,
                ),
            )
            .join(
                CanonicalJobCategory,
                and_(
                    CanonicalJobCategory.id == CanonicalJobSubcategory.category_id,
                    CanonicalJobCategory.revision_id
                    == CanonicalJobSubcategory.revision_id,
                ),
            )
            .join(
                CanonicalJobDomain,
                and_(
                    CanonicalJobDomain.id == CanonicalJobCategory.domain_id,
                    CanonicalJobDomain.revision_id
                    == CanonicalJobCategory.revision_id,
                ),
            )
            .filter(
                Job.is_deleted.is_(False),
                JobTaxonomyAssignment.is_current.is_(True),
                JobTaxonomyAssignment.taxonomy_revision_id == active_revision_id,
            )
            .group_by(
                CanonicalJobDomain.label,
                CanonicalJobCategory.label,
                CanonicalJobSubcategory.label,
            )
            .order_by(
                desc("count"),
                CanonicalJobDomain.label.asc(),
                CanonicalJobCategory.label.asc(),
                CanonicalJobSubcategory.label.asc(),
            )
            .all()
        )

    specific_items = [
        {
            "path": " / ".join(
                (row.domain_label, row.category_label, row.subcategory_label)
            ),
            "label": row.subcategory_label,
            "count": int(row.count or 0),
        }
        for row in results
    ]

    specific_total = sum(item["count"] for item in specific_items)
    fallback_total = 0
    categorized_total = specific_total
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
        # Compatibility fields remain additive and empty. Default/fallback evidence
        # belongs in Unassigned governance metrics, never accepted assignment charts.
        "fallback_buckets": [],
    }
