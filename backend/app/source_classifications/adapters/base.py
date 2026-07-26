from __future__ import annotations

from typing import Any, Protocol

from app.source_classifications.domain import (
    CatalogNodeSnapshot,
    DiscoveredCatalog,
    SourceQueryTarget,
)


class SourceClassificationAdapter(Protocol):
    """Source-specific seam for discovering classifications and compiling queries."""

    source_site: str

    def discover(self) -> DiscoveredCatalog: ...

    def compile(self, node: CatalogNodeSnapshot) -> tuple[SourceQueryTarget, ...]: ...

    async def smoke(self, target: SourceQueryTarget) -> dict[str, Any]: ...
