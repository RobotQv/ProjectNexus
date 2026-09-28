"""模块契约 v2。统一任务候选、助手只读工具与风险预览；返回值经后端校验。"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.task_data import DependencyRecord, TaskChanges, TaskRecord, UpdateTaskProposal


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(Contract):
    project_id: int


class FileRef(Contract):
    project_id: int
    document_id: int
    version: int
    path: Path
    filename: str
    content_hash: str


class ParsedBlock(Contract):
    block_no: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=200000)
    page: int | None = Field(None, ge=1)
    heading: str | None = None
    locator: str | None = None


class Block(ParsedBlock):
    id: int
    document_id: int
    document_version: int


class ParsedDocument(Contract):
    blocks: list[ParsedBlock] = Field(min_length=1, max_length=50000)


class DocumentRef(Contract):
    project_id: int
    document_id: int
    version: int
    document_date: date | None = None
    filename: str = ""
    blocks: list[Block]


class IngestResult(Contract):
    index_version: str
    chunk_count: int = Field(ge=0)


class Evidence(Contract):
    document_id: int
    version: int
    block_ids: list[int] = Field(min_length=1, max_length=20)
    quote: str = Field(min_length=1, max_length=8000)


class Candidate(Contract):
    entity_type: Literal["task", "member"]
    entity_id: int
    title: str
    score: float | None = None
    match_reason: str = ""


class Resolution(Contract):
    outcome: Literal["resolved", "ambiguous", "not_found"]
    candidates: list[Candidate] = Field(default_factory=list, max_length=50)
    index_version: str = "unavailable"


class EntityRecord(Contract):
    project_id: int
    entity_type: Literal["task", "member"]
    entity_id: int
    source_version: int
    search_text: str
    is_active: bool


class SuggestionDraft(Contract):
    suggestion_type: Literal["create_task", "update_task", "propose_dependency", "create_risk"]
    proposed_payload: dict
    source_refs: list[Evidence] = Field(default_factory=list, max_length=30)
    entity_candidates: list[Candidate] = []
    validation_warnings: list[str] = []

    @model_validator(mode="after")
    def payload_contract(self):
        # 候选可以缺少创建必填信息，不能出现错拼字段或任意数据库字段。
        schema = {
            "create_task": TaskChanges,
            "update_task": UpdateTaskProposal,
            "propose_dependency": DependencyDraft,
            "create_risk": RiskDraft,
        }[self.suggestion_type]
        self.proposed_payload = schema.model_validate(self.proposed_payload).model_dump(
            mode="json", exclude_unset=True
        )
        return self


class DependencyDraft(Contract):
    predecessor_task_id: int | None = Field(None, gt=0)
    successor_task_id: int | None = Field(None, gt=0)
    predecessor_required_progress: int | None = Field(None, ge=1, le=100, strict=True)
    successor_gate: Literal["start", "progress", "finish"] | None = None
    successor_gate_progress: int | None = Field(None, ge=1, le=99, strict=True)
    gate_needed_on: date | None = None
    predecessor_forecast_ready_on: date | None = None
    description: str | None = Field(None, max_length=10000)


class RiskDraft(Contract):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, min_length=1, max_length=20000)
    related_task_id: int | None = Field(None, gt=0)
    severity: Literal["unknown", "low", "medium", "high"] | None = None


class ExtractionResult(Contract):
    suggestions: list[SuggestionDraft] = Field(default_factory=list, max_length=300)
    summary: str | None = None
    model_id: str
    prompt_version: str


class Snapshot(Contract):
    project_id: int
    timezone: str
    evaluation_date: date
    tasks: list[dict]
    dependencies: list[dict]

    @model_validator(mode="after")
    def typed_records(self):
        # 保持 dict 访问方式兼容风险实现，但每条数据先通过统一完整格式验证。
        self.tasks = [TaskRecord.model_validate(t).model_dump(mode="json") for t in self.tasks]
        self.dependencies = [
            DependencyRecord.model_validate(e).model_dump(mode="json") for e in self.dependencies
        ]
        if any(t["project_id"] != self.project_id for t in [*self.tasks, *self.dependencies]):
            raise ValueError("快照不能混入其他项目记录")
        return self


class Finding(Contract):
    task_ids: list[int]
    candidate_keys: list[str] = Field(default_factory=list)
    dependency_id: int | None = None
    dependency_status: (
        Literal[
            "satisfied", "condition_unmet", "blocked_now", "finish_condition_unmet", "data_conflict"
        ]
        | None
    ) = None
    timing_status: Literal["future_risk", "timing_unknown", "on_time"] | None = None
    reason_codes: list[str]
    explanation: str


class AnalysisResult(Contract):
    rule_version: str
    findings: list[Finding]
    warnings: list[str] = []


class CandidateChange(Contract):
    key: str = Field(min_length=1, max_length=64)
    suggestion: SuggestionDraft
    # 仅风险预览引用本批尚未创建的任务；正式审核时必须选择真实任务 ID。
    predecessor_key: str | None = Field(None, min_length=1, max_length=64)
    successor_key: str | None = Field(None, min_length=1, max_length=64)


class RiskPreview(Contract):
    snapshot: Snapshot
    changes: list[CandidateChange] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_keys(self):
        if len({c.key for c in self.changes}) != len(self.changes):
            raise ValueError("候选 key 不可重复")
        new_tasks = {c.key for c in self.changes if c.suggestion.suggestion_type == "create_task"}
        for c in self.changes:
            for side in ("predecessor", "successor"):
                ref = getattr(c, side + "_key")
                if ref is not None and (
                    c.suggestion.suggestion_type != "propose_dependency"
                    or ref not in new_tasks
                    or c.suggestion.proposed_payload.get(side + "_task_id") is not None
                ):
                    raise ValueError("候选依赖引用必须指向本批新建任务，且不能同时指定正式 ID")
        return self


class TaskSearch(Contract):
    task_id: int | None = Field(None, gt=0)
    keyword: str | None = Field(None, min_length=1, max_length=200)
    status: Literal["not_started", "in_progress", "done", "cancelled"] | None = None
    assignee_id: int | None = Field(None, gt=0)
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class AssistantRequest(Contract):
    entry: Literal["project_assistant", "task_assistant"]
    text: str = Field(min_length=1, max_length=4000)


class AssistantResult(Contract):
    answer: str = Field(max_length=30000)
    outcome: Literal["answered", "clarify", "insufficient", "partial"] = "answered"
    suggestions: list[SuggestionDraft] = Field(default_factory=list, max_length=100)
    task_ids: list[int] = Field(default_factory=list, max_length=100)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)
    candidates: list[Candidate] = Field(default_factory=list, max_length=50)
    warnings: list[str] = Field(default_factory=list)
    model_id: str
    prompt_version: str


class AssistantTools(Protocol):
    """绑定当前项目与登录身份的只读工具，绝不提供批准或正式任务写入工具。"""

    def search_tasks(self, query: TaskSearch) -> list[dict]: ...
    def entity_catalog(self) -> list[EntityRecord]: ...
    def resolve(self, text: str, entity_type: str = "task", limit: int = 10) -> Resolution: ...
    def retrieve(self, question: str, limit: int = 5) -> list[Evidence]: ...
    def snapshot(self) -> Snapshot: ...
    def preview_risk(self, changes: list[CandidateChange]) -> AnalysisResult: ...


class MainRAG(Protocol):
    def parse(self, file: FileRef) -> ParsedDocument: ...
    def ingest(self, document: DocumentRef) -> IngestResult: ...
    def retrieve(self, scope: Scope, question: str, limit: int) -> list[Evidence]: ...
    def delete(self, scope: Scope, document_id: int, version: int) -> None: ...


class EntityResolver(Protocol):
    def sync(self, entity: EntityRecord) -> None: ...
    def resolve(self, scope: Scope, text: str, entity_type: str, limit: int) -> Resolution: ...


class Workflow(Protocol):
    def respond(self, request: AssistantRequest, tools: AssistantTools) -> AssistantResult: ...
    def extract(
        self,
        document: DocumentRef,
        entity_catalog: list[EntityRecord],
        kind: str,
        *,
        tools: AssistantTools | None = None,
    ) -> ExtractionResult: ...


class RiskAnalyzer(Protocol):
    def analyze(self, snapshot: Snapshot) -> AnalysisResult: ...
    def analyze_candidates(self, preview: RiskPreview) -> AnalysisResult: ...


@dataclass
class Modules:
    main_rag: MainRAG
    entities: EntityResolver
    workflow: Workflow
    risk: RiskAnalyzer
    is_demo: bool = False
