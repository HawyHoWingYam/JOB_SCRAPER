"""add ai runtime profile test fields

Revision ID: 20260504_170000
Revises: 20260504_120000
Create Date: 2026-05-04 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260504_170000"
down_revision = "20260504_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_runtime_settings", sa.Column("jobs_last_test_status", sa.String(length=32), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("jobs_last_tested_at", sa.DateTime(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("jobs_last_test_error", sa.Text(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("jobs_last_test_provider", sa.String(length=32), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("jobs_last_test_model", sa.String(length=255), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("jobs_last_test_latency_ms", sa.Integer(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("jobs_last_test_fingerprint", sa.String(length=128), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("jobs_last_successful_test_fingerprint", sa.String(length=128), nullable=True))

    op.add_column("app_runtime_settings", sa.Column("companies_last_test_status", sa.String(length=32), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("companies_last_tested_at", sa.DateTime(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("companies_last_test_error", sa.Text(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("companies_last_test_provider", sa.String(length=32), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("companies_last_test_model", sa.String(length=255), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("companies_last_test_latency_ms", sa.Integer(), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("companies_last_test_fingerprint", sa.String(length=128), nullable=True))
    op.add_column("app_runtime_settings", sa.Column("companies_last_successful_test_fingerprint", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("app_runtime_settings", "companies_last_successful_test_fingerprint")
    op.drop_column("app_runtime_settings", "companies_last_test_fingerprint")
    op.drop_column("app_runtime_settings", "companies_last_test_latency_ms")
    op.drop_column("app_runtime_settings", "companies_last_test_model")
    op.drop_column("app_runtime_settings", "companies_last_test_provider")
    op.drop_column("app_runtime_settings", "companies_last_test_error")
    op.drop_column("app_runtime_settings", "companies_last_tested_at")
    op.drop_column("app_runtime_settings", "companies_last_test_status")

    op.drop_column("app_runtime_settings", "jobs_last_successful_test_fingerprint")
    op.drop_column("app_runtime_settings", "jobs_last_test_fingerprint")
    op.drop_column("app_runtime_settings", "jobs_last_test_latency_ms")
    op.drop_column("app_runtime_settings", "jobs_last_test_model")
    op.drop_column("app_runtime_settings", "jobs_last_test_provider")
    op.drop_column("app_runtime_settings", "jobs_last_test_error")
    op.drop_column("app_runtime_settings", "jobs_last_tested_at")
    op.drop_column("app_runtime_settings", "jobs_last_test_status")
