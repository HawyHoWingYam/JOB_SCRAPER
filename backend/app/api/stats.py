"""Statistics endpoints backed by ordinary current taxonomy assignments."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from sqlalchemy import and_, desc, func
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobTaxonomyAssignment,
    CurrentTaxonomyNodeRecord,
)
from app.models.job import Job
from app.schemas.stats import (
    DashboardCategoryItemSchema,
    DashboardCategoryStatsSchema,
    DashboardOtherSpecificCategoriesSchema,
)
from app.services.enrichment_run_service import EnrichmentRunService


router = APIRouter(prefix="/api/stats", tags=["stats"])


def get_skill_dashboard_bucket(skill_name: str, category_name: str) -> str | None:
    """Map current Skills into stable Dashboard presentation buckets."""
    category = str(category_name or "")
    name = str(skill_name or "").lower()
    if category == "Other":
        return None
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
            for token in ("firewall", "cybersecurity", "security", "identity")
        ):
            return "Security & Identity"
        return "Infrastructure"
    return category


def _english_label(node):
    return node.labels["en"].as_string()


def _current_job_category_rows(db: Session):
    subcategory = aliased(CurrentTaxonomyNodeRecord)
    category = aliased(CurrentTaxonomyNodeRecord)
    domain = aliased(CurrentTaxonomyNodeRecord)
    return (
        db.query(
            _english_label(domain).label("domain_label"),
            _english_label(category).label("category_label"),
            _english_label(subcategory).label("subcategory_label"),
            func.count(Job.id).label("count"),
        )
        .join(CurrentJobTaxonomyAssignment, CurrentJobTaxonomyAssignment.job_id == Job.id)
        .join(
            subcategory,
            and_(
                subcategory.taxonomy == "job",
                subcategory.code == CurrentJobTaxonomyAssignment.taxonomy_code,
                subcategory.is_active.is_(True),
                subcategory.is_assignable.is_(True),
            ),
        )
        .join(
            category,
            and_(
                category.taxonomy == "job",
                category.code == subcategory.parent_code,
                category.is_active.is_(True),
            ),
        )
        .join(
            domain,
            and_(
                domain.taxonomy == "job",
                domain.code == category.parent_code,
                domain.is_active.is_(True),
            ),
        )
        .filter(Job.is_deleted.is_(False))
        .group_by(
            _english_label(domain),
            _english_label(category),
            _english_label(subcategory),
        )
        .order_by(
            desc("count"),
            _english_label(domain).asc(),
            _english_label(category).asc(),
            _english_label(subcategory).asc(),
        )
        .all()
    )


@router.get("/overview")
async def get_overview(db: Session = Depends(get_db)) -> Dict[str, Any]:
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
    skill = aliased(CurrentTaxonomyNodeRecord)
    technology = aliased(CurrentTaxonomyNodeRecord)
    skill_category = aliased(CurrentTaxonomyNodeRecord)
    query = (
        db.query(
            _english_label(skill).label("name"),
            _english_label(skill_category).label("category"),
            func.count(func.distinct(CurrentJobSkillAssignment.job_id)).label("count"),
        )
        .select_from(skill)
        .join(
            CurrentJobSkillAssignment,
            CurrentJobSkillAssignment.skill_code == skill.code,
        )
        .join(
            technology,
            and_(
                technology.taxonomy == "skill",
                technology.code == skill.parent_code,
            ),
        )
        .join(
            skill_category,
            and_(
                skill_category.taxonomy == "skill",
                skill_category.code == technology.parent_code,
            ),
        )
        .filter(
            skill.taxonomy == "skill",
            skill.is_active.is_(True),
            skill.is_assignable.is_(True),
            technology.is_active.is_(True),
            skill_category.is_active.is_(True),
        )
        .group_by(_english_label(skill), _english_label(skill_category))
    )
    if category:
        query = query.filter(_english_label(skill_category) == category)
    results = query.order_by(desc("count")).limit(limit).all()
    return {
        "skills": [
            {
                "name": row.name,
                "category": row.category,
                "count": row.count,
                "dashboard_bucket": get_skill_dashboard_bucket(
                    row.name,
                    row.category,
                ),
            }
            for row in results
        ]
    }


@router.get("/categories")
async def get_category_stats(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    return [
        {
            "category": " / ".join(
                (row.domain_label, row.category_label, row.subcategory_label)
            ),
            "count": row.count,
        }
        for row in _current_job_category_rows(db)
    ]


@router.get("/categories/dashboard", response_model=DashboardCategoryStatsSchema)
async def get_dashboard_category_stats(db: Session = Depends(get_db)) -> Dict[str, Any]:
    results = _current_job_category_rows(db)
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
    visible_specific_items = specific_items[:6]
    other_specific_count = sum(item["count"] for item in specific_items[6:])
    other_specific_bucket_count = max(len(specific_items) - 6, 0)
    return {
        "categorized_total": specific_total,
        "specific_total": specific_total,
        "fallback_total": 0,
        "top_specific_categories": [
            DashboardCategoryItemSchema(
                path=item["path"],
                label=item["label"],
                count=item["count"],
                share_of_specific=round((item["count"] / specific_total) * 100)
                if specific_total
                else 0,
            ).model_dump(mode="json")
            for item in visible_specific_items
        ],
        "other_specific_categories": DashboardOtherSpecificCategoriesSchema(
            count=other_specific_count,
            bucket_count=other_specific_bucket_count,
            share_of_specific=round((other_specific_count / specific_total) * 100)
            if specific_total
            else 0,
        ).model_dump(mode="json"),
        "fallback_buckets": [],
    }
