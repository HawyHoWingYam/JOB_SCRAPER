#!/usr/bin/env python3
"""Validate or synchronize the governed Company Industry Source Mapping state."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.job_intelligence.current_taxonomies.company_mapping_manifest import (  # noqa: E402
    CompanyIndustryMappingManifestError,
    CompanyIndustryMappingSynchronizer,
    DEFAULT_COMPANY_INDUSTRY_MAPPING_MANIFEST,
    collect_observed_source_industry_labels,
    load_company_industry_mapping_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_COMPANY_INDUSTRY_MAPPING_MANIFEST,
        help="Current-state manifest path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and print the deterministic change plan without mutation",
    )
    parser.add_argument(
        "--format",
        choices=("json", "human"),
        default="json",
        help="Deterministic output format (default: json)",
    )
    return parser


def render_human_report(payload: Mapping[str, object]) -> str:
    mode = "check" if payload.get("check_only") else "synchronize"
    lines = [f"Company Industry Source Mapping ({mode})"]
    raw_sources = payload.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        lines.append(
            f"{source['source_site']}: "
            f"created={source['created']} updated={source['updated']} "
            f"removed={source['removed']} unchanged={source['unchanged']} "
            f"mapped={source['mapped_dispositions']} "
            f"non_mapping={source['non_mapping_dispositions']}"
        )
    return "\n".join(lines)


def _print_payload(payload: Mapping[str, object], output_format: str) -> None:
    if output_format == "human":
        print(render_human_report(payload))
    else:
        print(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    db = SessionLocal()
    try:
        manifest = load_company_industry_mapping_manifest(args.manifest)
        observed = collect_observed_source_industry_labels(
            db,
            tuple(source.source_site for source in manifest.sources),
        )
        synchronizer = CompanyIndustryMappingSynchronizer(db)
        plan = (
            synchronizer.plan(manifest, observed_labels=observed)
            if args.check
            else synchronizer.synchronize(manifest, observed_labels=observed)
        )
        if not args.check:
            db.commit()
        payload = plan.to_payload() | {"check_only": bool(args.check)}
        _print_payload(payload, args.format)
        return 0
    except CompanyIndustryMappingManifestError as exc:
        db.rollback()
        payload = {"error": str(exc), "ok": False}
        if args.format == "human":
            print(f"Company Industry Source Mapping failed: {exc}", file=sys.stderr)
        else:
            print(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
        return 1
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
