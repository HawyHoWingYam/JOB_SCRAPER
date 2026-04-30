"""Verify hierarchical taxonomy migration coverage."""

import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import engine


def _safe_scalar(connection, query: str, allow_missing: bool = False) -> int:
    """Execute a scalar query, optionally tolerating pre-convergence missing objects."""
    try:
        return connection.execute(text(query)).scalar() or 0
    except Exception:
        rollback = getattr(connection, "rollback", None)
        if callable(rollback):
            rollback()
        if allow_missing:
            return 0
        raise


def collect_verification_snapshot(connection) -> dict[str, int]:
    """Collect high-level migration coverage counts."""
    queries = {
        "jobs_enriched": {
            "query": "SELECT COUNT(*) FROM jobs WHERE ai_enriched_at IS NOT NULL",
            "allow_missing": False,
        },
        "jobs_total": {
            "query": "SELECT COUNT(*) FROM jobs WHERE is_deleted = false",
            "allow_missing": False,
        },
        "jobs_with_subcategory": {
            "query": """
                SELECT COUNT(*) FROM jobs
                WHERE subcategory_id IS NOT NULL AND is_deleted = false
            """,
            "allow_missing": True,
        },
        "jobs_without_subcategory": {
            "query": """
                SELECT COUNT(*) FROM jobs
                WHERE subcategory_id IS NULL AND is_deleted = false
            """,
            "allow_missing": True,
        },
        "jobs_unmapped_category": {
            "query": """
                SELECT COUNT(*) FROM jobs
                WHERE subcategory_id IS NULL AND ai_category IS NOT NULL AND is_deleted = false
            """,
            "allow_missing": True,
        },
        "skills_total": {
            "query": "SELECT COUNT(*) FROM skills",
            "allow_missing": False,
        },
        "skills_with_technology": {
            "query": "SELECT COUNT(*) FROM skills WHERE technology_id IS NOT NULL",
            "allow_missing": True,
        },
        "job_domains": {
            "query": "SELECT COUNT(*) FROM job_domains",
            "allow_missing": True,
        },
        "job_categories": {
            "query": "SELECT COUNT(*) FROM job_categories",
            "allow_missing": True,
        },
        "job_subcategories": {
            "query": "SELECT COUNT(*) FROM job_subcategories",
            "allow_missing": True,
        },
        "skill_categories": {
            "query": "SELECT COUNT(*) FROM skill_categories",
            "allow_missing": True,
        },
        "skill_technologies": {
            "query": "SELECT COUNT(*) FROM skill_technologies",
            "allow_missing": True,
        },
        "job_skills": {
            "query": "SELECT COUNT(*) FROM job_skills",
            "allow_missing": False,
        },
        "job_skills_with_skill_chain": {
            "query": """
                SELECT COUNT(*)
                FROM job_skills js
                JOIN skills s ON js.skill_id = s.id
                JOIN skill_technologies st ON s.technology_id = st.id
                JOIN skill_categories sc ON st.category_id = sc.id
            """,
            "allow_missing": True,
        },
        "visible_nodes_without_distinct_job_count": {
            "query": """
                SELECT COALESCE(SUM(node_count), 0)
                FROM (
                    SELECT COUNT(*) AS node_count
                    FROM skill_categories
                    WHERE is_filter_visible = true AND distinct_job_count = 0
                    UNION ALL
                    SELECT COUNT(*)
                    FROM skill_technologies
                    WHERE is_filter_visible = true AND distinct_job_count = 0
                    UNION ALL
                    SELECT COUNT(*)
                    FROM skills
                    WHERE is_filter_visible = true AND distinct_job_count = 0
                    UNION ALL
                    SELECT COUNT(*)
                    FROM job_domains
                    WHERE is_filter_visible = true AND distinct_job_count = 0
                    UNION ALL
                    SELECT COUNT(*)
                    FROM job_categories
                    WHERE is_filter_visible = true AND distinct_job_count = 0
                    UNION ALL
                    SELECT COUNT(*)
                    FROM job_subcategories
                    WHERE is_filter_visible = true AND distinct_job_count = 0
                ) visible_nodes
            """,
            "allow_missing": True,
        },
        "unenriched_jobs": {
            "query": """
                SELECT COUNT(*) FROM jobs
                WHERE ai_enriched_at IS NULL AND is_deleted = false
            """,
            "allow_missing": False,
        },
    }
    snapshot = {}

    for key, config in queries.items():
        snapshot[key] = _safe_scalar(
            connection,
            config["query"],
            allow_missing=config["allow_missing"],
        )

    return snapshot


