"""Source-guided registry for job taxonomy constraints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


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


@lru_cache(maxsize=None)
def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


class JobTaxonomyRegistry:
    """Resolves source classifications into a constrained taxonomy slice."""

    def __init__(self, taxonomy: dict[str, Any], mapping: dict[str, Any]):
        self.taxonomy = taxonomy
        self.mapping = mapping

    @classmethod
    def from_files(cls, taxonomy_path: str, mapping_path: str) -> "JobTaxonomyRegistry":
        return cls(
            taxonomy=_load_json(taxonomy_path),
            mapping=_load_json(mapping_path),
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
        hint_default_path = None
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
                    hint_default_path = tuple(str(part) for part in raw_default_path)

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
            default_path=hint_default_path or tuple(mapping_entry["default_path"]),
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
        return tuple(mapping_entry["default_path"])


_registry: JobTaxonomyRegistry | None = None


def get_job_taxonomy_registry() -> JobTaxonomyRegistry:
    """Return the default registry backed by project taxonomy files."""
    global _registry
    if _registry is None:
        backend_dir = Path(__file__).resolve().parents[1]
        _registry = JobTaxonomyRegistry.from_files(
            taxonomy_path=str(backend_dir / "data" / "job_category_taxonomy.json"),
            mapping_path=str(backend_dir / "data" / "job_source_taxonomy_mapping.json"),
        )
    return _registry
