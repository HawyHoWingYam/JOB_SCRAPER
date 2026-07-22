from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import json
import math
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, cast, exists, false, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.job_intelligence.foundation import normalized_content_hash
from app.models.canonical_job_taxonomy import (
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    CanonicalJobTaxonomyRelease,
    JobTaxonomyAssignment,
    JobTaxonomyReviewItem,
)
from app.models.governance import GovernanceRevision
from app.models.job import Job


_REVIEW_STATUSES = {
    "active",
    "assigned",
    "insufficient_evidence",
    "superseded",
}
_DEEP_LINK_PREFIX = "/api/v1/job-intelligence/governance/job-taxonomy/review-items"


class CanonicalReadError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})

    def to_detail(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            **({"context": self.context} if self.context else {}),
        }


@dataclass(frozen=True)
class CanonicalTaxonomyFilterQuery:
    domain_ids: tuple[UUID, ...] = ()
    domain_codes: tuple[str, ...] = ()
    category_ids: tuple[UUID, ...] = ()
    category_codes: tuple[str, ...] = ()
    subcategory_ids: tuple[UUID, ...] = ()
    subcategory_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CanonicalReviewQuery:
    statuses: tuple[str, ...] = ("active",)
    reason_codes: tuple[str, ...] = ()
    job_id: UUID | None = None
    job_ids: tuple[UUID, ...] = ()
    cursor: str | None = None
    page: int | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 200:
            raise CanonicalReadError(
                "CANONICAL_REVIEW_LIMIT_INVALID",
                "Canonical review page limit must be between 1 and 200",
            )
        if self.page is not None and self.page < 1:
            raise CanonicalReadError(
                "CANONICAL_REVIEW_PAGE_INVALID",
                "Canonical review page must be at least 1",
            )
        invalid_statuses = sorted(set(self.statuses) - _REVIEW_STATUSES)
        if invalid_statuses:
            raise CanonicalReadError(
                "CANONICAL_REVIEW_STATUS_INVALID",
                "Canonical review status filter is invalid",
                context={"statuses": invalid_statuses},
            )
        if any(not reason.strip() for reason in self.reason_codes):
            raise CanonicalReadError(
                "CANONICAL_REVIEW_REASON_INVALID",
                "Canonical review reason filters must be non-empty",
            )


@dataclass(frozen=True)
class CanonicalSubcategoryView:
    id: UUID
    code: str
    label: str
    order: int
    is_assignable: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "code": self.code,
            "label": self.label,
            "order": self.order,
            "is_assignable": self.is_assignable,
        }


@dataclass(frozen=True)
class CanonicalCategoryView:
    id: UUID
    code: str
    label: str
    order: int
    subcategories: tuple[CanonicalSubcategoryView, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "code": self.code,
            "label": self.label,
            "order": self.order,
            "subcategories": [item.to_payload() for item in self.subcategories],
        }


@dataclass(frozen=True)
class CanonicalDomainView:
    id: UUID
    code: str
    label: str
    order: int
    categories: tuple[CanonicalCategoryView, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "code": self.code,
            "label": self.label,
            "order": self.order,
            "categories": [item.to_payload() for item in self.categories],
        }


@dataclass(frozen=True)
class CanonicalRevisionView:
    id: UUID
    release_key: str
    content_hash: str
    lock_version: int
    activated_at: datetime
    counts: dict[str, int]
    active_mapping: dict[str, object] | None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "release_key": self.release_key,
            "content_hash": self.content_hash,
            "status": "active",
            "lock_version": self.lock_version,
            "activated_at": self.activated_at,
            "counts": dict(self.counts),
            "active_mapping": (
                dict(self.active_mapping) if self.active_mapping is not None else None
            ),
        }


@dataclass(frozen=True)
class CanonicalTreeView:
    revision: CanonicalRevisionView
    counts: dict[str, int]
    domains: tuple[CanonicalDomainView, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "revision": self.revision.to_payload(),
            "counts": dict(self.counts),
            "domains": [domain.to_payload() for domain in self.domains],
        }


