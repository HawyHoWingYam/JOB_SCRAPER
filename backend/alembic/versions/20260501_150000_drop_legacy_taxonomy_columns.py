"""drop legacy taxonomy columns and redundant indexes

Revision ID: 20260501_150000
Revises: 20260501_103000
Create Date: 2026-05-01 15:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260501_150000"
down_revision = "20260501_103000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_jobs_ai_category")
    op.execute("DROP INDEX IF EXISTS idx_jobs_category_posted")
    op.execute("DROP INDEX IF EXISTS idx_skills_category")
    op.execute("DROP INDEX IF EXISTS idx_skills_name")
    op.execute("DROP INDEX IF EXISTS idx_skills_technology_id")
    op.execute("DROP INDEX IF EXISTS idx_job_categories_domain_id")
    op.execute("DROP INDEX IF EXISTS idx_job_subcategories_category_id")
    op.execute("DROP INDEX IF EXISTS idx_skill_technologies_category_id")
    op.execute("DROP INDEX IF EXISTS idx_job_skills_job_id")
    op.execute("DROP INDEX IF EXISTS idx_jobs_job_id")
    op.execute("DROP INDEX IF EXISTS idx_companies_company_id")

    op.drop_constraint("skills_name_key", "skills", type_="unique")
    op.drop_column("jobs", "ai_generic_tags")
    op.drop_column("jobs", "ai_category")
    op.drop_column("skills", "category")


def downgrade() -> None:
    op.add_column("skills", sa.Column("category", sa.String(length=100), nullable=True))
    op.add_column("jobs", sa.Column("ai_category", sa.String(length=255), nullable=True))
    op.add_column("jobs", sa.Column("ai_generic_tags", sa.JSON(), nullable=True))

    op.create_unique_constraint("skills_name_key", "skills", ["name"])
    op.execute("CREATE INDEX IF NOT EXISTS idx_companies_company_id ON companies (company_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_job_id ON jobs (job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_skills_job_id ON job_skills (job_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_skill_technologies_category_id ON skill_technologies (category_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_subcategories_category_id ON job_subcategories (category_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_categories_domain_id ON job_categories (domain_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_technology_id ON skills (technology_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills (name)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_skills_category ON skills (category)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_jobs_ai_category ON jobs (ai_category)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_category_posted ON jobs (ai_category, posted_date DESC) WHERE (is_deleted = false)"
    )
