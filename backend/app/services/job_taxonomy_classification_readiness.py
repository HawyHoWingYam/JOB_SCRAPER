"""Shared readiness population for automated Job Taxonomy classification."""

from sqlalchemy import and_, select
from sqlalchemy.orm import aliased

from app.models.current_taxonomy import (
    CurrentJobTaxonomyAssignment,
    CurrentTaxonomyNodeRecord,
)
from app.models.job import Job


def accepted_job_taxonomy_assignment_job_ids():
    """Select Jobs whose current assignment points to an accepted Job leaf."""
    subcategory = aliased(CurrentTaxonomyNodeRecord)
    category = aliased(CurrentTaxonomyNodeRecord)
    domain = aliased(CurrentTaxonomyNodeRecord)
    return (
        select(CurrentJobTaxonomyAssignment.job_id.label("job_id"))
        .select_from(CurrentJobTaxonomyAssignment)
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
    )


def job_taxonomy_classification_ready_jobs():
    """Select the complete population safe to preview for classification."""
    accepted_assignments = accepted_job_taxonomy_assignment_job_ids().subquery()
    return (
        select(Job)
        .outerjoin(
            accepted_assignments,
            accepted_assignments.c.job_id == Job.id,
        )
        .where(
            Job.is_deleted.is_(False),
            accepted_assignments.c.job_id.is_(None),
            Job.source_attribute_projection.has(),
        )
    )
