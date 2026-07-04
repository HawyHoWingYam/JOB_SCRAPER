from __future__ import annotations

from app.sources.offertoday.search_space import (
    DEFAULT_OFFERTODAY_IT_KEYWORDS,
    DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS,
    OFFERTODAY_IT_CATEGORY_CODES,
    build_offertoday_listing_queries,
    expand_offertoday_category_ids,
    normalize_offertoday_keywords,
)


class TestOffertodaySearchSpace:
    def test_expands_it_category_to_leaf_codes(self) -> None:
        expanded = expand_offertoday_category_ids([118000])
        assert expanded == list(OFFERTODAY_IT_CATEGORY_CODES)

    def test_defaults_to_it_leaf_codes_when_no_category_ids(self) -> None:
        expanded = expand_offertoday_category_ids([])
        assert expanded == list(OFFERTODAY_IT_CATEGORY_CODES)

    def test_normalizes_keyword_string(self) -> None:
        keywords = normalize_offertoday_keywords("ERP, SAP, , IT")
        assert keywords == ["ERP", "SAP", "IT"]

    def test_build_offertoday_listing_queries_emits_category_and_keyword_families(self) -> None:
        queries = list(
            build_offertoday_listing_queries(
                [118000],
                keywords=None,
                max_pages_per_query=2,
            )
        )

        assert queries[:2] == [
            {
                "search_family": "it_category",
                "category_id": 118000,
                "keyword": "",
                "page": 1,
                "endpoint": "browse",
            },
            {
                "search_family": "it_category",
                "category_id": 118000,
                "keyword": "",
                "page": 2,
                "endpoint": "browse",
            },
        ]
        category_query_count = len(OFFERTODAY_IT_CATEGORY_CODES) * 2
        keyword_query_count = len(DEFAULT_OFFERTODAY_IT_KEYWORDS) * 2
        hybrid_query_count = len(DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS) * 2
        keyword_queries = queries[category_query_count : category_query_count + keyword_query_count]
        hybrid_queries = queries[category_query_count + keyword_query_count :]

        assert [query["search_family"] for query in queries[:category_query_count]] == [
            "it_category"
        ] * category_query_count
        assert [query["search_family"] for query in keyword_queries] == [
            "it_keyword"
        ] * keyword_query_count
        assert [query["keyword"] for query in keyword_queries if query["page"] == 1] == list(
            DEFAULT_OFFERTODAY_IT_KEYWORDS
        )
        assert keyword_queries[0] == {
            "search_family": "it_keyword",
            "category_id": None,
            "keyword": "IT",
            "page": 1,
        }
        assert [query["search_family"] for query in hybrid_queries] == [
            "it_hybrid"
        ] * hybrid_query_count
        assert [query["keyword"] for query in hybrid_queries if query["page"] == 1] == list(
            DEFAULT_OFFERTODAY_IT_HYBRID_KEYWORDS
        )
        assert hybrid_queries[0] == {
            "search_family": "it_hybrid",
            "category_id": 118000,
            "keyword": "network engineer",
            "page": 1,
        }
        assert len(queries) == (
            category_query_count
            + keyword_query_count
            + hybrid_query_count
        )

    def test_explicit_keyword_probe_is_keyword_only(self) -> None:
        queries = list(
            build_offertoday_listing_queries(
                [118000],
                keywords=["ERP"],
                max_pages_per_query=2,
            )
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
