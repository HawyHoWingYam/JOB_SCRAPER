from __future__ import annotations

import hashlib
import json
from dataclasses import fields

import pytest

from app.sources.offertoday import search_space
from app.sources.offertoday.constants import build_offertoday_listing_payload
from app.sources.offertoday.listing_runner import OfferTodayListingCondition
from app.sources.offertoday.search_space import (
    build_offertoday_census_conditions,
    build_offertoday_listing_conditions,
)


EXPECTED_OFFERTODAY_IT_CATEGORY_IDS = (
    118000,
    118001,
    118002,
    118003,
    118004,
    118005,
    118006,
    118007,
    118008,
    118009,
    118010,
    118011,
    118012,
    118013,
    118014,
    118015,
    118016,
    118017,
    118018,
    118019,
    118020,
    118021,
    118999,
)

EXPECTED_OFFERTODAY_CENSUS_CATEGORY_IDS = (
    101000,
    102000,
    103000,
    104000,
    105000,
    106000,
    107000,
    108000,
    109000,
    110000,
    111000,
    112000,
    113000,
    114000,
    115000,
    116000,
    117000,
    118000,
    119000,
    120000,
    121000,
    122000,
    123000,
    124000,
    125000,
    126000,
    127000,
    128000,
    129000,
    130000,
    999000,
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


@pytest.mark.parametrize("endpoint", ["", "SEARCH", "detail", 1, [], {}])
def test_listing_condition_rejects_unknown_endpoint(endpoint: object) -> None:
    with pytest.raises(
        ValueError,
        match="endpoint must be 'search' or 'browse'",
    ):
        OfferTodayListingCondition(
            search_family="explicit_keyword",
            category_id=None,
            keyword="ERP",
            endpoint=endpoint,
        )


@pytest.mark.parametrize("rcd_type", [True, False, "7", 7.0])
def test_listing_condition_rejects_non_integer_rcd_type(rcd_type: object) -> None:
    with pytest.raises(ValueError, match="rcd_type must be an int or None"):
        OfferTodayListingCondition(
            search_family="explicit_keyword",
            category_id=None,
            keyword="ERP",
            endpoint="search",
            rcd_type=rcd_type,
        )


def test_default_conditions_keep_stable_family_order_and_endpoint_semantics() -> None:
    conditions = build_offertoday_listing_conditions(
        [118000],
        endpoint="search",
        rcd_type=9,
    )
    category_conditions = conditions[:23]
    keyword_conditions = conditions[23:136]
    hybrid_conditions = conditions[136:]

    assert len(conditions) == 152
    assert [condition.search_family for condition in category_conditions] == [
        "it_category"
    ] * 23
    assert [condition.category_id for condition in category_conditions] == list(
        EXPECTED_OFFERTODAY_IT_CATEGORY_IDS
    )
    assert all(condition.endpoint == "browse" for condition in category_conditions)

    assert len(keyword_conditions) == 113
    assert keyword_conditions[0].keyword == "IT"
    assert keyword_conditions[-1].keyword == "quantum"
    assert all(
        condition.search_family == "it_keyword" for condition in keyword_conditions
    )
    assert all(
        condition.category_id is None and condition.endpoint == "search"
        for condition in keyword_conditions
    )

    assert len(hybrid_conditions) == 16
    assert hybrid_conditions[0].keyword == "engineer"
    assert hybrid_conditions[-1].keyword == "coordinator"
    assert all(
        condition.search_family == "it_hybrid" for condition in hybrid_conditions
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

    assert len(EXPECTED_OFFERTODAY_CENSUS_CATEGORY_IDS) == 31
    assert len(set(EXPECTED_OFFERTODAY_CENSUS_CATEGORY_IDS)) == 31
    assert [condition.category_id for condition in conditions] == list(
        EXPECTED_OFFERTODAY_CENSUS_CATEGORY_IDS
    )
    assert len({condition.condition_id for condition in conditions}) == 31
    assert all(condition.search_family == "census_category" for condition in conditions)
    assert all(condition.keyword == "" for condition in conditions)
    assert all(condition.endpoint == endpoint for condition in conditions)
    assert all(condition.rcd_type is None for condition in conditions)


def test_legacy_listing_queries_wrap_typed_conditions_without_shape_or_order_drift() -> (
    None
):
    queries = search_space.build_offertoday_listing_queries(
        [118000],
        max_pages_per_query=2,
    )

    assert len(queries) == 304
    assert queries[0] == {
        "search_family": "it_category",
        "category_id": 118000,
        "keyword": "",
        "page": 1,
        "endpoint": "browse",
    }
    assert queries[45] == {
        "search_family": "it_category",
        "category_id": 118999,
        "keyword": "",
        "page": 2,
        "endpoint": "browse",
    }
    assert queries[46] == {
        "search_family": "it_keyword",
        "category_id": None,
        "keyword": "IT",
        "page": 1,
    }
    assert queries[271] == {
        "search_family": "it_keyword",
        "category_id": None,
        "keyword": "quantum",
        "page": 2,
    }
    assert queries[272] == {
        "search_family": "it_hybrid",
        "category_id": 118000,
        "keyword": "engineer",
        "page": 1,
    }
    assert queries[-1] == {
        "search_family": "it_hybrid",
        "category_id": 118000,
        "keyword": "coordinator",
        "page": 2,
    }


def test_legacy_non_it_category_queries_are_golden() -> None:
    queries = search_space.build_offertoday_listing_queries(
        [101000],
        max_pages_per_query=2,
        default_to_it=False,
    )

    assert queries == [
        {
            "search_family": "category_search",
            "category_id": 101000,
            "keyword": "",
            "page": 1,
            "endpoint": "browse",
        },
        {
            "search_family": "category_search",
            "category_id": 101000,
            "keyword": "",
            "page": 2,
            "endpoint": "browse",
        },
    ]


def test_legacy_mixed_duplicate_categories_are_deduped_in_input_order() -> None:
    queries = search_space.build_offertoday_listing_queries(
        [101000, 118001, 101000, 102000],
        max_pages_per_query=1,
        default_to_it=False,
    )

    assert queries == [
        {
            "search_family": "category_search",
            "category_id": 101000,
            "keyword": "",
            "page": 1,
            "endpoint": "browse",
        },
        {
            "search_family": "it_category",
            "category_id": 118001,
            "keyword": "",
            "page": 1,
            "endpoint": "browse",
        },
        {
            "search_family": "category_search",
            "category_id": 102000,
            "keyword": "",
            "page": 1,
            "endpoint": "browse",
        },
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
    assert default_payload["pageSize"] == 50
    assert "sessionId" not in default_payload
    assert "supplePage" not in default_payload
    assert "suppleAmount" not in default_payload
    assert "suppleType" not in default_payload
    assert custom_payload["rcdType"] == 9
    assert "rcdType" not in no_rcd_payload


@pytest.mark.parametrize("rcd_type", [True, False, "7", 7.0])
def test_listing_payload_rejects_non_integer_rcd_type(rcd_type: object) -> None:
    with pytest.raises(ValueError, match="rcd_type must be an int or None"):
        build_offertoday_listing_payload(
            category_id=None,
            keyword="ERP",
            page=1,
            rcd_type=rcd_type,
        )


def test_listing_queries_reject_non_positive_page_count() -> None:
    with pytest.raises(ValueError, match="max_pages_per_query must be >= 1"):
        search_space.build_offertoday_listing_queries([], max_pages_per_query=0)