def infer_checkpoint(snapshot: dict[str, int]) -> str:
    """Infer the current rollout checkpoint from coverage metrics."""
    jobs_enriched = snapshot.get("jobs_enriched", 0)
    jobs_with_subcategory = snapshot.get("jobs_with_subcategory", 0)
    job_skills = snapshot.get("job_skills", 0)
    taxonomy_nodes = sum(
        snapshot.get(key, 0)
        for key in (
            "job_domains",
            "job_categories",
            "job_subcategories",
            "skill_categories",
            "skill_technologies",
        )
    )
    hierarchy_linkage = (
        snapshot.get("jobs_with_subcategory", 0)
        + snapshot.get("skills_with_technology", 0)
    )

    if taxonomy_nodes == 0 and hierarchy_linkage == 0:
        return "pre-convergence / legacy-only"

    if jobs_enriched > 0 or jobs_with_subcategory > 0 or job_skills > 0:
        return "post-smoke"

    if taxonomy_nodes > 0:
        return "post-reset / pre-smoke"
    return "pre-convergence / legacy-only"


def render_report(snapshot: dict[str, int]) -> str:
    """Render a human-readable verification report."""
    jobs_enriched = snapshot.get("jobs_enriched", 0)
    jobs_total = snapshot.get("jobs_total", 0)
    jobs_with_subcategory = snapshot.get("jobs_with_subcategory", 0)
    skills_total = snapshot.get("skills_total", 0)
    skills_with_technology = snapshot.get("skills_with_technology", 0)
    job_skills = snapshot.get("job_skills", 0)
    job_skills_with_skill_chain = snapshot.get("job_skills_with_skill_chain", 0)

    lines = [
        "=" * 60,
        "Taxonomy Migration Verification",
        "=" * 60,
        "",
        f"Checkpoint: {infer_checkpoint(snapshot)}",
        f"Jobs enriched: {jobs_enriched}/{jobs_total}",
        f"Subcategory coverage: {jobs_with_subcategory}/{jobs_total}",
        f"Jobs without subcategory: {snapshot.get('jobs_without_subcategory', 0)}",
        f"Job domains: {snapshot.get('job_domains', 0)}",
        f"Job categories: {snapshot.get('job_categories', 0)}",
        f"Job subcategories: {snapshot.get('job_subcategories', 0)}",
        f"Skills total: {skills_total}",
        f"Skill hierarchy coverage: {skills_with_technology}/{skills_total}",
        f"Skill categories: {snapshot.get('skill_categories', 0)}",
        f"Skill technologies: {snapshot.get('skill_technologies', 0)}",
        f"Job-skill associations: {job_skills}",
        f"Skill chain integrity: {job_skills_with_skill_chain}/{job_skills}",
        (
            "Filter visibility / distinct_job_count mismatches: "
            f"{snapshot.get('visible_nodes_without_distinct_job_count', 0)}"
        ),
    ]

    jobs_unmapped_category = snapshot.get("jobs_unmapped_category")
    if jobs_unmapped_category is not None:
        lines.append(f"Jobs still relying on ai_category only: {jobs_unmapped_category}")

    unenriched_jobs = snapshot.get("unenriched_jobs")
    if unenriched_jobs is not None:
        lines.append(f"Unenriched jobs: {unenriched_jobs}")

    lines.extend(
        [
            "",
            "=" * 60,
            "Migration verification complete!",
            "=" * 60,
        ]
    )
    return "\n".join(lines)


def verify_migration() -> dict[str, int]:
    """Collect and print migration verification metrics."""
    with engine.connect() as connection:
        snapshot = collect_verification_snapshot(connection)

    print(render_report(snapshot))
    return snapshot


if __name__ == "__main__":
    verify_migration()
