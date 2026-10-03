"""Add normalized source-faithful rich vocabulary fields.

Revision ID: 0006_vocabulary_fields
Revises: 0005_gold_releases
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_vocabulary_fields"
down_revision = "0005_gold_releases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vocabulary_fields",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("vocabulary_entry_id", sa.String(length=36), nullable=False),
        sa.Column("field_type", sa.String(length=50), nullable=False),
        sa.Column("field_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("verification_status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["vocabulary_entry_id"],
            ["vocabulary_entries.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "vocabulary_entry_id",
            "field_type",
            "field_order",
            name="uq_vocabulary_fields_entry_type_order",
        ),
    )
    op.create_index(
        "ix_vocabulary_fields_vocabulary_entry_id",
        "vocabulary_fields",
        ["vocabulary_entry_id"],
    )
    op.create_index(
        "ix_vocabulary_fields_field_type",
        "vocabulary_fields",
        ["field_type"],
    )
    op.create_index(
        "ix_vocabulary_fields_verification_status",
        "vocabulary_fields",
        ["verification_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_vocabulary_fields_verification_status", table_name="vocabulary_fields")
    op.drop_index("ix_vocabulary_fields_field_type", table_name="vocabulary_fields")
    op.drop_index("ix_vocabulary_fields_vocabulary_entry_id", table_name="vocabulary_fields")
    op.drop_table("vocabulary_fields")
