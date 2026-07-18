from __future__ import annotations

from collections import defaultdict
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, joinedload

from app.job_intelligence.foundation import normalized_content_hash
from app.job_intelligence.source_attributes.contracts import (
    EmploymentTypeView,
    ProjectionResult,
    SourceCatalogRevisionRef,
    SourceClassificationNodeView,
    SourceClassificationPathView,
    SourceEmploymentLabelView,
    SourceJobAttributeEvidence,
    SourceJobAttributesView,
)
from app.models.job import Job
from app.models.source_catalog import SourceCatalogRevision
from app.models.source_job_attributes import (
    EmploymentType,
    JobEmploymentType,
    JobSourceAttributeProjection,
    JobSourceClassificationPath,
    JobSourceClassificationPathNode,
    JobSourceEmploymentLabel,
)
from app.repositories.event_outbox_repository import EventOutboxRepository


EMPLOYMENT_TYPE_SEEDS = (
    ("full_time", "Full-time", 1),
    ("part_time", "Part-time", 2),
    ("permanent", "Permanent", 3),
    ("contract", "Contract", 4),
    ("temporary", "Temporary", 5),
    ("internship", "Internship", 6),
    ("freelance", "Freelance", 7),
)


class SourceJobAttributes:
    def __init__(
        self,
        db: Session,
        *,
        outbox_repository: EventOutboxRepository | None = None,
    ) -> None:
        self.db = db
        self.outbox_repository = outbox_repository or EventOutboxRepository()

    def project(
        self,
        job_id: UUID,
        evidence: SourceJobAttributeEvidence,
    ) -> ProjectionResult:
        job = (
            self.db.query(Job).filter(Job.id == job_id).with_for_update().one_or_none()
        )
        if job is None:
            raise ValueError(f"Job {job_id} does not exist")
        if job.source_site != evidence.source_site:
            raise ValueError(
                "Source Job Attribute evidence Source does not match its Job"
            )
        self._validate_evidence(evidence)
        self._validate_catalog_revisions(evidence)

        evidence_hash = normalized_content_hash(evidence.to_payload())
        projection = self.db.get(JobSourceAttributeProjection, job_id)
        if projection is not None and projection.evidence_hash == evidence_hash:
            view = self.get(job_id)
            return ProjectionResult(
                changed=False,
                version=projection.version,
                view=view,
            )

        if projection is None:
            projection = JobSourceAttributeProjection(
                job_id=job_id,
                source_site=evidence.source_site,
                evidence_hash=evidence_hash,
                version=1,
            )
            self.db.add(projection)
        else:
            projection.evidence_hash = evidence_hash
            projection.version += 1
            self._delete_current_projection(job_id)

        for path_evidence in evidence.classification_paths:
            path = JobSourceClassificationPath(
                id=uuid4(),
                job_id=job_id,
                source_site=evidence.source_site,
                source_catalog_revision_id=(
                    path_evidence.source_catalog_revision.revision_id
                    if path_evidence.source_catalog_revision is not None
                    else None
                ),
                source_order=path_evidence.source_order,
                path_fingerprint=normalized_content_hash(
                    [node.source_classification_id for node in path_evidence.nodes]
                ),
                is_primary=path_evidence.source_declared_primary,
                primary_basis=path_evidence.primary_basis,
                provenance=path_evidence.provenance.to_payload(),
                captured_at=path_evidence.provenance.captured_at,
            )
            path.nodes = [
                JobSourceClassificationPathNode(
                    id=uuid4(),
                    source_site=evidence.source_site,
                    source_position=node.source_position,
                    native_depth=node.native_depth,
                    source_classification_id=node.source_classification_id,
                    native_id=node.native_id,
                    label=node.label,
                )
                for node in path_evidence.nodes
            ]
            self.db.add(path)

        evidence_by_type: dict[str, list[UUID]] = defaultdict(list)
        provenance_by_type: dict[str, dict] = {}
        for label_evidence in evidence.employment_labels:
            label_id = uuid4()
            label = JobSourceEmploymentLabel(
                id=label_id,
                job_id=job_id,
                source_site=evidence.source_site,
                source_order=label_evidence.source_order,
                raw_code=label_evidence.raw_code,
                raw_label=label_evidence.raw_label,
                normalized_lookup_key=label_evidence.normalized_lookup_key,
                mapped_type_code=label_evidence.mapped_type_code,
                mapping_id=label_evidence.mapping_id,
                provenance=label_evidence.provenance.to_payload(),
                captured_at=label_evidence.provenance.captured_at,
            )
            self.db.add(label)
            if label_evidence.mapped_type_code is not None:
                evidence_by_type[label_evidence.mapped_type_code].append(label_id)
                provenance_by_type[
                    label_evidence.mapped_type_code
                ] = label_evidence.provenance.to_payload()

        for type_code, evidence_ids in evidence_by_type.items():
            self.db.add(
                JobEmploymentType(
                    job_id=job_id,
                    employment_type_code=type_code,
                    evidence_label_ids=[str(item) for item in evidence_ids],
                    provenance=provenance_by_type[type_code],
                )
            )

        self.outbox_repository.enqueue(
            self.db,
            topic="job-intelligence-projections",
            aggregate_type="job",
            aggregate_id=str(job_id),
            event_type="job.source_attributes_changed",
            source_service="source-job-attributes",
            payload={
                "job_id": str(job_id),
                "source_site": evidence.source_site,
                "version": projection.version,
                "evidence_hash": evidence_hash,
            },
            auto_commit=False,
        )
        self.db.flush()
        view = self.get(job_id)
        return ProjectionResult(
            changed=True,
            version=projection.version,
            view=view,
        )

    def get(self, job_id: UUID) -> SourceJobAttributesView:
        projection = self.db.get(JobSourceAttributeProjection, job_id)
        if projection is None:
            raise ValueError(f"Job {job_id} has no Source Job Attributes")

        paths = (
            self.db.query(JobSourceClassificationPath)
            .options(
                joinedload(JobSourceClassificationPath.nodes),
                joinedload(JobSourceClassificationPath.source_catalog_revision),
            )
            .filter(JobSourceClassificationPath.job_id == job_id)
            .order_by(JobSourceClassificationPath.source_order)
            .all()
        )
        labels = (
            self.db.query(JobSourceEmploymentLabel)
            .filter(JobSourceEmploymentLabel.job_id == job_id)
            .order_by(JobSourceEmploymentLabel.source_order)
            .all()
        )
        employment_types = (
            self.db.query(EmploymentType)
            .join(
                JobEmploymentType,
                JobEmploymentType.employment_type_code == EmploymentType.code,
            )
            .filter(JobEmploymentType.job_id == job_id)
            .order_by(EmploymentType.sort_order)
            .all()
        )
        return SourceJobAttributesView(
            job_id=job_id,
            source_site=projection.source_site,
            version=projection.version,
            evidence_hash=projection.evidence_hash,
            source_classification_paths=tuple(self._path_view(path) for path in paths),
            employment_types=tuple(
                EmploymentTypeView(
                    code=item.code,
                    label=item.label,
                    sort_order=item.sort_order,
                )
                for item in employment_types
            ),
            source_employment_labels=tuple(
                SourceEmploymentLabelView(
                    id=label.id,
                    source_order=label.source_order,
                    raw_code=label.raw_code,
                    raw_label=label.raw_label,
                    normalized_lookup_key=label.normalized_lookup_key,
                    mapped_type_code=label.mapped_type_code,
                    mapping_id=label.mapping_id,
                    provenance=label.provenance,
                )
                for label in labels
            ),
        )

    def build_filters(
        self,
        query,
        *,
        source_classification_ids: list[str] | tuple[str, ...] = (),
        employment_type_codes: list[str] | tuple[str, ...] = (),
    ):
        classification_ids = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in source_classification_ids
                if str(value).strip()
            )
        )
        type_codes = tuple(
            dict.fromkeys(
                str(value).strip()
                for value in employment_type_codes
                if str(value).strip()
            )
        )
        if classification_ids:
            query = query.filter(
                Job.source_classification_paths.any(
                    JobSourceClassificationPath.nodes.any(
                        JobSourceClassificationPathNode.source_classification_id.in_(
                            classification_ids
                        )
                    )
                )
            )
        if type_codes:
            query = query.filter(
                Job.employment_type_assignments.any(
                    JobEmploymentType.employment_type_code.in_(type_codes)
                )
            )
        return query

    def _delete_current_projection(self, job_id: UUID) -> None:
        self.db.query(JobSourceClassificationPath).filter(
            JobSourceClassificationPath.job_id == job_id
        ).delete(synchronize_session=False)
        self.db.query(JobSourceEmploymentLabel).filter(
            JobSourceEmploymentLabel.job_id == job_id
        ).delete(synchronize_session=False)
        self.db.query(JobEmploymentType).filter(
            JobEmploymentType.job_id == job_id
        ).delete(synchronize_session=False)

    def _validate_catalog_revisions(
        self,
        evidence: SourceJobAttributeEvidence,
    ) -> None:
        for path in evidence.classification_paths:
            reference = path.source_catalog_revision
            if reference is None:
                continue
            revision = self.db.get(SourceCatalogRevision, reference.revision_id)
            if revision is None:
                raise ValueError("Source Catalog revision does not exist")
            if (
                reference.source_site != evidence.source_site
                or revision.source_site != evidence.source_site
            ):
                raise ValueError("Source Catalog revision Source does not match")
            if revision.fingerprint != reference.fingerprint:
                raise ValueError("Source Catalog revision fingerprint does not match")

    @staticmethod
    def _validate_evidence(evidence: SourceJobAttributeEvidence) -> None:
        primary_paths = 0
        source_prefix = f"{evidence.source_site}:"
        for path in evidence.classification_paths:
            if path.source_declared_primary:
                primary_paths += 1
                if not str(path.primary_basis or "").strip():
                    raise ValueError("Primary path requires a non-empty basis")
            elif path.primary_basis is not None:
                raise ValueError("Non-primary path must not provide a primary basis")
            for node in path.nodes:
                if not node.source_classification_id.startswith(source_prefix) or len(
                    node.source_classification_id
                ) == len(source_prefix):
                    raise ValueError(
                        "Classification node identity does not belong to "
                        f"{evidence.source_site}"
                    )
        if primary_paths > 1:
            raise ValueError("Source Job Attribute evidence has multiple Primary paths")

    def _path_view(
        self,
        path: JobSourceClassificationPath,
    ) -> SourceClassificationPathView:
        revision = path.source_catalog_revision
        return SourceClassificationPathView(
            id=path.id,
            source_order=path.source_order,
            nodes=tuple(
                SourceClassificationNodeView(
                    source_position=node.source_position,
                    native_depth=node.native_depth,
                    source_classification_id=node.source_classification_id,
                    native_id=node.native_id,
                    label=node.label,
                )
                for node in path.nodes
            ),
            is_primary=path.is_primary,
            primary_basis=path.primary_basis,
            source_catalog_revision=(
                SourceCatalogRevisionRef(
                    source_site=revision.source_site,
                    revision_id=revision.id,
                    fingerprint=revision.fingerprint,
                )
                if revision is not None
                else None
            ),
            provenance_limited=revision is None,
            provenance=path.provenance,
        )
