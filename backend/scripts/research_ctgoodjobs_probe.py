"""Run the CTgoodjobs research probe and write a JSON report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

def _bootstrap_backend_dir() -> None:
    """Ensure `backend/` is importable when run as a direct script.

    Example: `cd backend && python scripts/research_ctgoodjobs_probe.py --help`
    """
    backend_dir = Path(__file__).resolve().parents[1]
    backend_dir_str = os.fspath(backend_dir)
    if backend_dir_str not in sys.path:
        sys.path.insert(0, backend_dir_str)


def run_research_probe(**kwargs):
    # Deferred import so importing this module doesn't mutate sys.path.
    _bootstrap_backend_dir()
    from app.scraper.ctgoodjobs.research_probe import run_research_probe as _impl

    return _impl(**kwargs)


def _parse_categories(raw_value: str) -> list[str]:
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CTgoodjobs scraping research probe")
    parser.add_argument(
        "--categories",
        default="information-technology,banking-finance,hotel-catering-club",
        help="Comma-separated CTgoodjobs category slugs",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Max number of listing pages to probe per category",
    )
    parser.add_argument(
        "--details-per-category",
        type=int,
        default=3,
        help="Max number of job detail pages to fetch per category",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write the JSON report",
    )
    parser.add_argument(
        "--api-probe",
        action="store_true",
        help="Enable API probe requests (if supported)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    report = run_research_probe(
        categories=_parse_categories(args.categories),
        max_pages=args.max_pages,
        details_per_category=args.details_per_category,
        enable_api_probe=args.api_probe,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote CTgoodjobs research probe report to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
