from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.job_intelligence.foundation import Provenance
from app.job_intelligence.source_attributes.contracts import (
    SourceCatalogRevisionRef,
    SourceClassificationContext,
    SourceClassificationNodeEvidence,
    SourceClassificationPathEvidence,
    SourceEmploymentLabelEvidence,
    SourceJobAttributeEvidence,
)


_JOBSDB_EMPLOYMENT_TYPES = {
    "contract": "contract",
    "freelance": "freelance",
    "full-time": "full_time",
    "internship": "internship",
    "part-time": "part_time",
    "permanent": "permanent",
    "temporary": "temporary",
}

_CTGOODJOBS_EMPLOYMENT_TYPES = {
    "full-time": "full_time",
    "temporary": "temporary",
}

_CTGOODJOBS_JSON_LD_TYPES = {
    "FULL_TIME": ("Full-time", "full_time"),
    "TEMPORARY": ("Temporary", "temporary"),
}

_OFFERTODAY_EMPLOYMENT_CODES = {
    "1": "full_time",
    "2": "part_time",
    "3": "internship",
}

_OFFERTODAY_EMPLOYMENT_LABELS = {
    "全職": "full_time",
    "兼職": "part_time",
    "實習": "internship",
}


def _normalized_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _lookup_key(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def _malformed_marker(
    value: Any,
    *,
    distinguish_empty_object: bool = True,
) -> str:
    """Describe malformed source evidence without retaining its payload."""
    if value is None:
        kind = "null"
    elif isinstance(value, str):
        kind = "empty-string" if _normalized_text(value) is None else "string"
    elif isinstance(value, Mapping):
        kind = "empty-object" if distinguish_empty_object and not value else "object"
    elif isinstance(value, list):
        kind = "array"
    elif isinstance(value, bool):
        kind = "boolean"
    elif isinstance(value, (int, float)):
        kind = "number"
    else:
        kind = "unknown"
    return f"<malformed:{kind}>"


def _bounded_employment_text(
    value: Any,
    *,
    allow_number: bool = False,
    distinguish_empty_object: bool = True,
) -> tuple[str, bool]:
    normalized = _normalized_text(value)
    if normalized is None and allow_number and isinstance(value, (int, float)):
        if not isinstance(value, bool):
            normalized = _normalized_text(str(value))
    if normalized is not None:
        return normalized, False
    return (
        _malformed_marker(
            value,
            distinguish_empty_object=distinguish_empty_object,
        ),
        True,
    )


def _jobsdb_node(
    payload: Any,
    *,
    source_position: int,
    native_depth: int,
) -> SourceClassificationNodeEvidence | None:
    if not isinstance(payload, Mapping):
        return None
    native_id = _normalized_text(str(payload.get("id") or ""))
    label = _normalized_text(payload.get("description"))
    if native_id is None or label is None:
        return None
    return SourceClassificationNodeEvidence(
        source_position=source_position,
        native_depth=native_depth,
        source_classification_id=f"jobsdb:{native_id}",
        native_id=native_id,
        label=label,
    )


class JobsDBSourceEvidenceAdapter:
    source_site = "jobsdb"

    def extract(
        self,
        payload: Mapping[str, Any],
        *,
        provenance: Provenance,
        source_catalog_revision: SourceCatalogRevisionRef | None = None,
    ) -> SourceJobAttributeEvidence:
        if (
            source_catalog_revision is not None
            and source_catalog_revision.source_site != self.source_site
        ):
            raise ValueError("Source Catalog revision does not belong to jobsdb")
        classifications = payload.get("classifications")
        paths: list[SourceClassificationPathEvidence] = []
        if isinstance(classifications, list):
            for item in classifications:
                if not isinstance(item, Mapping):
                    continue
                nodes = [
                    node
                    for node in (
                        _jobsdb_node(
                            item.get("classification"),
                            source_position=0,
                            native_depth=0,
                        ),
                        _jobsdb_node(
                            item.get("subclassification"),
                            source_position=1,
                            native_depth=1,
                        ),
                    )
                    if node is not None
                ]
                if not nodes:
                    continue
                paths.append(
                    SourceClassificationPathEvidence(
                        source_order=len(paths),
                        nodes=tuple(nodes),
                        source_declared_primary=False,
                        primary_basis=None,
                        source_catalog_revision=source_catalog_revision,
                        provenance=provenance,
                    )
                )

        employment_labels: list[SourceEmploymentLabelEvidence] = []
        work_types = payload.get("workTypes")
        if isinstance(work_types, list):
            for raw_value in work_types:
                raw_label, malformed = _bounded_employment_text(raw_value)
                lookup_key = None if malformed else _lookup_key(raw_label)
                mapped_type = (
                    None
                    if malformed
                    else _JOBSDB_EMPLOYMENT_TYPES.get(lookup_key or "")
                )
                employment_labels.append(
                    SourceEmploymentLabelEvidence(
                        source_order=len(employment_labels),
                        raw_code=None,
                        raw_label=raw_label,
                        normalized_lookup_key=lookup_key,
                        mapped_type_code=mapped_type,
                        mapping_id=(
                            f"jobsdb-label-v1:{lookup_key}"
                            if mapped_type is not None
                            else None
                        ),
                        provenance=provenance,
                    )
                )

        work_arrangements: list[str] = []
        raw_arrangements = payload.get("workArrangements")
        if isinstance(raw_arrangements, Mapping):
            items = raw_arrangements.get("data")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    label = item.get("label")
                    text = label.get("text") if isinstance(label, Mapping) else None
                    normalized = _normalized_text(text)
                    if normalized is not None:
                        work_arrangements.append(normalized)

        return SourceJobAttributeEvidence(
            source_site=self.source_site,
            classification_paths=tuple(paths),
            employment_labels=tuple(employment_labels),
            work_arrangements=tuple(work_arrangements),
        )


class CTGoodJobsSourceEvidenceAdapter:
    source_site = "ctgoodjobs"

    def extract(
        self,
        payload: Mapping[str, Any],
        *,
        provenance: Provenance,
        classification_context: SourceClassificationContext | None = None,
    ) -> SourceJobAttributeEvidence:
        paths: list[SourceClassificationPathEvidence] = []
        if classification_context is not None:
            prefix = f"{self.source_site}:"
            classification_id = classification_context.source_classification_id
            native_id = (
                classification_id[len(prefix) :]
                if classification_id.startswith(prefix)
                else classification_id
            )
            paths.append(
                SourceClassificationPathEvidence(
                    source_order=0,
                    nodes=(
                        SourceClassificationNodeEvidence(
                            source_position=0,
                            native_depth=0,
                            source_classification_id=classification_id,
                            native_id=native_id,
                            label=classification_context.label,
                        ),
                    ),
                    source_declared_primary=False,
                    primary_basis=None,
                    source_catalog_revision=(
                        classification_context.source_catalog_revision
                    ),
                    provenance=classification_context.provenance,
                )
            )

        job_content = payload.get("jobContent")
        basic_info = payload.get("basicInfo")
        work_types = (
            job_content.get("workTypes") if isinstance(job_content, Mapping) else None
        )
        if not isinstance(work_types, list) or not work_types:
            work_types = (
                basic_info.get("empTypes") if isinstance(basic_info, Mapping) else None
            )

        employment_labels: list[SourceEmploymentLabelEvidence] = []
        has_usable_employment_evidence = False
        if isinstance(work_types, list):
            for item in work_types:
                if not isinstance(item, Mapping):
                    employment_labels.append(
                        SourceEmploymentLabelEvidence(
                            source_order=len(employment_labels),
                            raw_code=None,
                            raw_label=_malformed_marker(item),
                            normalized_lookup_key=None,
                            mapped_type_code=None,
                            mapping_id=None,
                            provenance=provenance,
                        )
                    )
                    continue

                if not item:
                    employment_labels.append(
                        SourceEmploymentLabelEvidence(
                            source_order=len(employment_labels),
                            raw_code=None,
                            raw_label=_malformed_marker(item),
                            normalized_lookup_key=None,
                            mapped_type_code=None,
                            mapping_id=None,
                            provenance=provenance,
                        )
                    )
                    continue

                raw_label: str | None = None
                raw_label_malformed = False
                if "name" in item:
                    raw_label, raw_label_malformed = _bounded_employment_text(
                        item.get("name")
                    )

                raw_code: str | None = None
                raw_code_malformed = False
                code_present = "code" in item or "id" in item
                if code_present:
                    code_value = item.get("code")
                    if not code_value and "id" in item:
                        code_value = item.get("id")
                    raw_code, raw_code_malformed = _bounded_employment_text(
                        code_value,
                        allow_number=True,
                    )

                if raw_label is None and raw_code is None:
                    raw_label = _malformed_marker(item)
                    raw_label_malformed = True

                malformed = raw_label_malformed or raw_code_malformed
                if not malformed:
                    has_usable_employment_evidence = True
                elif (raw_label is not None and not raw_label_malformed) or (
                    raw_code is not None and not raw_code_malformed
                ):
                    has_usable_employment_evidence = True

                lookup_key = None if malformed else _lookup_key(raw_label)
                mapped_type = (
                    None
                    if malformed
                    else _CTGOODJOBS_EMPLOYMENT_TYPES.get(lookup_key or "")
                )
                employment_labels.append(
                    SourceEmploymentLabelEvidence(
                        source_order=len(employment_labels),
                        raw_code=raw_code,
                        raw_label=raw_label,
                        normalized_lookup_key=lookup_key,
                        mapped_type_code=mapped_type,
                        mapping_id=(
                            f"ctgoodjobs-label-v1:{lookup_key}"
                            if mapped_type is not None
                            else None
                        ),
                        provenance=provenance,
                    )
                )

        if not has_usable_employment_evidence:
            job_posting = payload.get("jobPosting")
            raw_json_ld_types = (
                job_posting.get("employmentType")
                if isinstance(job_posting, Mapping)
                else None
            )
            if isinstance(raw_json_ld_types, str):
                json_ld_types = [raw_json_ld_types]
            elif isinstance(raw_json_ld_types, list):
                json_ld_types = raw_json_ld_types
            else:
                json_ld_types = []
            for raw_value in json_ld_types:
                raw_code, malformed = _bounded_employment_text(raw_value)
                if malformed:
                    employment_labels.append(
                        SourceEmploymentLabelEvidence(
                            source_order=len(employment_labels),
                            raw_code=raw_code,
                            raw_label=None,
                            normalized_lookup_key=None,
                            mapped_type_code=None,
                            mapping_id=None,
                            provenance=provenance,
                        )
                    )
                    continue
                raw_label, mapped_type = _CTGOODJOBS_JSON_LD_TYPES.get(
                    raw_code,
                    (raw_code.replace("_", " ").title(), None),
                )
                employment_labels.append(
                    SourceEmploymentLabelEvidence(
                        source_order=len(employment_labels),
                        raw_code=raw_code,
                        raw_label=raw_label,
                        normalized_lookup_key=_lookup_key(raw_label),
                        mapped_type_code=mapped_type,
                        mapping_id=(
                            f"ctgoodjobs-jsonld-v1:{raw_code}"
                            if mapped_type is not None
                            else None
                        ),
                        provenance=provenance,
                    )
                )

        return SourceJobAttributeEvidence(
            source_site=self.source_site,
            classification_paths=tuple(paths),
            employment_labels=tuple(employment_labels),
        )


class OfferTodaySourceEvidenceAdapter:
    source_site = "offertoday"

    def extract(
        self,
        payload: Mapping[str, Any],
        *,
        provenance: Provenance,
    ) -> SourceJobAttributeEvidence:
        raw_functions = payload.get("jobFunctions") or payload.get("job_functions")
        paths: list[SourceClassificationPathEvidence] = []
        seen_paths: set[tuple[str, ...]] = set()
        if isinstance(raw_functions, list):
            for raw_root in raw_functions:
                if not isinstance(raw_root, Mapping):
                    continue
                root = self._node(raw_root, source_position=0, native_depth=0)
                if root is None:
                    continue
                raw_children = raw_root.get("children")
                children = raw_children if isinstance(raw_children, list) else []
                candidates: list[tuple[SourceClassificationNodeEvidence, ...]] = []
                if children:
                    for raw_child in children:
                        child = self._node(
                            raw_child,
                            source_position=1,
                            native_depth=1,
                        )
                        if child is None or child.source_classification_id == (
                            root.source_classification_id
                        ):
                            candidates.append((root,))
                        else:
                            candidates.append((root, child))
                else:
                    candidates.append((root,))

                for nodes in candidates:
                    identity = tuple(node.source_classification_id for node in nodes)
                    if identity in seen_paths:
                        continue
                    seen_paths.add(identity)
                    paths.append(
                        SourceClassificationPathEvidence(
                            source_order=len(paths),
                            nodes=nodes,
                            source_declared_primary=False,
                            primary_basis=None,
                            source_catalog_revision=None,
                            provenance=provenance,
                        )
                    )

        employment_labels: list[SourceEmploymentLabelEvidence] = []
        raw_code: str | None = None
        raw_code_malformed = False
        if "jobType" in payload:
            raw_code, raw_code_malformed = _bounded_employment_text(
                payload.get("jobType"),
                allow_number=True,
                distinguish_empty_object=False,
            )

        raw_label: str | None = None
        raw_label_malformed = False
        if "jobTypeDesc" in payload:
            raw_label, raw_label_malformed = _bounded_employment_text(
                payload.get("jobTypeDesc")
            )

        if raw_code is not None or raw_label is not None:
            malformed = raw_code_malformed or raw_label_malformed
            lookup_key = None if malformed else _lookup_key(raw_label)
            mapped_type = (
                None if malformed else _OFFERTODAY_EMPLOYMENT_CODES.get(raw_code or "")
            )
            if mapped_type is None and not malformed:
                mapped_type = _OFFERTODAY_EMPLOYMENT_LABELS.get(lookup_key or "")
            employment_labels.append(
                SourceEmploymentLabelEvidence(
                    source_order=len(employment_labels),
                    raw_code=raw_code,
                    raw_label=raw_label,
                    normalized_lookup_key=lookup_key,
                    mapped_type_code=mapped_type,
                    mapping_id=(
                        f"offertoday-code-v1:{raw_code}"
                        if mapped_type is not None and raw_code is not None
                        else (
                            f"offertoday-label-v1:{lookup_key}"
                            if mapped_type is not None
                            else None
                        )
                    ),
                    provenance=provenance,
                )
            )

        raw_employ_type = payload.get("employType")
        employ_type_label: str | None = None
        employ_type_malformed = False
        if "employType" in payload:
            if isinstance(raw_employ_type, Mapping):
                if "name" in raw_employ_type:
                    employ_type_label, employ_type_malformed = _bounded_employment_text(
                        raw_employ_type.get("name")
                    )
                else:
                    employ_type_label = _malformed_marker(raw_employ_type)
                    employ_type_malformed = True
            else:
                employ_type_label = _malformed_marker(raw_employ_type)
                employ_type_malformed = True
        if employ_type_label is not None:
            lookup_key = (
                None if employ_type_malformed else _lookup_key(employ_type_label)
            )
            mapped_type = (
                None
                if employ_type_malformed
                else _OFFERTODAY_EMPLOYMENT_LABELS.get(lookup_key or "")
            )
            employment_labels.append(
                SourceEmploymentLabelEvidence(
                    source_order=len(employment_labels),
                    raw_code=None,
                    raw_label=employ_type_label,
                    normalized_lookup_key=lookup_key,
                    mapped_type_code=mapped_type,
                    mapping_id=(
                        f"offertoday-label-v1:{lookup_key}"
                        if mapped_type is not None
                        else None
                    ),
                    provenance=provenance,
                )
            )

        work_arrangement = _normalized_text(
            payload.get("workingModels") or payload.get("working_model")
        )
        working_days = _normalized_text(
            payload.get("workingDays") or payload.get("working_days")
        )
        return SourceJobAttributeEvidence(
            source_site=self.source_site,
            classification_paths=tuple(paths),
            employment_labels=tuple(employment_labels),
            work_arrangements=((work_arrangement,) if work_arrangement else ()),
            working_day_labels=((working_days,) if working_days else ()),
        )

    def _node(
        self,
        payload: Any,
        *,
        source_position: int,
        native_depth: int,
    ) -> SourceClassificationNodeEvidence | None:
        if not isinstance(payload, Mapping):
            return None
        native_id = _normalized_text(str(payload.get("code") or ""))
        label = _normalized_text(payload.get("name"))
        if native_id is None or label is None:
            return None
        return SourceClassificationNodeEvidence(
            source_position=source_position,
            native_depth=native_depth,
            source_classification_id=f"offertoday:{native_id}",
            native_id=native_id,
            label=label,
        )
