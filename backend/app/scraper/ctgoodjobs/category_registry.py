"""Production CTgoodjobs category registry parsing.

This module intentionally does NOT depend on research-only orchestration.
Parsing logic is extracted from the validated research probe implementation.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from typing import Any


CTGOODJOBS_BASE_URL = "https://jobs.ctgoodjobs.hk"


@dataclass(frozen=True)
class CategoryMapping:
    proposed_internal_domain: str
    mapping_status: str
    mapping_notes: str


@dataclass(frozen=True)
class CTGoodJobsCategory:
    source_site: str
    source_classification_id: str
    ctgoodjobs_id: str
    name: str
    slug: str
    url: str
    child_count: int
    proposed_internal_domain: str
    mapping_status: str
    mapping_notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CTGOODJOBS_CATEGORY_MAPPINGS: dict[str, CategoryMapping] = {
    "ctgoodjobs:001": CategoryMapping("Accounting", "clean_match", "Strong fit"),
    "ctgoodjobs:048": CategoryMapping(
        "Administration & Office Support", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:007": CategoryMapping(
        "Banking & Financial Services", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:004": CategoryMapping(
        "Construction", "conservative_match", "May overlap Engineering and Real Estate"
    ),
    "ctgoodjobs:013": CategoryMapping(
        "Design & Architecture",
        "conservative_match",
        "CT category is broader and may include non-architecture design",
    ),
    "ctgoodjobs:052": CategoryMapping(
        "Retail & Consumer Products",
        "taxonomy_debt",
        "Could be retail, marketing, technology, or operations",
    ),
    "ctgoodjobs:041": CategoryMapping("Education & Training", "clean_match", "Strong fit"),
    "ctgoodjobs:015": CategoryMapping("Engineering", "clean_match", "Strong fit"),
    "ctgoodjobs:010": CategoryMapping(
        "Community Services & Development",
        "taxonomy_debt",
        "May need a dedicated public-sector domain or policy",
    ),
    "ctgoodjobs:017": CategoryMapping(
        "Healthcare & Medical",
        "taxonomy_debt",
        "Beauty care does not cleanly fit medical",
    ),
    "ctgoodjobs:018": CategoryMapping(
        "Hospitality & Tourism", "clean_match", "Name differs but meaning aligns"
    ),
    "ctgoodjobs:002": CategoryMapping(
        "Human Resources & Recruitment", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:021": CategoryMapping(
        "Information & Communication Technology", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:022": CategoryMapping(
        "Insurance & Superannuation", "clean_match", "Strong fit for Hong Kong context"
    ),
    "ctgoodjobs:025": CategoryMapping(
        "Manufacturing, Transport & Logistics",
        "conservative_match",
        "Internal domain merges manufacturing/logistics",
    ),
    "ctgoodjobs:051": CategoryMapping(
        "Manufacturing, Transport & Logistics",
        "conservative_match",
        "Internal domain is broader",
    ),
    "ctgoodjobs:026": CategoryMapping("Marketing & Communications", "clean_match", "Strong fit"),
    "ctgoodjobs:003": CategoryMapping(
        "Advertising, Arts & Media", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:027": CategoryMapping("Healthcare & Medical", "clean_match", "Strong fit"),
    "ctgoodjobs:028": CategoryMapping(
        "Manufacturing, Transport & Logistics",
        "taxonomy_debt",
        "Could map to retail, supply chain, or procurement",
    ),
    "ctgoodjobs:039": CategoryMapping(
        "Community Services & Development", "clean_match", "Strong fit"
    ),
    "ctgoodjobs:029": CategoryMapping(
        "General", "taxonomy_debt", "Too ambiguous for source-guided enrichment"
    ),
    "ctgoodjobs:049": CategoryMapping(
        "Consulting & Strategy",
        "taxonomy_debt",
        "Too broad; could include legal, accounting, consulting",
    ),
    "ctgoodjobs:032": CategoryMapping("Real Estate & Property", "clean_match", "Strong fit"),
    "ctgoodjobs:037": CategoryMapping("Retail & Consumer Products", "clean_match", "Strong fit"),
    "ctgoodjobs:038": CategoryMapping(
        "Sales", "conservative_match", "Contains customer service and business development"
    ),
    "ctgoodjobs:043": CategoryMapping(
        "Hospitality & Tourism", "conservative_match", "Shares domain with hotel/catering"
    ),
}


_NEXT_F_PUSH_PATTERN = re.compile(
    r"self\.__next_f\.push\s*\(\s*\[\s*\d+\s*,\s*\"(?P<payload>.*?)\"\s*\]\s*\)\s*;?",
    re.DOTALL,
)


def _decode_rendered_text(value: str) -> str:
    # The payload captured from `self.__next_f.push([1,"..."])` is a JS/JSON-string-like
    # fragment with backslash escapes (e.g. `\\"`). Decoding via `unicode_escape` can
    # corrupt non-ASCII. Instead, interpret it as a JSON string literal.
    try:
        decoded = json.loads(f'"{value}"')
    except json.JSONDecodeError:
        decoded = value
    return html.unescape(decoded)


def _decode_next_f_payload_json(payload_text: str) -> Any | None:
    candidate = payload_text.strip()
    match = re.match(r"^\d+:(?P<body>.*)$", candidate, re.DOTALL)
    if match:
        candidate = match.group("body").strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _find_jobcats_container(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("jobcats"), list):
            return payload
        for value in payload.values():
            found = _find_jobcats_container(value)
            if found is not None:
                return found
        return None
    if isinstance(payload, list):
        for item in payload:
            found = _find_jobcats_container(item)
            if found is not None:
                return found
    return None


def parse_category_registry(page_html: str) -> list[CTGoodJobsCategory]:
    """Parse the CTgoodjobs /jobs registry page into top-level categories."""

    categories: list[CTGoodJobsCategory] = []
    index_by_key: dict[tuple[str, str], int] = {}

    for match in _NEXT_F_PUSH_PATTERN.finditer(page_html):
        payload_text = _decode_rendered_text(match.group("payload"))
        payload_obj = _decode_next_f_payload_json(payload_text)
        if payload_obj is None:
            continue

        container = _find_jobcats_container(payload_obj)
        if container is None:
            continue

        jobcats = container.get("jobcats")
        if not isinstance(jobcats, list):
            continue

        for category in jobcats:
            if not isinstance(category, dict):
                continue

            raw_id = category.get("id")
            if not isinstance(raw_id, str):
                continue
            id_match = re.match(r"^(?P<id>[^_]+)_jc$", raw_id)
            if not id_match:
                continue

            total = category.get("total")
            name = category.get("name")
            slug = category.get("nameForUrl")
            if not isinstance(total, int) or not isinstance(name, str) or not isinstance(slug, str):
                continue

            ctgoodjobs_id = id_match.group("id")
            dedupe_key = (ctgoodjobs_id, slug)
            existing_index = index_by_key.get(dedupe_key)

            source_id = f"ctgoodjobs:{ctgoodjobs_id}"
            mapping = CTGOODJOBS_CATEGORY_MAPPINGS.get(
                source_id,
                CategoryMapping("General", "taxonomy_debt", "No reviewed mapping exists"),
            )
            parsed = CTGoodJobsCategory(
                source_site="ctgoodjobs",
                source_classification_id=source_id,
                ctgoodjobs_id=ctgoodjobs_id,
                name=name,
                slug=slug,
                url=f"{CTGOODJOBS_BASE_URL}/jobs/jobs-in-{slug}",
                child_count=total,
                proposed_internal_domain=mapping.proposed_internal_domain,
                mapping_status=mapping.mapping_status,
                mapping_notes=mapping.mapping_notes,
            )

            if existing_index is None:
                index_by_key[dedupe_key] = len(categories)
                categories.append(parsed)
                continue

            # Prefer English record if we detect it; CTgoodjobs often includes both languages.
            existing = categories[existing_index]
            existing_is_english = existing.name.isascii()
            parsed_is_english = parsed.name.isascii()
            if not existing_is_english and parsed_is_english:
                categories[existing_index] = parsed

    return categories
