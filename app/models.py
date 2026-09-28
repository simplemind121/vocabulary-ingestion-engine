from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Artifact(Base):
    __tablename__="artifacts"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    artifact_type: Mapped[str]=mapped_column(String(100),index=True)
    storage_provider: Mapped[str]=mapped_column(String(100),default="local")
    bucket: Mapped[str]=mapped_column(String(255),default="local")
    object_key: Mapped[str]=mapped_column(String(2048),unique=True)
    mime_type: Mapped[str|None]=mapped_column(String(255),nullable=True)
    byte_size: Mapped[int|None]=mapped_column(BigInteger,nullable=True)
    sha256: Mapped[str|None]=mapped_column(String(64),index=True,nullable=True)
    metadata_json: Mapped[dict]=mapped_column("metadata",JSON,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Document(Base):
    __tablename__="documents"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    original_filename: Mapped[str]=mapped_column(String(1024))
    status: Mapped[str]=mapped_column(String(50),default="INGESTED",index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)

class DocumentVersion(Base):
    __tablename__="document_versions"
    __table_args__=(UniqueConstraint("document_id","version_no",name="uq_document_versions_document_version"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    document_id: Mapped[str]=mapped_column(ForeignKey("documents.id",ondelete="RESTRICT"),index=True)
    version_no: Mapped[int]=mapped_column(Integer,default=1)
    source_artifact_id: Mapped[str]=mapped_column(ForeignKey("artifacts.id",ondelete="RESTRICT"))
    sha256: Mapped[str]=mapped_column(String(64),index=True)
    mime_type: Mapped[str]=mapped_column(String(255))
    file_size: Mapped[int]=mapped_column(BigInteger)
    page_count: Mapped[int]=mapped_column(Integer)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class Page(Base):
    __tablename__="pages"
    __table_args__=(UniqueConstraint("document_version_id","page_number",name="uq_pages_version_page"),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    document_version_id: Mapped[str]=mapped_column(ForeignKey("document_versions.id",ondelete="RESTRICT"),index=True)
    page_number: Mapped[int]=mapped_column(Integer)
    render_artifact_id: Mapped[str]=mapped_column(ForeignKey("artifacts.id",ondelete="RESTRICT"))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ProcessingRun(Base):
    __tablename__="processing_runs"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    document_version_id: Mapped[str]=mapped_column(ForeignKey("document_versions.id",ondelete="RESTRICT"),index=True)
    pipeline_version: Mapped[str]=mapped_column(String(100),default="0.1.0-alpha.2")
    canonical_schema_version: Mapped[str]=mapped_column(String(50),default="1.0")
    configuration_snapshot: Mapped[dict]=mapped_column(JSON,default=dict)
    configuration_hash: Mapped[str]=mapped_column(String(64),default="")
    status: Mapped[str]=mapped_column(String(50),default="RUNNING",index=True)
    metrics: Mapped[dict]=mapped_column(JSON,default=dict)
    error_summary: Mapped[dict|None]=mapped_column(JSON,nullable=True)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class GateEvaluation(Base):
    __tablename__="gate_evaluations"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    processing_run_id: Mapped[str]=mapped_column(ForeignKey("processing_runs.id",ondelete="RESTRICT"),index=True)
    gate: Mapped[str]=mapped_column(String(20),index=True)
    ruleset_version: Mapped[str]=mapped_column(String(50),default="1.0.0")
    scope_type: Mapped[str]=mapped_column(String(100),default="DOCUMENT")
    scope_id: Mapped[str]=mapped_column(String(36))
    status: Mapped[str]=mapped_column(String(50),index=True)
    metrics: Mapped[dict]=mapped_column(JSON,default=dict)
    blocking_failures: Mapped[list]=mapped_column(JSON,default=list)
    warnings: Mapped[list]=mapped_column(JSON,default=list)
    evidence: Mapped[dict]=mapped_column(JSON,default=dict)
    evaluated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ReviewTask(Base):
    __tablename__="review_tasks"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    processing_run_id: Mapped[str]=mapped_column(ForeignKey("processing_runs.id",ondelete="RESTRICT"),index=True)
    reason_code: Mapped[str]=mapped_column(String(255))
    status: Mapped[str]=mapped_column(String(50),default="OPEN",index=True)
    target_entity_type: Mapped[str]=mapped_column(String(100))
    target_entity_id: Mapped[str]=mapped_column(String(36))
    target_field_path: Mapped[str|None]=mapped_column(String(512),nullable=True)
    source_context: Mapped[dict]=mapped_column(JSON,default=dict)
    candidate_values: Mapped[list]=mapped_column(JSON,default=list)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)

class ProvenanceRecord(Base):
    __tablename__="provenance_records"
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    processing_run_id: Mapped[str]=mapped_column(ForeignKey("processing_runs.id",ondelete="RESTRICT"),index=True)
    target_entity_type: Mapped[str]=mapped_column(String(100))
    target_entity_id: Mapped[str]=mapped_column(String(36))
    target_field_path: Mapped[str]=mapped_column(String(512))
    provenance_type: Mapped[str]=mapped_column(String(100),index=True)
    source_text: Mapped[str|None]=mapped_column(Text,nullable=True)
    metadata_json: Mapped[dict]=mapped_column("metadata",JSON,default=dict)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
