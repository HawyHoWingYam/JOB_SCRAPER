"""add company ai enrichment run concurrency

Revision ID: 20260602_113000
Revises: 20260504_170000
Create Date: 2026-06-02 11:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260602_113000"
down_revision = "20260504_170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("app_runtime_settings")}
    if "company_ai_enrichment_run_concurrency" not in column_names:
        op.add_column(
            "app_runtime_settings",
            sa.Column("company_ai_enrichment_run_concurrency", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    column_names = {column["name"] for column in inspector.get_columns("app_runtime_settings")}
    if "company_ai_enrichment_run_concurrency" in column_names:
        op.drop_column("app_runtime_settings", "company_ai_enrichment_run_concurrency")
