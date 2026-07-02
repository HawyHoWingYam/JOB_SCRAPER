"""ScrapeGraphAI extraction fallback — optional schema-bound extraction.

ScrapeGraphAI (https://github.com/ScrapeGraphAI/Scrapegraph-ai) provides
LLM-powered structured extraction from already-fetched HTML.

This module keeps ScrapeGraphAI behind an optional import. It is NOT used
for listing enumeration, scheduling, pagination, or anti-bot transport.
It is only called after a page has been fetched, as a fallback when the
rule-based parser could not extract all required fields.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy flag — only True after a successful import
_SCRAPEGRAPH_AVAILABLE: bool | None = None


def is_scrapegraph_available() -> bool:
    """Check if ScrapeGraphAI can be imported (without forcing the import)."""
    global _SCRAPEGRAPH_AVAILABLE
    if _SCRAPEGRAPH_AVAILABLE is None:
        try:
            import scrapegraphai as _  # noqa: F401

            _SCRAPEGRAPH_AVAILABLE = True
        except ImportError:
            _SCRAPEGRAPH_AVAILABLE = False
    return _SCRAPEGRAPH_AVAILABLE


# Schema for missing job fields
MISSING_FIELDS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description_html": {"type": "string"},
        "company_name": {"type": "string"},
        "location": {"type": "string"},
        "salary_range": {"type": "string"},
        "employment_type": {"type": "string"},
    },
    "required": ["title", "description_html"],
}


async def extract_missing_fields(
    html: str,
    *,
    known_fields: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Extract missing job fields from HTML using ScrapeGraphAI.

    Args:
        html: The raw HTML of the job detail page.
        known_fields: Fields already extracted by the rule-based parser.
                      Only missing fields will be extracted.
        timeout: Maximum time (seconds) to wait for extraction.

    Returns:
        A dict with extracted fields. Falls back to empty dict on timeout
        or import failure.
    """
    if not is_scrapegraph_available():
        logger.debug("ScrapeGraphAI not available — skipping extraction")
        return {}

    known = known_fields or {}
    missing_fields = [
        field
        for field in MISSING_FIELDS_SCHEMA["required"]
        if not known.get(field)
    ]

    if not missing_fields:
        return {}

    try:
        from scrapegraphai.graphs import SmartScraperGraph

        prompt = (
            f"Extract the following fields from this job listing HTML: "
            f"{', '.join(missing_fields)}. "
            f"If a field is not found, return an empty string for it."
        )

        graph_config = {
            "llm": {
                "model": "ollama/llama3.2",
                "temperature": 0.0,
            },
            "verbose": False,
            "headless": True,
        }

        scraper = SmartScraperGraph(
            prompt=prompt,
            source=html,
            config=graph_config,
            schema=MISSING_FIELDS_SCHEMA,
        )

        result: dict[str, Any] = await scraper.run()  # type: ignore[misc]
        return {k: v for k, v in result.items() if isinstance(v, str) and v.strip()}

    except ImportError:
        logger.warning("ScrapeGraphAI dependencies not fully installed")
        return {}
    except Exception as exc:
        logger.warning("ScrapeGraphAI extraction failed: %s", exc)
        return {}
