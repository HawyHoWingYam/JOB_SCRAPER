#!/usr/bin/env python3
"""Reset all AI-derived live data before taxonomy cutover."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Callable, ContextManager, Optional

from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import engine


def build_statements() -> list[str]:
    """Build destructive SQL statements for a full AI-derived data reset."""
    return [
        "DELETE FROM job_skills",
        """
        UPDATE jobs
        SET ai_summary = NULL,
            ai_enriched_at = NULL,
            subcategory_id = NULL
        """,
        "DELETE FROM skills",
        "DELETE FROM skill_technologies",
        "DELETE FROM skill_categories",
        "DELETE FROM job_subcategories",
        "DELETE FROM job_categories",
        "DELETE FROM job_domains",
    ]


def run_statements(
    statements: list[str],
    execute: bool,
    connection_factory: Optional[Callable[[], ContextManager]] = None,
) -> None:
    """Print or execute the reset statements."""
    if not execute:
        for index, statement in enumerate(statements, start=1):
            print(f"-- [{index}]")
            print(statement.strip())
        return

    factory = connection_factory or engine.begin
    with factory() as connection:
        for statement in statements:
            connection.execute(text(statement))


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Apply the destructive reset")
    mode.add_argument("--dry-run", action="store_true", help="Print the destructive reset only")
    return parser


def main() -> None:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    run_statements(build_statements(), execute=args.execute)


if __name__ == "__main__":
    main()
