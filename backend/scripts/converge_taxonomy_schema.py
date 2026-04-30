#!/usr/bin/env python3
"""Converge the live PostgreSQL schema with governed taxonomy models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine


def build_statements() -> list[str]:
    """Build ordered SQL statements for taxonomy schema convergence."""
    return [
        "CREATE EXTENSION IF NOT EXISTS pgcrypto",
        """
        CREATE TABLE IF NOT EXISTS skill_categories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) UNIQUE NOT NULL,
            description TEXT,
            created_by VARCHAR(20) NOT NULL DEFAULT 'seed',
            is_auto_created BOOLEAN NOT NULL DEFAULT FALSE,
            is_filter_visible BOOLEAN NOT NULL DEFAULT FALSE,
            usage_count INTEGER NOT NULL DEFAULT 0,
            distinct_job_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS skill_technologies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id UUID NOT NULL REFERENCES skill_categories(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            created_by VARCHAR(20) NOT NULL DEFAULT 'seed',
            is_auto_created BOOLEAN NOT NULL DEFAULT FALSE,
            is_filter_visible BOOLEAN NOT NULL DEFAULT FALSE,
            usage_count INTEGER NOT NULL DEFAULT 0,
            distinct_job_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            UNIQUE(category_id, name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_domains (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) UNIQUE NOT NULL,
            description TEXT,
            created_by VARCHAR(20) NOT NULL DEFAULT 'seed',
            is_auto_created BOOLEAN NOT NULL DEFAULT FALSE,
            is_filter_visible BOOLEAN NOT NULL DEFAULT FALSE,
            usage_count INTEGER NOT NULL DEFAULT 0,
            distinct_job_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_categories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            domain_id UUID NOT NULL REFERENCES job_domains(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            created_by VARCHAR(20) NOT NULL DEFAULT 'seed',
            is_auto_created BOOLEAN NOT NULL DEFAULT FALSE,
            is_filter_visible BOOLEAN NOT NULL DEFAULT FALSE,
            usage_count INTEGER NOT NULL DEFAULT 0,
            distinct_job_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            UNIQUE(domain_id, name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_subcategories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            category_id UUID NOT NULL REFERENCES job_categories(id) ON DELETE CASCADE,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            created_by VARCHAR(20) NOT NULL DEFAULT 'seed',
            is_auto_created BOOLEAN NOT NULL DEFAULT FALSE,
            is_filter_visible BOOLEAN NOT NULL DEFAULT FALSE,
            usage_count INTEGER NOT NULL DEFAULT 0,
            distinct_job_count INTEGER NOT NULL DEFAULT 0,
            last_used_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            UNIQUE(category_id, name)
        )
        """,
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS technology_id UUID",
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS aliases TEXT[]",
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS created_by VARCHAR(20) NOT NULL DEFAULT 'seed'",
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS is_auto_created BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS is_filter_visible BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS usage_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS distinct_job_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE skills ADD COLUMN IF NOT EXISTS last_used_at TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS subcategory_id UUID",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_classification_id VARCHAR(50)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_classification_name VARCHAR(255)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_subclassification_id VARCHAR(50)",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source_subclassification_name VARCHAR(255)",
        "CREATE INDEX IF NOT EXISTS idx_skill_categories_is_filter_visible ON skill_categories (is_filter_visible)",
        "CREATE INDEX IF NOT EXISTS idx_skill_categories_distinct_job_count ON skill_categories (distinct_job_count)",
        "CREATE INDEX IF NOT EXISTS idx_skill_technologies_category_id ON skill_technologies (category_id)",
        "CREATE INDEX IF NOT EXISTS idx_skill_technologies_name ON skill_technologies (name)",
        "CREATE INDEX IF NOT EXISTS idx_skill_technologies_created_by ON skill_technologies (created_by)",
        "CREATE INDEX IF NOT EXISTS idx_skill_technologies_is_auto_created ON skill_technologies (is_auto_created)",
        "CREATE INDEX IF NOT EXISTS idx_skill_technologies_is_filter_visible ON skill_technologies (is_filter_visible)",
        "CREATE INDEX IF NOT EXISTS idx_skill_technologies_distinct_job_count ON skill_technologies (distinct_job_count)",
        "CREATE INDEX IF NOT EXISTS idx_job_domains_is_filter_visible ON job_domains (is_filter_visible)",
        "CREATE INDEX IF NOT EXISTS idx_job_domains_distinct_job_count ON job_domains (distinct_job_count)",
        "CREATE INDEX IF NOT EXISTS idx_job_categories_domain_id ON job_categories (domain_id)",
        "CREATE INDEX IF NOT EXISTS idx_job_categories_name ON job_categories (name)",
        "CREATE INDEX IF NOT EXISTS idx_job_categories_created_by ON job_categories (created_by)",
        "CREATE INDEX IF NOT EXISTS idx_job_categories_is_auto_created ON job_categories (is_auto_created)",
        "CREATE INDEX IF NOT EXISTS idx_job_categories_is_filter_visible ON job_categories (is_filter_visible)",
        "CREATE INDEX IF NOT EXISTS idx_job_categories_distinct_job_count ON job_categories (distinct_job_count)",
        "CREATE INDEX IF NOT EXISTS idx_job_subcategories_category_id ON job_subcategories (category_id)",
        "CREATE INDEX IF NOT EXISTS idx_job_subcategories_name ON job_subcategories (name)",
        "CREATE INDEX IF NOT EXISTS idx_job_subcategories_created_by ON job_subcategories (created_by)",
        "CREATE INDEX IF NOT EXISTS idx_job_subcategories_is_auto_created ON job_subcategories (is_auto_created)",
        "CREATE INDEX IF NOT EXISTS idx_job_subcategories_is_filter_visible ON job_subcategories (is_filter_visible)",
        "CREATE INDEX IF NOT EXISTS idx_job_subcategories_distinct_job_count ON job_subcategories (distinct_job_count)",
        "CREATE INDEX IF NOT EXISTS idx_skills_technology_id ON skills (technology_id)",
        "CREATE INDEX IF NOT EXISTS idx_skills_name ON skills (name)",
        "CREATE INDEX IF NOT EXISTS idx_skills_created_by ON skills (created_by)",
        "CREATE INDEX IF NOT EXISTS idx_skills_is_auto_created ON skills (is_auto_created)",
        "CREATE INDEX IF NOT EXISTS idx_skills_is_filter_visible ON skills (is_filter_visible)",
        "CREATE INDEX IF NOT EXISTS idx_skills_distinct_job_count ON skills (distinct_job_count)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_subcategory_id ON jobs (subcategory_id)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_source_classification_id ON jobs (source_classification_id)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_source_classification_name ON jobs (source_classification_name)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_source_subclassification_id ON jobs (source_subclassification_id)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_source_subclassification_name ON jobs (source_subclassification_name)",
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_skills_technology_id'
            ) THEN
                ALTER TABLE skills
                ADD CONSTRAINT fk_skills_technology_id
                FOREIGN KEY (technology_id) REFERENCES skill_technologies(id) ON DELETE CASCADE;
            END IF;
        END
        $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_skill_technology_name'
            ) THEN
                ALTER TABLE skills
                ADD CONSTRAINT uq_skill_technology_name
                UNIQUE (technology_id, name);
            END IF;
        END
        $$;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_jobs_subcategory_id'
            ) THEN
                ALTER TABLE jobs
                ADD CONSTRAINT fk_jobs_subcategory_id
                FOREIGN KEY (subcategory_id) REFERENCES job_subcategories(id);
            END IF;
        END
        $$;
        """,
    ]


def run_statements(statements: list[str], execute: bool) -> None:
    """Print or execute the convergence plan."""
    if not execute:
        for index, statement in enumerate(statements, start=1):
            print(f"-- [{index}]")
            print(statement.strip())
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def build_parser() -> argparse.ArgumentParser:
    """Create the script argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="Apply the statements")
    mode.add_argument("--dry-run", action="store_true", help="Print statements only")
    return parser


def main() -> None:
    """CLI entrypoint."""
    args = build_parser().parse_args()
    run_statements(build_statements(), execute=args.execute)


if __name__ == "__main__":
    main()
