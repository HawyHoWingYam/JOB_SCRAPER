#!/usr/bin/env python3
"""Regenerate the frozen OfferToday POSITION catalog from its source git blob.

This is a deterministic development helper. It never performs a network request and
does not restore the historical ``.debug`` capture into the working tree.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


SOURCE_COMMIT = "ed03f114fb8bc73eeb11139d82325a7944802701"
SOURCE_GIT_BLOB = "80960e8dad9a0f84ca928218ed81bd0133fc18c5"
SOURCE_PATH = ".debug/offertoday-filter-content.network-response"
SOURCE_ENDPOINT = "/wapi/geek/recommend/filter/content/all"
OUTPUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "scraper"
    / "offertoday"
    / "category_catalog_v1.json"
)


def _normalize_node(
    node: dict[str, Any],
    *,
    root: bool = False,
) -> dict[str, Any]:
    return {
        "code": int(node["code"]),
        "name": str(node["name"]),
        # The official snapshot self-parents root 999000 (Other). Normalize every
        # L1 root to the existing registry convention so the tree cannot cycle.
        "parent_code": 0 if root else int(node["parentCode"]),
        "level": int(node["level"]),
        "children": [
            _normalize_node(child) for child in node.get("children", [])
        ],
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    resolved_blob = subprocess.run(
        ["git", "rev-parse", f"{SOURCE_COMMIT}:{SOURCE_PATH}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    if resolved_blob != SOURCE_GIT_BLOB:
        raise ValueError("official category source blob does not match v1")
    completed = subprocess.run(
        ["git", "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout)
    categories = [
        _normalize_node(node, root=True)
        for node in payload["data"]["en"]["POSITION"]["children"]
    ]
    child_count = sum(len(node["children"]) for node in categories)
    alias_count = sum(
        child["code"] == child["parent_code"]
        for node in categories
        for child in node["children"]
    )
    if (len(categories), child_count, alias_count) != (31, 462, 31):
        raise ValueError("official category snapshot counts do not match v1")
    output = {
        "schema_version": 1,
        "source_commit": SOURCE_COMMIT,
        "source_git_blob": SOURCE_GIT_BLOB,
        "source_endpoint": SOURCE_ENDPOINT,
        "language": "en",
        "categories": categories,
    }
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=True, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(OUTPUT_PATH.relative_to(repo_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
