"""add source identity and ingest outbox fields

Revision ID: 20260506_210000
Revises: 20260506_150000
Create Date: 2026-05-06 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


revision = "20260506_210000"
down_revision = "20260506_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column("source_site", sa.String(length=32), nullable=True, server_default="jobsdb"),
    )
    op.add_column(
        "companies",
        sa.Column("source_company_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("source_job_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "event_outbox",
        sa.Column("source_service", sa.String(length=100), nullable=False, server_default="outbox-publisher"),
    )

    op.execute("ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_name_key")

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        from app.services.source_identity_backfill_service import SourceIdentityBackfillService

        SourceIdentityBackfillService().backfill_source_identity(session)
        session.commit()
    finally:
        session.close()

    op.alter_column("companies", "source_site", nullable=False, server_default="jobsdb")
    op.alter_column("companies", "source_company_id", nullable=False)
    op.alter_column("jobs", "source_job_id", nullable=False)

    op.create_index("ix_companies_source_site", "companies", ["source_site"], unique=False)
    op.create_index("ix_companies_source_company_id", "companies", ["source_company_id"], unique=False)
    op.create_index("ix_jobs_source_job_id", "jobs", ["source_job_id"], unique=False)

    op.create_unique_constraint(
        "uq_companies_source_company_key",
        "companies",
        ["source_site", "source_company_id"],
    )
    op.create_unique_constraint(
        "uq_jobs_source_job_key",
        "jobs",
        ["source_site", "source_job_id"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: source-owned company splitting cannot be downgraded safely."
    )
