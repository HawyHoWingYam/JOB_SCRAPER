from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session, selectinload, undefer

from app.job_intelligence.source_attributes.contracts import (
    SourceCatalogRevisionRef,
)
from app.job_intelligence.source_attributes.module import SourceJobAttributes
from app.models.job import Job
from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogRevision,
)
from app.models.source_job_attributes import JobSourceClassificationPath
from app.repositories.source_catalog_repository import SourceCatalogRepository
from app.source_catalog.domain import DiscoveredCatalog


@dataclass(frozen=True)
class ProvenanceRepairReport:
    source_site: str
    revision_id: UUID
    revision_fingerprint: str
    revision_sequence: int
    active_revision_id: UUID | None
    active_revision_fingerprint: str | None
    revision_is_active: bool
    jobs_inspected: int
    paths_inspected: int
    missing_provenance_paths: int
    already_bound_paths: int
    repairable_jobs: int
    repairable_paths: int
    missing_path_jobs: int
    empty_path_jobs: int
    incompatible_revision_jobs: int
    incompatible_revision_paths: int
    source_mismatch_jobs: int
    source_mismatch_paths: int
    unknown_identity_jobs: tuple[dict[str, Any], ...]
    unknown_classification_ids: tuple[str, ...]
    repairable_job_ids: tuple[UUID, ...]
    pending_only: bool

    @property
    def coverage_complete(self) -> bool:
        return (
            not self.unknown_classification_ids
            and self.incompatible_revision_paths == 0
            and self.source_mismatch_paths == 0
            and self.empty_path_jobs == 0
            and self.missing_path_jobs == 0
        )

    @property
    def write_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.revision_is_active:
            blockers.append("source_catalog_revision_drift")
        if not self.coverage_complete:
            blockers.append("source_catalog_identity_coverage_incomplete")
        return tuple(blockers)

    @property
    def write_allowed(self) -> bool:
        return not self.write_blockers

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_site": self.source_site,
            "revision_id": str(self.revision_id),
            "revision_fingerprint": self.revision_fingerprint,
            "revision_sequence": self.revision_sequence,
            "active_revision_id": (
                str(self.active_revision_id)
                if self.active_revision_id is not None
                else None
            ),
            "active_revision_fingerprint": self.active_revision_fingerprint,
            "revision_is_active": self.revision_is_active,
            "jobs_inspected": self.jobs_inspected,
            "paths_inspected": self.paths_inspected,
            "missing_provenance_paths": self.missing_provenance_paths,
            "already_bound_paths": self.already_bound_paths,
            "repairable_jobs": self.repairable_jobs,
            "repairable_paths": self.repairable_paths,
            "missing_path_jobs": self.missing_path_jobs,
            "empty_path_jobs": self.empty_path_jobs,
            "incompatible_revision_jobs": self.incompatible_revision_jobs,
            "incompatible_revision_paths": self.incompatible_revision_paths,
            "source_mismatch_jobs": self.source_mismatch_jobs,
            "source_mismatch_paths": self.source_mismatch_paths,
            "unknown_identity_jobs": [
                {
                    "job_id": str(item["job_id"]),
                    "source_job_id": item["source_job_id"],
                    "classification_ids": list(item["classification_ids"]),
                }
                for item in self.unknown_identity_jobs
            ],
            "unknown_classification_ids": list(self.unknown_classification_ids),
            "repairable_job_ids": [str(job_id) for job_id in self.repairable_job_ids],
            "pending_only": self.pending_only,
            "coverage_complete": self.coverage_complete,
            "write_blockers": list(self.write_blockers),
        }


@dataclass(frozen=True)
class ProvenanceRepairApplyResult:
    source_site: str
    revision_id: UUID
    changed_jobs: int
    changed_paths: int
    skipped_jobs: int
    batches_committed: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_site": self.source_site,
            "revision_id": str(self.revision_id),
            "changed_jobs": self.changed_jobs,
            "changed_paths": self.changed_paths,
            "skipped_jobs": self.skipped_jobs,
            "batches_committed": self.batches_committed,
        }


