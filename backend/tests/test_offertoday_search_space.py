from __future__ import annotations

import hashlib
import json
from dataclasses import fields

import pytest

from app.scraper.offertoday.category_registry import OFFERTODAY_CATEGORIES_L1
from app.sources.offertoday import search_space
from app.sources.offertoday.constants import build_offertoday_listing_payload
from app.sources.offertoday.listing_runner import OfferTodayListingCondition
from app.sources.offertoday.search_space import (
    build_offertoday_census_conditions,
    build_offertoday_listing_conditions,
)


def test_listing_condition_id_is_canonical_and_semantic() -> None:
    baseline_values = {
        "search_family": "it_hybrid",
        "category_id": 118000,
        "keyword": "developer",
        "endpoint": "search",
        "rcd_type": 7,
    }
    baseline = OfferTodayListingCondition(**baseline_values)
    canonical_json = json.dumps(
        {
            "category_id": 118000,
            "endpoint": "search",
            "keyword": "developer",
            "rcd_type": 7,
            "search_family": "it_hybrid",
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )

    assert [field.name for field in fields(baseline)] == [
        "search_family",
        "category_id",
        "keyword",
        "endpoint",
        "rcd_type",
    ]
    assert baseline.condition_id == hashlib.sha256(canonical_json.encode()).hexdigest()
    assert (
        OfferTodayListingCondition(**baseline_values).condition_id
        == baseline.condition_id
    )

    semantic_variants = (
        {**baseline_values, "search_family": "explicit_keyword"},
        {**baseline_values, "category_id": None},
        {**baseline_values, "keyword": "engineer"},
        {**baseline_values, "endpoint": "browse"},
        {**baseline_values, "rcd_type": None},
    )
    assert (
        len(
            {
                OfferTodayListingCondition(**values).condition_id
                for values in semantic_variants
            }
        )
        == 5
    )
    assert all(
        OfferTodayListingCondition(**values).condition_id != baseline.condition_id
        for values in semantic_variants
    )


def test_default_conditions_keep_stable_family_order_and_endpoint_semantics() -> None:
    conditions = build_offertoday_listing_conditions(
        [118000],
        endpoint="search",
        rcd_type=9,
    )
    category_count = len(search_space.OFFERTODAY_IT_CATEGORY_CODES)
    keyword_count = len(search_space.DEFAULT_OFFERTODAY_IT_KEYWORDS)
    hybrid_count = len(search_space.DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS)

    assert [condition.search_family for condition in conditions] == (
        ["it_category"] * category_count
        + ["it_keyword"] * keyword_count
        + ["it_hybrid"] * hybrid_count
    )
    assert [condition.category_id for condition in conditions[:category_count]] == list(
        search_space.OFFERTODAY_IT_CATEGORY_CODES
    )
    assert all(
        condition.endpoint == "browse" for condition in conditions[:category_count]
    )

    keyword_conditions = conditions[category_count : category_count + keyword_count]
    assert [condition.keyword for condition in keyword_conditions] == list(
        search_space.DEFAULT_OFFERTODAY_IT_KEYWORDS
    )
    assert all(
        condition.category_id is None and condition.endpoint == "search"
        for condition in keyword_conditions
    )

    hybrid_conditions = conditions[-hybrid_count:]
    assert [condition.keyword for condition in hybrid_conditions] == list(
        search_space.DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS
    )
    assert all(
        condition.category_id == 118000 and condition.endpoint == "search"
        for condition in hybrid_conditions
    )
    assert all(condition.rcd_type == 9 for condition in conditions)


def test_explicit_keywords_are_the_only_conditions_and_use_selected_endpoint() -> None:
    conditions = build_offertoday_listing_conditions(
        [118000, 101000],
        keywords="ERP, SAP, ERP",
        endpoint="browse",
        rcd_type=None,
    )

    assert [
        (
            condition.search_family,
            condition.category_id,
            condition.keyword,
            condition.endpoint,
            condition.rcd_type,
        )
        for condition in conditions
    ] == [
        ("explicit_keyword", None, "ERP", "browse", None),
        ("explicit_keyword", None, "SAP", "browse", None),
    ]


def test_non_it_category_uses_category_search_family_and_browse_endpoint() -> None:
    conditions = build_offertoday_listing_conditions(
        [101000],
        default_to_it=False,
        endpoint="search",
        rcd_type=3,
    )

    assert len(conditions) == 1
    condition = conditions[0]
    assert (
        condition.search_family,
        condition.category_id,
        condition.keyword,
        condition.endpoint,
        condition.rcd_type,
    ) == ("category_search", 101000, "", "browse", 3)


@pytest.mark.parametrize("endpoint", ["search", "browse"])
def test_census_conditions_are_exactly_canonical_l1_categories(endpoint: str) -> None:
    conditions = build_offertoday_census_conditions(endpoint=endpoint, rcd_type=None)

    assert len(conditions) == len(OFFERTODAY_CATEGORIES_L1) == 31
    assert [condition.category_id for condition in conditions] == [
        category.code for category in OFFERTODAY_CATEGORIES_L1
    ]
    assert all(condition.search_family == "census_category" for condition in conditions)
    assert all(condition.keyword == "" for condition in conditions)
    assert all(condition.endpoint == endpoint for condition in conditions)
    assert all(condition.rcd_type is None for condition in conditions)


def test_legacy_listing_queries_wrap_typed_conditions_without_shape_or_order_drift() -> (
    None
):
    conditions = build_offertoday_listing_conditions([118000])
    queries = search_space.build_offertoday_listing_queries(
        [118000],
        max_pages_per_query=2,
    )
    expected_queries: list[dict[str, object]] = []
    for condition in conditions:
        for page in (1, 2):
            query: dict[str, object] = {
                "search_family": condition.search_family,
                "category_id": condition.category_id,
                "keyword": condition.keyword,
                "page": page,
            }
            if condition.search_family in {"it_category", "category_search"}:
                query["endpoint"] = "browse"
            expected_queries.append(query)

    assert queries == expected_queries
    assert list(queries[0]) == [
        "search_family",
        "category_id",
        "keyword",
        "page",
        "endpoint",
    ]
    first_keyword_query = queries[len(search_space.OFFERTODAY_IT_CATEGORY_CODES) * 2]
    assert list(first_keyword_query) == [
        "search_family",
        "category_id",
        "keyword",
        "page",
    ]


def test_legacy_explicit_keyword_queries_preserve_keyword_only_shape() -> None:
    queries = search_space.build_offertoday_listing_queries(
        [118000],
        keywords=["ERP"],
        max_pages_per_query=2,
    )

    assert queries == [
        {
            "search_family": "explicit_keyword",
            "category_id": None,
            "keyword": "ERP",
            "page": 1,
        },
        {
            "search_family": "explicit_keyword",
            "category_id": None,
            "keyword": "ERP",
            "page": 2,
        },
    ]


def test_listing_payload_includes_rcd_type_only_when_requested() -> None:
    default_payload = build_offertoday_listing_payload(
        category_id=118000,
        keyword="developer",
        page=2,
    )
    custom_payload = build_offertoday_listing_payload(
        category_id=None,
        keyword="ERP",
        page=1,
        rcd_type=9,
    )
    no_rcd_payload = build_offertoday_listing_payload(
        category_id=None,
        keyword="ERP",
        page=1,
        rcd_type=None,
    )

    assert default_payload["rcdType"] == 7
    assert custom_payload["rcdType"] == 9
    assert "rcdType" not in no_rcd_payload


def test_listing_queries_reject_non_positive_page_count() -> None:
    with pytest.raises(ValueError, match="max_pages_per_query must be >= 1"):
        search_space.build_offertoday_listing_queries([], max_pages_per_query=0)
