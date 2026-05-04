"""add app runtime settings

Revision ID: 20260503_170000
Revises: 20260501_150000
Create Date: 2026-05-03 17:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260503_170000"
down_revision = "20260501_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_runtime_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("llm_provider", sa.String(length=32), nullable=True),
        sa.Column("ai_enrichment_run_concurrency", sa.Integer(), nullable=True),
        sa.Column("anthropic_api_key", sa.Text(), nullable=True),
        sa.Column("anthropic_model", sa.String(length=255), nullable=True),
        sa.Column("anthropic_base_url", sa.String(length=512), nullable=True),
        sa.Column("gemini_api_key", sa.Text(), nullable=True),
        sa.Column("gemini_model", sa.String(length=255), nullable=True),
        sa.Column("custom_api_key", sa.Text(), nullable=True),
        sa.Column("custom_model", sa.String(length=255), nullable=True),
        sa.Column("custom_base_url", sa.String(length=512), nullable=True),
        sa.Column("custom_api_format", sa.String(length=64), nullable=True),
        sa.Column("zhipu_api_key", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("app_runtime_settings")
