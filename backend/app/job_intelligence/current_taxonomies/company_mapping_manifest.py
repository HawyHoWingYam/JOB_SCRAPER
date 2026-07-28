from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import cast
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.current_taxonomy import (
    CurrentSourceTaxonomyMapping,
    CurrentTaxonomyNodeRecord,
)
from app.models.job import Job


TAXONOMY = "company_industry"
SUPPORTED_SOURCE_SITES = frozenset({"jobsdb", "offertoday", "ctgoodjobs"})
DEFAULT_COMPANY_INDUSTRY_MAPPING_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "company_industry_source_mappings.json"
)
_MANAGED_BY = "company_industry_source_mapping_manifest"


class CompanyIndustryMappingManifestError(ValueError):
    """The governed Company Industry Source Mapping state is invalid."""


def normalize_source_industry_label(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFC", " ".join(value.split())).casefold()


def company_industry_source_key(value: object) -> str:
    normalized = normalize_source_industry_label(value)
    return f"label:{normalized}" if normalized else ""


def extract_source_industry_label(raw_data: object) -> str | None:
    if not isinstance(raw_data, Mapping):
        return None
    industry = raw_data.get("industry")
    label = industry.get("name") if isinstance(industry, Mapping) else None
    if not isinstance(label, str) or not label.strip():
        label = raw_data.get("company_industry")
    if not isinstance(label, str) or not label.strip():
        return None
    return unicodedata.normalize("NFC", " ".join(label.split()))


@dataclass(frozen=True)
class CompanyIndustryMappingDisposition:
    source_label: str
    source_key: str
    disposition: str
    target_codes: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class CompanyIndustrySourceManifest:
    source_site: str
    entries: tuple[CompanyIndustryMappingDisposition, ...]

    def by_source_key(self) -> dict[str, CompanyIndustryMappingDisposition]:
        return {entry.source_key: entry for entry in self.entries}


@dataclass(frozen=True)
class CompanyIndustryMappingManifest:
    sources: tuple[CompanyIndustrySourceManifest, ...]

    def source(self, source_site: str) -> CompanyIndustrySourceManifest | None:
        normalized = str(source_site or "").strip().lower()
        return next(
            (source for source in self.sources if source.source_site == normalized),
            None,
        )


@dataclass(frozen=True)
class CompanyIndustryMappingResolution:
    kind: str
    source_site: str
    source_label: str | None
    source_key: str | None
    target_codes: tuple[str, ...] = ()
    reason: str | None = None


@dataclass(frozen=True)
class _DesiredMapping:
    source_key: str
    source_label: str
    target_code: str
    role: str
    evidence: dict[str, object]


@dataclass(frozen=True)
class CompanyIndustrySourceSyncPlan:
    source_site: str
    created: int
    updated: int
    removed: int
    unchanged: int
    mapped_dispositions: int
    non_mapping_dispositions: int
    desired: tuple[_DesiredMapping, ...] = field(repr=False)

    def to_payload(self) -> dict[str, object]:
        return {
            "source_site": self.source_site,
            "created": self.created,
            "updated": self.updated,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "mapped_dispositions": self.mapped_dispositions,
            "non_mapping_dispositions": self.non_mapping_dispositions,
        }


@dataclass(frozen=True)
class CompanyIndustryMappingSyncPlan:
    sources: tuple[CompanyIndustrySourceSyncPlan, ...]

    def to_payload(self) -> dict[str, object]:
        return {"taxonomy": TAXONOMY, "sources": [item.to_payload() for item in self.sources]}


def load_company_industry_mapping_manifest(
    path: Path | str = DEFAULT_COMPANY_INDUSTRY_MAPPING_MANIFEST,
) -> CompanyIndustryMappingManifest:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompanyIndustryMappingManifestError(
            f"Cannot load Company Industry mapping manifest: {exc}"
        ) from exc
    if not isinstance(payload, Mapping) or payload.get("taxonomy") != TAXONOMY:
        raise CompanyIndustryMappingManifestError(
            "Manifest taxonomy must be 'company_industry'"
        )
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise CompanyIndustryMappingManifestError("Manifest sources must be a non-empty list")

    sources: list[CompanyIndustrySourceManifest] = []
    seen_sources: set[str] = set()
    for raw_source in raw_sources:
        if not isinstance(raw_source, Mapping):
            raise CompanyIndustryMappingManifestError("Each manifest Source must be an object")
        source_site = str(raw_source.get("source_site") or "").strip().lower()
        if source_site not in SUPPORTED_SOURCE_SITES:
            raise CompanyIndustryMappingManifestError(
                f"Unsupported Source identity '{source_site or '<empty>'}'"
            )
        if source_site in seen_sources:
            raise CompanyIndustryMappingManifestError(
                f"Manifest contains duplicate Source '{source_site}'"
            )
        seen_sources.add(source_site)
        raw_entries = raw_source.get("entries")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise CompanyIndustryMappingManifestError(
                f"Manifest Source '{source_site}' entries must be a non-empty list"
            )
        entries = _parse_entries(source_site, raw_entries)
        sources.append(
            CompanyIndustrySourceManifest(
                source_site=source_site,
                entries=entries,
            )
        )
    return CompanyIndustryMappingManifest(
        sources=tuple(sorted(sources, key=lambda item: item.source_site))
    )


def _parse_entries(
    source_site: str,
    raw_entries: Sequence[object],
) -> tuple[CompanyIndustryMappingDisposition, ...]:
    entries: list[CompanyIndustryMappingDisposition] = []
    seen_keys: set[str] = set()
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise CompanyIndustryMappingManifestError(
                f"Manifest Source '{source_site}' contains a non-object entry"
            )
        raw_label = raw_entry.get("source_label")
        source_label = " ".join(raw_label.split()) if isinstance(raw_label, str) else ""
        source_label = unicodedata.normalize("NFC", source_label)
        source_key = company_industry_source_key(source_label)
        supplied_key = str(raw_entry.get("source_key") or "").strip()
        if not source_label or not source_key:
            raise CompanyIndustryMappingManifestError("source_label must be non-empty")
        if supplied_key != source_key:
            raise CompanyIndustryMappingManifestError(
                f"source_key '{supplied_key}' does not match normalized label '{source_key}'"
            )
        if source_key in seen_keys:
            raise CompanyIndustryMappingManifestError(
                f"Manifest Source '{source_site}' contains duplicate label '{source_label}'"
            )
        seen_keys.add(source_key)
        disposition = str(raw_entry.get("disposition") or "").strip()
        raw_targets = raw_entry.get("target_codes")
        target_codes = _target_codes(raw_targets)
        reason = str(raw_entry.get("reason") or "").strip() or None
        if disposition == "mapped":
            if not target_codes:
                raise CompanyIndustryMappingManifestError(
                    f"Mapped entry '{source_label}' requires at least one target code"
                )
            if reason is not None:
                raise CompanyIndustryMappingManifestError(
                    f"mapped entry '{source_label}' cannot contain a non-mapping reason"
                )
        elif disposition == "non_mapping":
            if target_codes:
                raise CompanyIndustryMappingManifestError(
                    f"non_mapping entry '{source_label}' cannot contain targets"
                )
            if reason is None:
                raise CompanyIndustryMappingManifestError(
                    f"non_mapping entry '{source_label}' requires a reason"
                )
        else:
            raise CompanyIndustryMappingManifestError(
                f"Entry '{source_label}' has unsupported disposition '{disposition}'"
            )
        entries.append(
            CompanyIndustryMappingDisposition(
                source_label=source_label,
                source_key=source_key,
                disposition=disposition,
                target_codes=target_codes,
                reason=reason,
            )
        )
    return tuple(sorted(entries, key=lambda item: item.source_key))


def _target_codes(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CompanyIndustryMappingManifestError("target_codes must be a list")
    targets = tuple(str(item).strip() for item in value)
    if any(not item for item in targets) or len(set(targets)) != len(targets):
        raise CompanyIndustryMappingManifestError(
            "target_codes must contain unique non-empty codes"
        )
    return tuple(sorted(targets))


def collect_observed_source_industry_labels(
    db: Session,
    source_sites: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    observed: dict[str, tuple[str, ...]] = {}
    for raw_source_site in source_sites:
        source_site = str(raw_source_site or "").strip().lower()
        labels: dict[str, str] = {}
        for raw_data in db.scalars(
            select(Job.raw_data).where(Job.source_site == source_site)
        ):
            if not isinstance(raw_data, Mapping):
                continue
            label = extract_source_industry_label(raw_data)
            normalized = normalize_source_industry_label(label)
            if normalized and label is not None:
                labels.setdefault(normalized, label)
        observed[source_site] = tuple(labels[key] for key in sorted(labels))
    return observed


class CompanyIndustryMappingResolver:
    """Resolve governed runtime dispositions and fail closed on database drift."""

    def __init__(
        self,
        db: Session,
        manifest: CompanyIndustryMappingManifest,
    ) -> None:
        self.manifest = manifest
        rows = tuple(
            db.scalars(
                select(CurrentSourceTaxonomyMapping).where(
                    CurrentSourceTaxonomyMapping.taxonomy == TAXONOMY
                )
            )
        )
        self.rows_by_identity: dict[
            tuple[str, str], tuple[CurrentSourceTaxonomyMapping, ...]
        ] = {}
        grouped_rows: dict[tuple[str, str], list[CurrentSourceTaxonomyMapping]] = {}
        for row in rows:
            lookup_identity = cast(str, row.source_site), cast(str, row.source_key)
            grouped_rows.setdefault(lookup_identity, []).append(row)
        self.rows_by_identity = {
            identity: tuple(
                sorted(values, key=lambda row: cast(str, row.target_code))
            )
            for identity, values in grouped_rows.items()
        }
        target_codes = {cast(str, row.target_code) for row in rows}
        self.nodes: dict[str, CurrentTaxonomyNodeRecord] = {
            cast(str, node.code): node
            for node in db.scalars(
                select(CurrentTaxonomyNodeRecord).where(
                    CurrentTaxonomyNodeRecord.taxonomy == TAXONOMY,
                    CurrentTaxonomyNodeRecord.code.in_(target_codes),
                )
            )
        } if target_codes else {}

    def resolve(
        self,
        source_site: str,
        raw_data: object,
    ) -> CompanyIndustryMappingResolution:
        label = extract_source_industry_label(raw_data)
        normalized_source = str(source_site or "").strip().lower()
        if label is None:
            return CompanyIndustryMappingResolution(
                kind="unsupported",
                source_site=normalized_source,
                source_label=None,
                source_key=None,
                reason="Company has no Source Industry Label evidence",
            )
        source_key = company_industry_source_key(label)
        source_manifest = self.manifest.source(normalized_source)
        entry = (
            source_manifest.by_source_key().get(source_key)
            if source_manifest is not None
            else None
        )
        rows = self.rows_by_identity.get((normalized_source, source_key), ())
        if entry is None:
            return CompanyIndustryMappingResolution(
                kind="unsupported",
                source_site=normalized_source,
                source_label=label,
                source_key=source_key,
                reason=f"Source Industry Label '{label}' has no governed disposition",
            )
        if entry.disposition == "non_mapping":
            if rows:
                return CompanyIndustryMappingResolution(
                    kind="unsupported",
                    source_site=normalized_source,
                    source_label=label,
                    source_key=source_key,
                    reason=f"Source Industry Label '{label}' has manifest/database mapping drift",
                )
            return CompanyIndustryMappingResolution(
                kind="non_mapping",
                source_site=normalized_source,
                source_label=label,
                source_key=source_key,
                reason=entry.reason,
            )

        expected_role = "deterministic" if len(entry.target_codes) == 1 else "allowed"
        actual_codes = tuple(cast(str, row.target_code) for row in rows)
        valid_rows = all(
            cast(str | None, row.source_label) == entry.source_label
            and cast(str, row.role) == expected_role
            and cast(object, row.evidence)
            == {"managed_by": _MANAGED_BY, "disposition": "mapped"}
            and (node := self.nodes.get(cast(str, row.target_code))) is not None
            and bool(node.is_active)
            and bool(node.is_assignable)
            for row in rows
        )
        if actual_codes != entry.target_codes or not valid_rows:
            return CompanyIndustryMappingResolution(
                kind="unsupported",
                source_site=normalized_source,
                source_label=label,
                source_key=source_key,
                reason=f"Source Industry Label '{label}' has manifest/database mapping drift",
            )
        return CompanyIndustryMappingResolution(
            kind="mapped",
            source_site=normalized_source,
            source_label=label,
            source_key=source_key,
            target_codes=entry.target_codes,
        )


class CompanyIndustryMappingSynchronizer:
    def __init__(self, db: Session):
        self.db = db

    def plan(
        self,
        manifest: CompanyIndustryMappingManifest,
        *,
        observed_labels: Mapping[str, Sequence[str]],
    ) -> CompanyIndustryMappingSyncPlan:
        self._validate_coverage(manifest, observed_labels)
        target_codes = {
            code
            for source in manifest.sources
            for entry in source.entries
            for code in entry.target_codes
        }
        nodes: dict[str, CurrentTaxonomyNodeRecord] = {
            cast(str, node.code): node
            for node in self.db.scalars(
                select(CurrentTaxonomyNodeRecord).where(
                    CurrentTaxonomyNodeRecord.taxonomy == TAXONOMY,
                    CurrentTaxonomyNodeRecord.code.in_(target_codes),
                )
            )
        } if target_codes else {}
        for code in sorted(target_codes):
            node = nodes.get(code)
            if node is None or not node.is_active or not node.is_assignable:
                raise CompanyIndustryMappingManifestError(
                    f"Company Industry target '{code}' is unknown, inactive, or non-assignable"
                )

        plans = tuple(self._plan_source(source) for source in manifest.sources)
        return CompanyIndustryMappingSyncPlan(sources=plans)

    def synchronize(
        self,
        manifest: CompanyIndustryMappingManifest,
        *,
        observed_labels: Mapping[str, Sequence[str]],
    ) -> CompanyIndustryMappingSyncPlan:
        plan = self.plan(manifest, observed_labels=observed_labels)
        for source_plan in plan.sources:
            with self.db.begin_nested():
                self._apply_source(source_plan)
        return plan

    @staticmethod
    def _validate_coverage(
        manifest: CompanyIndustryMappingManifest,
        observed_labels: Mapping[str, Sequence[str]],
    ) -> None:
        for source in manifest.sources:
            manifest_keys = {entry.source_key for entry in source.entries}
            observed = {
                company_industry_source_key(label): str(label)
                for label in observed_labels.get(source.source_site, ())
                if company_industry_source_key(label)
            }
            missing = sorted(
                observed[key] for key in observed.keys() - manifest_keys
            )
            if missing:
                raise CompanyIndustryMappingManifestError(
                    f"Manifest Source '{source.source_site}' is missing observed labels: "
                    + ", ".join(missing)
                )

    def _plan_source(
        self,
        source: CompanyIndustrySourceManifest,
    ) -> CompanyIndustrySourceSyncPlan:
        desired = tuple(
            _DesiredMapping(
                source_key=entry.source_key,
                source_label=entry.source_label,
                target_code=target_code,
                role="deterministic" if len(entry.target_codes) == 1 else "allowed",
                evidence={"managed_by": _MANAGED_BY, "disposition": "mapped"},
            )
            for entry in source.entries
            if entry.disposition == "mapped"
            for target_code in entry.target_codes
        )
        existing = tuple(
            self.db.scalars(
                select(CurrentSourceTaxonomyMapping).where(
                    CurrentSourceTaxonomyMapping.taxonomy == TAXONOMY,
                    CurrentSourceTaxonomyMapping.source_site == source.source_site,
                )
            )
        )
        desired_by_identity = {
            (item.source_key, item.target_code): item for item in desired
        }
        existing_by_identity = {
            _mapping_identity(item): item for item in existing
        }
        created = desired_by_identity.keys() - existing_by_identity.keys()
        removed = existing_by_identity.keys() - desired_by_identity.keys()
        shared = desired_by_identity.keys() & existing_by_identity.keys()
        updated = {
            identity
            for identity in shared
            if not _mapping_matches(existing_by_identity[identity], desired_by_identity[identity])
        }
        return CompanyIndustrySourceSyncPlan(
            source_site=source.source_site,
            created=len(created),
            updated=len(updated),
            removed=len(removed),
            unchanged=len(shared - updated),
            mapped_dispositions=sum(
                entry.disposition == "mapped" for entry in source.entries
            ),
            non_mapping_dispositions=sum(
                entry.disposition == "non_mapping" for entry in source.entries
            ),
            desired=tuple(sorted(desired, key=lambda item: (item.source_key, item.target_code))),
        )

    def _apply_source(self, plan: CompanyIndustrySourceSyncPlan) -> None:
        existing = tuple(
            self.db.scalars(
                select(CurrentSourceTaxonomyMapping).where(
                    CurrentSourceTaxonomyMapping.taxonomy == TAXONOMY,
                    CurrentSourceTaxonomyMapping.source_site == plan.source_site,
                )
            )
        )
        existing_by_identity = {
            _mapping_identity(item): item for item in existing
        }
        desired_by_identity = {
            (item.source_key, item.target_code): item for item in plan.desired
        }
        for identity, row in existing_by_identity.items():
            if identity not in desired_by_identity:
                self.db.delete(row)
        for identity, item in desired_by_identity.items():
            current_row = existing_by_identity.get(identity)
            if current_row is None:
                self.db.add(
                    CurrentSourceTaxonomyMapping(
                        taxonomy=TAXONOMY,
                        source_site=plan.source_site,
                        source_key=item.source_key,
                        source_label=item.source_label,
                        target_code=item.target_code,
                        role=item.role,
                        evidence=item.evidence,
                    )
                )
            elif not _mapping_matches(current_row, item):
                setattr(current_row, "source_label", item.source_label)
                setattr(current_row, "role", item.role)
                setattr(current_row, "evidence", item.evidence)
        self.db.flush()


def _mapping_matches(
    row: CurrentSourceTaxonomyMapping,
    desired: _DesiredMapping,
) -> bool:
    return (
        cast(str | None, row.source_label) == desired.source_label
        and cast(str, row.role) == desired.role
        and cast(object, row.evidence) == desired.evidence
    )


def _mapping_identity(row: CurrentSourceTaxonomyMapping) -> tuple[str, str]:
    return cast(str, row.source_key), cast(str, row.target_code)


__all__ = [
    "CompanyIndustryMappingDisposition",
    "CompanyIndustryMappingManifest",
    "CompanyIndustryMappingManifestError",
    "CompanyIndustryMappingResolution",
    "CompanyIndustryMappingResolver",
    "CompanyIndustryMappingSynchronizer",
    "CompanyIndustrySourceManifest",
    "CompanyIndustryMappingSyncPlan",
    "DEFAULT_COMPANY_INDUSTRY_MAPPING_MANIFEST",
    "company_industry_source_key",
    "collect_observed_source_industry_labels",
    "extract_source_industry_label",
    "load_company_industry_mapping_manifest",
    "normalize_source_industry_label",
]
