"""M0 core persistence baseline.

Revision ID: 0001_m0_core
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_m0_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("artifact_type", sa.String(length=100), nullable=False),
        sa.Column("storage_provider", sa.String(length=100), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=2048), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_artifact_type", "artifacts", ["artifact_type"])
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"])

    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("original_filename", sa.String(length=1024), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("source_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("document_id", "version_no", name="uq_document_versions_document_version"),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index("ix_document_versions_sha256", "document_versions", ["sha256"])

    op.create_table(
        "pages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("render_artifact_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["render_artifact_id"], ["artifacts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("document_version_id", "page_number", name="uq_pages_version_page"),
    )
    op.create_index("ix_pages_document_version_id", "pages", ["document_version_id"])

    op.create_table(
        "processing_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("document_version_id", sa.String(length=36), nullable=False),
        sa.Column("pipeline_version", sa.String(length=100), nullable=False),
        sa.Column("canonical_schema_version", sa.String(length=50), nullable=False),
        sa.Column("configuration_snapshot", sa.JSON(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_processing_runs_document_version_id", "processing_runs", ["document_version_id"])
    op.create_index("ix_processing_runs_status", "processing_runs", ["status"])

    op.create_table(
        "gate_evaluations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("gate", sa.String(length=20), nullable=False),
        sa.Column("ruleset_version", sa.String(length=50), nullable=False),
        sa.Column("scope_type", sa.String(length=100), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("blocking_failures", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_gate_evaluations_processing_run_id", "gate_evaluations", ["processing_run_id"])
    op.create_index("ix_gate_evaluations_gate", "gate_evaluations", ["gate"])
    op.create_index("ix_gate_evaluations_status", "gate_evaluations", ["status"])

    op.create_table(
        "review_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("reason_code", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("target_entity_type", sa.String(length=100), nullable=False),
        sa.Column("target_entity_id", sa.String(length=36), nullable=False),
        sa.Column("target_field_path", sa.String(length=512), nullable=True),
        sa.Column("source_context", sa.JSON(), nullable=False),
        sa.Column("candidate_values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_review_tasks_processing_run_id", "review_tasks", ["processing_run_id"])
    op.create_index("ix_review_tasks_status", "review_tasks", ["status"])

    op.create_table(
        "provenance_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("processing_run_id", sa.String(length=36), nullable=False),
        sa.Column("target_entity_type", sa.String(length=100), nullable=False),
        sa.Column("target_entity_id", sa.String(length=36), nullable=False),
        sa.Column("target_field_path", sa.String(length=512), nullable=False),
        sa.Column("provenance_type", sa.String(length=100), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_provenance_records_processing_run_id", "provenance_records", ["processing_run_id"])
    op.create_index("ix_provenance_records_provenance_type", "provenance_records", ["provenance_type"])


def downgrade() -> None:
    op.drop_table("provenance_records")
    op.drop_table("review_tasks")
    op.drop_table("gate_evaluations")
    op.drop_table("processing_runs")
    op.drop_table("pages")
    op.drop_table("document_versions")
    op.drop_table("documents")
    op.drop_table("artifacts")