class SourceCatalogProvenanceRepair:
    """Report and operator-approved repair for missing Source Catalog bindings."""

    def __init__(
        self,
        db: Session,
        *,
        source_catalog_repository: SourceCatalogRepository | None = None,
    ) -> None:
        self.db = db
        self.source_catalog_repository = (
            source_catalog_repository or SourceCatalogRepository()
        )

    def inspect_active(
        self,
        *,
        source_site: str,
        job_ids: Sequence[UUID] | None = None,
        pending_only: bool = True,
    ) -> ProvenanceRepairReport:
        """Inspect the currently published revision without guessing a fallback."""
        active_revision_id, _fingerprint = self._active_revision(source_site)
        if active_revision_id is None:
            raise ValueError("Source Catalog has no active revision")
        return self.inspect(
            source_site=source_site,
            revision_id=active_revision_id,
            job_ids=job_ids,
            pending_only=pending_only,
        )

    def inspect(
        self,
        *,
        source_site: str,
        revision_id: UUID,
        job_ids: Sequence[UUID] | None = None,
        pending_only: bool = True,
    ) -> ProvenanceRepairReport:
        source_site = str(source_site or "").strip().lower()
        revision = self._load_revision(
            source_site=source_site,
            revision_id=revision_id,
        )
        catalog = DiscoveredCatalog.from_payloads(
            normalized_payload=revision.normalized_payload,
            source_payload=revision.source_payload,
            provenance=revision.provenance,
        )
        if catalog.source_site != source_site:
            raise ValueError("Source Catalog revision payload Source does not match")
        if catalog.fingerprint != revision.fingerprint:
            raise ValueError("Source Catalog revision fingerprint does not match payload")
        catalog_identity_ids = frozenset(
            node.classification_id
            for node in catalog.nodes
            if node.classification_id is not None
        )
        active_revision_id, active_revision_fingerprint = self._active_revision(
            source_site
        )

        jobs = self._load_jobs(
            source_site=source_site,
            job_ids=job_ids,
            pending_only=pending_only,
        )
        missing_provenance_paths = 0
        already_bound_paths = 0
        repairable_paths = 0
        missing_path_jobs = 0
        empty_path_job_ids: set[UUID] = set()
        incompatible_revision_paths = 0
        source_mismatch_paths = 0
        unknown_classification_ids: set[str] = set()
        unknown_identity_jobs: list[dict[str, Any]] = []
        repairable_job_ids: list[UUID] = []
        incompatible_job_ids: set[UUID] = set()
        source_mismatch_job_ids: set[UUID] = set()

        for job in jobs:
            paths = tuple(job.source_classification_paths or ())
            if not paths:
                missing_path_jobs += 1
                continue

            job_unknown_ids: set[str] = set()
            job_missing_paths = 0
            job_incompatible = False
            job_source_mismatch = False
            for path in paths:
                if path.source_site != job.source_site:
                    source_mismatch_paths += 1
                    job_source_mismatch = True
                    source_mismatch_job_ids.add(job.id)
                if path.source_catalog_revision_id is None:
                    missing_provenance_paths += 1
                    job_missing_paths += 1
                elif path.source_catalog_revision_id == revision.id:
                    already_bound_paths += 1
                else:
                    incompatible_revision_paths += 1
                    job_incompatible = True
                    incompatible_job_ids.add(job.id)

                node_ids = {
                    str(node.source_classification_id).strip()
                    for node in path.nodes
                    if str(node.source_classification_id).strip()
                }
                if not node_ids:
                    empty_path_job_ids.add(job.id)
                job_unknown_ids.update(node_ids - catalog_identity_ids)
                job_unknown_ids.update(
                    node_id
                    for node_id in node_ids
                    if not node_id.startswith(f"{source_site}:")
                )

            if job_unknown_ids:
                unknown_classification_ids.update(job_unknown_ids)
                unknown_identity_jobs.append(
                    {
                        "job_id": job.id,
                        "source_job_id": str(job.source_job_id),
                        "classification_ids": tuple(sorted(job_unknown_ids)),
                    }
                )

            if job_missing_paths and not (
                job_unknown_ids
                or job_incompatible
                or job_source_mismatch
                or any(not path.nodes for path in paths)
            ):
                repairable_job_ids.append(job.id)
                repairable_paths += job_missing_paths

        return ProvenanceRepairReport(
            source_site=source_site,
            revision_id=revision.id,
            revision_fingerprint=revision.fingerprint,
            revision_sequence=int(revision.sequence),
            active_revision_id=active_revision_id,
            active_revision_fingerprint=active_revision_fingerprint,
            revision_is_active=active_revision_id == revision.id,
            jobs_inspected=len(jobs),
            paths_inspected=sum(
                len(tuple(job.source_classification_paths or ())) for job in jobs
            ),
            missing_provenance_paths=missing_provenance_paths,
            already_bound_paths=already_bound_paths,
            repairable_jobs=len(repairable_job_ids),
            repairable_paths=repairable_paths,
            missing_path_jobs=missing_path_jobs,
            empty_path_jobs=len(empty_path_job_ids),
            incompatible_revision_jobs=len(incompatible_job_ids),
            incompatible_revision_paths=incompatible_revision_paths,
            source_mismatch_jobs=len(source_mismatch_job_ids),
            source_mismatch_paths=source_mismatch_paths,
            unknown_identity_jobs=tuple(
                sorted(
                    unknown_identity_jobs,
                    key=lambda item: (item["source_job_id"], str(item["job_id"])),
                )
            ),
            unknown_classification_ids=tuple(sorted(unknown_classification_ids)),
            repairable_job_ids=tuple(repairable_job_ids),
            pending_only=pending_only,
        )

    def apply(
        self,
        report: ProvenanceRepairReport,
        *,
        expected_revision_id: UUID,
        expected_fingerprint: str,
        batch_size: int = 100,
    ) -> ProvenanceRepairApplyResult:
        """Apply a reviewed report in bounded transactions with drift fencing."""

        if report.revision_id != expected_revision_id:
            raise ValueError("Expected Source Catalog revision ID does not match report")
        if report.revision_fingerprint != expected_fingerprint:
            raise ValueError("Expected Source Catalog fingerprint does not match report")
        if not report.write_allowed:
            raise ValueError(
                "Source Catalog provenance repair is blocked: "
                + ",".join(report.write_blockers)
            )
        batch_size = max(1, min(int(batch_size), 1_000))
        job_ids = report.repairable_job_ids
        changed_jobs = 0
        changed_paths = 0
        skipped_jobs = 0
        batches_committed = 0

        self.db.rollback()
        for start in range(0, len(job_ids), batch_size):
            batch_ids = job_ids[start : start + batch_size]
            try:
                self._assert_active_revision(report)
                batch_report = self.inspect(
                    source_site=report.source_site,
                    revision_id=report.revision_id,
                    job_ids=batch_ids,
                    pending_only=report.pending_only,
                )
                if not batch_report.write_allowed:
                    raise ValueError(
                        "Source Catalog provenance coverage changed during repair: "
                        + ",".join(batch_report.write_blockers)
                    )
                for job_id in batch_report.repairable_job_ids:
                    result = SourceJobAttributes(self.db).repair_catalog_provenance(
                        job_id,
                        SourceCatalogRevisionRef(
                            source_site=report.source_site,
                            revision_id=report.revision_id,
                            fingerprint=report.revision_fingerprint,
                        ),
                    )
                    if result.changed:
                        changed_jobs += 1
                changed_paths += batch_report.repairable_paths
                skipped_jobs += len(batch_ids) - len(batch_report.repairable_job_ids)
                self.db.commit()
                batches_committed += 1
            except Exception:
                self.db.rollback()
                raise

        return ProvenanceRepairApplyResult(
            source_site=report.source_site,
            revision_id=report.revision_id,
            changed_jobs=changed_jobs,
            changed_paths=changed_paths,
            skipped_jobs=skipped_jobs,
            batches_committed=batches_committed,
        )

    def _assert_active_revision(self, report: ProvenanceRepairReport) -> None:
        pointer = self.source_catalog_repository.get_active_pointer_for_update(
            self.db,
            source_site=report.source_site,
        )
        if pointer is None or pointer.revision_id != report.revision_id:
            raise ValueError("Source Catalog active revision drifted since report")
        revision = self.source_catalog_repository.get_revision_for_update(
            self.db,
            report.revision_id,
        )
        if revision is None or revision.fingerprint != report.revision_fingerprint:
            raise ValueError("Source Catalog revision fingerprint drifted since report")

    def _load_revision(
        self,
        *,
        source_site: str,
        revision_id: UUID,
    ) -> SourceCatalogRevision:
        revision = self.source_catalog_repository.get_revision(self.db, revision_id)
        if revision is None:
            raise ValueError("Source Catalog revision does not exist")
        if revision.source_site != source_site:
            raise ValueError("Source Catalog revision Source does not match scope")
        return revision

    def _active_revision(
        self,
        source_site: str,
    ) -> tuple[UUID | None, str | None]:
        pointer = (
            self.db.query(SourceCatalogActiveRevision)
            .filter(SourceCatalogActiveRevision.source_site == source_site)
            .one_or_none()
        )
        if pointer is None:
            return None, None
        revision = self.source_catalog_repository.get_revision(
            self.db,
            pointer.revision_id,
        )
        return (
            pointer.revision_id,
            revision.fingerprint if revision is not None else None,
        )

    def _load_jobs(
        self,
        *,
        source_site: str,
        job_ids: Sequence[UUID] | None,
        pending_only: bool,
    ) -> list[Job]:
        with self.db.no_autoflush:
            query = (
                self.db.query(Job)
                .options(
                    undefer(Job.source_site),
                    undefer(Job.source_job_id),
                    selectinload(Job.source_classification_paths).selectinload(
                        JobSourceClassificationPath.nodes
                    ),
                )
                .filter(Job.source_site == source_site)
                .order_by(Job.created_at.asc(), Job.id.asc())
            )
            if pending_only:
                query = query.filter(
                    Job.ai_enriched_at.is_(None),
                    Job.is_deleted.is_(False),
                    Job.source_attribute_projection.has(),
                )
            if job_ids is not None:
                query = query.filter(Job.id.in_(tuple(job_ids)))
            return query.all()
