"""业务表与审计预案字段对应；JSON 只保存契约数据，不保存 Provider 密钥。"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login_name: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    status: Mapped[str] = mapped_column(String(16), default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16), default="member")
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100"),
        CheckConstraint("status IN ('not_started','in_progress','done','cancelled')"),
        CheckConstraint("status != 'done' OR progress = 100"),
        CheckConstraint("status != 'not_started' OR progress = 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    module_name: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[list] = mapped_column(JSON, default=list)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="not_started")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    planned_start: Mapped[date | None] = mapped_column(Date)
    planned_end: Mapped[date | None] = mapped_column(Date)
    forecast_end: Mapped[date | None] = mapped_column(Date)
    forecast_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    forecast_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    deadline: Mapped[date | None] = mapped_column(Date)
    actual_start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    actual_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    progress_updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    source_suggestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("suggestions.id"), unique=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class TaskDependency(TimestampMixin, Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("project_id", "predecessor_task_id", "successor_task_id"),
        CheckConstraint("predecessor_task_id != successor_task_id", name="ck_dependency_not_self"),
        CheckConstraint(
            "predecessor_required_progress BETWEEN 1 AND 100",
            name="ck_dependency_required_progress",
        ),
        CheckConstraint(
            "(successor_gate = 'progress' AND successor_gate_progress IS NOT NULL AND successor_gate_progress BETWEEN 1 AND 99) OR (successor_gate IN ('start','finish') AND successor_gate_progress IS NULL)",
            name="ck_dependency_gate",
        ),
        {"sqlite_autoincrement": True},
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    predecessor_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    successor_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    predecessor_required_progress: Mapped[int] = mapped_column(Integer)
    successor_gate: Mapped[str] = mapped_column(String(16))
    successor_gate_progress: Mapped[int | None] = mapped_column(Integer)
    gate_needed_on: Mapped[date | None] = mapped_column(Date)
    predecessor_forecast_ready_on: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(Text)
    source_suggestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("suggestions.id"), unique=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(128), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    document_type: Mapped[str | None] = mapped_column(String(64))
    document_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")
    index_status: Mapped[str] = mapped_column(String(16), default="pending")
    index_version: Mapped[str | None] = mapped_column(String(128))
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class DocumentBlock(Base):
    __tablename__ = "document_blocks"
    __table_args__ = (UniqueConstraint("document_id", "document_version", "block_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    block_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(300))
    locator: Mapped[str | None] = mapped_column(String(300))


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("uq_workflow_document_kind", "document_id", "document_version", "kind", unique=True),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    document_version: Mapped[int | None] = mapped_column(Integer)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    source_kind: Mapped[str] = mapped_column(
        String(32), default="document", server_default="document"
    )
    input_text: Mapped[str | None] = mapped_column(Text)
    response_data: Mapped[dict | None] = mapped_column(JSON)
    progress_events: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    request_key: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16), default="extract")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    model_id: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    input_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(Text)


class Suggestion(Base):
    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    source_kind: Mapped[str] = mapped_column(
        String(32), default="document", server_default="document"
    )
    original_payload: Mapped[dict | None] = mapped_column(JSON)
    review_note: Mapped[str | None] = mapped_column(Text)
    suggestion_type: Mapped[str] = mapped_column(String(32))
    proposed_payload: Mapped[dict] = mapped_column(JSON)
    source_refs: Mapped[list] = mapped_column(JSON)
    entity_candidates: Mapped[list] = mapped_column(JSON, default=list)
    validation_warnings: Mapped[list] = mapped_column(JSON, default=list)
    review_status: Mapped[str] = mapped_column(String(16), default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)


class RiskItem(TimestampMixin, Base):
    __tablename__ = "risk_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    related_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    source_suggestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("suggestions.id"), unique=True
    )
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    status: Mapped[str] = mapped_column(String(16), default="open")
    version: Mapped[int] = mapped_column(Integer, default=1)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[int] = mapped_column(Integer)
    resource_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    trigger_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), unique=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    findings: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class QueryRun(Base):
    __tablename__ = "query_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    question: Mapped[str] = mapped_column(Text)
    route: Mapped[str] = mapped_column(String(16))
    entity_ids: Mapped[list] = mapped_column(JSON)
    evidence_refs: Mapped[list] = mapped_column(JSON)
    model_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16))
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[int] = mapped_column(Integer)
    before_version: Mapped[int | None] = mapped_column(Integer)
    after_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TaskHistory(Base):
    """仅追加的完整生效快照；旧数据迁移只补当前基线，不伪造过去的版本。"""

    __tablename__ = "task_history"
    __table_args__ = (UniqueConstraint("task_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(32))
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("suggestions.id"))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


Index(
    "uq_assistant_request",
    WorkflowRun.project_id,
    WorkflowRun.submitted_by,
    WorkflowRun.request_key,
    unique=True,
)


# 同项目相同内容只允许一份有效文档；软删后可重新上传。
Index(
    "uq_documents_live_hash",
    Document.project_id,
    Document.content_hash,
    unique=True,
    sqlite_where=Document.deleted_at.is_(None),
)
