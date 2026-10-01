"""Add XLSX artifact to immutable Gold releases.

Revision ID: 0007_gold_xlsx
Revises: 0006_vocabulary_fields
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_gold_xlsx"
down_revision = "0006_vocabulary_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gold_releases") as batch_op:
        batch_op.add_column(sa.Column("xlsx_artifact_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_gold_releases_xlsx_artifact_id_artifacts",
            "artifacts",
            ["xlsx_artifact_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("gold_releases") as batch_op:
        batch_op.drop_constraint(
            "fk_gold_releases_xlsx_artifact_id_artifacts",
            type_="foreignkey",
        )
        batch_op.drop_column("xlsx_artifact_id")
