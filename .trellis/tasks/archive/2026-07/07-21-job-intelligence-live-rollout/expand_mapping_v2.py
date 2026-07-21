"""Generate the catalog-complete mapping v2 from the pinned live catalog.

This is rollout evidence tooling, not an application runtime path. It expands
OfferToday child identities by inheriting the already reviewed root mapping;
the inherited target set can never exceed the reviewed root target set.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal  # noqa: E402
from app.models.source_catalog import (  # noqa: E402
    SourceCatalogActiveRevision,
    SourceCatalogRevision,
)
from app.source_catalog.domain import DiscoveredCatalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    document = json.loads(args.input.read_text(encoding="utf-8"))
    entries = {
        entry["source_classification_id"]: entry for entry in document["entries"]
    }

    db = SessionLocal()
    try:
        revision = (
            db.query(SourceCatalogRevision)
            .join(
                SourceCatalogActiveRevision,
                SourceCatalogActiveRevision.revision_id == SourceCatalogRevision.id,
            )
            .filter(SourceCatalogActiveRevision.source_site == "offertoday")
            .one()
        )
        catalog = DiscoveredCatalog.from_payloads(
            normalized_payload=revision.normalized_payload,
            source_payload=revision.source_payload,
            provenance=revision.provenance,
        )
    finally:
        db.rollback()
        db.close()

    by_key = {node.node_key: node for node in catalog.nodes}
    for node in catalog.nodes:
        source_id = node.classification_id
        if source_id is None or source_id in entries:
            continue
        parent = by_key.get(node.parent_node_key or "")
        if parent is None or parent.classification_id is None:
            raise RuntimeError(f"OfferToday child {source_id} has no mapped root")
        root_entry = entries.get(parent.classification_id)
        if root_entry is None:
            raise RuntimeError(
                f"OfferToday child {source_id} root {parent.classification_id} is unmapped"
            )
        entries[source_id] = {
            "source_site": "offertoday",
            "source_classification_id": source_id,
            "source_label": node.native_label,
            "disposition": root_entry["disposition"],
            "target_codes": list(root_entry["target_codes"]),
            "review_evidence": {
                "inherited_from_source_classification_id": parent.classification_id,
                "reason": (
                    "Child mapping is bounded by the reviewed parent Source mapping "
                    "for the pinned Source Catalog revision."
                ),
            },
        }

    ordered = sorted(entries.values(), key=lambda entry: entry["source_classification_id"])
    counts = Counter(entry["disposition"] for entry in ordered)
    document["release_key"] = "source-to-canonical-job-mapping-v2"
    document["expected_counts"] = {
        "entries": len(ordered),
        "deterministic": counts["deterministic"],
        "allowed_slice": counts["allowed_slice"],
        "excluded": counts["excluded"],
        "unmapped": counts["unmapped"],
    }
    document["entries"] = ordered
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(document["expected_counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
