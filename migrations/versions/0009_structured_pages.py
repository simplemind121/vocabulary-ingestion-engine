"""Add structured pages: one checked document tree per page and version.

Revision ID: 0009_structured_pages
Revises: 0008_source_media
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_structured_pages"
down_revision = "0008_source_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "structured_pages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("page_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("unit", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("blocks", sa.JSON(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("producer", sa.String(length=100), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=True),
        sa.Column("source_plan", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("processing_run_id", "page_id", "version", name="uq_structured_pages_run_page_version"),
    )
    for column in ("processing_run_id", "page_id", "page_number", "kind", "status"):
        op.create_index(f"ix_structured_pages_{column}", "structured_pages", [column])


def downgrade() -> None:
    for column in ("status", "kind", "page_number", "page_id", "processing_run_id"):
        op.drop_index(f"ix_structured_pages_{column}", table_name="structured_pages")
    op.drop_table("structured_pages")
