from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
import re
from typing import Any
import uuid

from sqlalchemy.orm import Session

from app.job_intelligence.foundation import (
    RevisionManifest,
    RevisionRef,
    RevisionStore,
    SeedIssue,
    SeedValidator,
    ValidationReport,
    normalized_content_hash,
)
from app.models.canonical_job_taxonomy import (
    CanonicalJobCategory,
    CanonicalJobDomain,
    CanonicalJobSubcategory,
    CanonicalJobTaxonomyActiveMappingRevision,
    CanonicalJobTaxonomyMappingCoverage,
    CanonicalJobTaxonomyMappingRevision,
    CanonicalJobTaxonomyActiveRevision,
    CanonicalJobTaxonomyRelease,
    SourceJobTaxonomyMapping,
    SourceJobTaxonomyMappingTarget,
)
from app.models.source_catalog import (
    SourceCatalogActiveRevision,
    SourceCatalogRevision,
)
from app.source_catalog.domain import DiscoveredCatalog, validate_catalog
from app.utils.time import utc_now


_CODE_PATTERN = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+)*")
_FORBIDDEN_FALLBACK_LABELS = {"General", "Unknown"}
_MAPPING_DISPOSITIONS = {
    "deterministic",
    "allowed_slice",
    "excluded",
    "unmapped",
}
_TAXONOMY_REVISION_DOMAIN = "canonical-job-taxonomy"
_MAPPING_REVISION_DOMAIN = "canonical-job-taxonomy-mapping"


class CanonicalTaxonomyValidationError(ValueError):
    def __init__(self, report: ValidationReport) -> None:
        super().__init__("Canonical Job Taxonomy seed validation failed")
        self.report = report


class CanonicalTaxonomyActivationConflict(RuntimeError):
    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            "Canonical taxonomy active revision changed: "
            f"expected version {expected}, found {actual}"
        )
        self.expected = expected
        self.actual = actual


class CanonicalMappingCoverageError(ValueError):
    def __init__(
        self,
        *,
        code: str,
        source_site: str,
        missing: tuple[str, ...] = (),
        extra: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            f"{code}: invalid canonical mapping coverage for {source_site}"
        )
        self.code = code
        self.source_site = source_site
        self.missing = missing
        self.extra = extra


class CanonicalMappingActivationConflict(RuntimeError):
    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            "Canonical mapping active revision changed: "
            f"expected version {expected}, found {actual}"
        )
        self.expected = expected
        self.actual = actual


