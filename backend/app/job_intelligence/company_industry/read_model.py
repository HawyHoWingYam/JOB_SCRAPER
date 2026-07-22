from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
import json
import math
from uuid import UUID

from sqlalchemy import and_, exists, or_
from sqlalchemy.orm import Session

from app.job_intelligence.company_industry.contracts import (
    CompanyIndustryEvidence,
    CompanyIndustryOutcome,
)
from app.job_intelligence.foundation import normalized_content_hash
from app.models.company import Company
from app.models.company_industry import (
    CompanyIndustryActiveRevision,
    CompanyIndustryAssignment,
    CompanyIndustryReviewItem,
    CompanyIndustryTaxonomyNode,
    CompanyIndustryTaxonomyRelease,
    SourceIndustryMapping,
)
from app.models.governance import GovernanceRevision
from app.repositories.event_outbox_repository import EventOutboxRepository
from app.utils.time import utc_now


class CompanyIndustryReadError(ValueError):
    """Stable domain error for versioned Company Industry read contracts."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CompanyIndustryRevisionView:
    id: UUID
    release_key: str
    content_hash: str
    lock_version: int
    activated_at: datetime
    counts: dict[str, int]

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "release_key": self.release_key,
            "content_hash": self.content_hash,
            "status": "active",
            "lock_version": self.lock_version,
            "activated_at": self.activated_at,
            "counts": dict(self.counts),
        }


@dataclass(frozen=True)
class CompanyIndustryNodeView:
    id: UUID
    code: str
    parent_id: UUID | None
    level: str
    labels: dict[str, str]
    order: int

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "code": self.code,
            "parent_id": str(self.parent_id) if self.parent_id is not None else None,
            "level": self.level,
            "labels": dict(self.labels),
            "order": self.order,
        }


@dataclass(frozen=True)
class CompanyIndustryTreeView:
    revision: CompanyIndustryRevisionView
    parent_id: UUID | None
    nodes: tuple[CompanyIndustryNodeView, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "revision": self.revision.to_payload(),
            "parent_id": str(self.parent_id) if self.parent_id is not None else None,
            "nodes": [node.to_payload() for node in self.nodes],
        }


@dataclass(frozen=True)
class CompanyIndustryAssignmentView:
    id: UUID
    taxonomy_revision_id: UUID
    node_id: UUID
    method: str
    breadcrumb: list[dict[str, object]]
    is_primary: bool
    primary_basis: str | None
    version: int
    provenance: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "node_id": str(self.node_id),
            "method": self.method,
            "breadcrumb": [dict(item) for item in self.breadcrumb],
            "is_primary": self.is_primary,
            "primary_basis": self.primary_basis,
            "version": self.version,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class CompanyIndustryReviewRefView:
    id: UUID
    status: str
    reason: str
    version: int
    decision_audit_id: UUID | None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "status": self.status,
            "reason": self.reason,
            "version": self.version,
            "decision_audit_id": (
                str(self.decision_audit_id)
                if self.decision_audit_id is not None
                else None
            ),
            "deep_link": (
                "/api/v1/job-intelligence/governance/company-industries/"
                f"review-items/{self.id}"
            ),
        }


@dataclass(frozen=True)
class CompanyIndustryCompanyStateView:
    company_id: UUID
    assignments: tuple[CompanyIndustryAssignmentView, ...]
    review_item_refs: tuple[CompanyIndustryReviewRefView, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "company_id": str(self.company_id),
            "assignments": [item.to_payload() for item in self.assignments],
            "review_item_refs": [item.to_payload() for item in self.review_item_refs],
        }


@dataclass(frozen=True)
class CompanyIndustryReviewItemView:
    id: UUID
    company_id: UUID
    taxonomy_revision_id: UUID | None
    source_site: str | None
    key_kind: str | None
    raw_value: str | None
    normalized_key: str | None
    reason: str
    status: str
    evidence_hash: str
    provenance: dict[str, object]
    recommendations: tuple[dict[str, object], ...]
    version: int
    decision_audit_id: UUID | None
    assignment_id: UUID | None
    mapping_id: UUID | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "company_id": str(self.company_id),
            "taxonomy_revision_id": (
                str(self.taxonomy_revision_id)
                if self.taxonomy_revision_id is not None
                else None
            ),
            "source_site": self.source_site,
            "key_kind": self.key_kind,
            "raw_value": self.raw_value,
            "normalized_key": self.normalized_key,
            "reason": self.reason,
            "status": self.status,
            "evidence_hash": self.evidence_hash,
            "provenance": dict(self.provenance),
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
            "mapping_id": str(self.mapping_id) if self.mapping_id is not None else None,
            "deep_link": (
                "/api/v1/job-intelligence/governance/company-industries/"
                f"review-items/{self.id}"
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
        }


@dataclass(frozen=True)
class CompanyIndustryReviewPage:
    items: tuple[CompanyIndustryReviewItemView, ...]
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
class CompanyIndustryReviewQuery:
    statuses: tuple[str, ...] = ("active",)
    source_sites: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    company_id: UUID | None = None
    raw_value: str | None = None
    cursor: str | None = None
    page: int | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        allowed_statuses = {
            "active",
            "assigned",
            "insufficient_evidence",
            "not_company_industry",
            "superseded",
        }
        if not 1 <= self.limit <= 200:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_REVIEW_LIMIT_INVALID",
                "Company Industry review limit must be 1..200",
            )
        if self.page is not None and self.page < 1:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_REVIEW_PAGE_INVALID",
                "Company Industry review page must be at least 1",
            )
        if set(self.statuses) - allowed_statuses:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_REVIEW_STATUS_INVALID",
                "Company Industry review status is invalid",
            )
        if any(not value.strip() for value in (*self.source_sites, *self.reasons)):
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_REVIEW_FILTER_INVALID",
                "Company Industry review filters must be non-empty",
            )


@dataclass(frozen=True)
class SourceIndustryMappingView:
    id: UUID
    source_site: str
    key_kind: str
    raw_value: str
    normalized_key: str
    taxonomy_revision_id: UUID
    target_node_id: UUID
    status: str
    version: int
    approved_by: str
    approved_at: datetime
    decision_audit_id: UUID | None

    def to_payload(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "source_site": self.source_site,
            "key_kind": self.key_kind,
            "raw_value": self.raw_value,
            "normalized_key": self.normalized_key,
            "taxonomy_revision_id": str(self.taxonomy_revision_id),
            "target_node_id": str(self.target_node_id),
            "status": self.status,
            "version": self.version,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "decision_audit_id": (
                str(self.decision_audit_id)
                if self.decision_audit_id is not None
                else None
            ),
        }


def _encode_review_cursor(row: CompanyIndustryReviewItem) -> str:
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
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CompanyIndustryReadError(
            "COMPANY_INDUSTRY_REVIEW_CURSOR_INVALID",
            "Invalid Company Industry review cursor",
        ) from exc


class CompanyIndustry:
    """Read governed Company Industry hierarchy and descendant semantics."""

    def __init__(
        self,
        db: Session,
        *,
        outbox_repository: EventOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.outbox_repository = outbox_repository or EventOutboxRepository()

    @staticmethod
    def _node_view(row: CompanyIndustryTaxonomyNode) -> CompanyIndustryNodeView:
        return CompanyIndustryNodeView(
            id=row.id,
            code=row.code,
            parent_id=row.parent_id,
            level=row.level,
            labels={
                "en": row.label_en,
                "zh_hant": row.label_zh_hant,
                "zh_hans": row.label_zh_hans,
            },
            order=row.source_order,
        )

    @staticmethod
    def _assignment_view(
        row: CompanyIndustryAssignment,
    ) -> CompanyIndustryAssignmentView:
        return CompanyIndustryAssignmentView(
            id=row.id,
            taxonomy_revision_id=row.taxonomy_revision_id,
            node_id=row.node_id,
            method=row.method,
            breadcrumb=[dict(item) for item in row.breadcrumb],
            is_primary=row.is_primary,
            primary_basis=row.primary_basis,
            version=row.lock_version,
            provenance=dict(row.provenance),
        )

    @staticmethod
    def _review_ref(row: CompanyIndustryReviewItem) -> CompanyIndustryReviewRefView:
        return CompanyIndustryReviewRefView(
            id=row.id,
            status=row.status,
            reason=row.reason,
            version=row.lock_version,
            decision_audit_id=row.decision_audit_id,
        )

    @staticmethod
    def _review_view(
        row: CompanyIndustryReviewItem,
    ) -> CompanyIndustryReviewItemView:
        return CompanyIndustryReviewItemView(
            id=row.id,
            company_id=row.company_id,
            taxonomy_revision_id=row.taxonomy_revision_id,
            source_site=row.source_site,
            key_kind=row.key_kind,
            raw_value=row.raw_value,
            normalized_key=row.normalized_key,
            reason=row.reason,
            status=row.status,
            evidence_hash=row.evidence_hash,
            provenance=dict(row.provenance),
            recommendations=tuple(dict(item) for item in row.recommendations),
            version=row.lock_version,
            decision_audit_id=row.decision_audit_id,
            assignment_id=row.assignment_id,
            mapping_id=row.mapping_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            resolved_at=row.resolved_at,
        )

    def get_active_revision(self) -> CompanyIndustryRevisionView:
        active = self.db.get(CompanyIndustryActiveRevision, "company-industry")
        if active is None:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_TAXONOMY_NOT_ACTIVE",
                "Company Industry taxonomy is not active",
            )
        release = self.db.get(CompanyIndustryTaxonomyRelease, active.revision_id)
        governance = self.db.get(GovernanceRevision, active.revision_id)
        if (
            release is None
            or release.status != "ready"
            or governance is None
            or release.content_hash != active.content_hash
            or governance.content_hash != active.content_hash
        ):
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_ACTIVE_REVISION_INVALID",
                "Company Industry active revision is invalid",
            )
        return CompanyIndustryRevisionView(
            id=release.revision_id,
            release_key=governance.release_key,
            content_hash=release.content_hash,
            lock_version=active.lock_version,
            activated_at=active.activated_at,
            counts=dict(release.materialized_counts),
        )

    def get_tree(self, parent_id: UUID | None = None) -> CompanyIndustryTreeView:
        revision = self.get_active_revision()
        query = self.db.query(CompanyIndustryTaxonomyNode).filter(
            CompanyIndustryTaxonomyNode.revision_id == revision.id
        )
        if parent_id is None:
            query = query.filter(CompanyIndustryTaxonomyNode.parent_id.is_(None))
        else:
            parent = self.db.get(CompanyIndustryTaxonomyNode, parent_id)
            if parent is None or parent.revision_id != revision.id:
                raise CompanyIndustryReadError(
                    "COMPANY_INDUSTRY_PARENT_NOT_FOUND",
                    "Company Industry parent node was not found",
                )
            query = query.filter(CompanyIndustryTaxonomyNode.parent_id == parent_id)
        rows = query.order_by(CompanyIndustryTaxonomyNode.source_order).all()
        return CompanyIndustryTreeView(
            revision=revision,
            parent_id=parent_id,
            nodes=tuple(self._node_view(row) for row in rows),
        )

    def get_breadcrumb(self, node_id: UUID) -> tuple[CompanyIndustryNodeView, ...]:
        revision = self.get_active_revision()
        row = self.db.get(CompanyIndustryTaxonomyNode, node_id)
        if row is None or row.revision_id != revision.id:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_NODE_NOT_FOUND",
                "Company Industry node was not found",
            )
        breadcrumb: list[CompanyIndustryTaxonomyNode] = []
        seen: set[UUID] = set()
        while row is not None:
            if row.id in seen:
                raise CompanyIndustryReadError(
                    "COMPANY_INDUSTRY_HIERARCHY_INVALID",
                    "Company Industry hierarchy contains a cycle",
                )
            seen.add(row.id)
            breadcrumb.append(row)
            row = (
                self.db.get(CompanyIndustryTaxonomyNode, row.parent_id)
                if row.parent_id is not None
                else None
            )
        return tuple(self._node_view(item) for item in reversed(breadcrumb))

    def get_descendant_ids(self, node_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
        revision = self.get_active_revision()
        selected = set(node_ids)
        rows = (
            self.db.query(CompanyIndustryTaxonomyNode)
            .filter(CompanyIndustryTaxonomyNode.revision_id == revision.id)
            .order_by(CompanyIndustryTaxonomyNode.source_order)
            .all()
        )
        if selected - {row.id for row in rows}:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_FILTER_NODE_INVALID",
                "Company Industry filter contains an unknown node",
            )
        children: dict[UUID | None, list[UUID]] = {}
        for row in rows:
            children.setdefault(row.parent_id, []).append(row.id)
        resolved = set(selected)
        pending = list(selected)
        while pending:
            current = pending.pop()
            for child in children.get(current, ()):
                if child not in resolved:
                    resolved.add(child)
                    pending.append(child)
        return tuple(row.id for row in rows if row.id in resolved)

    def get_company_state(
        self,
        company_id: UUID,
    ) -> CompanyIndustryCompanyStateView:
        if self.db.get(Company, company_id) is None:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_COMPANY_NOT_FOUND",
                "Company was not found",
            )
        assignments = (
            self.db.query(CompanyIndustryAssignment)
            .filter(
                CompanyIndustryAssignment.company_id == company_id,
                CompanyIndustryAssignment.status == "active",
            )
            .order_by(
                CompanyIndustryAssignment.is_primary.desc(),
                CompanyIndustryAssignment.captured_at,
                CompanyIndustryAssignment.id,
            )
            .all()
        )
        reviews = (
            self.db.query(CompanyIndustryReviewItem)
            .filter(CompanyIndustryReviewItem.company_id == company_id)
            .order_by(
                CompanyIndustryReviewItem.created_at.desc(),
                CompanyIndustryReviewItem.id.desc(),
            )
            .all()
        )
        return CompanyIndustryCompanyStateView(
            company_id=company_id,
            assignments=tuple(self._assignment_view(row) for row in assignments),
            review_item_refs=tuple(self._review_ref(row) for row in reviews),
        )

    def build_company_filter(self, node_ids: tuple[UUID, ...]):
        descendants = self.get_descendant_ids(node_ids)
        revision = self.get_active_revision()
        return exists().where(
            and_(
                CompanyIndustryAssignment.company_id == Company.id,
                CompanyIndustryAssignment.taxonomy_revision_id == revision.id,
                CompanyIndustryAssignment.node_id.in_(descendants),
                CompanyIndustryAssignment.status == "active",
            )
        )

    def list_review_items(
        self,
        query: CompanyIndustryReviewQuery,
    ) -> CompanyIndustryReviewPage:
        statement = self.db.query(CompanyIndustryReviewItem)
        if query.statuses:
            statement = statement.filter(
                CompanyIndustryReviewItem.status.in_(query.statuses)
            )
        if query.source_sites:
            statement = statement.filter(
                CompanyIndustryReviewItem.source_site.in_(query.source_sites)
            )
        if query.reasons:
            statement = statement.filter(
                CompanyIndustryReviewItem.reason.in_(query.reasons)
            )
        if query.company_id is not None:
            statement = statement.filter(
                CompanyIndustryReviewItem.company_id == query.company_id
            )
        if query.raw_value:
            statement = statement.filter(
                CompanyIndustryReviewItem.raw_value.ilike(f"%{query.raw_value}%")
            )
        total = statement.count()
        if query.page is not None:
            offset = (query.page - 1) * query.limit
            page_rows = (
                statement.order_by(
                    CompanyIndustryReviewItem.created_at.desc(),
                    CompanyIndustryReviewItem.id.desc(),
                )
                .offset(offset)
                .limit(query.limit)
                .all()
            )
            return CompanyIndustryReviewPage(
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
                    CompanyIndustryReviewItem.created_at < created_at,
                    and_(
                        CompanyIndustryReviewItem.created_at == created_at,
                        CompanyIndustryReviewItem.id < review_id,
                    ),
                )
            )
        rows = (
            statement.order_by(
                CompanyIndustryReviewItem.created_at.desc(),
                CompanyIndustryReviewItem.id.desc(),
            )
            .limit(query.limit + 1)
            .all()
        )
        page_rows = rows[: query.limit]
        return CompanyIndustryReviewPage(
            items=tuple(self._review_view(row) for row in page_rows),
            next_cursor=(
                _encode_review_cursor(page_rows[-1])
                if len(rows) > query.limit and page_rows
                else None
            ),
            total=total,
        )

    def get_review_item(self, review_id: UUID) -> CompanyIndustryReviewItemView:
        row = self.db.get(CompanyIndustryReviewItem, review_id)
        if row is None:
            raise CompanyIndustryReadError(
                "COMPANY_INDUSTRY_REVIEW_ITEM_NOT_FOUND",
                "Company Industry Review Item was not found",
            )
        return self._review_view(row)

    def list_mappings(
        self,
        *,
        source_sites: tuple[str, ...] = (),
        statuses: tuple[str, ...] = ("active",),
    ) -> tuple[SourceIndustryMappingView, ...]:
        query = self.db.query(SourceIndustryMapping)
        if source_sites:
            query = query.filter(SourceIndustryMapping.source_site.in_(source_sites))
        if statuses:
            query = query.filter(SourceIndustryMapping.status.in_(statuses))
        rows = query.order_by(
            SourceIndustryMapping.source_site,
            SourceIndustryMapping.key_kind,
            SourceIndustryMapping.normalized_key,
            SourceIndustryMapping.created_at,
            SourceIndustryMapping.id,
        ).all()
        return tuple(
            SourceIndustryMappingView(
                id=row.id,
                source_site=row.source_site,
                key_kind=row.key_kind,
                raw_value=row.raw_value,
                normalized_key=row.normalized_key,
                taxonomy_revision_id=row.taxonomy_revision_id,
                target_node_id=row.target_node_id,
                status=row.status,
                version=row.lock_version,
                approved_by=row.approved_by,
                approved_at=row.approved_at,
                decision_audit_id=row.decision_audit_id,
            )
            for row in rows
        )

    @staticmethod
    def normalize_mapping_key(value: str) -> str:
        return " ".join(value.split()).casefold()

    def _active_pointer(self) -> CompanyIndustryActiveRevision | None:
        return self.db.get(CompanyIndustryActiveRevision, "company-industry")

    def _evidence_hash(
        self,
        company_id: UUID,
        evidence: CompanyIndustryEvidence,
    ) -> str:
        return normalized_content_hash(
            {
                "company_id": str(company_id),
                "evidence": evidence.to_payload(),
            }
        )

    def _breadcrumb_payload(
        self,
        node: CompanyIndustryTaxonomyNode,
    ) -> list[dict[str, object]]:
        rows: list[CompanyIndustryTaxonomyNode] = []
        current: CompanyIndustryTaxonomyNode | None = node
        while current is not None:
            rows.append(current)
            current = (
                self.db.get(CompanyIndustryTaxonomyNode, current.parent_id)
                if current.parent_id is not None
                else None
            )
        return [
            {
                "id": str(item.id),
                "code": item.code,
                "level": item.level,
                "labels": {
                    "en": item.label_en,
                    "zh_hant": item.label_zh_hant,
                    "zh_hans": item.label_zh_hans,
                },
            }
            for item in reversed(rows)
        ]

    def _emit_projection_event(
        self,
        *,
        company_id: UUID,
        event_type: str,
        payload: dict[str, object],
    ) -> None:
        self.outbox_repository.enqueue(
            self.db,
            topic="job-intelligence-projections",
            aggregate_type="company",
            aggregate_id=str(company_id),
            event_type=event_type,
            source_service="company-industry",
            payload=payload,
            auto_commit=False,
        )

    def _create_assignment(
        self,
        *,
        company_id: UUID,
        node: CompanyIndustryTaxonomyNode,
        evidence: CompanyIndustryEvidence,
        evidence_hash: str,
        method: str,
        mapping: SourceIndustryMapping | None = None,
        primary_basis: str | None = None,
        emit_event: bool = True,
    ) -> tuple[CompanyIndustryAssignment, bool]:
        existing = (
            self.db.query(CompanyIndustryAssignment)
            .filter(
                CompanyIndustryAssignment.company_id == company_id,
                CompanyIndustryAssignment.node_id == node.id,
                CompanyIndustryAssignment.status == "active",
            )
            .with_for_update()
            .one_or_none()
        )
        make_primary = primary_basis is not None
        mapping_id = mapping.id if mapping is not None else None
        if existing is not None and (
            existing.taxonomy_revision_id == node.revision_id
            and existing.evidence_hash == evidence_hash
            and existing.method == method
            and existing.mapping_id == mapping_id
        ):
            changed = False
            if make_primary and (
                not existing.is_primary or existing.primary_basis != primary_basis
            ):
                current_primary = (
                    self.db.query(CompanyIndustryAssignment)
                    .filter(
                        CompanyIndustryAssignment.company_id == company_id,
                        CompanyIndustryAssignment.status == "active",
                        CompanyIndustryAssignment.is_primary.is_(True),
                    )
                    .with_for_update()
                    .one_or_none()
                )
                if current_primary is not None and current_primary.id != existing.id:
                    current_primary.is_primary = False
                    current_primary.primary_basis = None
                    current_primary.lock_version += 1
                existing.is_primary = True
                existing.primary_basis = primary_basis
                existing.lock_version += 1
                changed = True
            return existing, changed

        assignment_version = 1
        assignment_is_primary = make_primary
        assignment_primary_basis = primary_basis
        if existing is not None:
            assignment_version = existing.lock_version + 1
            if existing.is_primary and not make_primary:
                assignment_is_primary = True
                assignment_primary_basis = existing.primary_basis
            existing.status = "superseded"
            existing.superseded_at = utc_now()
            self.db.flush()

        if assignment_is_primary:
            current_primary = (
                self.db.query(CompanyIndustryAssignment)
                .filter(
                    CompanyIndustryAssignment.company_id == company_id,
                    CompanyIndustryAssignment.status == "active",
                    CompanyIndustryAssignment.is_primary.is_(True),
                )
                .with_for_update()
                .one_or_none()
            )
            if current_primary is not None:
                current_primary.is_primary = False
                current_primary.primary_basis = None
                current_primary.lock_version += 1
        provenance = evidence.provenance.to_payload()
        if mapping is not None:
            provenance = {**provenance, "mapping_id": str(mapping.id)}
        assignment = CompanyIndustryAssignment(
            company_id=company_id,
            taxonomy_revision_id=node.revision_id,
            node_id=node.id,
            mapping_id=mapping_id,
            method=method,
            provenance=provenance,
            evidence_hash=evidence_hash,
            breadcrumb=self._breadcrumb_payload(node),
            is_primary=assignment_is_primary,
            primary_basis=assignment_primary_basis,
            status="active",
            lock_version=assignment_version,
            captured_at=evidence.provenance.captured_at,
        )
        self.db.add(assignment)
        self.db.flush()
        if emit_event:
            self._emit_projection_event(
                company_id=company_id,
                event_type="company.industry_changed",
                payload={
                    "company_id": str(company_id),
                    "assignment_id": str(assignment.id),
                    "taxonomy_revision_id": str(node.revision_id),
                    "node_id": str(node.id),
                    "invalidate": ["company-industry-read-model", "job-search"],
                },
            )
        return assignment, True

    def _create_review(
        self,
        *,
        company_id: UUID,
        evidence: CompanyIndustryEvidence,
        evidence_hash: str,
        reason: str,
        taxonomy_revision_id: UUID | None,
    ) -> CompanyIndustryOutcome:
        existing = (
            self.db.query(CompanyIndustryReviewItem)
            .filter(
                CompanyIndustryReviewItem.company_id == company_id,
                CompanyIndustryReviewItem.evidence_hash == evidence_hash,
                CompanyIndustryReviewItem.status == "active",
            )
            .one_or_none()
        )
        if existing is not None:
            return CompanyIndustryOutcome(
                company_id=company_id,
                state="review",
                assignment_id=None,
                review_item_id=existing.id,
                changed=False,
            )
        raw_value = evidence.raw_code or evidence.raw_label
        key_kind = (
            "code" if evidence.raw_code else ("label" if evidence.raw_label else None)
        )
        review = CompanyIndustryReviewItem(
            company_id=company_id,
            taxonomy_revision_id=taxonomy_revision_id,
            source_site=evidence.source_site,
            key_kind=key_kind,
            raw_value=raw_value,
            normalized_key=(
                self.normalize_mapping_key(raw_value) if raw_value is not None else None
            ),
            reason=reason,
            status="active",
            evidence_hash=evidence_hash,
            provenance=evidence.provenance.to_payload(),
            recommendations=[dict(item) for item in evidence.recommendations],
            lock_version=1,
        )
        self.db.add(review)
        self.db.flush()
        self._emit_projection_event(
            company_id=company_id,
            event_type="company.industry_review_changed",
            payload={
                "company_id": str(company_id),
                "review_item_id": str(review.id),
                "reason": reason,
                "invalidate": ["company-industry-review-queue"],
            },
        )
        return CompanyIndustryOutcome(
            company_id=company_id,
            state="review",
            assignment_id=None,
            review_item_id=review.id,
            changed=True,
        )

    def ingest_evidence(
        self,
        company_id: UUID,
        evidence: CompanyIndustryEvidence,
    ) -> CompanyIndustryOutcome:
        company = self.db.get(Company, company_id)
        if company is None:
            raise ValueError("Company Industry evidence Company was not found")
        evidence_hash = self._evidence_hash(company_id, evidence)
        active = self._active_pointer()
        if active is None:
            return self._create_review(
                company_id=company_id,
                evidence=evidence,
                evidence_hash=evidence_hash,
                reason="taxonomy_not_active",
                taxonomy_revision_id=None,
            )

        if evidence.evidence_kind == "source_industry" and evidence.hsic_codes:
            unique_codes = tuple(dict.fromkeys(evidence.hsic_codes))
            nodes = (
                self.db.query(CompanyIndustryTaxonomyNode)
                .filter(
                    CompanyIndustryTaxonomyNode.revision_id == active.revision_id,
                    CompanyIndustryTaxonomyNode.code.in_(unique_codes),
                )
                .all()
            )
            if len(nodes) != len(unique_codes):
                return self._create_review(
                    company_id=company_id,
                    evidence=evidence,
                    evidence_hash=evidence_hash,
                    reason="invalid_hsic_code",
                    taxonomy_revision_id=active.revision_id,
                )
            level_order = {
                "section": 1,
                "division": 2,
                "group": 3,
                "class": 4,
                "subclass": 5,
            }
            target = max(nodes, key=lambda node: level_order[node.level])
            breadcrumb_codes = {
                str(item["code"]) for item in self._breadcrumb_payload(target)
            }
            if set(unique_codes) - breadcrumb_codes:
                return self._create_review(
                    company_id=company_id,
                    evidence=evidence,
                    evidence_hash=evidence_hash,
                    reason="conflicting_hsic_codes",
                    taxonomy_revision_id=active.revision_id,
                )
            assignment, changed = self._create_assignment(
                company_id=company_id,
                node=target,
                evidence=evidence,
                evidence_hash=evidence_hash,
                method="authoritative_code",
                primary_basis=(
                    "authoritative_source" if evidence.declares_primary else None
                ),
            )
            return CompanyIndustryOutcome(
                company_id=company_id,
                state="assigned",
                assignment_id=assignment.id,
                review_item_id=None,
                changed=changed,
            )

        if evidence.evidence_kind == "source_industry":
            mapping_candidates: list[SourceIndustryMapping] = []
            for key_kind, value in (
                ("code", evidence.raw_code),
                ("label", evidence.raw_label),
            ):
                if value is None:
                    continue
                mapping = (
                    self.db.query(SourceIndustryMapping)
                    .filter(
                        SourceIndustryMapping.source_site == evidence.source_site,
                        SourceIndustryMapping.key_kind == key_kind,
                        SourceIndustryMapping.normalized_key
                        == self.normalize_mapping_key(value),
                        SourceIndustryMapping.status == "active",
                        SourceIndustryMapping.taxonomy_revision_id
                        == active.revision_id,
                    )
                    .one_or_none()
                )
                if mapping is not None:
                    mapping_candidates.append(mapping)
            mapping_targets = {mapping.target_node_id for mapping in mapping_candidates}
            if len(mapping_targets) > 1:
                return self._create_review(
                    company_id=company_id,
                    evidence=evidence,
                    evidence_hash=evidence_hash,
                    reason="conflicting_source_mapping",
                    taxonomy_revision_id=active.revision_id,
                )
            if mapping_candidates:
                mapping = mapping_candidates[0]
                target = self.db.get(
                    CompanyIndustryTaxonomyNode,
                    mapping.target_node_id,
                )
                if target is None or target.revision_id != active.revision_id:
                    raise ValueError("Active Source Industry mapping target is invalid")
                assignment, changed = self._create_assignment(
                    company_id=company_id,
                    node=target,
                    evidence=evidence,
                    evidence_hash=evidence_hash,
                    method="reviewed_mapping",
                    mapping=mapping,
                    primary_basis=(
                        "authoritative_source" if evidence.declares_primary else None
                    ),
                )
                return CompanyIndustryOutcome(
                    company_id=company_id,
                    state="assigned",
                    assignment_id=assignment.id,
                    review_item_id=None,
                    changed=changed,
                )

        reason = {
            "source_industry": "unmapped_source_evidence",
            "manual": "manual_evidence",
            "ai_recommendation": "ai_recommendation",
        }[evidence.evidence_kind]
        return self._create_review(
            company_id=company_id,
            evidence=evidence,
            evidence_hash=evidence_hash,
            reason=reason,
            taxonomy_revision_id=active.revision_id,
        )


__all__ = [
    "CompanyIndustry",
    "CompanyIndustryAssignmentView",
    "CompanyIndustryCompanyStateView",
    "CompanyIndustryNodeView",
    "CompanyIndustryReadError",
    "CompanyIndustryReviewItemView",
    "CompanyIndustryReviewPage",
    "CompanyIndustryReviewQuery",
    "CompanyIndustryReviewRefView",
    "CompanyIndustryRevisionView",
    "CompanyIndustryTreeView",
    "SourceIndustryMappingView",
]
