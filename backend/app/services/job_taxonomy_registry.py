"""Source-guided registry for job taxonomy constraints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class SourceBoundTaxonomySlice:
    """Allowed taxonomy slice for a single JobsDB source classification."""

    source_classification_id: str | None
    source_classification_name: str | None
    source_subclassification_name: str | None
    allowed_domains: list[str]
    allowed_categories: list[str]
    allowed_subcategories: list[str]
    default_path: tuple[str, str, str]


@dataclass(frozen=True)
class SourceTaxonomyHandling:
    """Preflight outcome for a persisted source classification."""

    source_classification_id: str | None
    status: str
    source_classification_name: str | None
    reason: str | None = None


@lru_cache(maxsize=None)
def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


class JobTaxonomyRegistry:
    """Resolves source classifications into a constrained taxonomy slice."""

    def __init__(
        self,
        taxonomy: dict[str, Any],
        mapping: dict[str, Any],
        exclusions: dict[str, Any] | None = None,
    ):
        self.taxonomy = taxonomy
        self.mapping = mapping
        self.exclusions = exclusions or {}

    @classmethod
    def from_files(
        cls,
        taxonomy_path: str,
        mapping_path: str,
        exclusions_path: str | None = None,
    ) -> "JobTaxonomyRegistry":
        return cls(
            taxonomy=_load_json(taxonomy_path),
            mapping=_load_json(mapping_path),
            exclusions=(
                _load_json(exclusions_path)
                if exclusions_path is not None
                else None
            ),
        )

    def get_handling(
        self,
        source_classification_id: str | None,
        source_classification_name: str | None = None,
    ) -> SourceTaxonomyHandling:
        """Return a safe preflight result without raising for unsupported IDs."""
        normalized_id = str(source_classification_id or "").strip() or None
        if normalized_id in self.mapping:
            mapping_entry = self.mapping[normalized_id]
            return SourceTaxonomyHandling(
                source_classification_id=normalized_id,
                status="mapped",
                source_classification_name=(
                    source_classification_name
                    or mapping_entry.get("source_name")
                ),
            )

        exclusion = self.exclusions.get(normalized_id or "")
        if exclusion is not None:
            return SourceTaxonomyHandling(
                source_classification_id=normalized_id,
                status="excluded",
                source_classification_name=(
                    source_classification_name
                    or exclusion.get("source_name")
                ),
                reason=str(exclusion.get("reason") or "Unsupported source taxonomy"),
            )

        return SourceTaxonomyHandling(
            source_classification_id=normalized_id,
            status="excluded",
            source_classification_name=source_classification_name,
            reason=(
                f"No source taxonomy mapping configured for "
                f"{normalized_id or 'missing classification'}"
            ),
        )

    def get_allowed_slice(
        self,
        source_classification_id: str | None,
        source_classification_name: str | None,
        source_subclassification_name: str | None,
    ) -> SourceBoundTaxonomySlice:
        if not source_classification_id or source_classification_id not in self.mapping:
            raise ValueError(
                f"Unknown source classification: {source_classification_id or 'missing'}"
            )

        mapping_entry = self.mapping[source_classification_id]
        self._validate_default_path(mapping_entry["default_path"])
        allowed_domains = list(mapping_entry["allowed_domains"])
        domain_names = set(allowed_domains)

        categories_by_name: dict[str, list[str]] = {}
        for domain in self.taxonomy["domains"]:
            if domain["name"] not in domain_names:
                continue
            for category in domain["categories"]:
                categories_by_name[category["name"]] = list(category["subcategories"])

        allowed_categories = list(categories_by_name.keys())

        hint_categories = None
        hint_default_path: tuple[str, str, str] | None = None
        if source_subclassification_name:
            hint = mapping_entry.get("subcategory_hints", {}).get(source_subclassification_name)
            if hint:
                hint_categories = [
                    category
                    for category in hint.get("allowed_categories", [])
                    if category in categories_by_name
                ]
                raw_default_path = hint.get("default_path")
                if (
                    isinstance(raw_default_path, list)
                    and len(raw_default_path) == 3
                    and raw_default_path[0] in allowed_domains
                    and raw_default_path[1] in categories_by_name
                    and raw_default_path[2] in categories_by_name.get(raw_default_path[1], [])
                ):
                    hint_default_path = (
                        str(raw_default_path[0]),
                        str(raw_default_path[1]),
                        str(raw_default_path[2]),
                    )

        if hint_categories:
            allowed_categories = hint_categories

        allowed_subcategories: list[str] = []
        for category_name in allowed_categories:
            allowed_subcategories.extend(categories_by_name.get(category_name, []))

        return SourceBoundTaxonomySlice(
            source_classification_id=source_classification_id,
            source_classification_name=(
                source_classification_name or mapping_entry.get("source_name")
            ),
            source_subclassification_name=source_subclassification_name,
            allowed_domains=allowed_domains,
            allowed_categories=allowed_categories,
            allowed_subcategories=allowed_subcategories,
            default_path=hint_default_path
            or cast(tuple[str, str, str], tuple(mapping_entry["default_path"])),
        )

    def _validate_default_path(self, raw_path: Any) -> None:
        if not isinstance(raw_path, list) or len(raw_path) != 3:
            raise ValueError("Source taxonomy mapping default_path must contain three parts")

        domain_name, category_name, subcategory_name = (str(part) for part in raw_path)
        domain = next(
            (
                item
                for item in self.taxonomy["domains"]
                if item["name"] == domain_name
            ),
            None,
        )
        if domain is None:
            raise ValueError(f"Unknown taxonomy domain in source mapping: {domain_name}")

        category = next(
            (
                item
                for item in domain["categories"]
                if item["name"] == category_name
            ),
            None,
        )
        if category is None or subcategory_name not in category["subcategories"]:
            raise ValueError(
                "Unknown taxonomy default path in source mapping: "
                f"{domain_name} / {category_name} / {subcategory_name}"
            )

    def get_base_default_path(
        self,
        source_classification_id: str | None,
    ) -> tuple[str, str, str]:
        if not source_classification_id or source_classification_id not in self.mapping:
            raise ValueError(
                f"Unknown source classification: {source_classification_id or 'missing'}"
            )

        mapping_entry = self.mapping[source_classification_id]
        return cast(tuple[str, str, str], tuple(mapping_entry["default_path"]))


_registry: JobTaxonomyRegistry | None = None


def get_job_taxonomy_registry() -> JobTaxonomyRegistry:
    """Return the default registry backed by project taxonomy files."""
    global _registry
    if _registry is None:
        backend_dir = Path(__file__).resolve().parents[1]
        _registry = JobTaxonomyRegistry.from_files(
            taxonomy_path=str(backend_dir / "data" / "job_category_taxonomy.json"),
            mapping_path=str(backend_dir / "data" / "job_source_taxonomy_mapping.json"),
            exclusions_path=str(backend_dir / "data" / "job_source_taxonomy_exclusions.json"),
        )
    return _registry
