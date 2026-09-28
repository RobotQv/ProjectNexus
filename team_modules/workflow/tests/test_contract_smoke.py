import pytest

from shared.contracts import DocumentRef, Scope
from shared.errors import AppError
from shared.llm import LLMResult
from team_modules.workflow.adapters import EntityAdapter, WorkflowAdapter


class FakeLLM:
    def complete(self, messages, *, max_tokens=1000):
        return LLMResult(content="只供单测", model="fake", usage={})


def test_workflow_accepts_fake_provider_without_backend():
    workflow = WorkflowAdapter(llm=FakeLLM())
    assert workflow.llm.complete([]).model == "fake"
    with pytest.raises(AppError):
        workflow.extract(
            DocumentRef(project_id=1, document_id=1, version=1, blocks=[]), [], "extract"
        )


def test_entity_adapter_rejects_empty_query_without_embedding():
    # 空文本在调用 Embedding 之前就被拒绝，离线也能验证参数校验。
    with pytest.raises(AppError) as exc:
        EntityAdapter().resolve(Scope(project_id=1), "  ", "task", 5)
    assert exc.value.code == "invalid_entity_query"
