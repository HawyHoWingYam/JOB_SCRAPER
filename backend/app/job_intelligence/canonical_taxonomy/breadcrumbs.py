from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.canonical_job_taxonomy import (
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
)


def canonical_breadcrumb(
    db: Session,
    subcategory_id: UUID,
    *,
    taxonomy_revision_id: UUID,
) -> dict[str, dict[str, str]]:
    subcategory, category, domain = (
        db.query(
            CanonicalJobSubcategory,
            CanonicalJobCategory,
            CanonicalJobDomain,
        )
        .join(
            CanonicalJobCategory,
            CanonicalJobCategory.id == CanonicalJobSubcategory.category_id,
        )
        .join(
            CanonicalJobDomain,
            CanonicalJobDomain.id == CanonicalJobCategory.domain_id,
        )
        .filter(
            CanonicalJobSubcategory.id == subcategory_id,
            CanonicalJobSubcategory.revision_id == taxonomy_revision_id,
        )
        .one()
    )
    return {
        "domain": {
            "id": str(domain.id),
            "code": domain.code,
            "label": domain.label,
        },
        "category": {
            "id": str(category.id),
            "code": category.code,
            "label": category.label,
        },
        "subcategory": {
            "id": str(subcategory.id),
            "code": subcategory.code,
            "label": subcategory.label,
        },
    }
