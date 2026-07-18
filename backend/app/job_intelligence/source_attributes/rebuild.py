from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import tuple_
from sqlalchemy.orm import Session, undefer

from app.job_intelligence.foundation import Provenance, normalized_content_hash
from app.job_intelligence.source_attributes.adapters import (
    JobsDBSourceEvidenceAdapter,
    OfferTodaySourceEvidenceAdapter,
)
from app.job_intelligence.source_attributes.contracts import (
    SourceJobAttributeEvidence,
)
from app.models.job import Job
from app.models.crawl_job_listing import CrawlJobListing


@dataclass(frozen=True)
class SourceRebuildInspection:
    source_site: str
    jobs_inspected: int
    recoverable_jobs: int
    recoverable_classification_paths: int
    recoverable_employment_labels: int
    mapped_employment_labels: int
    multi_path_jobs: int
    explicit_primary_paths: int
    evidence_source_distribution: dict[str, int]
    path_count_distribution: dict[str, int]
    unknown_employment_labels: int
    ambiguous_jobs: int
    conflicting_legacy_jobs: int
    missing_catalog_revision_paths: int
    provenance_limited_jobs: int
    malformed_jobs: int
    unrecoverable_jobs: int
    unrecoverable_cause_distribution: dict[str, int]

    def to_payload(self) -> dict[str, object]:
        return {
            "source_site": self.source_site,
            "jobs_inspected": self.jobs_inspected,
            "recoverable_jobs": self.recoverable_jobs,
            "recoverable_classification_paths": (self.recoverable_classification_paths),
            "recoverable_employment_labels": self.recoverable_employment_labels,
            "mapped_employment_labels": self.mapped_employment_labels,
            "multi_path_jobs": self.multi_path_jobs,
            "explicit_primary_paths": self.explicit_primary_paths,
            "evidence_source_distribution": dict(
                sorted(self.evidence_source_distribution.items())
            ),
            "path_count_distribution": dict(
                sorted(self.path_count_distribution.items())
            ),
            "unknown_employment_labels": self.unknown_employment_labels,
            "ambiguous_jobs": self.ambiguous_jobs,
            "conflicting_legacy_jobs": self.conflicting_legacy_jobs,
            "missing_catalog_revision_paths": (self.missing_catalog_revision_paths),
            "provenance_limited_jobs": self.provenance_limited_jobs,
            "malformed_jobs": self.malformed_jobs,
            "unrecoverable_jobs": self.unrecoverable_jobs,
            "unrecoverable_cause_distribution": dict(
                sorted(self.unrecoverable_cause_distribution.items())
            ),
        }


@dataclass(frozen=True)
class SourceJobAttributeRebuildReport:
    jobs_inspected: int
    sources: tuple[SourceRebuildInspection, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "jobs_inspected": self.jobs_inspected,
            "sources": [source.to_payload() for source in self.sources],
        }


@dataclass
class _SourceCounters:
    jobs_inspected: int = 0
    recoverable_jobs: int = 0
    recoverable_classification_paths: int = 0
    recoverable_employment_labels: int = 0
    mapped_employment_labels: int = 0
    multi_path_jobs: int = 0
    explicit_primary_paths: int = 0
    evidence_source_distribution: dict[str, int] = field(default_factory=dict)
    path_count_distribution: dict[str, int] = field(default_factory=dict)
    unknown_employment_labels: int = 0
    ambiguous_jobs: int = 0
    conflicting_legacy_jobs: int = 0
    missing_catalog_revision_paths: int = 0
    provenance_limited_jobs: int = 0
    malformed_jobs: int = 0
    unrecoverable_jobs: int = 0
    unrecoverable_cause_distribution: dict[str, int] = field(default_factory=dict)


