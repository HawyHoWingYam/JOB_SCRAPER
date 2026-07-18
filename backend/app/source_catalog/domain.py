from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Literal, Protocol


SUPPORTED_SOURCE_SITES = ("jobsdb", "ctgoodjobs", "offertoday")
_SOURCE_CLASSIFICATION_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class CatalogValidationError(ValueError):
    """Stable domain validation failure for a catalog or scope."""

    def __init__(self, code: str, message: str, *, node_key: str | None = None):
        super().__init__(message)
        self.code = code
        self.node_key = node_key


def _is_source_qualified_classification_id(value: str, source_site: str) -> bool:
    """Accept exactly ``<source>:<opaque-token>`` with no whitespace ambiguity."""

    prefix, separator, token = value.partition(":")
    return bool(
        separator
        and prefix == source_site
        and _SOURCE_CLASSIFICATION_TOKEN.fullmatch(token)
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise TypeError(f"Source Catalog payload contains non-JSON value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def payload_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CatalogNodeSnapshot:
    node_key: str
    source_site: str
    classification_id: str | None
    native_id: int | str
    native_label: str
    parent_node_key: str | None
    native_path: tuple[str, ...]
    depth: int
    selectable: bool
    supports_exact: bool
    supports_subtree: bool
    queryable: bool
    alias_of_node_key: str | None
    query_semantics_hash: str | None
    source_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "source_site": self.source_site,
            "classification_id": self.classification_id,
            "native_id": self.native_id,
            "native_label": self.native_label,
            "parent_node_key": self.parent_node_key,
            "native_path": list(self.native_path),
            "depth": self.depth,
            "selectable": self.selectable,
            "supports_exact": self.supports_exact,
            "supports_subtree": self.supports_subtree,
            "queryable": self.queryable,
            "alias_of_node_key": self.alias_of_node_key,
            "query_semantics_hash": self.query_semantics_hash,
            "source_metadata": _json_safe(self.source_metadata),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CatalogNodeSnapshot:
        return cls(
            node_key=str(payload["node_key"]),
            source_site=str(payload["source_site"]),
            classification_id=(
                str(payload["classification_id"])
                if payload.get("classification_id") is not None
                else None
            ),
            native_id=payload["native_id"],
            native_label=str(payload["native_label"]),
            parent_node_key=(
                str(payload["parent_node_key"])
                if payload.get("parent_node_key") is not None
                else None
            ),
            native_path=tuple(str(part) for part in payload["native_path"]),
            depth=int(payload["depth"]),
            selectable=bool(payload["selectable"]),
            supports_exact=bool(payload["supports_exact"]),
            supports_subtree=bool(payload["supports_subtree"]),
            queryable=bool(payload["queryable"]),
            alias_of_node_key=(
                str(payload["alias_of_node_key"])
                if payload.get("alias_of_node_key") is not None
                else None
            ),
            query_semantics_hash=(
                str(payload["query_semantics_hash"])
                if payload.get("query_semantics_hash") is not None
                else None
            ),
            source_metadata=dict(payload.get("source_metadata") or {}),
        )


@dataclass(frozen=True)
class CatalogScopeCapabilities:
    supports_all_scope: bool
    all_scope_root_node_keys: tuple[str, ...]
    recommended_scope: Mapping[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "supports_all_scope": self.supports_all_scope,
            "all_scope_root_node_keys": list(self.all_scope_root_node_keys),
            "recommended_scope": (
                _json_safe(self.recommended_scope)
                if self.recommended_scope is not None
                else None
            ),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> CatalogScopeCapabilities:
        return cls(
            supports_all_scope=bool(payload["supports_all_scope"]),
            all_scope_root_node_keys=tuple(
                str(item) for item in payload.get("all_scope_root_node_keys") or ()
            ),
            recommended_scope=(
                dict(payload["recommended_scope"])
                if payload.get("recommended_scope") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class DiscoveredCatalog:
    source_site: str
    nodes: tuple[CatalogNodeSnapshot, ...]
    capabilities: CatalogScopeCapabilities
    source_payload: Mapping[str, Any]
    provenance: Mapping[str, Any]
    version: int = 1

    def normalized_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "source_site": self.source_site,
            "nodes": [node.to_payload() for node in self.nodes],
            "capabilities": self.capabilities.to_payload(),
        }

    @classmethod
    def from_payloads(
        cls,
        *,
        normalized_payload: Mapping[str, Any],
        source_payload: Mapping[str, Any],
        provenance: Mapping[str, Any] | None = None,
    ) -> DiscoveredCatalog:
        return cls(
            source_site=str(normalized_payload["source_site"]),
            nodes=tuple(
                CatalogNodeSnapshot.from_payload(item)
                for item in normalized_payload.get("nodes") or ()
            ),
            capabilities=CatalogScopeCapabilities.from_payload(
                normalized_payload["capabilities"]
            ),
            source_payload=dict(source_payload),
            provenance=dict(provenance or {}),
            version=int(normalized_payload.get("version", 1)),
        )

    @property
    def fingerprint(self) -> str:
        return catalog_fingerprint(self)


@dataclass(frozen=True)
class SourceQueryTarget:
    adapter: str
    classification_id: str
    payload: Mapping[str, Any]
    version: int = 1

    def to_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "adapter": self.adapter,
            "classification_id": self.classification_id,
            **_json_safe(self.payload),
        }

    @property
    def fingerprint(self) -> str:
        return payload_fingerprint(self.to_payload())


@dataclass(frozen=True)
class CatalogValidationReport:
    node_count: int
    selectable_count: int
    queryable_count: int
    fingerprint: str


@dataclass(frozen=True)
class CatalogDiff:
    added: tuple[dict[str, Any], ...] = ()
    removed: tuple[dict[str, Any], ...] = ()
    renamed: tuple[dict[str, Any], ...] = ()
    moved: tuple[dict[str, Any], ...] = ()
    alias_changed: tuple[dict[str, Any], ...] = ()
    capabilities_changed: tuple[dict[str, Any], ...] = ()
    query_semantics_changed: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "renamed": list(self.renamed),
            "moved": list(self.moved),
            "alias_changed": list(self.alias_changed),
            "capabilities_changed": list(self.capabilities_changed),
            "query_semantics_changed": list(self.query_semantics_changed),
        }


class CatalogCompiler(Protocol):
    source_site: str

    def compile(self, node: CatalogNodeSnapshot) -> tuple[SourceQueryTarget, ...]: ...


@dataclass(frozen=True)
class CompiledCatalogValidationReport:
    source_site: str
    node_count: int
    target_count: int
    target_fingerprints: tuple[str, ...]


def catalog_fingerprint(catalog: DiscoveredCatalog) -> str:
    normalized = catalog.normalized_payload()
    for node in normalized["nodes"]:
        metadata = dict(node.get("source_metadata") or {})
        node["source_metadata"] = {
            key: value
            for key, value in metadata.items()
            if not (
                key.startswith("canonical_")
                or key
                in {
                    "mapping_notes",
                    "mapping_status",
                    "proposed_internal_domain",
                }
            )
        }
    return payload_fingerprint(
        {
            "normalized": normalized,
            "source": catalog.source_payload,
        }
    )


def _node_identity(node: CatalogNodeSnapshot) -> str:
    if node.classification_id is not None:
        return f"classification:{node.classification_id}"
    return f"node:{node.node_key}"


def _change_record(
    before: CatalogNodeSnapshot | None,
    after: CatalogNodeSnapshot | None,
    *,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    node = after or before
    assert node is not None
    return {
        "node_key": node.node_key,
        "classification_id": node.classification_id,
        "native_id": node.native_id,
        **dict(fields or {}),
    }


def diff_catalogs(
    previous: DiscoveredCatalog | None,
    current: DiscoveredCatalog,
) -> CatalogDiff:
    """Return a deterministic operator-facing and execution-facing catalog diff."""

    validate_catalog(current)
    if previous is None:
        return CatalogDiff(
            added=tuple(
                _change_record(None, node)
                for node in current.nodes
                if node.classification_id is not None
            )
        )
    validate_catalog(previous)
    if previous.source_site != current.source_site:
        raise CatalogValidationError(
            "CATALOG_DIFF_SOURCE_MISMATCH", "Catalog revisions must belong to one Source"
        )

    before = {_node_identity(node): node for node in previous.nodes}
    after = {_node_identity(node): node for node in current.nodes}
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    alias_changed: list[dict[str, Any]] = []
    capabilities_changed: list[dict[str, Any]] = []
    query_semantics_changed: list[dict[str, Any]] = []

    for identity, node in after.items():
        old = before.get(identity)
        if old is None:
            added.append(_change_record(None, node))
            continue
        if old.native_label != node.native_label:
            renamed.append(
                _change_record(
                    old,
                    node,
                    fields={"before": old.native_label, "after": node.native_label},
                )
            )
        if old.parent_node_key != node.parent_node_key:
            moved.append(
                _change_record(
                    old,
                    node,
                    fields={
                        "before_parent_node_key": old.parent_node_key,
                        "after_parent_node_key": node.parent_node_key,
                    },
                )
            )
        if old.alias_of_node_key != node.alias_of_node_key:
            alias_changed.append(
                _change_record(
                    old,
                    node,
                    fields={
                        "before_alias_of_node_key": old.alias_of_node_key,
                        "after_alias_of_node_key": node.alias_of_node_key,
                    },
                )
            )
        old_capabilities = (
            old.selectable,
            old.supports_exact,
            old.supports_subtree,
            old.queryable,
        )
        new_capabilities = (
            node.selectable,
            node.supports_exact,
            node.supports_subtree,
            node.queryable,
        )
        if old_capabilities != new_capabilities:
            capabilities_changed.append(
                _change_record(
                    old,
                    node,
                    fields={
                        "before": list(old_capabilities),
                        "after": list(new_capabilities),
                    },
                )
            )
        if old.query_semantics_hash != node.query_semantics_hash:
            query_semantics_changed.append(
                _change_record(
                    old,
                    node,
                    fields={
                        "before_hash": old.query_semantics_hash,
                        "after_hash": node.query_semantics_hash,
                    },
                )
            )

    for identity, node in before.items():
        if identity not in after:
            removed.append(_change_record(node, None))

    return CatalogDiff(
        added=tuple(added),
        removed=tuple(removed),
        renamed=tuple(renamed),
        moved=tuple(moved),
        alias_changed=tuple(alias_changed),
        capabilities_changed=tuple(capabilities_changed),
        query_semantics_changed=tuple(query_semantics_changed),
    )


def validate_catalog(catalog: DiscoveredCatalog) -> CatalogValidationReport:
    if catalog.version != 1:
        raise CatalogValidationError("CATALOG_SCHEMA_UNSUPPORTED", "Catalog version must be 1")
    if catalog.source_site not in SUPPORTED_SOURCE_SITES:
        raise CatalogValidationError(
            "CATALOG_SOURCE_UNSUPPORTED", f"Unsupported source {catalog.source_site!r}"
        )

    by_key: dict[str, CatalogNodeSnapshot] = {}
    by_classification: dict[str, CatalogNodeSnapshot] = {}
    for node in catalog.nodes:
        if not node.node_key or node.node_key in by_key:
            raise CatalogValidationError(
                "CATALOG_NODE_KEY_DUPLICATE",
                f"Duplicate or empty node key {node.node_key!r}",
                node_key=node.node_key,
            )
        by_key[node.node_key] = node
        if node.source_site != catalog.source_site:
            raise CatalogValidationError(
                "CATALOG_NODE_SOURCE_MISMATCH",
                "Node source does not match catalog source",
                node_key=node.node_key,
            )
        if node.classification_id is not None:
            if not _is_source_qualified_classification_id(
                node.classification_id,
                catalog.source_site,
            ):
                raise CatalogValidationError(
                    "CATALOG_CLASSIFICATION_SOURCE_MISMATCH",
                    "Source Classification identity must be exactly <source>:<token>",
                    node_key=node.node_key,
                )
            if node.classification_id in by_classification:
                raise CatalogValidationError(
                    "CATALOG_CLASSIFICATION_DUPLICATE",
                    f"Duplicate Source Classification {node.classification_id!r}",
                    node_key=node.node_key,
                )
            by_classification[node.classification_id] = node

    children: dict[str, list[CatalogNodeSnapshot]] = defaultdict(list)
    for node in catalog.nodes:
        if node.depth < 0 or len(node.native_path) != node.depth + 1:
            raise CatalogValidationError(
                "CATALOG_PATH_DEPTH_INVALID",
                "Native path length must equal depth + 1",
                node_key=node.node_key,
            )
        if not node.native_path or node.native_path[-1] != node.native_label:
            raise CatalogValidationError(
                "CATALOG_PATH_LABEL_INVALID",
                "Native path must end with the node label",
                node_key=node.node_key,
            )
        if node.parent_node_key is None:
            if node.depth != 0:
                raise CatalogValidationError(
                    "CATALOG_ROOT_DEPTH_INVALID",
                    "Root node depth must be zero",
                    node_key=node.node_key,
                )
        else:
            parent = by_key.get(node.parent_node_key)
            if parent is None:
                raise CatalogValidationError(
                    "CATALOG_PARENT_UNKNOWN",
                    f"Unknown parent {node.parent_node_key!r}",
                    node_key=node.node_key,
                )
            if node.depth != parent.depth + 1 or node.native_path[:-1] != parent.native_path:
                raise CatalogValidationError(
                    "CATALOG_PARENT_PATH_INVALID",
                    "Node depth/path does not extend its parent",
                    node_key=node.node_key,
                )
            children[parent.node_key].append(node)

        if node.alias_of_node_key is not None:
            if node.alias_of_node_key not in by_key or node.alias_of_node_key == node.node_key:
                raise CatalogValidationError(
                    "CATALOG_ALIAS_TARGET_INVALID",
                    "Alias target must be another catalog node",
                    node_key=node.node_key,
                )
            if (
                node.classification_id is not None
                or node.selectable
                or node.queryable
                or node.supports_exact
                or node.supports_subtree
                or node.query_semantics_hash is not None
            ):
                raise CatalogValidationError(
                    "CATALOG_ALIAS_EXECUTABLE",
                    "Alias nodes must remain visible but non-executable",
                    node_key=node.node_key,
                )
        else:
            if node.selectable != (node.classification_id is not None):
                raise CatalogValidationError(
                    "CATALOG_SELECTABILITY_INVALID",
                    "Selectable nodes require one independent Source Classification identity",
                    node_key=node.node_key,
                )
            if (node.supports_exact or node.supports_subtree or node.queryable) and not node.selectable:
                raise CatalogValidationError(
                    "CATALOG_CAPABILITY_INVALID",
                    "Executable capabilities require a selectable node",
                    node_key=node.node_key,
                )
            if node.queryable and not node.query_semantics_hash:
                raise CatalogValidationError(
                    "CATALOG_QUERY_SEMANTICS_MISSING",
                    "Queryable nodes require a query-semantics hash",
                    node_key=node.node_key,
                )
            if node.queryable and not node.supports_exact:
                raise CatalogValidationError(
                    "CATALOG_CAPABILITY_INVALID",
                    "Queryable Source Classifications must support exact scope",
                    node_key=node.node_key,
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_key: str) -> None:
        if node_key in visiting:
            raise CatalogValidationError(
                "CATALOG_HIERARCHY_CYCLE", "Catalog hierarchy contains a cycle", node_key=node_key
            )
        if node_key in visited:
            return
        visiting.add(node_key)
        for child in children.get(node_key, ()):  # pragma: no branch - tiny traversal
            visit(child.node_key)
        visiting.remove(node_key)
        visited.add(node_key)

    for node in catalog.nodes:
        visit(node.node_key)

    roots = catalog.capabilities.all_scope_root_node_keys
    if catalog.capabilities.supports_all_scope and not roots:
        raise CatalogValidationError(
            "CATALOG_ALL_ROOTS_MISSING", "All-classifications support requires declared roots"
        )
    for root_key in roots:
        root = by_key.get(root_key)
        if root is None or root.parent_node_key is not None:
            raise CatalogValidationError(
                "CATALOG_ALL_ROOT_INVALID", f"All-scope root {root_key!r} is not a root node"
            )

    return CatalogValidationReport(
        node_count=len(catalog.nodes),
        selectable_count=sum(node.selectable for node in catalog.nodes),
        queryable_count=sum(node.queryable for node in catalog.nodes),
        fingerprint=catalog.fingerprint,
    )


def validate_compiled_catalog(
    catalog: DiscoveredCatalog,
    compiler: CatalogCompiler,
) -> CompiledCatalogValidationReport:
    """Compile every queryable node and prove the node semantics match its targets."""

    validate_catalog(catalog)
    if compiler.source_site != catalog.source_site:
        raise CatalogValidationError(
            "CATALOG_ADAPTER_SOURCE_MISMATCH",
            "Source Catalog adapter does not own this catalog",
        )
    target_fingerprints: list[str] = []
    seen_targets: set[str] = set()
    for node in catalog.nodes:
        if not node.queryable:
            continue
        targets = compiler.compile(node)
        if not targets:
            raise CatalogValidationError(
                "CATALOG_QUERY_TARGET_MISSING",
                "Queryable node compiled to no Query Target",
                node_key=node.node_key,
            )
        for target in targets:
            if target.classification_id != node.classification_id:
                raise CatalogValidationError(
                    "CATALOG_QUERY_TARGET_CLASSIFICATION_MISMATCH",
                    "Query Target identity differs from its Source Classification",
                    node_key=node.node_key,
                )
            if target.fingerprint in seen_targets:
                raise CatalogValidationError(
                    "CATALOG_QUERY_TARGET_DUPLICATE",
                    "Two catalog nodes compiled to the same Query Target",
                    node_key=node.node_key,
                )
            seen_targets.add(target.fingerprint)
            target_fingerprints.append(target.fingerprint)
        semantics_hash = (
            targets[0].fingerprint
            if len(targets) == 1
            else payload_fingerprint([target.to_payload() for target in targets])
        )
        if node.query_semantics_hash != semantics_hash:
            raise CatalogValidationError(
                "CATALOG_QUERY_SEMANTICS_MISMATCH",
                "Node query-semantics hash does not match compiled Query Targets",
                node_key=node.node_key,
            )
    return CompiledCatalogValidationReport(
        source_site=catalog.source_site,
        node_count=len(catalog.nodes),
        target_count=len(target_fingerprints),
        target_fingerprints=tuple(target_fingerprints),
    )


def expand_catalog_scope(
    catalog: DiscoveredCatalog,
    *,
    mode: Literal["all", "exact", "subtree"],
    classification_ids: Sequence[str] = (),
) -> tuple[CatalogNodeSnapshot, ...]:
    validate_catalog(catalog)
    by_key = {node.node_key: node for node in catalog.nodes}
    by_classification = {
        node.classification_id: node
        for node in catalog.nodes
        if node.classification_id is not None
    }
    children: dict[str, list[CatalogNodeSnapshot]] = defaultdict(list)
    for node in catalog.nodes:
        if node.parent_node_key is not None:
            children[node.parent_node_key].append(node)

    selected: list[CatalogNodeSnapshot] = []
    seen_node_keys: set[str] = set()

    def include(node: CatalogNodeSnapshot) -> None:
        if node.queryable and node.node_key not in seen_node_keys:
            selected.append(node)
            seen_node_keys.add(node.node_key)

    def include_subtree(node: CatalogNodeSnapshot) -> None:
        include(node)
        for child in children.get(node.node_key, ()):  # source order is revision order
            if child.alias_of_node_key is None:
                include_subtree(child)

    if mode == "all":
        if not catalog.capabilities.supports_all_scope:
            raise CatalogValidationError(
                "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                "This Source Catalog does not support all-classifications scope",
            )
        for root_key in catalog.capabilities.all_scope_root_node_keys:
            include_subtree(by_key[root_key])
        return tuple(selected)

    if not classification_ids:
        raise CatalogValidationError(
            "SOURCE_CLASSIFICATION_UNKNOWN", "Exact/Subtree scope requires classifications"
        )
    for classification_id in classification_ids:
        node = by_classification.get(str(classification_id))
        if node is None:
            raise CatalogValidationError(
                "SOURCE_CLASSIFICATION_UNKNOWN",
                f"Unknown Source Classification {classification_id!r}",
            )
        if mode == "exact":
            if not node.supports_exact or not node.queryable:
                raise CatalogValidationError(
                    "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                    f"Source Classification {classification_id!r} has no exact query",
                    node_key=node.node_key,
                )
            include(node)
        elif mode == "subtree":
            if not node.supports_subtree:
                raise CatalogValidationError(
                    "SOURCE_CLASSIFICATION_NOT_EXECUTABLE",
                    f"Source Classification {classification_id!r} does not support subtree scope",
                    node_key=node.node_key,
                )
            include_subtree(node)
        else:
            raise CatalogValidationError("CATALOG_SCOPE_MODE_INVALID", f"Unknown scope mode {mode!r}")
    return tuple(selected)


def expansion_fingerprint(nodes: Sequence[CatalogNodeSnapshot]) -> str:
    return payload_fingerprint(
        [
            {
                "node_key": node.node_key,
                "classification_id": node.classification_id,
                "query_semantics_hash": node.query_semantics_hash,
            }
            for node in nodes
        ]
    )
