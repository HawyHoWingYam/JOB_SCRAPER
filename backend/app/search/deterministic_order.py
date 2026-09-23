from __future__ import annotations

from sqlalchemy import case, func

from app.models.job import Job


def apply_deterministic_lexical_order(query, *, prefix_job_ids=()):
    """One total lexical order shared by pages, previews, and CSV exports."""
    ordered = query.order_by(None)
    prefix = list(prefix_job_ids)
    if prefix:
        positions = {job_id: position for position, job_id in enumerate(prefix)}
        ordered = ordered.order_by(
            case(positions, value=Job.id, else_=len(prefix)),
        )
    return ordered.order_by(
        func.coalesce(Job.posted_date, Job.created_at).desc(),
        Job.source_site.asc(),
        Job.source_job_id.asc(),
        Job.id.asc(),
    )


__all__ = ["apply_deterministic_lexical_order"]
