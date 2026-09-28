"""Add source entries and canonical vocabulary entries.

Revision ID: 0003_entries
Revises: 0002_source_blocks
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_entries"
down_revision = "0002_source_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("entry_order", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("segmentation_confidence", sa.Float(), nullable=True),
        sa.Column("continuation_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("processing_run_id", "entry_order", name="uq_source_entries_run_order"),
    )
    op.create_index("ix_source_entries_document_version_id", "source_entries", ["document_version_id"])
    op.create_index("ix_source_entries_processing_run_id", "source_entries", ["processing_run_id"])
    op.create_index("ix_source_entries_status", "source_entries", ["status"])

    op.create_table(
        "source_entry_blocks",
        sa.Column("source_entry_id", sa.String(length=36), primary_key=True),
        sa.Column("source_block_id", sa.String(length=36), primary_key=True),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["source_entry_id"], ["source_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_block_id"], ["source_blocks.id"], ondelete="RESTRICT"),
    )

    op.create_table(
        "vocabulary_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_entry_id", sa.String(length=36), nullable=False),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("lemma", sa.String(length=512), nullable=False),
        sa.Column("display_form", sa.String(length=512), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column("canonical_schema_version", sa.String(length=50), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_entry_id"], ["source_entries.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_vocabulary_entries_source_entry_id", "vocabulary_entries", ["source_entry_id"])
    op.create_index("ix_vocabulary_entries_processing_run_id", "vocabulary_entries", ["processing_run_id"])
    op.create_index("ix_vocabulary_entries_lemma", "vocabulary_entries", ["lemma"])
    op.create_index("ix_vocabulary_entries_language", "vocabulary_entries", ["language"])
    op.create_index("ix_vocabulary_entries_verification_status", "vocabulary_entries", ["verification_status"])


def downgrade() -> None:
    op.drop_index("ix_vocabulary_entries_verification_status", table_name="vocabulary_entries")
    op.drop_index("ix_vocabulary_entries_language", table_name="vocabulary_entries")
    op.drop_index("ix_vocabulary_entries_lemma", table_name="vocabulary_entries")
    op.drop_index("ix_vocabulary_entries_processing_run_id", table_name="vocabulary_entries")
    op.drop_index("ix_vocabulary_entries_source_entry_id", table_name="vocabulary_entries")
    op.drop_table("vocabulary_entries")
    op.drop_table("source_entry_blocks")
    op.drop_index("ix_source_entries_status", table_name="source_entries")
    op.drop_index("ix_source_entries_processing_run_id", table_name="source_entries")
    op.drop_index("ix_source_entries_document_version_id", table_name="source_entries")
    op.drop_table("source_entries")
