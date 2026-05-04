"""add company runtime profile fields

Revision ID: 20260504_120000
Revises: 20260503_170000
Create Date: 2026-05-04 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260504_120000"
down_revision = "20260503_170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_runtime_settings", sa.Column("company_llm_provider", sa.String(length=32), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_anthropic_api_key", sa.Text(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_anthropic_model", sa.String(length=255), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_anthropic_base_url", sa.String(length=512), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_gemini_api_key", sa.Text(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_gemini_model", sa.String(length=255), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_custom_api_key", sa.Text(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_custom_model", sa.String(length=255), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_custom_base_url", sa.String(length=512), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_custom_api_format", sa.String(length=64), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("company_zhipu_api_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_runtime_settings", "company_zhipu_api_key")
    op.drop_column("app_runtime_settings", "company_custom_api_key")
    op.drop_column("app_runtime_settings", "company_custom_api_format")
    op.drop_column("app_runtime_settings", "company_custom_base_url")
    op.drop_column("app_runtime_settings", "company_custom_model")
    op.drop_column("app_runtime_settings", "company_gemini_api_key")
    op.drop_column("app_runtime_settings", "company_gemini_model")
    op.drop_column("app_runtime_settings", "company_anthropic_base_url")
    op.drop_column("app_runtime_settings", "company_anthropic_api_key")
    op.drop_column("app_runtime_settings", "company_anthropic_model")
    op.drop_column("app_runtime_settings", "company_llm_provider")
