"""Add immutable Gold release metadata.

Revision ID: 0005_gold_releases
Revises: 0004_canonical_fields
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_gold_releases"
down_revision = "0004_canonical_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gold_releases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("json_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("csv_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["json_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["csv_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("processing_run_id", "version", name="uq_gold_releases_run_version"),
        sa.UniqueConstraint("sha256", name="uq_gold_releases_sha256"),
    )
    op.create_index("ix_gold_releases_processing_run_id", "gold_releases", ["processing_run_id"])


def downgrade() -> None:
    op.drop_index("ix_gold_releases_processing_run_id", table_name="gold_releases")
    op.drop_table("gold_releases")
