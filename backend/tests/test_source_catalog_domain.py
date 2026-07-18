from __future__ import annotations

from dataclasses import replace

import pytest

from app.source_catalog.domain import (
    CatalogNodeSnapshot,
    CatalogScopeCapabilities,
    CatalogValidationError,
    DiscoveredCatalog,
    diff_catalogs,
    expand_catalog_scope,
    expansion_fingerprint,
    validate_catalog,
)


def _offertoday_like_catalog() -> DiscoveredCatalog:
    return DiscoveredCatalog(
        source_site="offertoday",
        nodes=(
            CatalogNodeSnapshot(
                node_key="root:118000",
                source_site="offertoday",
                classification_id="offertoday:118000",
                native_id=118000,
                native_label="Information Technology",
                parent_node_key=None,
                native_path=("Information Technology",),
                depth=0,
                selectable=True,
                supports_exact=True,
                supports_subtree=True,
                queryable=True,
                alias_of_node_key=None,
                query_semantics_hash="1" * 64,
                source_metadata={},
            ),
            CatalogNodeSnapshot(
                node_key="alias:118000:118000",
                source_site="offertoday",
                classification_id=None,
                native_id=118000,
                native_label="All Information Technology",
                parent_node_key="root:118000",
                native_path=("Information Technology", "All Information Technology"),
                depth=1,
                selectable=False,
                supports_exact=False,
                supports_subtree=False,
                queryable=False,
                alias_of_node_key="root:118000",
                query_semantics_hash=None,
                source_metadata={"relationship": "same-code-alias"},
            ),
            CatalogNodeSnapshot(
                node_key="leaf:118101",
                source_site="offertoday",
                classification_id="offertoday:118101",
                native_id=118101,
                native_label="Software Development",
                parent_node_key="root:118000",
                native_path=("Information Technology", "Software Development"),
                depth=1,
                selectable=True,
                supports_exact=True,
                supports_subtree=False,
                queryable=True,
                alias_of_node_key=None,
                query_semantics_hash="2" * 64,
                source_metadata={},
            ),
        ),
        capabilities=CatalogScopeCapabilities(
            supports_all_scope=True,
            all_scope_root_node_keys=("root:118000",),
            recommended_scope={
                "mode": "subtree",
                "classification_ids": ["offertoday:118000"],
            },
        ),
        source_payload={"fixture": True},
        provenance={"discovered_at": "ignored-by-fingerprint"},
    )


def test_all_and_subtree_expansion_keep_alias_visible_without_query_duplication():
    catalog = _offertoday_like_catalog()

    report = validate_catalog(catalog)
    all_nodes = expand_catalog_scope(catalog, mode="all")
    subtree_nodes = expand_catalog_scope(
        catalog,
        mode="subtree",
        classification_ids=("offertoday:118000",),
    )

    assert report.node_count == 3
    assert report.queryable_count == 2
    assert [node.classification_id for node in all_nodes] == [
        "offertoday:118000",
        "offertoday:118101",
    ]
    assert subtree_nodes == all_nodes
    assert expansion_fingerprint(all_nodes) == expansion_fingerprint(subtree_nodes)


@pytest.mark.parametrize(
    "classification_id",
    (
        "offertoday:",
        "offertoday:118000:child",
        "offertoday: 118000",
        "jobsdb:118000",
    ),
)
def test_catalog_rejects_ambiguous_source_classification_identity(
    classification_id,
):
    catalog = _offertoday_like_catalog()
    malformed = replace(
        catalog,
        nodes=(replace(catalog.nodes[0], classification_id=classification_id),)
        + catalog.nodes[1:],
    )

    with pytest.raises(CatalogValidationError) as exc_info:
        validate_catalog(malformed)

    assert exc_info.value.code == "CATALOG_CLASSIFICATION_SOURCE_MISMATCH"


def test_catalog_diff_separates_operator_visible_and_query_semantic_changes():
    previous = _offertoday_like_catalog()
    root, alias, leaf = previous.nodes
    renamed_root = replace(
        root,
        native_label="IT",
        native_path=("IT",),
    )
    changed_leaf = replace(
        leaf,
        native_path=("IT", "Software Development"),
        supports_subtree=True,
        query_semantics_hash="3" * 64,
    )
    new_leaf = replace(
        leaf,
        node_key="leaf:118102",
        classification_id="offertoday:118102",
        native_id=118102,
        native_label="Cybersecurity",
        native_path=("IT", "Cybersecurity"),
        query_semantics_hash="4" * 64,
    )
    current = replace(
        previous,
        nodes=(
            renamed_root,
            replace(alias, native_path=("IT", "All Information Technology")),
            changed_leaf,
            new_leaf,
        ),
    )

    diff = diff_catalogs(previous, current)

    assert [item["classification_id"] for item in diff.added] == [
        "offertoday:118102"
    ]
    assert [item["classification_id"] for item in diff.renamed] == [
        "offertoday:118000"
    ]
    assert [item["classification_id"] for item in diff.capabilities_changed] == [
        "offertoday:118101"
    ]
    assert [item["classification_id"] for item in diff.query_semantics_changed] == [
        "offertoday:118101"
    ]
    assert diff.removed == ()


def test_catalog_fingerprint_ignores_optional_canonical_taxonomy_annotations():
    catalog = _offertoday_like_catalog()
    annotated = replace(
        catalog,
        nodes=(
            replace(
                catalog.nodes[0],
                source_metadata={
                    "canonical_job_taxonomy": {"category": "software"},
                    "mapping_status": "reviewed",
                },
            ),
            *catalog.nodes[1:],
        ),
        provenance={"discovered_at": "another-time"},
    )

    assert annotated.fingerprint == catalog.fingerprint
