"""OfferToday job function (position) category registry.

Fetched from the live filter API at:
  GET https://www.offertoday.com/wapi/geek/recommend/filter/content/all
  → data.[lang].POSITION

This registry is static (not live-fetched) for simplicity. If you need
to refresh categories, re-scrape the filter API and update this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class OfferTodayCategory:
    """A single category node from the POSITION taxonomy."""

    code: int
    name: str
    parent_code: int
    level: int
    children: tuple[OfferTodayCategory, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "parent_code": self.parent_code,
            "level": self.level,
        }


# L1 categories — 31 top-level positions
# fmt: off
OFFERTODAY_CATEGORIES_L1: tuple[OfferTodayCategory, ...] = (
    OfferTodayCategory(101000, "Accounting", 0, 1),
    OfferTodayCategory(102000, "Administration & Office Support", 0, 1),
    OfferTodayCategory(103000, "Advertising & Media", 0, 1),
    OfferTodayCategory(104000, "Banking & Financial Services", 0, 1),
    OfferTodayCategory(105000, "Customer Service", 0, 1),
    OfferTodayCategory(106000, "CEO & General Management", 0, 1),
    OfferTodayCategory(107000, "Community Services", 0, 1),
    OfferTodayCategory(108000, "Construction", 0, 1),
    OfferTodayCategory(109000, "Consulting", 0, 1),
    OfferTodayCategory(110000, "Design", 0, 1),
    OfferTodayCategory(111000, "Education", 0, 1),
    OfferTodayCategory(112000, "Engineering", 0, 1),
    OfferTodayCategory(113000, "Farming", 0, 1),
    OfferTodayCategory(114000, "Government", 0, 1),
    OfferTodayCategory(115000, "Healthcare & Medical", 0, 1),
    OfferTodayCategory(116000, "Hospitality & Catering & Tourism", 0, 1),
    OfferTodayCategory(117000, "Human Resources & Recruitment", 0, 1),
    OfferTodayCategory(118000, "Information Technology", 0, 1),
    OfferTodayCategory(119000, "Insurance", 0, 1),
    OfferTodayCategory(120000, "Legal", 0, 1),
    OfferTodayCategory(121000, "Manufacturing & Logistics", 0, 1),
    OfferTodayCategory(122000, "Marketing & Communications", 0, 1),
    OfferTodayCategory(123000, "Natural Energy", 0, 1),
    OfferTodayCategory(124000, "Real Estate & Property", 0, 1),
    OfferTodayCategory(125000, "Retail & Consumer Products", 0, 1),
    OfferTodayCategory(126000, "Sales", 0, 1),
    OfferTodayCategory(127000, "Science & Technology", 0, 1),
    OfferTodayCategory(128000, "Self Employment", 0, 1),
    OfferTodayCategory(129000, "Sport", 0, 1),
    OfferTodayCategory(130000, "Trades & Services", 0, 1),
    OfferTodayCategory(999000, "Other", 0, 1),
)
# fmt: on


def get_offertoday_category(code: int) -> OfferTodayCategory | None:
    """Look up a category by code."""
    for cat in OFFERTODAY_CATEGORIES_L1:
        if cat.code == code:
            return cat
    return None


def get_all_offertoday_categories() -> list[dict[str, Any]]:
    """Return all L1 categories as plain dicts (for the source_category_registry)."""
    return [
        {
            "id": cat.code,
            "name": cat.name,
            "code": cat.code,
            "slug": cat.name.lower().replace(" & ", "-").replace(" ", "-"),
            "source_site": "offertoday",
        }
        for cat in OFFERTODAY_CATEGORIES_L1
    ]
