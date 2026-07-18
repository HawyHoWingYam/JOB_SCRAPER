"""Authoritative Source Catalog domain and adapter boundary."""

from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogDiff,
    CatalogScopeCapabilities,
    CatalogValidationError,
    CompiledCatalogValidationReport,
    DiscoveredCatalog,
    SourceQueryTarget,
    catalog_fingerprint,
    diff_catalogs,
    expand_catalog_scope,
    expansion_fingerprint,
    validate_catalog,
    validate_compiled_catalog,
)

__all__ = [
    "CatalogNodeSnapshot",
    "CatalogDiff",
    "CatalogScopeCapabilities",
    "CatalogValidationError",
    "CompiledCatalogValidationReport",
    "DiscoveredCatalog",
    "SourceQueryTarget",
    "catalog_fingerprint",
    "diff_catalogs",
    "expand_catalog_scope",
    "expansion_fingerprint",
    "validate_catalog",
    "validate_compiled_catalog",
]
