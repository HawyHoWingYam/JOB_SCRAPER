"""Current OfferToday POSITION classification registry."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping


OFFERTODAY_CATEGORY_SOURCE_COMMIT = (
    "ed03f114fb8bc73eeb11139d82325a7944802701"
)
OFFERTODAY_CATEGORY_SOURCE_GIT_BLOB = "80960e8dad9a0f84ca928218ed81bd0133fc18c5"
OFFERTODAY_CATEGORY_SOURCE_ENDPOINT = "/wapi/geek/recommend/filter/content/all"
_REGISTRY_PATH = Path(__file__).with_name("category_registry.json")
_NODE_FIELDS = {"code", "name", "parent_code", "level", "children"}
_REGISTRY_FIELDS = {
    "source_commit",
    "source_git_blob",
    "source_endpoint",
    "language",
    "categories",
}


def _exact_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an exact integer")
    return value


def _nonblank_string(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise ValueError(f"{field_name} must be a nonblank trimmed string")
    return value


@dataclass(frozen=True, slots=True)
class OfferTodayCategory:
    """One current node from the official POSITION taxonomy."""

    code: int
    name: str
    parent_code: int
    level: int
    children: tuple[OfferTodayCategory, ...] = ()

    def __post_init__(self) -> None:
        _exact_int(self.code, "code")
        _nonblank_string(self.name, "name")
        _exact_int(self.parent_code, "parent_code")
        if (
            not isinstance(self.level, int)
            or isinstance(self.level, bool)
            or self.level not in (1, 2)
        ):
            raise ValueError("level must be the exact integer 1 or 2")
        if not isinstance(self.children, tuple) or any(
            not isinstance(child, OfferTodayCategory) for child in self.children
        ):
            raise ValueError("children must be an OfferTodayCategory tuple")
        if self.level == 2 and self.children:
            raise ValueError("level-2 category nodes cannot own children")

    def to_dict(self) -> dict[str, Any]:
        """Return the flat shape used by SourceCategoryRegistry."""

        return {
            "code": self.code,
            "name": self.name,
            "parent_code": self.parent_code,
            "level": self.level,
        }

    def to_registry_dict(self) -> dict[str, Any]:
        return {
            **self.to_dict(),
            "children": [child.to_registry_dict() for child in self.children],
        }


def _parse_node(value: Any) -> OfferTodayCategory:
    if not isinstance(value, Mapping) or set(value) != _NODE_FIELDS:
        raise ValueError("category node fields are invalid")
    children = value["children"]
    if not isinstance(children, list):
        raise ValueError("category children must be a list")
    return OfferTodayCategory(
        code=_exact_int(value["code"], "code"),
        name=_nonblank_string(value["name"], "name"),
        parent_code=_exact_int(value["parent_code"], "parent_code"),
        level=_exact_int(value["level"], "level"),
        children=tuple(_parse_node(child) for child in children),
    )


def _load_registry() -> tuple[OfferTodayCategory, ...]:
    payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != _REGISTRY_FIELDS:
        raise ValueError("OfferToday classification registry fields are invalid")
    expected_metadata = {
        "source_commit": OFFERTODAY_CATEGORY_SOURCE_COMMIT,
        "source_git_blob": OFFERTODAY_CATEGORY_SOURCE_GIT_BLOB,
        "source_endpoint": OFFERTODAY_CATEGORY_SOURCE_ENDPOINT,
        "language": "en",
    }
    if any(payload.get(key) != value for key, value in expected_metadata.items()):
        raise ValueError("OfferToday classification registry provenance is invalid")
    raw_categories = payload["categories"]
    if not isinstance(raw_categories, list):
        raise ValueError("OfferToday classification registry categories must be a list")
    categories = tuple(_parse_node(item) for item in raw_categories)
    if len(categories) != 31 or len({item.code for item in categories}) != 31:
        raise ValueError("OfferToday classification registry must contain 31 unique roots")

    child_count = 0
    alias_count = 0
    query_leaf_codes: set[int] = set()
    for category in categories:
        if category.level != 1 or category.parent_code != 0:
            raise ValueError("OfferToday root category ownership is invalid")
        aliases = 0
        for child in category.children:
            child_count += 1
            if child.level != 2 or child.parent_code != category.code:
                raise ValueError("OfferToday child category ownership is invalid")
            if child.code == category.code:
                aliases += 1
                alias_count += 1
            elif child.code in query_leaf_codes:
                raise ValueError("OfferToday query leaf codes must be unique")
            else:
                query_leaf_codes.add(child.code)
        if aliases != 1:
            raise ValueError("each OfferToday root must own one same-code alias")
    if (child_count, alias_count, len(query_leaf_codes)) != (462, 31, 431):
        raise ValueError("OfferToday classification registry counts do not match")
    return categories


OFFERTODAY_CATEGORIES_L1: tuple[OfferTodayCategory, ...] = _load_registry()


def iter_offertoday_category_nodes() -> Iterator[OfferTodayCategory]:
    for category in OFFERTODAY_CATEGORIES_L1:
        yield category
        yield from category.children


def iter_offertoday_leaf_categories(
    *,
    include_same_code_aliases: bool = False,
) -> Iterator[OfferTodayCategory]:
    for category in OFFERTODAY_CATEGORIES_L1:
        for child in category.children:
            if include_same_code_aliases or child.code != child.parent_code:
                yield child


def offertoday_category_registry_payload() -> dict[str, Any]:
    return {
        "source_commit": OFFERTODAY_CATEGORY_SOURCE_COMMIT,
        "source_git_blob": OFFERTODAY_CATEGORY_SOURCE_GIT_BLOB,
        "source_endpoint": OFFERTODAY_CATEGORY_SOURCE_ENDPOINT,
        "language": "en",
        "categories": [
            category.to_registry_dict() for category in OFFERTODAY_CATEGORIES_L1
        ],
    }


def offertoday_category_registry_hash() -> str:
    canonical = json.dumps(
        offertoday_category_registry_payload(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_offertoday_category(code: int) -> OfferTodayCategory | None:
    """Look up a current top-level category by code."""

    for category in OFFERTODAY_CATEGORIES_L1:
        if category.code == code:
            return category
    return None


def get_all_offertoday_categories() -> list[dict[str, Any]]:
    """Return all current L1 categories for SourceCategoryRegistry."""

    return [
        {
            "id": category.code,
            "name": category.name,
            "code": category.code,
            "slug": category.name.lower().replace(" & ", "-").replace(" ", "-"),
            "source_site": "offertoday",
        }
        for category in OFFERTODAY_CATEGORIES_L1
    ]