class SourceJobAttributeRebuildInspector:
    """Inspect historical Source Job Attribute recoverability without writes."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def inspect(
        self,
        job_ids: Sequence[UUID] | None = None,
    ) -> SourceJobAttributeRebuildReport:
        with self.db.no_autoflush:
            query = (
                self.db.query(Job)
                .options(
                    undefer(Job.source_site),
                    undefer(Job.source_job_id),
                )
                .order_by(
                    Job.source_site.asc(),
                    Job.source_job_id.asc(),
                    Job.id.asc(),
                )
            )
            if job_ids is not None:
                query = query.filter(Job.id.in_(tuple(job_ids)))
            jobs = query.all()
            staging_rows = self._load_staging_rows(jobs)

        staging_by_job: dict[tuple[str, str], list[CrawlJobListing]] = defaultdict(list)
        for row in staging_rows:
            staging_by_job[(row.source_site, row.source_job_id)].append(row)

        counters_by_source: dict[str, _SourceCounters] = defaultdict(_SourceCounters)
        for job in jobs:
            counters = counters_by_source[job.source_site]
            counters.jobs_inspected += 1
            evidence, evidence_source, malformed, ambiguous = self._evidence_for_job(
                job,
                staging_by_job[(job.source_site, job.source_job_id)],
            )
            if ambiguous:
                counters.ambiguous_jobs += 1
            if evidence is None:
                if malformed:
                    counters.malformed_jobs += 1
                counters.unrecoverable_jobs += 1
                counters.provenance_limited_jobs += 1
                unrecoverable_cause = self._unrecoverable_cause(job, malformed)
                self._increment_count(
                    counters.unrecoverable_cause_distribution,
                    unrecoverable_cause,
                )
                continue

            marker_malformed = any(
                label.normalized_lookup_key is None
                and (
                    self._is_malformed_marker(label.raw_code)
                    or self._is_malformed_marker(label.raw_label)
                )
                for label in evidence.employment_labels
            )
            if malformed or marker_malformed:
                counters.malformed_jobs += 1
            counters.recoverable_jobs += 1
            path_count = len(evidence.classification_paths)
            label_count = len(evidence.employment_labels)
            counters.recoverable_classification_paths += path_count
            counters.recoverable_employment_labels += label_count
            counters.mapped_employment_labels += sum(
                label.mapped_type_code is not None
                for label in evidence.employment_labels
            )
            counters.explicit_primary_paths += sum(
                path.source_declared_primary for path in evidence.classification_paths
            )
            if evidence_source is not None:
                self._increment_count(
                    counters.evidence_source_distribution,
                    evidence_source,
                )
            self._increment_count(
                counters.path_count_distribution,
                str(path_count),
            )
            if self._legacy_conflicts(job, evidence):
                counters.conflicting_legacy_jobs += 1
            if path_count > 1:
                counters.multi_path_jobs += 1
            counters.unknown_employment_labels += sum(
                label.mapped_type_code is None
                and not (
                    label.normalized_lookup_key is None
                    and (
                        self._is_malformed_marker(label.raw_code)
                        or self._is_malformed_marker(label.raw_label)
                    )
                )
                for label in evidence.employment_labels
            )
            missing_revision_paths = sum(
                path.source_catalog_revision is None
                for path in evidence.classification_paths
            )
            counters.missing_catalog_revision_paths += missing_revision_paths
            if missing_revision_paths:
                counters.provenance_limited_jobs += 1

        sources = tuple(
            SourceRebuildInspection(
                source_site=source_site,
                **vars(counters_by_source[source_site]),
            )
            for source_site in sorted(counters_by_source)
        )
        return SourceJobAttributeRebuildReport(
            jobs_inspected=len(jobs),
            sources=sources,
        )

    def _load_staging_rows(
        self,
        jobs: Sequence[Job],
    ) -> list[CrawlJobListing]:
        source_keys = tuple((job.source_site, job.source_job_id) for job in jobs)
        if not source_keys:
            return []
        return (
            self.db.query(CrawlJobListing)
            .filter(
                tuple_(
                    CrawlJobListing.source_site,
                    CrawlJobListing.source_job_id,
                ).in_(source_keys)
            )
            .all()
        )

    def _evidence_for_job(
        self,
        job: Job,
        staging_rows: Sequence[CrawlJobListing],
    ) -> tuple[SourceJobAttributeEvidence | None, str | None, bool, bool]:
        def select_staging_candidate(
            *,
            payload_attribute: str,
            evidence_kind: str,
            detail: bool,
        ) -> tuple[SourceJobAttributeEvidence | None, bool, bool]:
            def freshness(row: CrawlJobListing) -> tuple[int, ...]:
                if detail:
                    return (
                        self._datetime_key(row.detail_completed_at),
                        self._datetime_key(row.updated_at),
                        self._datetime_key(row.created_at),
                    )
                return (
                    self._datetime_key(row.updated_at),
                    self._datetime_key(row.created_at),
                )

            ordered_rows = sorted(
                staging_rows,
                key=lambda row: (freshness(row), str(row.id)),
                reverse=True,
            )
            malformed = False
            selected: SourceJobAttributeEvidence | None = None
            selected_freshness: tuple[int, ...] | None = None
            selected_hash: str | None = None
            ambiguous = False
            for row in ordered_rows:
                row_freshness = freshness(row)
                if (
                    selected_freshness is not None
                    and row_freshness != selected_freshness
                ):
                    break
                evidence, payload_malformed = self._evidence_candidate(
                    getattr(row, payload_attribute),
                    source_site=job.source_site,
                    evidence_ref={
                        "kind": evidence_kind,
                        "listing_id": str(row.id),
                        "source_job_id": job.source_job_id,
                    },
                    captured_at=(
                        row.detail_completed_at or row.updated_at or row.created_at
                        if detail
                        else row.updated_at or row.created_at
                    ),
                )
                malformed = malformed or payload_malformed
                if evidence is None:
                    continue
                evidence_hash = self._semantic_evidence_hash(evidence)
                if selected is None:
                    selected = evidence
                    selected_freshness = row_freshness
                    selected_hash = evidence_hash
                elif evidence_hash != selected_hash:
                    ambiguous = True
            return selected, malformed, ambiguous

        detail_evidence, malformed, ambiguous = select_staging_candidate(
            payload_attribute="detail_payload",
            evidence_kind="staging-detail-payload",
            detail=True,
        )
        if detail_evidence is not None:
            return detail_evidence, "staging_detail_payload", malformed, ambiguous

        (
            listing_evidence,
            listing_malformed,
            listing_ambiguous,
        ) = select_staging_candidate(
            payload_attribute="listing_payload",
            evidence_kind="staging-listing-payload",
            detail=False,
        )
        malformed = malformed or listing_malformed
        if listing_evidence is not None:
            return (
                listing_evidence,
                "staging_listing_payload",
                malformed,
                listing_ambiguous,
            )

        evidence, payload_malformed = self._evidence_candidate(
            job.raw_data,
            source_site=job.source_site,
            evidence_ref={
                "kind": "job-raw-data",
                "job_id": str(job.id),
                "source_job_id": job.source_job_id,
            },
            captured_at=job.updated_at or job.created_at,
        )
        return (
            evidence,
            "job_raw_data" if evidence is not None else None,
            malformed or payload_malformed,
            False,
        )

    @staticmethod
    def _semantic_evidence_hash(evidence: SourceJobAttributeEvidence) -> str:
        payload = evidence.to_payload()
        for path in payload["classification_paths"]:
            path.pop("provenance", None)
        for label in payload["employment_labels"]:
            label.pop("provenance", None)
        return normalized_content_hash(payload)

    def _evidence_candidate(
        self,
        container: object,
        *,
        source_site: str,
        evidence_ref: Mapping[str, object],
        captured_at: datetime | None,
    ) -> tuple[SourceJobAttributeEvidence | None, bool]:
        evidence, malformed = self._payload_evidence(
            container,
            source_site=source_site,
        )
        if evidence is not None:
            return evidence, malformed
        recovered = self._recover_preserved_raw_evidence(
            container,
            source_site=source_site,
            evidence_ref=evidence_ref,
            captured_at=captured_at,
        )
        return recovered, malformed

    @staticmethod
    def _recover_preserved_raw_evidence(
        container: object,
        *,
        source_site: str,
        evidence_ref: Mapping[str, object],
        captured_at: datetime | None,
    ) -> SourceJobAttributeEvidence | None:
        if not isinstance(container, Mapping):
            return None
        nested_raw = container.get("raw_data")
        raw_payload = nested_raw if isinstance(nested_raw, Mapping) else container
        attribute_fields = (
            {
                "classifications",
                "workTypes",
                "workArrangements",
            }
            if source_site == "jobsdb"
            else {
                "jobFunctions",
                "job_functions",
                "jobType",
                "jobTypeDesc",
                "employType",
                "workingModels",
                "workingDays",
            }
            if source_site == "offertoday"
            else set()
        )
        if not attribute_fields.intersection(raw_payload):
            return None
        observed_at = captured_at or datetime(1970, 1, 1, tzinfo=timezone.utc)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        provenance = Provenance(
            method=f"{source_site}-preserved-raw-payload",
            source_site=source_site,
            evidence_refs=(dict(evidence_ref),),
            captured_at=observed_at,
        )
        if source_site == "jobsdb":
            return JobsDBSourceEvidenceAdapter().extract(
                raw_payload,
                provenance=provenance,
            )
        return OfferTodaySourceEvidenceAdapter().extract(
            raw_payload,
            provenance=provenance,
        )

    @classmethod
    def _legacy_conflicts(
        cls,
        job: Job,
        evidence: SourceJobAttributeEvidence,
    ) -> bool:
        root_ids: set[str] = set()
        root_labels: set[str] = set()
        child_ids: set[str] = set()
        child_labels: set[str] = set()
        for path in evidence.classification_paths:
            for node in path.nodes:
                target_ids = root_ids if node.source_position == 0 else child_ids
                target_labels = (
                    root_labels if node.source_position == 0 else child_labels
                )
                target_ids.update(
                    value
                    for value in (
                        cls._normalized_comparison(node.native_id),
                        cls._normalized_comparison(node.source_classification_id),
                    )
                    if value is not None
                )
                label = cls._normalized_comparison(node.label)
                if label is not None:
                    target_labels.add(label)

        comparisons = (
            (job.source_classification_id, root_ids),
            (job.source_classification_name, root_labels),
            (job.source_subclassification_id, child_ids),
            (job.source_subclassification_name, child_labels),
        )
        for legacy_value, typed_values in comparisons:
            normalized_legacy = cls._normalized_comparison(legacy_value)
            if normalized_legacy is not None and normalized_legacy not in typed_values:
                return True

        legacy_employment = {
            normalized
            for part in str(job.employment_type or "").split(",")
            if (normalized := cls._normalized_comparison(part)) is not None
        }
        if not legacy_employment:
            return False
        typed_employment = {
            normalized
            for label in evidence.employment_labels
            for value in (label.raw_label, label.raw_code)
            if (normalized := cls._normalized_comparison(value)) is not None
        }
        return legacy_employment != typed_employment

    @staticmethod
    def _payload_evidence(
        container: object,
        *,
        source_site: str,
    ) -> tuple[SourceJobAttributeEvidence | None, bool]:
        if not isinstance(container, Mapping):
            return None, False
        payload = container.get("source_attribute_evidence")
        if payload is None:
            return None, False
        try:
            evidence = SourceJobAttributeEvidence.from_payload(payload)
        except (KeyError, TypeError, ValueError):
            return None, True
        if evidence.source_site != source_site:
            return None, True
        return evidence, False

    @staticmethod
    def _datetime_key(value: datetime | None) -> int:
        if value is None:
            return -1
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1_000_000)

    @classmethod
    def _unrecoverable_cause(cls, job: Job, malformed: bool) -> str:
        if malformed:
            return "malformed_source_attribute_evidence"
        legacy_values = (
            job.source_classification_id,
            job.source_classification_name,
            job.source_subclassification_id,
            job.source_subclassification_name,
            job.employment_type,
        )
        if any(cls._normalized_comparison(value) for value in legacy_values):
            return "parser_discarded_to_legacy_scalars"
        return "no_preserved_evidence"

    @staticmethod
    def _increment_count(counts: dict[str, int], key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    @staticmethod
    def _is_malformed_marker(value: object) -> bool:
        return (
            isinstance(value, str)
            and value.startswith("<malformed:")
            and value.endswith(">")
        )

    @staticmethod
    def _normalized_comparison(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.split()).casefold()
        return normalized or None
