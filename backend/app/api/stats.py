"""Statistics endpoints backed by ordinary current taxonomy assignments."""

from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, desc, func, select
from sqlalchemy.orm import Session, aliased

from app.database import get_db
from app.models.current_taxonomy import (
    CurrentJobSkillAssignment,
    CurrentJobSkillMention,
    CurrentJobTaxonomyAssignment,
    CurrentSkillCandidate,
    CurrentTaxonomyNodeRecord,
)
from app.models.job import Job
from app.schemas.stats import (
    DashboardCategoryItemSchema,
    DashboardCategoryStatsSchema,
    DashboardOtherCategoriesSchema,
    DashboardSkillStatsSchema,
)
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.services.enrichment_run_service import EnrichmentRunService
from app.services.job_taxonomy_classification_readiness import (
    job_taxonomy_classification_ready_jobs,
)


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


def _percentage(numerator: int, denominator: int) -> int:
    return round((numerator / denominator) * 100) if denominator else 0


def _dashboard_job_population_predicate():
    """Return the shared retained-corpus predicate for Dashboard Job metrics."""
    return Job.is_deleted.is_(False)


def _current_job_category_rows(db: Session):
    subcategory = aliased(CurrentTaxonomyNodeRecord)
    category = aliased(CurrentTaxonomyNodeRecord)
    domain = aliased(CurrentTaxonomyNodeRecord)
    return (
        db.query(
            subcategory.code.label("subcategory_code"),
            _english_label(domain).label("domain_label"),
            _english_label(category).label("category_label"),
            _english_label(subcategory).label("subcategory_label"),
            func.count(Job.id).label("count"),
        )
        .join(
            CurrentJobTaxonomyAssignment, CurrentJobTaxonomyAssignment.job_id == Job.id
        )
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
        .filter(_dashboard_job_population_predicate())
        .group_by(
            subcategory.code,
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


@router.get("/skills", response_model=DashboardSkillStatsSchema)
async def get_skill_stats(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    skill = aliased(CurrentTaxonomyNodeRecord)
    technology = aliased(CurrentTaxonomyNodeRecord)
    skill_category = aliased(CurrentTaxonomyNodeRecord)
    query = (
        db.query(
            skill.code.label("code"),
            _english_label(skill).label("name"),
            _english_label(skill_category).label("category"),
            func.count(func.distinct(Job.id)).label("count"),
        )
        .select_from(skill)
        .join(
            CurrentJobSkillAssignment,
            CurrentJobSkillAssignment.skill_code == skill.code,
        )
        .join(Job, Job.id == CurrentJobSkillAssignment.job_id)
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
            _dashboard_job_population_predicate(),
            Job.ai_enriched_at.isnot(None),
        )
        .group_by(
            skill.code,
            _english_label(skill),
            _english_label(skill_category),
        )
    )
    if category:
        query = query.filter(_english_label(skill_category) == category)
    results = query.order_by(desc("count"), skill.code.asc()).limit(limit).all()
    processed_total = int(
        db.query(func.count(Job.id))
        .filter(
            _dashboard_job_population_predicate(),
            Job.ai_enriched_at.isnot(None),
        )
        .scalar()
        or 0
    )
    matched_job_total = int(
        db.query(func.count(func.distinct(Job.id)))
        .select_from(skill)
        .join(
            CurrentJobSkillAssignment,
            CurrentJobSkillAssignment.skill_code == skill.code,
        )
        .join(Job, Job.id == CurrentJobSkillAssignment.job_id)
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
            _dashboard_job_population_predicate(),
            Job.ai_enriched_at.isnot(None),
        )
        .scalar()
        or 0
    )
    ready_threshold = AIRuntimeSettingsService(
        db
    ).get_skill_auto_create_distinct_job_threshold()
    unresolved_candidate_total, affected_job_total, ready_candidate_total = (
        db.query(
            func.count(func.distinct(CurrentJobSkillMention.candidate_id)),
            func.count(func.distinct(CurrentJobSkillMention.job_id)),
            func.count(
                func.distinct(
                    case(
                        (
                            CurrentSkillCandidate.distinct_job_count >= ready_threshold,
                            CurrentJobSkillMention.candidate_id,
                        ),
                        else_=None,
                    )
                )
            ),
        )
        .select_from(CurrentJobSkillMention)
        .join(Job, Job.id == CurrentJobSkillMention.job_id)
        .join(
            CurrentSkillCandidate,
            CurrentSkillCandidate.id == CurrentJobSkillMention.candidate_id,
        )
        .filter(
            CurrentJobSkillMention.status == "active",
            CurrentJobSkillMention.resolution == "candidate",
            _dashboard_job_population_predicate(),
        )
        .one()
    )
    return {
        "processed_total": processed_total,
        "matched_job_total": matched_job_total,
        "match_coverage": _percentage(matched_job_total, processed_total),
        "candidate_backlog": {
            "unresolved_candidate_total": int(unresolved_candidate_total or 0),
            "affected_job_total": int(affected_job_total or 0),
            "ready_candidate_total": int(ready_candidate_total or 0),
            "ready_threshold": ready_threshold,
        },
        "skills": [
            {
                "code": row.code,
                "name": row.name,
                "category": row.category,
                "count": int(row.count or 0),
                "prevalence": _percentage(int(row.count or 0), processed_total),
                "dashboard_bucket": get_skill_dashboard_bucket(
                    row.name,
                    row.category,
                ),
            }
            for row in results
        ],
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
            "code": row.subcategory_code,
            "path": " / ".join(
                (row.domain_label, row.category_label, row.subcategory_label)
            ),
            "label": row.subcategory_label,
            "count": int(row.count or 0),
        }
        for row in results
    ]
    assigned_total = sum(item["count"] for item in specific_items)
    population_total = int(
        db.query(func.count(Job.id))
        .filter(_dashboard_job_population_predicate())
        .scalar()
        or 0
    )
    unassigned_total = max(population_total - assigned_total, 0)
    classification_ready_unassigned_total = int(
        db.scalar(
            select(func.count()).select_from(
                job_taxonomy_classification_ready_jobs()
                .with_only_columns(Job.id)
                .subquery()
            )
        )
        or 0
    )

    def serialize_item(item: dict[str, Any]) -> dict[str, Any]:
        return DashboardCategoryItemSchema(
            **item,
            share_of_assigned=_percentage(item["count"], assigned_total),
        ).model_dump(mode="json")

    top_categories = specific_items[:6]
    other_items = specific_items[6:]
    other_count = sum(item["count"] for item in other_items)
    return {
        "population_total": population_total,
        "assigned_total": assigned_total,
        "unassigned_total": unassigned_total,
        "assignment_coverage": _percentage(assigned_total, population_total),
        "classification_ready_unassigned_total": (
            classification_ready_unassigned_total
        ),
        "top_categories": [serialize_item(item) for item in top_categories],
        "other_categories": DashboardOtherCategoriesSchema(
            count=other_count,
            bucket_count=len(other_items),
            share_of_assigned=_percentage(other_count, assigned_total),
            items=[serialize_item(item) for item in other_items],
        ).model_dump(mode="json"),
    }
