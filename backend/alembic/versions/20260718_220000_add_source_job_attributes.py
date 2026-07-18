"""add Source Job Attribute projections

Revision ID: 20260718_220000
Revises: 20260718_210000
Create Date: 2026-07-18 22:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_220000"
down_revision = "20260718_210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_source_catalog_revision_id_source",
        "source_catalog_revisions",
        ["id", "source_site"],
    )

    op.create_table(
        "job_source_attribute_projections",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_job_source_attribute_projection_source",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_job_source_attribute_projection_hash",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_job_source_attribute_projection_version",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_job_source_attribute_projections_source_site",
        "job_source_attribute_projections",
        ["source_site"],
    )

    employment_types = op.create_table(
        "employment_types",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "sort_order > 0",
            name="ck_employment_type_sort_order",
        ),
        sa.PrimaryKeyConstraint("code"),
        sa.UniqueConstraint("label", name="uq_employment_type_label"),
        sa.UniqueConstraint("sort_order", name="uq_employment_type_sort_order"),
    )
    op.bulk_insert(
        employment_types,
        [
            {"code": "full_time", "label": "Full-time", "sort_order": 1},
            {"code": "part_time", "label": "Part-time", "sort_order": 2},
            {"code": "permanent", "label": "Permanent", "sort_order": 3},
            {"code": "contract", "label": "Contract", "sort_order": 4},
            {"code": "temporary", "label": "Temporary", "sort_order": 5},
            {"code": "internship", "label": "Internship", "sort_order": 6},
            {"code": "freelance", "label": "Freelance", "sort_order": 7},
        ],
    )

    op.create_table(
        "job_source_classification_paths",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column(
            "source_catalog_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("path_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("primary_basis", sa.String(length=255), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_job_source_classification_path_source",
        ),
        sa.CheckConstraint(
            "source_order >= 0",
            name="ck_job_source_classification_path_order",
        ),
        sa.CheckConstraint(
            "length(path_fingerprint) = 64",
            name="ck_job_source_classification_path_fingerprint",
        ),
        sa.CheckConstraint(
            "(is_primary AND primary_basis IS NOT NULL AND length(trim(primary_basis)) > 0) "
            "OR (NOT is_primary AND primary_basis IS NULL)",
            name="ck_job_source_classification_path_primary_basis",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_catalog_revision_id", "source_site"],
            ["source_catalog_revisions.id", "source_catalog_revisions.source_site"],
            name="fk_job_source_classification_path_catalog_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_site",
            name="uq_job_source_classification_path_id_source",
        ),
        sa.UniqueConstraint(
            "job_id",
            "path_fingerprint",
            name="uq_job_source_classification_path_fingerprint",
        ),
        sa.UniqueConstraint(
            "job_id",
            "source_order",
            name="uq_job_source_classification_path_order",
        ),
    )
    op.create_index(
        "ix_job_source_classification_paths_job_id",
        "job_source_classification_paths",
        ["job_id"],
    )
    op.create_index(
        "ix_job_source_classification_paths_source_site",
        "job_source_classification_paths",
        ["source_site"],
    )
    op.create_index(
        "ix_job_source_classification_paths_source_catalog_revision_id",
        "job_source_classification_paths",
        ["source_catalog_revision_id"],
    )
    op.create_index(
        "ux_job_source_classification_primary",
        "job_source_classification_paths",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "job_source_classification_path_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("source_position", sa.Integer(), nullable=False),
        sa.Column("native_depth", sa.Integer(), nullable=False),
        sa.Column(
            "source_classification_id",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("native_id", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            "source_position >= 0",
            name="ck_job_source_classification_node_position",
        ),
        sa.CheckConstraint(
            "native_depth >= 0",
            name="ck_job_source_classification_node_depth",
        ),
        sa.CheckConstraint(
            "source_classification_id LIKE source_site || ':%' "
            "AND length(source_classification_id) > length(source_site) + 1",
            name="ck_job_source_classification_node_source_identity",
        ),
        sa.ForeignKeyConstraint(
            ["path_id", "source_site"],
            [
                "job_source_classification_paths.id",
                "job_source_classification_paths.source_site",
            ],
            name="fk_job_source_classification_node_path_source",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "path_id",
            "source_position",
            name="uq_job_source_classification_node_position",
        ),
        sa.UniqueConstraint(
            "path_id",
            "source_classification_id",
            name="uq_job_source_classification_node_identity",
        ),
    )
    op.create_index(
        "ix_job_source_classification_path_nodes_path_id",
        "job_source_classification_path_nodes",
        ["path_id"],
    )
    op.create_index(
        "ix_job_source_classification_node_source_identity",
        "job_source_classification_path_nodes",
        ["source_site", "source_classification_id"],
    )

    op.create_table(
        "job_source_employment_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("raw_code", sa.String(length=255), nullable=True),
        sa.Column("raw_label", sa.String(length=255), nullable=True),
        sa.Column("normalized_lookup_key", sa.String(length=255), nullable=True),
        sa.Column("mapped_type_code", sa.String(length=32), nullable=True),
        sa.Column("mapping_id", sa.String(length=255), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_job_source_employment_label_source",
        ),
        sa.CheckConstraint(
            "source_order >= 0",
            name="ck_job_source_employment_label_order",
        ),
        sa.CheckConstraint(
            "raw_code IS NOT NULL OR raw_label IS NOT NULL",
            name="ck_job_source_employment_label_evidence",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mapped_type_code"],
            ["employment_types.code"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "source_order",
            name="uq_job_source_employment_label_order",
        ),
    )
    op.create_index(
        "ix_job_source_employment_labels_job_id",
        "job_source_employment_labels",
        ["job_id"],
    )
    op.create_index(
        "ix_job_source_employment_labels_mapped_type_code",
        "job_source_employment_labels",
        ["mapped_type_code"],
    )
    op.create_index(
        "ix_job_source_employment_label_source_lookup",
        "job_source_employment_labels",
        ["source_site", "normalized_lookup_key"],
    )

    op.create_table(
        "job_employment_types",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employment_type_code", sa.String(length=32), nullable=False),
        sa.Column("evidence_label_ids", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["employment_type_code"],
            ["employment_types.code"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("job_id", "employment_type_code"),
    )
    op.create_index(
        "ix_job_employment_types_employment_type_code",
        "job_employment_types",
        ["employment_type_code"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_job_employment_types_employment_type_code",
        table_name="job_employment_types",
    )
    op.drop_table("job_employment_types")

    op.drop_index(
        "ix_job_source_employment_label_source_lookup",
        table_name="job_source_employment_labels",
    )
    op.drop_index(
        "ix_job_source_employment_labels_mapped_type_code",
        table_name="job_source_employment_labels",
    )
    op.drop_index(
        "ix_job_source_employment_labels_job_id",
        table_name="job_source_employment_labels",
    )
    op.drop_table("job_source_employment_labels")

    op.drop_index(
        "ix_job_source_classification_node_source_identity",
        table_name="job_source_classification_path_nodes",
    )
    op.drop_index(
        "ix_job_source_classification_path_nodes_path_id",
        table_name="job_source_classification_path_nodes",
    )
    op.drop_table("job_source_classification_path_nodes")

    op.drop_index(
        "ux_job_source_classification_primary",
        table_name="job_source_classification_paths",
    )
    op.drop_index(
        "ix_job_source_classification_paths_source_catalog_revision_id",
        table_name="job_source_classification_paths",
    )
    op.drop_index(
        "ix_job_source_classification_paths_source_site",
        table_name="job_source_classification_paths",
    )
    op.drop_index(
        "ix_job_source_classification_paths_job_id",
        table_name="job_source_classification_paths",
    )
    op.drop_table("job_source_classification_paths")

    op.drop_table("employment_types")

    op.drop_index(
        "ix_job_source_attribute_projections_source_site",
        table_name="job_source_attribute_projections",
    )
    op.drop_table("job_source_attribute_projections")

    op.drop_constraint(
        "uq_source_catalog_revision_id_source",
        "source_catalog_revisions",
        type_="unique",
    )
