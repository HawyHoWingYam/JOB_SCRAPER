"""One-time authoring tool for explicit Canonical Job Taxonomy stable codes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import unicodedata
from typing import Any


DEFAULT_RELEASE_KEY = "canonical-job-taxonomy-v1"


def stable_code_part(label: str) -> str:
    ascii_label = (
        unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    )
    code = re.sub(r"[^a-z0-9]+", "_", ascii_label.lower()).strip("_")
    if not code:
        raise ValueError(f"Cannot derive a stable code from label {label!r}")
    return code


def convert_legacy_manifest(
    document: dict[str, Any],
    *,
    release_key: str,
) -> dict[str, Any]:
    domains: list[dict[str, Any]] = []
    for domain_order, raw_domain in enumerate(document["domains"], start=1):
        domain_label = str(raw_domain["name"])
        domain_code = stable_code_part(domain_label)
        categories: list[dict[str, Any]] = []

        for raw_category in raw_domain["categories"]:
            category_label = str(raw_category["name"])
            raw_subcategories = list(raw_category["subcategories"])
            if category_label == "General":
                if raw_subcategories != ["General"]:
                    raise ValueError(
                        f"Unexpected General fallback shape under {domain_label!r}"
                    )
                continue

            category_code = f"{domain_code}.{stable_code_part(category_label)}"
            subcategories = [
                {
                    "code": f"{category_code}.{stable_code_part(str(label))}",
                    "label": str(label),
                    "order": subcategory_order,
                    "is_assignable": True,
                }
                for subcategory_order, label in enumerate(
                    raw_subcategories,
                    start=1,
                )
            ]
            categories.append(
                {
                    "code": category_code,
                    "label": category_label,
                    "order": len(categories) + 1,
                    "subcategories": subcategories,
                }
            )

        domains.append(
            {
                "code": domain_code,
                "label": domain_label,
                "order": domain_order,
                "categories": categories,
            }
        )

    categories = [category for domain in domains for category in domain["categories"]]
    subcategories = [
        subcategory
        for category in categories
        for subcategory in category["subcategories"]
    ]
    return {
        "schema_version": 1,
        "release_key": release_key,
        "expected_counts": {
            "domains": len(domains),
            "categories": len(categories),
            "subcategories": len(subcategories),
        },
        "domains": domains,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--release-key", default=DEFAULT_RELEASE_KEY)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = json.loads(args.input.read_text())
    converted = convert_legacy_manifest(source, release_key=args.release_key)
    args.output.write_text(json.dumps(converted, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
