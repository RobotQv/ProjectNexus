"""HTTP 输入契约：拒绝未知字段，避免前端拼错字段却得到成功响应。"""

from datetime import date
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

ShortText = Annotated[str, Field(min_length=1, max_length=200)]
TaskStatus = Literal["not_started", "in_progress", "done", "cancelled"]
StringList = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=30)
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    login_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ProjectCreate(Input):
    name: ShortText
    description: str | None = Field(None, max_length=10000)
    timezone: str = "Asia/Shanghai"

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("无效的 IANA 时区") from None
        return value


class ProjectPatch(Input):
    name: ShortText | None = None
    description: str | None = Field(None, max_length=10000)
    status: Literal["active", "archived"] | None = None


class MemberAdd(Input):
    login_name: str = Field(min_length=1, max_length=64)
    aliases: StringList = []


class MemberPatch(Input):
    aliases: StringList


from shared.task_data import (  # noqa: E402,F401 — 保留旧导入路径，定义仅维护一份
    DependencyCreate,
    DependencyReplace,
    RiskCreate,
    TaskCreate,
    TaskPatch,
)


class RiskPatch(Input):
    expected_version: int = Field(ge=1)
    status: Literal["open", "resolved"]


class Review(Input):
    action: Literal["confirm", "reject"]
    expected_version: int = Field(ge=1)
    # 修改值在确认时再按 TaskCreate / DependencyCreate / RiskCreate 严格验证。
    overrides: dict = Field(default_factory=dict, max_length=30)
    note: str | None = Field(None, max_length=2000)


class SuggestionEdit(Input):
    expected_version: int = Field(ge=1)
    # 完整替换候选载荷，仍按对应建议类型校验；不允许编辑身份/来源/类型。
    proposed_payload: dict = Field(max_length=30)


class SuggestionSubmit(Input):
    expected_version: int = Field(ge=1)


class AssistantStart(Input):
    entry: Literal["project_assistant", "task_assistant"]
    text: str = Field(min_length=1, max_length=4000)
    # 同一次点击/网络重试使用同一个 UUID；主动新提问使用新 UUID。
    request_key: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class Query(Input):
    question: str = Field(min_length=1, max_length=4000)
    route: Literal["auto", "structured", "document", "mixed"] = "auto"
    task_id: int | None = Field(None, gt=0)
    assignee_id: int | None = Field(None, gt=0)
    status: TaskStatus | None = None
    overdue: bool | None = None
    entity_type: Literal["task", "member"] = "task"
    limit: int = Field(10, ge=1, le=50)
    synthesize: bool = False
    include_analysis: bool = False


class Analyze(Input):
    evaluation_date: date | None = None


class WorkflowStart(Input):
    kind: Literal["extract", "summary"] = "extract"


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str