class CanonicalTaxonomyPublisher:
    """Validate and publish governed Canonical Job Taxonomy releases."""

    def __init__(self, db: Session | None = None) -> None:
        self.db = db

    @staticmethod
    def validate(
        seed: Mapping[str, Any],
        mapping_seed: Mapping[str, Any] | None = None,
    ) -> ValidationReport:
        """Return every deterministic seed issue before publication writes."""
        issues = list(_validate_taxonomy_seed(seed))
        if mapping_seed is not None:
            issues.extend(_validate_mapping_seed(mapping_seed, taxonomy_seed=seed))

        def collected_issues(_: Mapping[str, Any]) -> Iterable[SeedIssue]:
            return issues

        return SeedValidator.validate({}, (collected_issues,))

    def materialize(self, seed: Mapping[str, Any]) -> RevisionRef:
        """Materialize one complete inactive release; exact retry is a replay."""
        if self.db is None:
            raise RuntimeError("Canonical taxonomy materialization requires a Session")

        report = self.validate(seed)
        if not report.valid:
            raise CanonicalTaxonomyValidationError(report)

        expected_counts = seed["expected_counts"]
        manifest = RevisionManifest.from_content(
            domain=_TAXONOMY_REVISION_DOMAIN,
            release_key=str(seed["release_key"]),
            content=seed,
            source_metadata={
                "schema_version": seed["schema_version"],
                "expected_counts": dict(expected_counts),
            },
        )
        revision = RevisionStore(self.db).publish(manifest)
        release = self.db.get(CanonicalJobTaxonomyRelease, revision.revision_id)
        if release is not None and release.status == "ready":
            self._require_release_identity(release, revision, expected_counts)
            return revision

        if release is None:
            release = CanonicalJobTaxonomyRelease(
                revision_id=revision.revision_id,
                content_hash=revision.content_hash,
                expected_domain_count=expected_counts["domains"],
                expected_category_count=expected_counts["categories"],
                expected_subcategory_count=expected_counts["subcategories"],
                status="materializing",
            )
            self.db.add(release)
            self.db.flush()
        else:
            self._require_release_identity(release, revision, expected_counts)

        try:
            self._materialize_nodes(seed, revision)
            self.db.flush()
            actual_counts = self._release_counts(revision.revision_id)
            required_counts = (
                expected_counts["domains"],
                expected_counts["categories"],
                expected_counts["subcategories"],
            )
            if actual_counts != required_counts:
                raise RuntimeError(
                    "Canonical taxonomy materialization count mismatch: "
                    f"expected {required_counts}, found {actual_counts}"
                )

            (
                release.materialized_domain_count,
                release.materialized_category_count,
                release.materialized_subcategory_count,
            ) = actual_counts
            release.status = "ready"
            release.ready_at = utc_now()
            self.db.commit()
            return revision
        except Exception:
            self.db.rollback()
            raise

    def activate(
        self,
        revision: RevisionRef,
        *,
        expected_lock_version: int,
    ) -> CanonicalJobTaxonomyActiveRevision:
        """Compare-and-swap the active pointer to one complete ready release."""
        if self.db is None:
            raise RuntimeError("Canonical taxonomy activation requires a Session")
        if revision.domain != _TAXONOMY_REVISION_DOMAIN:
            raise ValueError("Canonical taxonomy activation received another domain")
        if expected_lock_version < 0:
            raise ValueError(
                "Canonical taxonomy expected lock version cannot be negative"
            )

        release = self.db.get(CanonicalJobTaxonomyRelease, revision.revision_id)
        if (
            release is None
            or release.status != "ready"
            or release.content_hash != revision.content_hash
        ):
            self.db.rollback()
            raise RuntimeError("Canonical taxonomy activation requires a ready release")

        active = (
            self.db.query(CanonicalJobTaxonomyActiveRevision)
            .filter(
                CanonicalJobTaxonomyActiveRevision.singleton_key
                == "canonical-job-taxonomy"
            )
            .with_for_update()
            .one_or_none()
        )
        if (
            active is not None
            and active.revision_id == revision.revision_id
            and active.content_hash == revision.content_hash
        ):
            self.db.commit()
            return active

        actual_version = active.lock_version if active is not None else 0
        if expected_lock_version != actual_version:
            self.db.rollback()
            raise CanonicalTaxonomyActivationConflict(
                expected=expected_lock_version,
                actual=actual_version,
            )

        if active is None:
            active = CanonicalJobTaxonomyActiveRevision(
                singleton_key="canonical-job-taxonomy",
                revision_id=revision.revision_id,
                content_hash=revision.content_hash,
                lock_version=1,
                activated_at=utc_now(),
            )
            self.db.add(active)
        else:
            active.revision_id = revision.revision_id
            active.content_hash = revision.content_hash
            active.lock_version += 1
            active.activated_at = utc_now()

        try:
            self.db.commit()
            self.db.refresh(active)
            return active
        except Exception:
            self.db.rollback()
            raise

    def materialize_mapping(
        self,
        taxonomy_seed: Mapping[str, Any],
        mapping_seed: Mapping[str, Any],
    ) -> RevisionRef:
        """Materialize one reviewed mapping release pinned to active catalogs."""
        if self.db is None:
            raise RuntimeError("Canonical mapping materialization requires a Session")

        report = self.validate(taxonomy_seed, mapping_seed)
        if not report.valid:
            raise CanonicalTaxonomyValidationError(report)

        taxonomy_revision = self.materialize(taxonomy_seed)
        active_taxonomy = self.db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        if (
            active_taxonomy is None
            or active_taxonomy.revision_id != taxonomy_revision.revision_id
            or active_taxonomy.content_hash != taxonomy_revision.content_hash
        ):
            raise RuntimeError(
                "Canonical mapping materialization requires its taxonomy release active"
            )

        coverage_payloads = self._resolve_mapping_coverages(mapping_seed)
        target_count = sum(
            len(entry["target_codes"]) for entry in mapping_seed["entries"]
        )
        revision_manifest = RevisionManifest.from_content(
            domain=_MAPPING_REVISION_DOMAIN,
            release_key=str(mapping_seed["release_key"]),
            content={
                "mapping_seed": mapping_seed,
                "coverages": coverage_payloads,
            },
            source_metadata={
                "taxonomy_revision_id": str(taxonomy_revision.revision_id),
                "taxonomy_content_hash": taxonomy_revision.content_hash,
                "coverage_count": len(coverage_payloads),
                "entry_count": len(mapping_seed["entries"]),
                "target_count": target_count,
            },
        )
        revision = RevisionStore(self.db).publish(revision_manifest)
        mapping_revision = self.db.get(
            CanonicalJobTaxonomyMappingRevision,
            revision.revision_id,
        )
        expected_counts = (
            len(coverage_payloads),
            len(mapping_seed["entries"]),
            target_count,
        )
        if mapping_revision is not None and mapping_revision.status == "ready":
            self._require_mapping_revision_identity(
                mapping_revision,
                revision,
                taxonomy_revision,
                expected_counts,
            )
            return revision

        if mapping_revision is None:
            mapping_revision = CanonicalJobTaxonomyMappingRevision(
                revision_id=revision.revision_id,
                taxonomy_revision_id=taxonomy_revision.revision_id,
                content_hash=revision.content_hash,
                expected_coverage_count=expected_counts[0],
                expected_entry_count=expected_counts[1],
                expected_target_count=expected_counts[2],
                status="materializing",
            )
            self.db.add(mapping_revision)
            self.db.flush()
        else:
            self._require_mapping_revision_identity(
                mapping_revision,
                revision,
                taxonomy_revision,
                expected_counts,
            )

        try:
            self._materialize_mapping_rows(
                taxonomy_revision=taxonomy_revision,
                mapping_revision=revision,
                mapping_seed=mapping_seed,
                coverage_payloads=coverage_payloads,
            )
            self.db.flush()
            actual_counts = self._mapping_release_counts(revision.revision_id)
            if actual_counts != expected_counts:
                raise RuntimeError(
                    "Canonical mapping materialization count mismatch: "
                    f"expected {expected_counts}, found {actual_counts}"
                )
            (
                mapping_revision.materialized_coverage_count,
                mapping_revision.materialized_entry_count,
                mapping_revision.materialized_target_count,
            ) = actual_counts
            mapping_revision.status = "ready"
            mapping_revision.ready_at = utc_now()
            self.db.commit()
            return revision
        except Exception:
            self.db.rollback()
            raise

    def activate_mapping(
        self,
        revision: RevisionRef,
        *,
        expected_lock_version: int,
    ) -> CanonicalJobTaxonomyActiveMappingRevision:
        """Activate a ready mapping only while every pinned catalog stays active."""
        if self.db is None:
            raise RuntimeError("Canonical mapping activation requires a Session")
        if revision.domain != _MAPPING_REVISION_DOMAIN:
            raise ValueError("Canonical mapping activation received another domain")
        if expected_lock_version < 0:
            raise ValueError(
                "Canonical mapping expected lock version cannot be negative"
            )

        mapping_release = self.db.get(
            CanonicalJobTaxonomyMappingRevision,
            revision.revision_id,
        )
        if (
            mapping_release is None
            or mapping_release.status != "ready"
            or mapping_release.content_hash != revision.content_hash
        ):
            self.db.rollback()
            raise RuntimeError("Canonical mapping activation requires a ready release")

        active_taxonomy = self.db.get(
            CanonicalJobTaxonomyActiveRevision,
            "canonical-job-taxonomy",
        )
        if (
            active_taxonomy is None
            or active_taxonomy.revision_id != mapping_release.taxonomy_revision_id
        ):
            self.db.rollback()
            raise RuntimeError(
                "Canonical mapping activation requires its taxonomy revision active"
            )

        coverages = (
            self.db.query(CanonicalJobTaxonomyMappingCoverage)
            .filter(
                CanonicalJobTaxonomyMappingCoverage.mapping_revision_id
                == revision.revision_id
            )
            .order_by(CanonicalJobTaxonomyMappingCoverage.source_site)
            .all()
        )
        for coverage in coverages:
            source_pointer = self.db.get(
                SourceCatalogActiveRevision,
                coverage.source_site,
            )
            if source_pointer is None:
                self.db.rollback()
                raise CanonicalMappingCoverageError(
                    code="CATALOG_NOT_PUBLISHED",
                    source_site=coverage.source_site,
                )
            if source_pointer.revision_id != coverage.source_catalog_revision_id:
                self.db.rollback()
                raise CanonicalMappingCoverageError(
                    code="CANONICAL_MAPPING_CATALOG_STALE",
                    source_site=coverage.source_site,
                )

        active = (
            self.db.query(CanonicalJobTaxonomyActiveMappingRevision)
            .filter(
                CanonicalJobTaxonomyActiveMappingRevision.singleton_key
                == "canonical-job-taxonomy-mapping"
            )
            .with_for_update()
            .one_or_none()
        )
        if (
            active is not None
            and active.mapping_revision_id == revision.revision_id
            and active.content_hash == revision.content_hash
        ):
            self.db.commit()
            return active

        actual_version = active.lock_version if active is not None else 0
        if expected_lock_version != actual_version:
            self.db.rollback()
            raise CanonicalMappingActivationConflict(
                expected=expected_lock_version,
                actual=actual_version,
            )

        if active is None:
            active = CanonicalJobTaxonomyActiveMappingRevision(
                singleton_key="canonical-job-taxonomy-mapping",
                mapping_revision_id=revision.revision_id,
                taxonomy_revision_id=mapping_release.taxonomy_revision_id,
                content_hash=revision.content_hash,
                lock_version=1,
                activated_at=utc_now(),
            )
            self.db.add(active)
        else:
            active.mapping_revision_id = revision.revision_id
            active.taxonomy_revision_id = mapping_release.taxonomy_revision_id
            active.content_hash = revision.content_hash
            active.lock_version += 1
            active.activated_at = utc_now()

        try:
            self.db.commit()
            self.db.refresh(active)
            return active
        except Exception:
            self.db.rollback()
            raise

    def _resolve_mapping_coverages(
        self,
        mapping_seed: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        assert self.db is not None
        declared_by_source: dict[str, set[str]] = {}
        for entry in mapping_seed["entries"]:
            declared_by_source.setdefault(entry["source_site"], set()).add(
                entry["source_classification_id"]
            )

        coverages: list[dict[str, Any]] = []
        for source_site, declared_ids in sorted(declared_by_source.items()):
            revision = (
                self.db.query(SourceCatalogRevision)
                .join(
                    SourceCatalogActiveRevision,
                    SourceCatalogActiveRevision.revision_id == SourceCatalogRevision.id,
                )
                .filter(SourceCatalogActiveRevision.source_site == source_site)
                .one_or_none()
            )
            if revision is None:
                raise CanonicalMappingCoverageError(
                    code="CATALOG_NOT_PUBLISHED",
                    source_site=source_site,
                )

            catalog = DiscoveredCatalog.from_payloads(
                normalized_payload=revision.normalized_payload,
                source_payload=revision.source_payload,
                provenance=revision.provenance,
            )
            validate_catalog(catalog)
            if catalog.fingerprint != revision.fingerprint:
                raise CanonicalMappingCoverageError(
                    code="CATALOG_FINGERPRINT_MISMATCH",
                    source_site=source_site,
                )
            catalog_ids = {
                node.classification_id
                for node in catalog.nodes
                if node.classification_id is not None
            }
            missing = tuple(sorted(catalog_ids - declared_ids))
            extra = tuple(sorted(declared_ids - catalog_ids))
            if missing or extra:
                raise CanonicalMappingCoverageError(
                    code="CANONICAL_MAPPING_COVERAGE_MISMATCH",
                    source_site=source_site,
                    missing=missing,
                    extra=extra,
                )
            ordered_ids = sorted(catalog_ids)
            coverages.append(
                {
                    "source_site": source_site,
                    "source_catalog_revision_id": str(revision.id),
                    "source_catalog_sequence": revision.sequence,
                    "source_catalog_fingerprint": revision.fingerprint,
                    "identity_set_hash": normalized_content_hash(ordered_ids),
                    "identity_count": len(ordered_ids),
                }
            )
        return coverages

    def _materialize_mapping_rows(
        self,
        *,
        taxonomy_revision: RevisionRef,
        mapping_revision: RevisionRef,
        mapping_seed: Mapping[str, Any],
        coverage_payloads: list[dict[str, Any]],
    ) -> None:
        assert self.db is not None
        coverage_ids: dict[str, uuid.UUID] = {}
        for coverage_payload in coverage_payloads:
            source_site = coverage_payload["source_site"]
            coverage_id = _node_uuid(
                mapping_revision.revision_id,
                "coverage",
                source_site,
            )
            coverage_ids[source_site] = coverage_id
            self._add_mapping_row_if_missing(
                CanonicalJobTaxonomyMappingCoverage,
                coverage_id,
                mapping_revision_id=mapping_revision.revision_id,
                source_site=source_site,
                source_catalog_revision_id=uuid.UUID(
                    coverage_payload["source_catalog_revision_id"]
                ),
                source_catalog_sequence=coverage_payload["source_catalog_sequence"],
                source_catalog_fingerprint=coverage_payload[
                    "source_catalog_fingerprint"
                ],
                identity_set_hash=coverage_payload["identity_set_hash"],
                identity_count=coverage_payload["identity_count"],
            )
        self.db.flush()

        mapping_ids: dict[str, uuid.UUID] = {}
        for source_order, entry in enumerate(mapping_seed["entries"], start=1):
            source_id = entry["source_classification_id"]
            mapping_id = _node_uuid(
                mapping_revision.revision_id,
                "mapping",
                source_id,
            )
            mapping_ids[source_id] = mapping_id
            self._add_mapping_row_if_missing(
                SourceJobTaxonomyMapping,
                mapping_id,
                mapping_revision_id=mapping_revision.revision_id,
                coverage_id=coverage_ids[entry["source_site"]],
                source_site=entry["source_site"],
                source_classification_id=source_id,
                source_label=entry["source_label"],
                disposition=entry["disposition"],
                source_order=source_order,
                review_evidence=dict(entry.get("review_evidence") or {}),
            )
        self.db.flush()

        subcategories = {
            row.code: row
            for row in self.db.query(CanonicalJobSubcategory)
            .filter(
                CanonicalJobSubcategory.revision_id == taxonomy_revision.revision_id
            )
            .all()
        }
        for entry in mapping_seed["entries"]:
            source_id = entry["source_classification_id"]
            mapping_id = mapping_ids[source_id]
            role = (
                "deterministic"
                if entry["disposition"] == "deterministic"
                else "allowed"
            )
            for target_order, target_code in enumerate(
                entry["target_codes"],
                start=1,
            ):
                subcategory = subcategories.get(target_code)
                if subcategory is None or subcategory.is_assignable is not True:
                    raise RuntimeError(
                        f"Canonical mapping target {target_code!r} is not assignable"
                    )
                target_id = _node_uuid(
                    mapping_revision.revision_id,
                    "target",
                    f"{source_id}:{target_code}",
                )
                self._add_mapping_row_if_missing(
                    SourceJobTaxonomyMappingTarget,
                    target_id,
                    mapping_id=mapping_id,
                    mapping_revision_id=mapping_revision.revision_id,
                    taxonomy_revision_id=taxonomy_revision.revision_id,
                    subcategory_id=subcategory.id,
                    role=role,
                    source_order=target_order,
                )

    def _add_mapping_row_if_missing(
        self,
        model: Any,
        row_id: uuid.UUID,
        **values: Any,
    ) -> None:
        assert self.db is not None
        existing = self.db.get(model, row_id)
        if existing is None:
            self.db.add(model(id=row_id, **values))
            return
        for field_name, expected_value in values.items():
            if getattr(existing, field_name) != expected_value:
                raise RuntimeError(
                    f"Canonical mapping retry found mismatched {model.__name__} "
                    f"field {field_name}"
                )

    def _mapping_release_counts(
        self,
        revision_id: uuid.UUID,
    ) -> tuple[int, int, int]:
        assert self.db is not None
        return (
            self.db.query(CanonicalJobTaxonomyMappingCoverage)
            .filter(
                CanonicalJobTaxonomyMappingCoverage.mapping_revision_id == revision_id
            )
            .count(),
            self.db.query(SourceJobTaxonomyMapping)
            .filter(SourceJobTaxonomyMapping.mapping_revision_id == revision_id)
            .count(),
            self.db.query(SourceJobTaxonomyMappingTarget)
            .filter(SourceJobTaxonomyMappingTarget.mapping_revision_id == revision_id)
            .count(),
        )

    @staticmethod
    def _require_mapping_revision_identity(
        mapping_release: CanonicalJobTaxonomyMappingRevision,
        revision: RevisionRef,
        taxonomy_revision: RevisionRef,
        expected_counts: tuple[int, int, int],
    ) -> None:
        identity = (
            mapping_release.content_hash,
            mapping_release.taxonomy_revision_id,
            mapping_release.expected_coverage_count,
            mapping_release.expected_entry_count,
            mapping_release.expected_target_count,
        )
        expected_identity = (
            revision.content_hash,
            taxonomy_revision.revision_id,
            *expected_counts,
        )
        if identity != expected_identity:
            raise RuntimeError("Canonical mapping release identity mismatch")

    def _materialize_nodes(
        self,
        seed: Mapping[str, Any],
        revision: RevisionRef,
    ) -> None:
        assert self.db is not None
        domain_ids: dict[str, uuid.UUID] = {}
        for domain in seed["domains"]:
            domain_id = _node_uuid(revision.revision_id, "domain", domain["code"])
            domain_ids[domain["code"]] = domain_id
            self._add_node_if_missing(
                CanonicalJobDomain,
                domain_id,
                revision_id=revision.revision_id,
                code=domain["code"],
                label=domain["label"],
                source_order=domain["order"],
            )
        self.db.flush()

        category_ids: dict[str, uuid.UUID] = {}
        for domain in seed["domains"]:
            domain_id = domain_ids[domain["code"]]
            for category in domain["categories"]:
                category_id = _node_uuid(
                    revision.revision_id,
                    "category",
                    category["code"],
                )
                category_ids[category["code"]] = category_id
                self._add_node_if_missing(
                    CanonicalJobCategory,
                    category_id,
                    revision_id=revision.revision_id,
                    domain_id=domain_id,
                    code=category["code"],
                    label=category["label"],
                    source_order=category["order"],
                )
        self.db.flush()

        for domain in seed["domains"]:
            for category in domain["categories"]:
                category_id = category_ids[category["code"]]
                for subcategory in category["subcategories"]:
                    subcategory_id = _node_uuid(
                        revision.revision_id,
                        "subcategory",
                        subcategory["code"],
                    )
                    self._add_node_if_missing(
                        CanonicalJobSubcategory,
                        subcategory_id,
                        revision_id=revision.revision_id,
                        category_id=category_id,
                        code=subcategory["code"],
                        label=subcategory["label"],
                        source_order=subcategory["order"],
                        is_assignable=subcategory["is_assignable"],
                    )

    def _add_node_if_missing(
        self, model: Any, node_id: uuid.UUID, **values: Any
    ) -> None:
        assert self.db is not None
        existing = self.db.get(model, node_id)
        if existing is None:
            self.db.add(model(id=node_id, **values))
            return

        for field_name, expected_value in values.items():
            if getattr(existing, field_name) != expected_value:
                raise RuntimeError(
                    f"Canonical taxonomy retry found mismatched {model.__name__} "
                    f"field {field_name}"
                )

    def _release_counts(self, revision_id: uuid.UUID) -> tuple[int, int, int]:
        assert self.db is not None
        return (
            self.db.query(CanonicalJobDomain)
            .filter(CanonicalJobDomain.revision_id == revision_id)
            .count(),
            self.db.query(CanonicalJobCategory)
            .filter(CanonicalJobCategory.revision_id == revision_id)
            .count(),
            self.db.query(CanonicalJobSubcategory)
            .filter(CanonicalJobSubcategory.revision_id == revision_id)
            .count(),
        )

    @staticmethod
    def _require_release_identity(
        release: CanonicalJobTaxonomyRelease,
        revision: RevisionRef,
        expected_counts: Mapping[str, Any],
    ) -> None:
        identity = (
            release.content_hash,
            release.expected_domain_count,
            release.expected_category_count,
            release.expected_subcategory_count,
        )
        expected_identity = (
            revision.content_hash,
            expected_counts["domains"],
            expected_counts["categories"],
            expected_counts["subcategories"],
        )
        if identity != expected_identity:
            raise RuntimeError("Canonical taxonomy release identity mismatch")


def _validate_taxonomy_seed(document: Mapping[str, Any]) -> Iterable[SeedIssue]:
    issues: list[SeedIssue] = []
    if document.get("schema_version") != 1:
        issues.append(
            SeedIssue(
                json_path="$.schema_version",
                code="canonical_taxonomy_schema_version_invalid",
                message="Canonical taxonomy schema_version must be 1",
            )
        )

    release_key = document.get("release_key")
    if not isinstance(release_key, str) or not release_key.strip():
        issues.append(
            SeedIssue(
                json_path="$.release_key",
                code="canonical_taxonomy_release_key_invalid",
                message="Canonical taxonomy release_key is required",
            )
        )

    domains = document.get("domains")
    if not isinstance(domains, list):
        issues.append(
            SeedIssue(
                json_path="$.domains",
                code="canonical_taxonomy_domains_invalid",
                message="Canonical taxonomy domains must be an array",
            )
        )
        return issues

    counts = {"domains": 0, "categories": 0, "subcategories": 0}
    seen_codes: dict[str, str] = {}
    domain_labels: dict[str, str] = {}
    counts["domains"] = len(domains)

    for domain_index, domain in enumerate(domains):
        domain_path = f"$.domains[{domain_index}]"
        if not isinstance(domain, Mapping):
            issues.append(_node_type_issue(domain_path, "Domain"))
            continue

        _validate_node(
            domain,
            path=domain_path,
            kind="Domain",
            expected_order=domain_index + 1,
            seen_codes=seen_codes,
            sibling_labels=domain_labels,
            issues=issues,
        )
        categories = domain.get("categories")
        if not isinstance(categories, list):
            issues.append(
                SeedIssue(
                    json_path=f"{domain_path}.categories",
                    code="canonical_taxonomy_categories_invalid",
                    message="Canonical taxonomy categories must be an array",
                    related_id=_related_code(domain),
                )
            )
            continue

        counts["categories"] += len(categories)
        category_labels: dict[str, str] = {}
        for category_index, category in enumerate(categories):
            category_path = f"{domain_path}.categories[{category_index}]"
            if not isinstance(category, Mapping):
                issues.append(_node_type_issue(category_path, "Category"))
                continue

            _validate_node(
                category,
                path=category_path,
                kind="Category",
                expected_order=category_index + 1,
                seen_codes=seen_codes,
                sibling_labels=category_labels,
                issues=issues,
            )
            subcategories = category.get("subcategories")
            if not isinstance(subcategories, list):
                issues.append(
                    SeedIssue(
                        json_path=f"{category_path}.subcategories",
                        code="canonical_taxonomy_subcategories_invalid",
                        message="Canonical taxonomy subcategories must be an array",
                        related_id=_related_code(category),
                    )
                )
                continue

            counts["subcategories"] += len(subcategories)
            subcategory_labels: dict[str, str] = {}
            for subcategory_index, subcategory in enumerate(subcategories):
                subcategory_path = f"{category_path}.subcategories[{subcategory_index}]"
                if not isinstance(subcategory, Mapping):
                    issues.append(_node_type_issue(subcategory_path, "Subcategory"))
                    continue

                _validate_node(
                    subcategory,
                    path=subcategory_path,
                    kind="Subcategory",
                    expected_order=subcategory_index + 1,
                    seen_codes=seen_codes,
                    sibling_labels=subcategory_labels,
                    issues=issues,
                )
                if not isinstance(subcategory.get("is_assignable"), bool):
                    issues.append(
                        SeedIssue(
                            json_path=f"{subcategory_path}.is_assignable",
                            code="canonical_taxonomy_assignability_invalid",
                            message="Subcategory is_assignable must be boolean",
                            related_id=_related_code(subcategory),
                        )
                    )

    expected_counts = document.get("expected_counts")
    if not isinstance(expected_counts, Mapping):
        issues.append(
            SeedIssue(
                json_path="$.expected_counts",
                code="canonical_taxonomy_expected_counts_invalid",
                message="Canonical taxonomy expected_counts must be an object",
            )
        )
        return issues

    for count_name, actual_count in counts.items():
        expected_count = expected_counts.get(count_name)
        count_path = f"$.expected_counts.{count_name}"
        if (
            not isinstance(expected_count, int)
            or isinstance(expected_count, bool)
            or expected_count < 0
        ):
            issues.append(
                SeedIssue(
                    json_path=count_path,
                    code="canonical_taxonomy_expected_count_invalid",
                    message=f"Expected {count_name} count must be a non-negative integer",
                )
            )
        elif expected_count != actual_count:
            issues.append(
                SeedIssue(
                    json_path=count_path,
                    code="canonical_taxonomy_count_mismatch",
                    message=(
                        f"Expected {expected_count} {count_name}, found {actual_count}"
                    ),
                )
            )

    return issues


def _validate_node(
    node: Mapping[str, Any],
    *,
    path: str,
    kind: str,
    expected_order: int,
    seen_codes: dict[str, str],
    sibling_labels: dict[str, str],
    issues: list[SeedIssue],
) -> None:
    raw_code = node.get("code")
    code = raw_code if isinstance(raw_code, str) else ""
    if not _CODE_PATTERN.fullmatch(code):
        issues.append(
            SeedIssue(
                json_path=f"{path}.code",
                code="canonical_taxonomy_code_invalid",
                message=(f"{kind} code must use lowercase stable-code characters"),
                related_id=code or None,
            )
        )
    elif code in seen_codes:
        issues.append(
            SeedIssue(
                json_path=f"{path}.code",
                code="canonical_taxonomy_code_duplicate",
                message=f"{kind} code duplicates {seen_codes[code]}",
                related_id=code,
            )
        )
    else:
        seen_codes[code] = path

    raw_label = node.get("label")
    label = raw_label if isinstance(raw_label, str) else ""
    if not label.strip():
        issues.append(
            SeedIssue(
                json_path=f"{path}.label",
                code="canonical_taxonomy_label_invalid",
                message=f"{kind} label is required",
                related_id=code or None,
            )
        )
    elif label in _FORBIDDEN_FALLBACK_LABELS:
        issues.append(
            SeedIssue(
                json_path=f"{path}.label",
                code="canonical_taxonomy_fallback_forbidden",
                message=f"{kind} label {label!r} is a forbidden fallback",
                related_id=code or None,
            )
        )
    elif label in sibling_labels:
        issues.append(
            SeedIssue(
                json_path=f"{path}.label",
                code="canonical_taxonomy_sibling_label_duplicate",
                message=f"{kind} label duplicates {sibling_labels[label]}",
                related_id=code or None,
            )
        )
    else:
        sibling_labels[label] = path

    node_order = node.get("order")
    if (
        not isinstance(node_order, int)
        or isinstance(node_order, bool)
        or node_order != expected_order
    ):
        issues.append(
            SeedIssue(
                json_path=f"{path}.order",
                code="canonical_taxonomy_order_invalid",
                message=f"{kind} order must be {expected_order}",
                related_id=code or None,
            )
        )


def _node_type_issue(path: str, kind: str) -> SeedIssue:
    return SeedIssue(
        json_path=path,
        code="canonical_taxonomy_node_invalid",
        message=f"{kind} must be an object",
    )


def _related_code(node: Mapping[str, Any]) -> str | None:
    value = node.get("code")
    return value if isinstance(value, str) and value else None


def _node_uuid(revision_id: uuid.UUID, kind: str, code: str) -> uuid.UUID:
    return uuid.uuid5(revision_id, f"{kind}:{code}")


def _validate_mapping_seed(
    document: Mapping[str, Any],
    *,
    taxonomy_seed: Mapping[str, Any],
) -> Iterable[SeedIssue]:
    issues: list[SeedIssue] = []
    if document.get("schema_version") != 1:
        issues.append(
            SeedIssue(
                json_path="$.schema_version",
                code="canonical_mapping_schema_version_invalid",
                message="Canonical mapping schema_version must be 1",
            )
        )

    release_key = document.get("release_key")
    if not isinstance(release_key, str) or not release_key.strip():
        issues.append(
            SeedIssue(
                json_path="$.release_key",
                code="canonical_mapping_release_key_invalid",
                message="Canonical mapping release_key is required",
            )
        )

    taxonomy_release_key = taxonomy_seed.get("release_key")
    if document.get("taxonomy_release_key") != taxonomy_release_key:
        issues.append(
            SeedIssue(
                json_path="$.taxonomy_release_key",
                code="canonical_mapping_taxonomy_release_mismatch",
                message="Mapping taxonomy_release_key must match the taxonomy seed",
            )
        )

    leaf_order: dict[str, int] = {}
    assignable_codes: set[str] = set()
    domains = taxonomy_seed.get("domains")
    if isinstance(domains, list):
        for domain in domains:
            if not isinstance(domain, Mapping):
                continue
            categories = domain.get("categories")
            if not isinstance(categories, list):
                continue
            for category in categories:
                if not isinstance(category, Mapping):
                    continue
                subcategories = category.get("subcategories")
                if not isinstance(subcategories, list):
                    continue
                for subcategory in subcategories:
                    if not isinstance(subcategory, Mapping):
                        continue
                    code = subcategory.get("code")
                    if isinstance(code, str) and code not in leaf_order:
                        leaf_order[code] = len(leaf_order)
                        if subcategory.get("is_assignable") is True:
                            assignable_codes.add(code)

    entries = document.get("entries")
    if not isinstance(entries, list):
        issues.append(
            SeedIssue(
                json_path="$.entries",
                code="canonical_mapping_entries_invalid",
                message="Canonical mapping entries must be an array",
            )
        )
        return issues

    disposition_counts: Counter[str] = Counter()
    source_ids: dict[str, str] = {}
    ordered_source_ids: list[str] = []
    for entry_index, entry in enumerate(entries):
        entry_path = f"$.entries[{entry_index}]"
        if not isinstance(entry, Mapping):
            issues.append(_node_type_issue(entry_path, "Mapping entry"))
            continue

        source_site_value = entry.get("source_site")
        source_site = source_site_value if isinstance(source_site_value, str) else ""
        source_id_value = entry.get("source_classification_id")
        source_id = source_id_value if isinstance(source_id_value, str) else ""
        if not source_site or not _CODE_PATTERN.fullmatch(source_site):
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.source_site",
                    code="canonical_mapping_source_invalid",
                    message="Mapping source_site must be a stable lowercase code",
                    related_id=source_id or None,
                )
            )
        if (
            not source_id.startswith(f"{source_site}:")
            or source_id == f"{source_site}:"
        ):
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.source_classification_id",
                    code="canonical_mapping_source_identity_invalid",
                    message="Mapping identity must be source-qualified",
                    related_id=source_id or None,
                )
            )
        elif source_id in source_ids:
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.source_classification_id",
                    code="canonical_mapping_source_identity_duplicate",
                    message=f"Mapping identity duplicates {source_ids[source_id]}",
                    related_id=source_id,
                )
            )
        else:
            source_ids[source_id] = entry_path
            ordered_source_ids.append(source_id)

        source_label = entry.get("source_label")
        if not isinstance(source_label, str) or not source_label.strip():
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.source_label",
                    code="canonical_mapping_source_label_invalid",
                    message="Mapping source_label is required as review evidence",
                    related_id=source_id or None,
                )
            )

        disposition_value = entry.get("disposition")
        disposition = disposition_value if isinstance(disposition_value, str) else ""
        if disposition not in _MAPPING_DISPOSITIONS:
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.disposition",
                    code="canonical_mapping_disposition_invalid",
                    message="Mapping disposition is not supported",
                    related_id=source_id or None,
                )
            )
        else:
            disposition_counts[disposition] += 1

        target_codes_value = entry.get("target_codes")
        if not isinstance(target_codes_value, list) or not all(
            isinstance(code, str) for code in target_codes_value
        ):
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.target_codes",
                    code="canonical_mapping_targets_invalid",
                    message="Mapping target_codes must be an array of stable codes",
                    related_id=source_id or None,
                )
            )
            continue

        target_codes = list(target_codes_value)
        required_count = 1 if disposition == "deterministic" else None
        if required_count is not None and len(target_codes) != required_count:
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.target_codes",
                    code="canonical_mapping_target_cardinality_invalid",
                    message="Deterministic mappings require exactly one target",
                    related_id=source_id or None,
                )
            )
        elif disposition == "allowed_slice" and not target_codes:
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.target_codes",
                    code="canonical_mapping_target_cardinality_invalid",
                    message="Allowed-slice mappings require at least one target",
                    related_id=source_id or None,
                )
            )
        elif disposition in {"excluded", "unmapped"} and target_codes:
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.target_codes",
                    code="canonical_mapping_target_cardinality_invalid",
                    message=f"{disposition} mappings cannot have targets",
                    related_id=source_id or None,
                )
            )

        if len(target_codes) != len(set(target_codes)):
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.target_codes",
                    code="canonical_mapping_target_duplicate",
                    message="Mapping targets must be unique",
                    related_id=source_id or None,
                )
            )

        known_positions: list[int] = []
        for target_index, target_code in enumerate(target_codes):
            if target_code not in assignable_codes:
                issues.append(
                    SeedIssue(
                        json_path=f"{entry_path}.target_codes[{target_index}]",
                        code="canonical_mapping_target_invalid",
                        message="Mapping target must be an assignable taxonomy leaf",
                        related_id=target_code,
                    )
                )
            elif target_code in leaf_order:
                known_positions.append(leaf_order[target_code])
        if known_positions != sorted(known_positions):
            issues.append(
                SeedIssue(
                    json_path=f"{entry_path}.target_codes",
                    code="canonical_mapping_target_order_invalid",
                    message="Mapping targets must follow canonical taxonomy order",
                    related_id=source_id or None,
                )
            )

    if ordered_source_ids != sorted(ordered_source_ids):
        issues.append(
            SeedIssue(
                json_path="$.entries",
                code="canonical_mapping_entry_order_invalid",
                message="Mapping entries must sort by source-qualified identity",
            )
        )

    actual_counts = {"entries": len(entries)}
    actual_counts.update(
        {
            disposition: disposition_counts[disposition]
            for disposition in sorted(_MAPPING_DISPOSITIONS)
        }
    )
    expected_counts = document.get("expected_counts")
    if not isinstance(expected_counts, Mapping):
        issues.append(
            SeedIssue(
                json_path="$.expected_counts",
                code="canonical_mapping_expected_counts_invalid",
                message="Canonical mapping expected_counts must be an object",
            )
        )
    else:
        for count_name, actual_count in actual_counts.items():
            expected_count = expected_counts.get(count_name)
            count_path = f"$.expected_counts.{count_name}"
            if (
                not isinstance(expected_count, int)
                or isinstance(expected_count, bool)
                or expected_count < 0
            ):
                issues.append(
                    SeedIssue(
                        json_path=count_path,
                        code="canonical_mapping_expected_count_invalid",
                        message=f"Expected {count_name} count must be a non-negative integer",
                    )
                )
            elif expected_count != actual_count:
                issues.append(
                    SeedIssue(
                        json_path=count_path,
                        code="canonical_mapping_count_mismatch",
                        message=(
                            f"Expected {expected_count} {count_name}, found {actual_count}"
                        ),
                    )
                )

    discrepancies = document.get("legacy_discrepancies")
    proposal_only_ids = (
        discrepancies.get("ctgoodjobs_proposal_only_ids")
        if isinstance(discrepancies, Mapping)
        else None
    )
    discrepancy_path = "$.legacy_discrepancies.ctgoodjobs_proposal_only_ids"
    if not isinstance(proposal_only_ids, list) or not all(
        isinstance(source_id, str) and source_id.startswith("ctgoodjobs:")
        for source_id in proposal_only_ids
    ):
        issues.append(
            SeedIssue(
                json_path=discrepancy_path,
                code="canonical_mapping_legacy_discrepancy_invalid",
                message="CTgoodjobs legacy discrepancy IDs must be source-qualified",
            )
        )
    elif proposal_only_ids != sorted(set(proposal_only_ids)):
        issues.append(
            SeedIssue(
                json_path=discrepancy_path,
                code="canonical_mapping_legacy_discrepancy_invalid",
                message="CTgoodjobs legacy discrepancy IDs must be unique and sorted",
            )
        )
    elif proposal_only_ids:
        issues.append(
            SeedIssue(
                json_path=discrepancy_path,
                code="canonical_mapping_legacy_discrepancy",
                message=(
                    f"{len(proposal_only_ids)} CTgoodjobs IDs exist only in legacy "
                    "proposed-domain metadata"
                ),
                severity="warning",
            )
        )

    return issues
