from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.job_intelligence.foundation import normalized_content_hash


HSIC_RELEASE_KEY = "hsic-v2.0-2008"
HSIC_OVERVIEW_URL = "https://www.censtatd.gov.hk/en/page_698.html"
HSIC_HIERARCHY_URL = (
    "https://www.censtatd.gov.hk/search/index.php?"
    "lang_search=en&l=web&c=HsicCode&m=structure"
)
HSIC_TERMS_URL = "https://www.censtatd.gov.hk/en/page_31.html"
HSIC_OFFICIAL_COUNTS = {
    "section": 21,
    "division": 88,
    "group": 221,
    "class": 483,
    "subclass": 1001,
}

_LEVEL_SOURCES = (
    ("section", "queryArray1"),
    ("division", "queryArray2"),
    ("group", "queryArray3"),
    ("class", "queryArray4"),
    ("subclass", "queryArray5"),
)


def _parent_code(level: str, row: Mapping[str, Any]) -> str | None:
    code = str(row.get("HSIC20") or "").strip()
    if level == "section":
        return None
    if level == "division":
        return str(row.get("Array1") or "").strip()
    return {
        "group": code[:2],
        "class": code[:3],
        "subclass": code[:4],
    }[level]


def _governed_content(seed: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: seed[key]
        for key in (
            "schema_version",
            "standard",
            "release",
            "release_key",
            "source",
            "expected_counts",
            "nodes",
            "crosswalks",
        )
    }


def seed_content_hash(seed: Mapping[str, Any]) -> str:
    return normalized_content_hash(_governed_content(seed))


def build_hsic_seed(
    raw_document: Mapping[str, Any],
    *,
    retrieved_at: str,
    raw_sha256: str,
    expected_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Transform the public C&SD hierarchy response into the project seed."""

    nodes: list[dict[str, Any]] = []
    source_order = 0
    for level, source_key in _LEVEL_SOURCES:
        source_rows = raw_document.get(source_key)
        if not isinstance(source_rows, list):
            raise ValueError(f"Official HSIC payload is missing {source_key}")
        for item in source_rows:
            if not isinstance(item, Mapping):
                raise ValueError(
                    f"Official HSIC {source_key} contains a non-object row"
                )
            source_order += 1
            nodes.append(
                {
                    "code": str(item.get("HSIC20") or "").strip(),
                    "parent_code": _parent_code(level, item),
                    "level": level,
                    "labels": {
                        "en": str(item.get("ENG_TITLE") or "").strip(),
                        "zh_hant": str(item.get("CHI_TITLE") or "").strip(),
                        "zh_hans": str(item.get("SC_TITLE") or "").strip(),
                    },
                    "source_order": source_order,
                }
            )

    seed: dict[str, Any] = {
        "schema_version": 1,
        "standard": "HSIC",
        "release": "V2.0",
        "release_key": HSIC_RELEASE_KEY,
        "source": {
            "publisher": "Hong Kong Census and Statistics Department",
            "rights_owner": (
                "Government of the Hong Kong Special Administrative Region"
            ),
            "overview_url": HSIC_OVERVIEW_URL,
            "hierarchy_url": HSIC_HIERARCHY_URL,
            "terms_url": HSIC_TERMS_URL,
            "retrieved_at": retrieved_at,
            "raw_sha256": raw_sha256,
            "modifications": [
                "Descriptions omitted",
                "Parent codes and global source order derived",
                "Fields normalized into the project seed schema",
            ],
        },
        "expected_counts": dict(expected_counts or HSIC_OFFICIAL_COUNTS),
        "nodes": nodes,
        "crosswalks": [],
    }
    seed["content_hash"] = seed_content_hash(seed)
    return seed


__all__ = [
    "HSIC_HIERARCHY_URL",
    "HSIC_OFFICIAL_COUNTS",
    "HSIC_OVERVIEW_URL",
    "HSIC_RELEASE_KEY",
    "HSIC_TERMS_URL",
    "build_hsic_seed",
    "seed_content_hash",
]
