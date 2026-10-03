"""Add source media printed in the original book.

Revision ID: 0008_source_media
Revises: 0007_gold_xlsx
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_source_media"
down_revision = "0007_gold_xlsx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_media",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("page_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("media_order", sa.Integer(), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("source_entry_id", sa.String(length=36), nullable=True),
        sa.Column("vocabulary_entry_id", sa.String(length=36), nullable=True),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("media_role", sa.String(length=50), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("extraction_method", sa.String(length=100), nullable=False),
        sa.Column("association_method", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_entry_id"], ["source_entries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["vocabulary_entry_id"], ["vocabulary_entries.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "processing_run_id", "page_id", "media_order", name="uq_source_media_run_page_order"
        ),
    )
    for column in (
        "document_version_id",
        "processing_run_id",
        "page_id",
        "source_entry_id",
        "vocabulary_entry_id",
        "media_role",
        "sha256",
        "verification_status",
    ):
        op.create_index(f"ix_source_media_{column}", "source_media", [column])


def downgrade() -> None:
    for column in (
        "verification_status",
        "sha256",
        "media_role",
        "vocabulary_entry_id",
        "source_entry_id",
        "page_id",
        "processing_run_id",
        "document_version_id",
    ):
        op.drop_index(f"ix_source_media_{column}", table_name="source_media")
    op.drop_table("source_media")