@dataclass(frozen=True)
class CanonicalAssignmentView:
    id: UUID
    job_id: UUID
    taxonomy_revision_id: UUID
    subcategory_id: UUID
    method: str
    breadcrumb: dict[str, object]
    version: int
    provenance: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "job_id": str(self.job_id),
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "subcategory_id": str(self.subcategory_id),
            "method": self.method,
            "breadcrumb": dict(self.breadcrumb),
            "version": self.version,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class CanonicalReviewRefView:
    id: UUID
    status: str
    version: int
    decision_audit_id: UUID | None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "status": self.status,
            "version": self.version,
            "decision_audit_id": (
                str(self.decision_audit_id)
                if self.decision_audit_id is not None
                else None
            ),
            "deep_link": f"{_DEEP_LINK_PREFIX}/{self.id}",
        }


@dataclass(frozen=True)
class CanonicalJobStateView:
    job_id: UUID
    state: Literal["assigned", "unassigned"]
    assignment: CanonicalAssignmentView | None
    reasons: tuple[str, ...]
    review_item_refs: tuple[CanonicalReviewRefView, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "job_id": str(self.job_id),
            "state": self.state,
            "assignment": (
                self.assignment.to_payload() if self.assignment is not None else None
            ),
            "reasons": list(self.reasons),
            "review_item_refs": [item.to_payload() for item in self.review_item_refs],
        }


@dataclass(frozen=True)
class CanonicalReviewItemView:
    id: UUID
    job_id: UUID
    taxonomy_revision_id: UUID
    mapping_revision_id: UUID | None
    status: str
    reasons: tuple[str, ...]
    evidence_hash: str
    evidence_refs: tuple[dict[str, object], ...]
    recommendations: tuple[dict[str, object], ...]
    version: int
    decision_audit_id: UUID | None
    assignment_id: UUID | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "job_id": str(self.job_id),
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "mapping_revision_id": (
                str(self.mapping_revision_id)
                if self.mapping_revision_id is not None
                else None
            ),
            "status": self.status,
            "reasons": list(self.reasons),
            "evidence_hash": self.evidence_hash,
            "evidence_refs": [dict(item) for item in self.evidence_refs],
            "recommendations": [dict(item) for item in self.recommendations],
            "version": self.version,
            "decision_audit_id": (
                str(self.decision_audit_id)
                if self.decision_audit_id is not None
                else None
            ),
            "assignment_id": (
                str(self.assignment_id) if self.assignment_id is not None else None
            ),
            "deep_link": f"{_DEEP_LINK_PREFIX}/{self.id}",
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
        }


@dataclass(frozen=True)
class CanonicalReviewPage:
    items: tuple[CanonicalReviewItemView, ...]
    next_cursor: str | None
    total: int
    page: int | None = None
    limit: int | None = None
    offset: int | None = None
    page_count: int | None = None

    def to_payload(self) -> dict[str, object]:
        payload = {
            "items": [item.to_payload() for item in self.items],
            "next_cursor": self.next_cursor,
            "total": self.total,
        }
        if self.page is not None:
            payload.update(
                page=self.page,
                limit=self.limit,
                offset=self.offset,
                page_count=self.page_count,
            )
        return payload


@dataclass(frozen=True)
class CanonicalEmbeddingDocument:
    job_id: UUID
    assignment_id: UUID
    taxonomy_revision_id: UUID
    method: str
    breadcrumb: dict[str, object]
    document_text: str
    document_hash: str

    def to_payload(self) -> dict[str, object]:
        return {
            "job_id": str(self.job_id),
            "assignment_id": str(self.assignment_id),
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "method": self.method,
            "breadcrumb": dict(self.breadcrumb),
            "document_text": self.document_text,
            "document_hash": self.document_hash,
        }


