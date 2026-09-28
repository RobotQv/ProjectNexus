"""所有模块共用的任务业务字段；正式写入和 AI 候选使用同一套字段约束。"""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
TaskStatus = Literal["not_started", "in_progress", "done", "cancelled"]
StringList = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=30)
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TaskCreate(Input):
    title: ShortText
    description: str | None = Field(None, max_length=20000)
    assignee_id: int | None = Field(None, gt=0)
    module_name: str | None = Field(None, max_length=100)
    tags: StringList = []
    aliases: StringList = []
    status: TaskStatus = "not_started"
    progress: int = Field(0, ge=0, le=100, strict=True)
    planned_start: date | None = None
    planned_end: date | None = None
    forecast_end: date | None = None
    deadline: date | None = None
    actual_start_at: AwareDatetime | None = None
    actual_end_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "done" and self.progress != 100:
            raise ValueError("done 状态的 progress 必须为 100")
        if self.status == "not_started" and self.progress != 0:
            raise ValueError("not_started 状态的 progress 必须为 0")
        if self.planned_start and self.planned_end and self.planned_start > self.planned_end:
            raise ValueError("计划开始不能晚于计划完成")
        if (
            self.actual_start_at
            and self.actual_end_at
            and self.actual_start_at > self.actual_end_at
        ):
            raise ValueError("实际开始不能晚于实际完成")
        return self


class DependencyCreate(Input):
    predecessor_task_id: int = Field(gt=0)
    successor_task_id: int = Field(gt=0)
    predecessor_required_progress: int = Field(ge=1, le=100, strict=True)
    successor_gate: Literal["start", "progress", "finish"]
    successor_gate_progress: int | None = Field(None, ge=1, le=99, strict=True)
    gate_needed_on: date | None = None
    predecessor_forecast_ready_on: date | None = None
    description: str | None = Field(None, max_length=10000)

    @model_validator(mode="after")
    def gate(self):
        if self.predecessor_task_id == self.successor_task_id:
            raise ValueError("不允许自依赖")
        if (self.successor_gate == "progress") != (self.successor_gate_progress is not None):
            raise ValueError("仅 progress 关卡必须填写 successor_gate_progress")
        return self


class DependencyReplace(DependencyCreate):
    expected_version: int = Field(ge=1)


class RiskCreate(Input):
    title: ShortText
    description: str = Field(min_length=1, max_length=20000)
    related_task_id: int | None = Field(None, gt=0)
    severity: Literal["unknown", "low", "medium", "high"] = "unknown"


class TaskChanges(Input):
    """AI 候选和人工修正的部分字段；省略表示不改，null 仅用于可清空字段。"""

    title: ShortText | None = None
    description: str | None = Field(None, max_length=20000)
    assignee_id: int | None = Field(None, gt=0)
    module_name: str | None = Field(None, max_length=100)
    tags: StringList | None = None
    aliases: StringList | None = None
    status: TaskStatus | None = None
    progress: int | None = Field(None, ge=0, le=100, strict=True)
    planned_start: date | None = None
    planned_end: date | None = None
    forecast_end: date | None = None
    deadline: date | None = None
    actual_start_at: AwareDatetime | None = None
    actual_end_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def reject_required_null(self):
        for key in self.model_fields_set & {"title", "status", "progress", "tags", "aliases"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} 不可为 null")
        return self


class TaskPatch(TaskChanges):
    expected_version: int = Field(ge=1, strict=True)


class UpdateTaskProposal(Input):
    task_id: int = Field(gt=0, strict=True)
    expected_version: int = Field(ge=1, strict=True)
    changes: TaskChanges

    @model_validator(mode="after")
    def nonempty(self):
        if not self.changes.model_fields_set:
            raise ValueError("任务更新必须至少包含一个业务字段")
        return self


class TaskRecord(TaskCreate):
    id: int
    project_id: int
    forecast_updated_at: datetime | None
    forecast_by: int | None
    progress_updated_at: datetime
    source_suggestion_id: int | None
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class DependencyRecord(DependencyCreate):
    id: int
    project_id: int
    source_suggestion_id: int | None
    version: int
    created_at: datetime
    updated_at: datetime
