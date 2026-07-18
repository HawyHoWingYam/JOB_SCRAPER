from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any
from uuid import UUID
from datetime import datetime

from app.job_intelligence.foundation import Provenance, RevisionRef


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Source Job Attribute field {field_name} must be an object")
    return value


def _sequence(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"Source Job Attribute field {field_name} must be an array")
    return value


def _provenance_from_payload(value: Any) -> Provenance:
    payload = _mapping(value, "provenance")
    source_revision_payload = payload.get("source_revision")
    source_revision = None
    if source_revision_payload is not None:
        revision = _mapping(source_revision_payload, "provenance.source_revision")
        source_revision = RevisionRef(
            domain=str(revision["domain"]),
            revision_id=UUID(str(revision["revision_id"])),
            release_key=str(revision["release_key"]),
            content_hash=str(revision["content_hash"]),
        )
    captured_at = datetime.fromisoformat(str(payload["captured_at"]))
    return Provenance(
        method=str(payload["method"]),
        source_site=(
            str(payload["source_site"])
            if payload.get("source_site") is not None
            else None
        ),
        source_revision=source_revision,
        mapping_id=(
            str(payload["mapping_id"])
            if payload.get("mapping_id") is not None
            else None
        ),
        evidence_refs=tuple(
            _mapping(item, "provenance.evidence_refs[]")
            for item in _sequence(
                payload.get("evidence_refs"), "provenance.evidence_refs"
            )
        ),
        model_provider=(
            str(payload["model_provider"])
            if payload.get("model_provider") is not None
            else None
        ),
        model_name=(
            str(payload["model_name"])
            if payload.get("model_name") is not None
            else None
        ),
        model_version=(
            str(payload["model_version"])
            if payload.get("model_version") is not None
            else None
        ),
        captured_at=captured_at,
    )


@dataclass(frozen=True)
class SourceCatalogRevisionRef:
    source_site: str
    revision_id: UUID
    fingerprint: str

    def to_payload(self) -> dict[str, str]:
        return {
            "source_site": self.source_site,
            "revision_id": str(self.revision_id),
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_payload(cls, value: Any) -> SourceCatalogRevisionRef:
        payload = _mapping(value, "source_catalog_revision")
        return cls(
            source_site=str(payload["source_site"]),
            revision_id=UUID(str(payload["revision_id"])),
            fingerprint=str(payload["fingerprint"]),
        )


@dataclass(frozen=True)
class SourceClassificationContext:
    source_classification_id: str
    label: str
    source_catalog_revision: SourceCatalogRevisionRef | None
    provenance: Provenance


@dataclass(frozen=True)
class SourceClassificationNodeEvidence:
    source_position: int
    native_depth: int
    source_classification_id: str
    native_id: str
    label: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_position": self.source_position,
            "native_depth": self.native_depth,
            "source_classification_id": self.source_classification_id,
            "native_id": self.native_id,
            "label": self.label,
        }

    @classmethod
    def from_payload(cls, value: Any) -> SourceClassificationNodeEvidence:
        payload = _mapping(value, "classification_paths[].nodes[]")
        return cls(
            source_position=int(payload["source_position"]),
            native_depth=int(payload["native_depth"]),
            source_classification_id=str(payload["source_classification_id"]),
            native_id=str(payload["native_id"]),
            label=str(payload["label"]),
        )


@dataclass(frozen=True)
class SourceClassificationPathEvidence:
    source_order: int
    nodes: tuple[SourceClassificationNodeEvidence, ...]
    source_declared_primary: bool
    primary_basis: str | None
    source_catalog_revision: SourceCatalogRevisionRef | None
    provenance: Provenance

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_order": self.source_order,
            "nodes": [node.to_payload() for node in self.nodes],
            "source_declared_primary": self.source_declared_primary,
            "primary_basis": self.primary_basis,
            "source_catalog_revision": (
                self.source_catalog_revision.to_payload()
                if self.source_catalog_revision is not None
                else None
            ),
            "provenance": self.provenance.to_payload(),
        }

    @classmethod
    def from_payload(cls, value: Any) -> SourceClassificationPathEvidence:
        payload = _mapping(value, "classification_paths[]")
        revision_payload = payload.get("source_catalog_revision")
        return cls(
            source_order=int(payload["source_order"]),
            nodes=tuple(
                SourceClassificationNodeEvidence.from_payload(item)
                for item in _sequence(
                    payload.get("nodes"), "classification_paths[].nodes"
                )
            ),
            source_declared_primary=bool(payload["source_declared_primary"]),
            primary_basis=(
                str(payload["primary_basis"])
                if payload.get("primary_basis") is not None
                else None
            ),
            source_catalog_revision=(
                SourceCatalogRevisionRef.from_payload(revision_payload)
                if revision_payload is not None
                else None
            ),
            provenance=_provenance_from_payload(payload.get("provenance")),
        )


