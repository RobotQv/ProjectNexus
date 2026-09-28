"""给工作流提示词/前端使用的可导出 JSON Schema，与运行时校验共享字段类型。"""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from shared.contracts import Candidate, Contract, DependencyDraft, Evidence, RiskDraft
from shared.task_data import (
    DependencyCreate,
    TaskChanges,
    TaskCreate,
    TaskPatch,
    TaskRecord,
    UpdateTaskProposal,
)


class SuggestionMeta(Contract):
    source_refs: list[Evidence] = Field(default_factory=list, max_length=30)
    entity_candidates: list[Candidate] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


class CreateTaskSuggestion(SuggestionMeta):
    suggestion_type: Literal["create_task"]
    proposed_payload: TaskChanges


class UpdateTaskSuggestion(SuggestionMeta):
    suggestion_type: Literal["update_task"]
    proposed_payload: UpdateTaskProposal


class DependencySuggestion(SuggestionMeta):
    suggestion_type: Literal["propose_dependency"]
    proposed_payload: DependencyDraft


class RiskSuggestion(SuggestionMeta):
    suggestion_type: Literal["create_risk"]
    proposed_payload: RiskDraft


StructuredSuggestion = Annotated[
    CreateTaskSuggestion | UpdateTaskSuggestion | DependencySuggestion | RiskSuggestion,
    Field(discriminator="suggestion_type"),
]


def json_schemas():
    return {
        "contract_version": "2",
        "task_create": TaskCreate.model_json_schema(),
        "task_patch": TaskPatch.model_json_schema(),
        "task_record": TaskRecord.model_json_schema(),
        "dependency_create": DependencyCreate.model_json_schema(),
        "suggestion": TypeAdapter(StructuredSuggestion).json_schema(),
    }
