"""前端可从 OpenAPI 生成类型；输出模型避免内部列在重构时意外泄漏。"""

from datetime import date, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

from app.integrations.contracts import Candidate, Evidence
from app.schemas import DependencyCreate, RiskCreate
from shared.task_data import TaskRecord

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    limit: int
    offset: int


class UserOut(BaseModel):
    id: int
    login_name: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LoginOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: UserOut


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str | None
    owner_id: int
    timezone: str
    status: Literal["active", "archived"]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class TaskOut(TaskRecord):
    """HTTP 与模块任务记录使用同一套字段定义。"""


class DependencyOut(DependencyCreate):
    id: int
    project_id: int
    source_suggestion_id: int | None
    version: int
    created_at: datetime
    updated_at: datetime


class RiskOut(RiskCreate):
    id: int
    project_id: int
    origin: Literal["manual", "extracted"]
    source_suggestion_id: int | None
    version: int
    status: Literal["open", "resolved"]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class DocumentOut(BaseModel):
    id: int
    project_id: int
    uploaded_by: int
    filename: str
    media_type: str
    size_bytes: int
    content_hash: str
    document_type: str | None
    document_date: date | None
    version: int
    parse_status: Literal["pending", "running", "ready", "failed"]
    index_status: Literal["pending", "running", "ready", "failed"]
    index_version: str | None
    chunk_count: int | None
    error_message: str | None
    created_by_demo: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class UploadOut(BaseModel):
    document: DocumentOut
    job_id: int


class JobOut(BaseModel):
    id: int
    project_id: int
    kind: str
    resource_type: str
    resource_id: int
    resource_version: int
    status: Literal["queued", "running", "succeeded", "failed"]
    attempts: int
    dedup_key: str
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SuggestionOut(BaseModel):
    id: int
    run_id: int
    project_id: int
    suggestion_type: Literal["create_task", "update_task", "propose_dependency", "create_risk"]
    submitted_by: int | None
    created_at: datetime
    submitted_at: datetime | None
    source_kind: Literal["document", "project_assistant", "task_assistant"]
    original_payload: dict | None
    review_note: str | None
    proposed_payload: dict
    source_refs: list[Evidence]
    entity_candidates: list[Candidate]
    validation_warnings: list[str]
    review_status: Literal["draft", "pending", "approved", "rejected"]
    reviewed_by: int | None
    reviewed_at: datetime | None
    target_type: str | None
    target_id: int | None
    version: int


class AnalysisOut(BaseModel):
    id: int
    project_id: int
    trigger_job_id: int | None = None
    snapshot_hash: str
    rule_version: str
    evaluated_at: datetime
    input_snapshot: dict
    findings: list[dict]
    warnings: list[str]
    is_demo: bool


class QueryOut(BaseModel):
    request_id: str
    query_id: int
    outcome: Literal["answered", "clarify", "insufficient", "partial"]
    answer: str
    facts: list[TaskOut]
    evidence: list[Evidence]
    analysis: AnalysisOut | None
    candidates: list[Candidate]
    warnings: list[str]
    route: Literal["structured", "document", "mixed"]
    model_id: str | None
    is_demo: bool


class TaskHistoryOut(BaseModel):
    id: int
    project_id: int
    task_id: int
    version: int
    snapshot: TaskOut
    actor_id: int | None
    source: str
    suggestion_id: int | None
    recorded_at: datetime


class AssistantOut(BaseModel):
    run_id: int
    answer: str
    outcome: Literal["answered", "clarify", "insufficient", "partial"]
    suggestions: list[SuggestionOut]
    facts: list[TaskOut]
    evidence: list[Evidence]
    candidates: list[Candidate]
    warnings: list[str]
    risk_previews: list[dict]
    model_id: str
    prompt_version: str
    is_demo: bool
