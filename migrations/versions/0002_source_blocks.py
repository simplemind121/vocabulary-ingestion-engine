"""Add processing steps and source blocks.

Revision ID: 0002_source_blocks
Revises: 0001_m0_core
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_source_blocks"
down_revision = "0001_m0_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_steps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("step_type", sa.String(length=100), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("processor_name", sa.String(length=255), nullable=False),
        sa.Column("processor_version", sa.String(length=100), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "processing_run_id",
            "sequence_no",
            name="uq_processing_steps_run_sequence",
        ),
    )
    op.create_index(
        "ix_processing_steps_processing_run_id",
        "processing_steps",
        ["processing_run_id"],
    )
    op.create_index("ix_processing_steps_step_type", "processing_steps", ["step_type"])
    op.create_index("ix_processing_steps_status", "processing_steps", ["status"])

    op.create_table(
        "source_blocks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("page_id", sa.String(length=36), nullable=False),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("block_type", sa.String(length=100), nullable=False),
        sa.Column("reading_order", sa.Integer(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=False),
        sa.Column("source_engine", sa.String(length=255), nullable=False),
        sa.Column("source_engine_version", sa.String(length=100), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["page_id"], ["pages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_source_blocks_page_id", "source_blocks", ["page_id"])
    op.create_index(
        "ix_source_blocks_processing_run_id",
        "source_blocks",
        ["processing_run_id"],
    )
    op.create_index("ix_source_blocks_block_type", "source_blocks", ["block_type"])


def downgrade() -> None:
    op.drop_index("ix_source_blocks_block_type", table_name="source_blocks")
    op.drop_index("ix_source_blocks_processing_run_id", table_name="source_blocks")
    op.drop_index("ix_source_blocks_page_id", table_name="source_blocks")
    op.drop_table("source_blocks")
    op.drop_index("ix_processing_steps_status", table_name="processing_steps")
    op.drop_index("ix_processing_steps_step_type", table_name="processing_steps")
    op.drop_index("ix_processing_steps_processing_run_id", table_name="processing_steps")
    op.drop_table("processing_steps")
