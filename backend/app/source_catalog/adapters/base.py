from __future__ import annotations

from typing import Any, Protocol

from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    DiscoveredCatalog,
    SourceQueryTarget,
)


class SourceCatalogAdapter(Protocol):
    """The sole source-specific catalog seam: discover, compile, bounded smoke."""

    source_site: str

    def discover(self) -> DiscoveredCatalog: ...

    def compile(self, node: CatalogNodeSnapshot) -> tuple[SourceQueryTarget, ...]: ...

    async def smoke(self, target: SourceQueryTarget) -> dict[str, Any]: ...
