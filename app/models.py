from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    artifact_type: Mapped[str] = mapped_column(String(100), index=True)
    storage_provider: Mapped[str] = mapped_column(String(100), default="local")
    bucket: Mapped[str] = mapped_column(String(255), default="local")
    object_key: Mapped[str] = mapped_column(String(2048), unique=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    original_filename: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(50), default="INGESTED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_no", name="uq_document_versions_document_version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="RESTRICT"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    source_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_version_id", "page_number", name="uq_pages_version_page"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    render_artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingRun(Base):
    __tablename__ = "processing_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"), index=True)
    pipeline_version: Mapped[str] = mapped_column(String(100), default="0.1.0-alpha.2")
    canonical_schema_version: Mapped[str] = mapped_column(String(50), default="1.0")
    configuration_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    configuration_hash: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(50), default="RUNNING", index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GateEvaluation(Base):
    __tablename__ = "gate_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    gate: Mapped[str] = mapped_column(String(20), index=True)
    ruleset_version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    scope_type: Mapped[str] = mapped_column(String(100), default="DOCUMENT")
    scope_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(50), index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    blocking_failures: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    reason_code: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="OPEN", index=True)
    target_entity_type: Mapped[str] = mapped_column(String(100))
    target_entity_id: Mapped[str] = mapped_column(String(36))
    target_field_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_context: Mapped[dict] = mapped_column(JSON, default=dict)
    candidate_values: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProvenanceRecord(Base):
    __tablename__ = "provenance_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    target_entity_type: Mapped[str] = mapped_column(String(100))
    target_entity_id: Mapped[str] = mapped_column(String(36))
    target_field_path: Mapped[str] = mapped_column(String(512))
    provenance_type: Mapped[str] = mapped_column(String(100), index=True)
    source_entry_id: Mapped[str | None] = mapped_column(ForeignKey("source_entries.id", ondelete="RESTRICT"), index=True, nullable=True)
    source_block_id: Mapped[str | None] = mapped_column(ForeignKey("source_blocks.id", ondelete="RESTRICT"), index=True, nullable=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey("pages.id", ondelete="RESTRICT"), index=True, nullable=True)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingStep(Base):
    __tablename__ = "processing_steps"
    __table_args__ = (UniqueConstraint("processing_run_id", "sequence_no", name="uq_processing_steps_run_sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    step_type: Mapped[str] = mapped_column(String(100), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    processor_name: Mapped[str] = mapped_column(String(255))
    processor_version: Mapped[str] = mapped_column(String(100))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="CREATED", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceBlock(Base):
    __tablename__ = "source_blocks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="RESTRICT"), index=True)
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    block_type: Mapped[str] = mapped_column(String(100), default="TEXT", index=True)
    reading_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    bbox: Mapped[dict] = mapped_column(JSON)
    source_engine: Mapped[str] = mapped_column(String(255))
    source_engine_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceEntry(Base):
    __tablename__ = "source_entries"
    __table_args__ = (UniqueConstraint("processing_run_id", "entry_order", name="uq_source_entries_run_order"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id", ondelete="RESTRICT"), index=True)
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    entry_order: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    segmentation_confidence: Mapped[float | None] = mapped_column(nullable=True)
    continuation_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="PARSED", index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceEntryBlock(Base):
    __tablename__ = "source_entry_blocks"
    source_entry_id: Mapped[str] = mapped_column(ForeignKey("source_entries.id", ondelete="CASCADE"), primary_key=True)
    source_block_id: Mapped[str] = mapped_column(ForeignKey("source_blocks.id", ondelete="RESTRICT"), primary_key=True)
    block_order: Mapped[int] = mapped_column(Integer)


class VocabularyEntry(Base):
    __tablename__ = "vocabulary_entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_entry_id: Mapped[str] = mapped_column(ForeignKey("source_entries.id", ondelete="RESTRICT"), index=True)
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    lemma: Mapped[str] = mapped_column(String(512), index=True)
    display_form: Mapped[str | None] = mapped_column(String(512), nullable=True)
    language: Mapped[str] = mapped_column(String(32), default="en", index=True)
    verification_status: Mapped[str] = mapped_column(String(50), default="PARSED", index=True)
    canonical_schema_version: Mapped[str] = mapped_column(String(50), default="1.0")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Pronunciation(Base):
    __tablename__ = "pronunciations"
    __table_args__ = (UniqueConstraint("vocabulary_entry_id", "pronunciation_order", name="uq_pronunciations_entry_order"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vocabulary_entry_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_entries.id", ondelete="CASCADE"), index=True)
    pronunciation_order: Mapped[int] = mapped_column(Integer)
    ipa: Mapped[str | None] = mapped_column(Text, nullable=True)
    phonetic_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    dialect: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(50), default="PARSED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Sense(Base):
    __tablename__ = "senses"
    __table_args__ = (UniqueConstraint("vocabulary_entry_id", "sense_order", name="uq_senses_entry_order"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vocabulary_entry_id: Mapped[str] = mapped_column(ForeignKey("vocabulary_entries.id", ondelete="CASCADE"), index=True)
    sense_order: Mapped[int] = mapped_column(Integer)
    part_of_speech: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(50), default="PARSED", index=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Definition(Base):
    __tablename__ = "definitions"
    __table_args__ = (UniqueConstraint("sense_id", "definition_order", name="uq_definitions_sense_order"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sense_id: Mapped[str] = mapped_column(ForeignKey("senses.id", ondelete="CASCADE"), index=True)
    definition_order: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(50), default="PARSED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Example(Base):
    __tablename__ = "examples"
    __table_args__ = (UniqueConstraint("sense_id", "example_order", name="uq_examples_sense_order"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sense_id: Mapped[str] = mapped_column(ForeignKey("senses.id", ondelete="CASCADE"), index=True)
    example_order: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(50), default="PARSED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GoldRelease(Base):
    __tablename__ = "gold_releases"
    __table_args__ = (
        UniqueConstraint("processing_run_id", "version", name="uq_gold_releases_run_version"),
        UniqueConstraint("sha256", name="uq_gold_releases_sha256"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    processing_run_id: Mapped[str] = mapped_column(ForeignKey("processing_runs.id", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[str] = mapped_column(String(50))
    record_count: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    json_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=True)
    csv_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VocabularyField(Base):
    __tablename__ = "vocabulary_fields"
    __table_args__ = (
        UniqueConstraint(
            "vocabulary_entry_id",
            "field_type",
            "field_order",
            name="uq_vocabulary_fields_entry_type_order",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    vocabulary_entry_id: Mapped[str] = mapped_column(
        ForeignKey("vocabulary_entries.id", ondelete="CASCADE"), index=True
    )
    field_type: Mapped[str] = mapped_column(String(50), index=True)
    field_order: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(50), default="PARSED", index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
