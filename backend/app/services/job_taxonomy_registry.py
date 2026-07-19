"""Fail-closed compatibility shell for the retired label-based registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn


@dataclass(frozen=True)
class SourceBoundTaxonomySlice:
    """Legacy value shape retained only for unreachable comparison helpers."""

    source_classification_id: str | None
    source_classification_name: str | None
    source_subclassification_name: str | None
    allowed_domains: list[str]
    allowed_categories: list[str]
    allowed_subcategories: list[str]
    default_path: tuple[str, str, str]


class LegacyJobTaxonomyRegistryRetiredError(RuntimeError):
    """Raised when obsolete label/default-path authority is requested."""


def get_job_taxonomy_registry() -> NoReturn:
    """Reject use of the retired registry instead of guessing compatibility."""
    raise LegacyJobTaxonomyRegistryRetiredError(
        "Legacy JobTaxonomyRegistry is retired; use the active canonical mapping "
        "release through CanonicalTaxonomyPreflight or CanonicalJobTaxonomy"
    )