@dataclass(frozen=True)
class SourceEmploymentLabelEvidence:
    source_order: int
    raw_code: str | None
    raw_label: str | None
    normalized_lookup_key: str | None
    mapped_type_code: str | None
    mapping_id: str | None
    provenance: Provenance

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_order": self.source_order,
            "raw_code": self.raw_code,
            "raw_label": self.raw_label,
            "normalized_lookup_key": self.normalized_lookup_key,
            "mapped_type_code": self.mapped_type_code,
            "mapping_id": self.mapping_id,
            "provenance": self.provenance.to_payload(),
        }

    @classmethod
    def from_payload(cls, value: Any) -> SourceEmploymentLabelEvidence:
        payload = _mapping(value, "employment_labels[]")
        return cls(
            source_order=int(payload["source_order"]),
            raw_code=(
                str(payload["raw_code"])
                if payload.get("raw_code") is not None
                else None
            ),
            raw_label=(
                str(payload["raw_label"])
                if payload.get("raw_label") is not None
                else None
            ),
            normalized_lookup_key=(
                str(payload["normalized_lookup_key"])
                if payload.get("normalized_lookup_key") is not None
                else None
            ),
            mapped_type_code=(
                str(payload["mapped_type_code"])
                if payload.get("mapped_type_code") is not None
                else None
            ),
            mapping_id=(
                str(payload["mapping_id"])
                if payload.get("mapping_id") is not None
                else None
            ),
            provenance=_provenance_from_payload(payload.get("provenance")),
        )


@dataclass(frozen=True)
class SourceJobAttributeEvidence:
    source_site: str
    classification_paths: tuple[SourceClassificationPathEvidence, ...]
    employment_labels: tuple[SourceEmploymentLabelEvidence, ...]
    work_arrangements: tuple[str, ...] = ()
    working_day_labels: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_site": self.source_site,
            "classification_paths": [
                path.to_payload() for path in self.classification_paths
            ],
            "employment_labels": [
                label.to_payload() for label in self.employment_labels
            ],
            "work_arrangements": list(self.work_arrangements),
            "working_day_labels": list(self.working_day_labels),
        }

    @classmethod
    def from_payload(cls, value: Any) -> SourceJobAttributeEvidence:
        payload = _mapping(value, "source_attribute_evidence")
        return cls(
            source_site=str(payload["source_site"]),
            classification_paths=tuple(
                SourceClassificationPathEvidence.from_payload(item)
                for item in _sequence(
                    payload.get("classification_paths"),
                    "classification_paths",
                )
            ),
            employment_labels=tuple(
                SourceEmploymentLabelEvidence.from_payload(item)
                for item in _sequence(
                    payload.get("employment_labels"),
                    "employment_labels",
                )
            ),
            work_arrangements=tuple(
                str(item)
                for item in _sequence(
                    payload.get("work_arrangements"),
                    "work_arrangements",
                )
            ),
            working_day_labels=tuple(
                str(item)
                for item in _sequence(
                    payload.get("working_day_labels"),
                    "working_day_labels",
                )
            ),
        )


@dataclass(frozen=True)
class SourceClassificationNodeView:
    source_position: int
    native_depth: int
    source_classification_id: str
    native_id: str
    label: str


@dataclass(frozen=True)
class SourceClassificationPathView:
    id: UUID
    source_order: int
    nodes: tuple[SourceClassificationNodeView, ...]
    is_primary: bool
    primary_basis: str | None
    source_catalog_revision: SourceCatalogRevisionRef | None
    provenance_limited: bool
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class SourceEmploymentLabelView:
    id: UUID
    source_order: int
    raw_code: str | None
    raw_label: str | None
    normalized_lookup_key: str | None
    mapped_type_code: str | None
    mapping_id: str | None
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class EmploymentTypeView:
    code: str
    label: str
    sort_order: int


@dataclass(frozen=True)
class SourceJobAttributesView:
    job_id: UUID
    source_site: str
    version: int
    evidence_hash: str
    source_classification_paths: tuple[SourceClassificationPathView, ...]
    employment_types: tuple[EmploymentTypeView, ...]
    source_employment_labels: tuple[SourceEmploymentLabelView, ...]


@dataclass(frozen=True)
class ProjectionResult:
    changed: bool
    version: int
    view: SourceJobAttributesView
