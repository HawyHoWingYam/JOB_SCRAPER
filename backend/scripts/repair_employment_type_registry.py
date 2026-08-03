#!/usr/bin/env python3
"""Repair the governed Employment Type rows in an existing database."""

from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import Engine, inspect

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine  # noqa: E402
from app.job_intelligence.source_attributes import (  # noqa: E402
    EmploymentTypeRegistrySyncResult,
    reconcile_employment_type_registry,
)


class EmploymentTypeRegistryRepairError(RuntimeError):
    """Raised when the target is not eligible for registry-only repair."""


def repair_employment_type_registry(
    *,
    db_engine: Engine = engine,
) -> EmploymentTypeRegistrySyncResult:
    """Repair registry data without creating or changing schema objects."""

    with db_engine.begin() as connection:
        if "employment_types" not in set(inspect(connection).get_table_names()):
            raise EmploymentTypeRegistryRepairError(
                "Employment Type repair requires the existing employment_types table"
            )
        return reconcile_employment_type_registry(
            connection,
            allow_unknown_codes=True,
        )


def main() -> None:
    result = repair_employment_type_registry()
    print(
        "Employment Type registry repaired: "
        f"inserted={len(result.inserted_codes)} "
        f"updated={len(result.updated_codes)} "
        f"unchanged={len(result.unchanged_codes)}"
    )
    if result.unknown_codes:
        print("Unknown codes preserved: " + ", ".join(result.unknown_codes))


if __name__ == "__main__":
    main()
