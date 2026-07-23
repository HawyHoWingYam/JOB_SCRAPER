"""add Company Enrichment Web Search state

Revision ID: 20260723_120000
Revises: 20260722_120000
Create Date: 2026-07-23 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260723_120000"
down_revision = "20260722_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_enrichment_runs",
        sa.Column(
            "web_search_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "app_runtime_settings",
        sa.Column(
            "companies_web_search_last_test_status",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "app_runtime_settings",
        sa.Column("companies_web_search_last_tested_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "app_runtime_settings",
        sa.Column("companies_web_search_last_test_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "app_runtime_settings",
        sa.Column(
            "companies_web_search_last_test_latency_ms",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "app_runtime_settings",
        sa.Column(
            "companies_web_search_last_test_fingerprint",
            sa.String(length=128),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "app_runtime_settings", "companies_web_search_last_test_fingerprint"
    )
    op.drop_column(
        "app_runtime_settings", "companies_web_search_last_test_latency_ms"
    )
    op.drop_column("app_runtime_settings", "companies_web_search_last_test_error")
    op.drop_column("app_runtime_settings", "companies_web_search_last_tested_at")
    op.drop_column("app_runtime_settings", "companies_web_search_last_test_status")
    op.drop_column("company_enrichment_runs", "web_search_enabled")
