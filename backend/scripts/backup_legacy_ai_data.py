#!/usr/bin/env python3
"""Back up legacy AI enrichment tables before taxonomy cutover."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import engine


def build_backup_plan(output_dir: str) -> dict[str, object]:
    """Build the legacy AI backup export plan."""
    base_dir = Path(output_dir)
    exports = {
        "jobs": {
            "columns": ["id", "job_id", "title", "ai_category", "ai_summary", "ai_enriched_at"],
            "query": """
                SELECT id, job_id, title, ai_category, ai_summary, ai_enriched_at
                FROM jobs
            """,
            "path": str(base_dir / "jobs.csv"),
        },
        "skills": {
            "columns": ["id", "name", "technology_id", "popularity"],
            "query": """
                SELECT id, name, technology_id, popularity
                FROM skills
            """,
            "path": str(base_dir / "skills.csv"),
        },
        "job_skills": {
            "columns": ["job_id", "skill_id", "created_at"],
            "query": """
                SELECT job_id, skill_id, created_at
                FROM job_skills
            """,
            "path": str(base_dir / "job_skills.csv"),
        },
    }

    return {
        "output_dir": str(base_dir),
        "tables": list(exports.keys()),
        "exports": exports,
    }


def run_backup(plan: dict[str, object], execute: bool) -> None:
    """Print or execute the backup plan."""
    exports = plan["exports"]

    if not execute:
        for table_name in plan["tables"]:
            export = exports[table_name]
            print(f"{table_name}: {export['path']}")
            print(", ".join(export["columns"]))
        return

    output_dir = Path(plan["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    with engine.connect() as connection:
        for table_name in plan["tables"]:
            export = exports[table_name]
            result = connection.execute(text(export["query"]))
            with open(export["path"], "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(export["columns"])
                writer.writerows(result.fetchall())
            print(f"Backed up {table_name} to {export['path']}")


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", help="Directory for CSV backup files")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Write CSV backups")
    mode.add_argument("--dry-run", action="store_true", help="Print backup plan only")
    return parser


def main() -> None:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    plan = build_backup_plan(args.output_dir)
    run_backup(plan, execute=args.execute)


if __name__ == "__main__":
    main()
