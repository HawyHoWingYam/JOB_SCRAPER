"""One-time authoring tool for reviewed Source-to-Canonical mapping fixtures."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scraper.ctgoodjobs.category_registry import (  # noqa: E402
    CTGOODJOBS_CATEGORY_MAPPINGS,
)


DEFAULT_RELEASE_KEY = "source-to-canonical-job-mapping-v1"


def convert_legacy_mapping(
    taxonomy: dict[str, Any],
    legacy_mapping: dict[str, Any],
    legacy_exclusions: dict[str, Any],
    *,
    release_key: str,
) -> dict[str, Any]:
    leaf_codes_by_domain = {
        domain["label"]: [
            subcategory["code"]
            for category in domain["categories"]
            for subcategory in category["subcategories"]
            if subcategory["is_assignable"] is True
        ]
        for domain in taxonomy["domains"]
    }

    entries: list[dict[str, Any]] = []
    for raw_source_id, legacy_entry in legacy_mapping.items():
        source_id = raw_source_id if ":" in raw_source_id else f"jobsdb:{raw_source_id}"
        source_site = source_id.split(":", 1)[0]
        allowed_domains = list(legacy_entry["allowed_domains"])
        target_codes = [
            code
            for domain in taxonomy["domains"]
            if domain["label"] in allowed_domains
            for code in leaf_codes_by_domain[domain["label"]]
        ]
        if not target_codes:
            raise ValueError(f"No assignable targets for {source_id}")
        entries.append(
            {
                "source_site": source_site,
                "source_classification_id": source_id,
                "source_label": str(legacy_entry["source_name"]),
                "disposition": "allowed_slice",
                "target_codes": target_codes,
                "review_evidence": {
                    "legacy_default_path": legacy_entry.get("default_path"),
                    "legacy_subcategory_hints": legacy_entry.get(
                        "subcategory_hints",
                        {},
                    ),
                },
            }
        )

    for source_id, legacy_exclusion in legacy_exclusions.items():
        entries.append(
            {
                "source_site": source_id.split(":", 1)[0],
                "source_classification_id": source_id,
                "source_label": str(legacy_exclusion["source_name"]),
                "disposition": "excluded",
                "target_codes": [],
                "review_evidence": {"reason": str(legacy_exclusion["reason"])},
            }
        )

    entries.sort(key=lambda entry: entry["source_classification_id"])
    disposition_counts = Counter(entry["disposition"] for entry in entries)
    mapped_ctgoodjobs_ids = {
        entry["source_classification_id"]
        for entry in entries
        if entry["source_site"] == "ctgoodjobs"
    }
    proposal_only_ids = sorted(
        set(CTGOODJOBS_CATEGORY_MAPPINGS) - mapped_ctgoodjobs_ids
    )

    return {
        "schema_version": 1,
        "release_key": release_key,
        "taxonomy_release_key": taxonomy["release_key"],
        "expected_counts": {
            "entries": len(entries),
            "deterministic": disposition_counts["deterministic"],
            "allowed_slice": disposition_counts["allowed_slice"],
            "excluded": disposition_counts["excluded"],
            "unmapped": disposition_counts["unmapped"],
        },
        "legacy_discrepancies": {
            "ctgoodjobs_proposal_only_ids": proposal_only_ids,
        },
        "entries": entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("taxonomy", type=Path)
    parser.add_argument("legacy_mapping", type=Path)
    parser.add_argument("legacy_exclusions", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--release-key", default=DEFAULT_RELEASE_KEY)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    taxonomy = json.loads(args.taxonomy.read_text())
    legacy_mapping = json.loads(args.legacy_mapping.read_text())
    legacy_exclusions = json.loads(args.legacy_exclusions.read_text())
    converted = convert_legacy_mapping(
        taxonomy,
        legacy_mapping,
        legacy_exclusions,
        release_key=args.release_key,
    )
    args.output.write_text(json.dumps(converted, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