class CanonicalTaxonomyReader:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_revision(self) -> CanonicalRevisionView:
        active = self.db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        if active is None:
            raise CanonicalReadError(
                "CANONICAL_TAXONOMY_NOT_ACTIVE",
                "Canonical Job Taxonomy has no active revision",
            )
        release = self.db.get(CanonicalJobTaxonomyRelease, active.revision_id)
        identity = self.db.get(GovernanceRevision, active.revision_id)
        if release is None or release.status != "ready" or identity is None:
            raise CanonicalReadError(
                "CANONICAL_TAXONOMY_ACTIVE_REVISION_INVALID",
                "Canonical Job Taxonomy active revision is not materialized",
            )
        mapping = self.db.get(
            CanonicalJobTaxonomyActiveMappingRevision,
            "canonical-job-taxonomy-mapping",
        )
        active_mapping = None
        if mapping is not None:
            if mapping.taxonomy_revision_id != active.revision_id:
                raise CanonicalReadError(
                    "CANONICAL_MAPPING_ACTIVE_REVISION_MISMATCH",
                    "Active Canonical mapping belongs to another taxonomy revision",
                )
            active_mapping = {
                "id": str(mapping.mapping_revision_id),
                "content_hash": mapping.content_hash,
                "lock_version": mapping.lock_version,
                "activated_at": mapping.activated_at,
            }
        return CanonicalRevisionView(
            id=active.revision_id,
            release_key=identity.release_key,
            content_hash=active.content_hash,
            lock_version=active.lock_version,
            activated_at=active.activated_at,
            counts={
                "domains": release.materialized_domain_count,
                "categories": release.materialized_category_count,
                "subcategories": release.materialized_subcategory_count,
            },
            active_mapping=active_mapping,
        )

    def get_tree(self) -> CanonicalTreeView:
        revision = self.get_active_revision()
        domains = (
            self.db.query(CanonicalJobDomain)
            .filter(CanonicalJobDomain.revision_id == revision.id)
            .order_by(CanonicalJobDomain.source_order)
            .all()
        )
        categories = (
            self.db.query(CanonicalJobCategory)
            .filter(CanonicalJobCategory.revision_id == revision.id)
            .order_by(
                CanonicalJobCategory.domain_id,
                CanonicalJobCategory.source_order,
            )
            .all()
        )
        subcategories = (
            self.db.query(CanonicalJobSubcategory)
            .filter(CanonicalJobSubcategory.revision_id == revision.id)
            .order_by(
                CanonicalJobSubcategory.category_id,
                CanonicalJobSubcategory.source_order,
            )
            .all()
        )
        categories_by_domain: dict[UUID, list[CanonicalJobCategory]] = {}
        for category in categories:
            categories_by_domain.setdefault(category.domain_id, []).append(category)
        subcategories_by_category: dict[UUID, list[CanonicalJobSubcategory]] = {}
        for subcategory in subcategories:
            subcategories_by_category.setdefault(
                subcategory.category_id,
                [],
            ).append(subcategory)

        domain_views = tuple(
            CanonicalDomainView(
                id=domain.id,
                code=domain.code,
                label=domain.label,
                order=domain.source_order,
                categories=tuple(
                    CanonicalCategoryView(
                        id=category.id,
                        code=category.code,
                        label=category.label,
                        order=category.source_order,
                        subcategories=tuple(
                            CanonicalSubcategoryView(
                                id=subcategory.id,
                                code=subcategory.code,
                                label=subcategory.label,
                                order=subcategory.source_order,
                                is_assignable=subcategory.is_assignable,
                            )
                            for subcategory in subcategories_by_category.get(
                                category.id,
                                [],
                            )
                        ),
                    )
                    for category in categories_by_domain.get(domain.id, [])
                ),
            )
            for domain in domains
        )
        actual_counts = {
            "domains": len(domain_views),
            "categories": len(categories),
            "subcategories": len(subcategories),
        }
        if actual_counts != revision.counts:
            raise CanonicalReadError(
                "CANONICAL_TAXONOMY_TREE_COUNT_MISMATCH",
                "Canonical Job Taxonomy tree does not match its release counts",
                context={"expected": revision.counts, "actual": actual_counts},
            )
        return CanonicalTreeView(
            revision=revision,
            counts=actual_counts,
            domains=domain_views,
        )

    def get_job_state(self, job_id: UUID) -> CanonicalJobStateView:
        if self.db.get(Job, job_id) is None:
            raise CanonicalReadError(
                "CANONICAL_JOB_NOT_FOUND",
                "Job was not found",
                context={"job_id": str(job_id)},
            )
        assignment = (
            self.db.query(JobTaxonomyAssignment)
            .filter(
                JobTaxonomyAssignment.job_id == job_id,
                JobTaxonomyAssignment.is_current.is_(True),
            )
            .one_or_none()
        )
        latest_review = (
            self.db.query(JobTaxonomyReviewItem)
            .filter(
                JobTaxonomyReviewItem.job_id == job_id,
                JobTaxonomyReviewItem.status != "superseded",
            )
            .order_by(
                JobTaxonomyReviewItem.created_at.desc(),
                JobTaxonomyReviewItem.id.desc(),
            )
            .first()
        )
        review_refs = (
            (self._review_ref(latest_review),) if latest_review is not None else ()
        )
        reasons: tuple[str, ...] = ()
        if latest_review is not None and latest_review.status == "active":
            reasons = tuple(latest_review.reasons)
        elif (
            latest_review is not None
            and latest_review.status == "insufficient_evidence"
        ):
            reasons = ("insufficient_evidence",)
        return CanonicalJobStateView(
            job_id=job_id,
            state="assigned" if assignment is not None else "unassigned",
            assignment=(
                self._assignment_view(assignment) if assignment is not None else None
            ),
            reasons=reasons if assignment is None else (),
            review_item_refs=review_refs,
        )

    def list_review_items(
        self,
        query: CanonicalReviewQuery,
    ) -> CanonicalReviewPage:
        statement = self.db.query(JobTaxonomyReviewItem)
        if query.statuses:
            statement = statement.filter(
                JobTaxonomyReviewItem.status.in_(query.statuses)
            )
        if query.reason_codes:
            statement = statement.filter(
                or_(
                    *(
                        cast(JobTaxonomyReviewItem.reasons, JSONB).contains([reason])
                        for reason in query.reason_codes
                    )
                )
            )
        if query.job_id is not None:
            statement = statement.filter(JobTaxonomyReviewItem.job_id == query.job_id)
        if query.job_ids:
            statement = statement.filter(JobTaxonomyReviewItem.job_id.in_(query.job_ids))
        total = statement.count()
        if query.page is not None:
            offset = (query.page - 1) * query.limit
            page_rows = (
                statement.order_by(
                    JobTaxonomyReviewItem.created_at.desc(),
                    JobTaxonomyReviewItem.id.desc(),
                )
                .offset(offset)
                .limit(query.limit)
                .all()
            )
            return CanonicalReviewPage(
                items=tuple(self._review_view(row) for row in page_rows),
                next_cursor=None,
                total=total,
                page=query.page,
                limit=query.limit,
                offset=offset,
                page_count=max(1, math.ceil(total / query.limit)),
            )
        if query.cursor is not None:
            created_at, review_id = _decode_review_cursor(query.cursor)
            statement = statement.filter(
                or_(
                    JobTaxonomyReviewItem.created_at < created_at,
                    and_(
                        JobTaxonomyReviewItem.created_at == created_at,
                        JobTaxonomyReviewItem.id < review_id,
                    ),
                )
            )
        rows = (
            statement.order_by(
                JobTaxonomyReviewItem.created_at.desc(),
                JobTaxonomyReviewItem.id.desc(),
            )
            .limit(query.limit + 1)
            .all()
        )
        page_rows = rows[: query.limit]
        return CanonicalReviewPage(
            items=tuple(self._review_view(row) for row in page_rows),
            next_cursor=(
                _encode_review_cursor(page_rows[-1])
                if len(rows) > query.limit and page_rows
                else None
            ),
            total=total,
        )

    def get_review_item(self, review_item_id: UUID) -> CanonicalReviewItemView:
        row = self.db.get(JobTaxonomyReviewItem, review_item_id)
        if row is None:
            raise CanonicalReadError(
                "CANONICAL_REVIEW_ITEM_NOT_FOUND",
                "Canonical Job Taxonomy Review Item was not found",
                context={"review_item_id": str(review_item_id)},
            )
        return self._review_view(row)

    def build_filters(
        self,
        query: CanonicalTaxonomyFilterQuery,
    ) -> tuple[object, ...]:
        revision = self.get_active_revision()
        predicates: list[object] = []
        if query.domain_ids or query.domain_codes:
            domain_ids = self._resolve_node_ids(
                CanonicalJobDomain,
                revision_id=revision.id,
                ids=query.domain_ids,
                codes=query.domain_codes,
            )
            subcategory_ids = tuple(
                row[0]
                for row in self.db.query(CanonicalJobSubcategory.id)
                .join(
                    CanonicalJobCategory,
                    CanonicalJobCategory.id == CanonicalJobSubcategory.category_id,
                )
                .filter(
                    CanonicalJobSubcategory.revision_id == revision.id,
                    CanonicalJobCategory.domain_id.in_(domain_ids),
                )
                .all()
            )
            predicates.append(
                self._assignment_predicate(
                    revision_id=revision.id,
                    subcategory_ids=subcategory_ids,
                )
            )
        if query.category_ids or query.category_codes:
            category_ids = self._resolve_node_ids(
                CanonicalJobCategory,
                revision_id=revision.id,
                ids=query.category_ids,
                codes=query.category_codes,
            )
            subcategory_ids = tuple(
                row[0]
                for row in self.db.query(CanonicalJobSubcategory.id)
                .filter(
                    CanonicalJobSubcategory.revision_id == revision.id,
                    CanonicalJobSubcategory.category_id.in_(category_ids),
                )
                .all()
            )
            predicates.append(
                self._assignment_predicate(
                    revision_id=revision.id,
                    subcategory_ids=subcategory_ids,
                )
            )
        if query.subcategory_ids or query.subcategory_codes:
            subcategory_ids = self._resolve_node_ids(
                CanonicalJobSubcategory,
                revision_id=revision.id,
                ids=query.subcategory_ids,
                codes=query.subcategory_codes,
            )
            predicates.append(
                self._assignment_predicate(
                    revision_id=revision.id,
                    subcategory_ids=subcategory_ids,
                )
            )
        return tuple(predicates)

    def build_embedding_document(
        self,
        job_id: UUID,
    ) -> CanonicalEmbeddingDocument | None:
        assignment = (
            self.db.query(JobTaxonomyAssignment)
            .filter(
                JobTaxonomyAssignment.job_id == job_id,
                JobTaxonomyAssignment.is_current.is_(True),
            )
            .one_or_none()
        )
        if assignment is None:
            return None
        breadcrumb = dict(assignment.breadcrumb)
        nodes = []
        for level in ("domain", "category", "subcategory"):
            node = breadcrumb.get(level)
            if not isinstance(node, dict):
                raise CanonicalReadError(
                    "CANONICAL_ASSIGNMENT_BREADCRUMB_INVALID",
                    "Accepted Canonical assignment has an invalid breadcrumb",
                )
            code = str(node.get("code") or "").strip()
            label = str(node.get("label") or "").strip()
            if not code or not label or label in {"General", "Unknown"}:
                raise CanonicalReadError(
                    "CANONICAL_ASSIGNMENT_BREADCRUMB_INVALID",
                    "Accepted Canonical assignment has an invalid breadcrumb",
                )
            nodes.append((code, label))
        labels = " / ".join(label for _code, label in nodes)
        codes = " / ".join(code for code, _label in nodes)
        document_text = "\n".join(
            (
                f"Canonical Job Taxonomy: {labels}",
                f"Canonical Job Taxonomy Codes: {codes}",
                f"Canonical Taxonomy Revision: {assignment.taxonomy_revision_id}",
                f"Canonical Assignment Method: {assignment.method}",
            )
        )
        document_hash = normalized_content_hash(
            {
                "assignment_id": str(assignment.id),
                "taxonomy_revision_id": str(assignment.taxonomy_revision_id),
                "method": assignment.method,
                "breadcrumb": breadcrumb,
                "document_text": document_text,
            }
        )
        return CanonicalEmbeddingDocument(
            job_id=job_id,
            assignment_id=assignment.id,
            taxonomy_revision_id=assignment.taxonomy_revision_id,
            method=assignment.method,
            breadcrumb=breadcrumb,
            document_text=document_text,
            document_hash=document_hash,
        )

    @staticmethod
    def _assignment_view(row: JobTaxonomyAssignment) -> CanonicalAssignmentView:
        model = None
        if row.model_provider or row.model_name or row.model_version:
            model = {
                "provider": row.model_provider,
                "name": row.model_name,
                "version": row.model_version,
            }
        return CanonicalAssignmentView(
            id=row.id,
            job_id=row.job_id,
            taxonomy_revision_id=row.taxonomy_revision_id,
            subcategory_id=row.subcategory_id,
            method=row.method,
            breadcrumb=dict(row.breadcrumb),
            version=row.lock_version,
            provenance={
                "evidence_hash": row.evidence_hash,
                "source_evidence_refs": [
                    dict(item) for item in row.source_evidence_refs
                ],
                "mapping_revision_id": (
                    str(row.mapping_revision_id)
                    if row.mapping_revision_id is not None
                    else None
                ),
                "mapping_ids": list(row.mapping_ids),
                "model": model,
                "captured_at": row.captured_at,
            },
        )

    @staticmethod
    def _review_ref(row: JobTaxonomyReviewItem) -> CanonicalReviewRefView:
        return CanonicalReviewRefView(
            id=row.id,
            status=row.status,
            version=row.lock_version,
            decision_audit_id=row.decision_audit_id,
        )

    @staticmethod
    def _review_view(row: JobTaxonomyReviewItem) -> CanonicalReviewItemView:
        return CanonicalReviewItemView(
            id=row.id,
            job_id=row.job_id,
            taxonomy_revision_id=row.taxonomy_revision_id,
            mapping_revision_id=row.mapping_revision_id,
            status=row.status,
            reasons=tuple(row.reasons),
            evidence_hash=row.evidence_hash,
            evidence_refs=tuple(dict(item) for item in row.evidence_refs),
            recommendations=tuple(dict(item) for item in row.recommendations),
            version=row.lock_version,
            decision_audit_id=row.decision_audit_id,
            assignment_id=row.assignment_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            resolved_at=row.resolved_at,
        )

    def _resolve_node_ids(
        self,
        model,
        *,
        revision_id: UUID,
        ids: tuple[UUID, ...],
        codes: tuple[str, ...],
    ) -> tuple[UUID, ...]:
        filters = []
        if ids:
            filters.append(model.id.in_(tuple(dict.fromkeys(ids))))
        normalized_codes = tuple(
            dict.fromkeys(code.strip() for code in codes if code.strip())
        )
        if normalized_codes:
            filters.append(model.code.in_(normalized_codes))
        if not filters:
            return ()
        return tuple(
            row[0]
            for row in self.db.query(model.id)
            .filter(
                model.revision_id == revision_id,
                or_(*filters),
            )
            .all()
        )

    @staticmethod
    def _assignment_predicate(
        *,
        revision_id: UUID,
        subcategory_ids: tuple[UUID, ...],
    ):
        if not subcategory_ids:
            return false()
        return exists().where(
            JobTaxonomyAssignment.job_id == Job.id,
            JobTaxonomyAssignment.is_current.is_(True),
            JobTaxonomyAssignment.taxonomy_revision_id == revision_id,
            JobTaxonomyAssignment.subcategory_id.in_(subcategory_ids),
        )


def _encode_review_cursor(row: JobTaxonomyReviewItem) -> str:
    raw = json.dumps(
        {"created_at": row.created_at.isoformat(), "id": str(row.id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_review_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise CanonicalReadError(
            "CANONICAL_REVIEW_CURSOR_INVALID",
            "Invalid Canonical Job Taxonomy Review cursor",
        ) from exc
