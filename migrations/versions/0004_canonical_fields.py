"""Add canonical vocabulary substructures and provenance source links.

Revision ID: 0004_canonical_fields
Revises: 0003_entries
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_canonical_fields"
down_revision = "0003_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provenance_records", sa.Column("source_entry_id", sa.String(length=36), nullable=True))
    op.add_column("provenance_records", sa.Column("source_block_id", sa.String(length=36), nullable=True))
    op.add_column("provenance_records", sa.Column("page_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_provenance_source_entry",
        "provenance_records",
        "source_entries",
        ["source_entry_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_provenance_source_block",
        "provenance_records",
        "source_blocks",
        ["source_block_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_provenance_page",
        "provenance_records",
        "pages",
        ["page_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_provenance_records_source_entry_id", "provenance_records", ["source_entry_id"])
    op.create_index("ix_provenance_records_source_block_id", "provenance_records", ["source_block_id"])
    op.create_index("ix_provenance_records_page_id", "provenance_records", ["page_id"])

    op.create_table(
        "pronunciations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vocabulary_entry_id", sa.String(length=36), nullable=False),
        sa.Column("pronunciation_order", sa.Integer(), nullable=False),
        sa.Column("ipa", sa.Text(), nullable=True),
        sa.Column("phonetic_text", sa.Text(), nullable=True),
        sa.Column("dialect", sa.String(length=100), nullable=True),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["vocabulary_entry_id"], ["vocabulary_entries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "vocabulary_entry_id",
            "pronunciation_order",
            name="uq_pronunciations_entry_order",
        ),
    )
    op.create_index("ix_pronunciations_vocabulary_entry_id", "pronunciations", ["vocabulary_entry_id"])
    op.create_index("ix_pronunciations_verification_status", "pronunciations", ["verification_status"])

    op.create_table(
        "senses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vocabulary_entry_id", sa.String(length=36), nullable=False),
        sa.Column("sense_order", sa.Integer(), nullable=False),
        sa.Column("part_of_speech", sa.String(length=100), nullable=True),
        sa.Column("source_label", sa.String(length=255), nullable=True),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["vocabulary_entry_id"], ["vocabulary_entries.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("vocabulary_entry_id", "sense_order", name="uq_senses_entry_order"),
    )
    op.create_index("ix_senses_vocabulary_entry_id", "senses", ["vocabulary_entry_id"])
    op.create_index("ix_senses_verification_status", "senses", ["verification_status"])

    op.create_table(
        "definitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("sense_id", sa.String(length=36), nullable=False),
        sa.Column("definition_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sense_id"], ["senses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sense_id", "definition_order", name="uq_definitions_sense_order"),
    )
    op.create_index("ix_definitions_sense_id", "definitions", ["sense_id"])
    op.create_index("ix_definitions_verification_status", "definitions", ["verification_status"])

    op.create_table(
        "examples",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("sense_id", sa.String(length=36), nullable=False),
        sa.Column("example_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["sense_id"], ["senses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sense_id", "example_order", name="uq_examples_sense_order"),
    )
    op.create_index("ix_examples_sense_id", "examples", ["sense_id"])
    op.create_index("ix_examples_verification_status", "examples", ["verification_status"])


def downgrade() -> None:
    op.drop_index("ix_examples_verification_status", table_name="examples")
    op.drop_index("ix_examples_sense_id", table_name="examples")
    op.drop_table("examples")
    op.drop_index("ix_definitions_verification_status", table_name="definitions")
    op.drop_index("ix_definitions_sense_id", table_name="definitions")
    op.drop_table("definitions")
    op.drop_index("ix_senses_verification_status", table_name="senses")
    op.drop_index("ix_senses_vocabulary_entry_id", table_name="senses")
    op.drop_table("senses")
    op.drop_index("ix_pronunciations_verification_status", table_name="pronunciations")
    op.drop_index("ix_pronunciations_vocabulary_entry_id", table_name="pronunciations")
    op.drop_table("pronunciations")
    op.drop_index("ix_provenance_records_page_id", table_name="provenance_records")
    op.drop_index("ix_provenance_records_source_block_id", table_name="provenance_records")
    op.drop_index("ix_provenance_records_source_entry_id", table_name="provenance_records")
    op.drop_constraint("fk_provenance_page", "provenance_records", type_="foreignkey")
    op.drop_constraint("fk_provenance_source_block", "provenance_records", type_="foreignkey")
    op.drop_constraint("fk_provenance_source_entry", "provenance_records", type_="foreignkey")
    op.drop_column("provenance_records", "page_id")
    op.drop_column("provenance_records", "source_block_id")
    op.drop_column("provenance_records", "source_entry_id")
