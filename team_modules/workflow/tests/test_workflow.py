"""工作流单测：用脚本化假 LLM 和假工具，不请求真实模型或后端。"""

import json
from datetime import date

import pytest

from shared.contracts import (
    AssistantRequest,
    Block,
    Candidate,
    DocumentRef,
    EntityRecord,
    Resolution,
    Snapshot,
)
from shared.errors import AppError
from shared.llm import LLMResult
from team_modules.workflow.adapters import WorkflowAdapter


class ScriptedLLM:
    """按顺序返回预先写好的内容；用完就回退到空 JSON。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, *, max_tokens=1000):
        self.calls.append(messages)
        content = self.responses.pop(0) if self.responses else "{}"
        return LLMResult(content=content, model="fake", usage={})


class FakeTools:
    def __init__(
        self,
        tasks=None,
        entities=None,
        evidences=None,
        resolution=None,
        snapshot=None,
        preview_error=None,
    ):
        self.tasks = tasks or []
        self.entities = entities or []
        self.evidences = evidences or []
        self.resolution = resolution
        self._snapshot = snapshot
        self.preview_calls = []
        self.preview_error = preview_error

    def search_tasks(self, query):
        return self.tasks

    def entity_catalog(self):
        return self.entities

    def resolve(self, text, entity_type="task", limit=10):
        return self.resolution or Resolution(outcome="not_found", candidates=[])

    def retrieve(self, question, limit=5):
        return self.evidences

    def snapshot(self):
        return self._snapshot or Snapshot(
            project_id=1,
            timezone="Asia/Shanghai",
            evaluation_date=date.today(),
            tasks=[],
            dependencies=[],
        )

    def preview_risk(self, changes):
        self.preview_calls.append(changes)
        if self.preview_error:
            raise self.preview_error
        return None


def test_respond_query_answers():
    llm = ScriptedLLM(["query", "登录接口已完成七成。"])
    workflow = WorkflowAdapter(llm=llm)
    result = workflow.respond(
        AssistantRequest(entry="project_assistant", text="登录接口进度如何"), FakeTools()
    )
    assert result.answer == "登录接口已完成七成。"
    assert result.outcome == "insufficient"  # 无事实时明确 insufficient，不编造
    assert result.model_id == "fake"


def test_respond_query_uses_snapshot():
    # query 也要取项目快照，否则“有哪些依赖/阻塞风险”这类问题没有事实可答。
    snap = Snapshot(
        project_id=1,
        timezone="Asia/Shanghai",
        evaluation_date=date.today(),
        tasks=[],
        dependencies=[
            {
                "id": 9,
                "project_id": 1,
                "source_suggestion_id": None,
                "version": 1,
                "created_at": "2026-09-01T00:00:00",
                "updated_at": "2026-09-01T00:00:00",
                "predecessor_task_id": 10,
                "successor_task_id": 11,
                "predecessor_required_progress": 100,
                "successor_gate": "start",
            }
        ],
    )
    llm = ScriptedLLM(["query", "项目有哪些依赖"])
    workflow = WorkflowAdapter(llm=llm)
    result = workflow.respond(
        AssistantRequest(entry="project_assistant", text="项目有哪些依赖"), FakeTools(snapshot=snap)
    )
    user_content = llm.calls[1][1]["content"]
    assert "dependencies" in user_content
    assert "predecessor_task_id" in user_content
    assert result.outcome == "answered"  # 快照里有依赖，不再是 insufficient


def test_respond_suggest_parses_suggestions():
    payload = json.dumps(
        [{"suggestion_type": "create_task", "proposed_payload": {"title": "完成登录接口"}}],
        ensure_ascii=False,
    )
    llm = ScriptedLLM(["suggest", "create", payload])
    workflow = WorkflowAdapter(llm=llm)
    result = workflow.respond(
        AssistantRequest(entry="task_assistant", text="新建任务：完成登录接口"), FakeTools()
    )
    assert len(result.suggestions) == 1
    assert result.suggestions[0].suggestion_type == "create_task"
    assert result.suggestions[0].proposed_payload["title"] == "完成登录接口"


def test_extract_keeps_real_quote_and_evidence():
    doc = DocumentRef(
        project_id=1,
        document_id=5,
        version=1,
        filename="meeting.txt",
        blocks=[
            Block(
                id=18,
                document_id=5,
                document_version=1,
                block_no=0,
                text="登录接口已经完成七成。",
            )
        ],
    )
    payload = json.dumps(
        [
            {
                "suggestion_type": "create_task",
                "proposed_payload": {"title": "完成登录接口"},
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录接口已经完成七成。",
                    }
                ],
            }
        ],
        ensure_ascii=False,
    )
    llm = ScriptedLLM([payload])
    workflow = WorkflowAdapter(llm=llm)
    result = workflow.extract(doc, [], "extract")
    assert len(result.suggestions) == 1
    ref = result.suggestions[0].source_refs[0]
    assert ref.document_id == 5 and ref.version == 1
    assert ref.block_ids == [18]
    assert "登录接口" in ref.quote


def test_extract_falls_back_to_verbatim_block_text():
    doc = DocumentRef(
        project_id=1,
        document_id=5,
        version=1,
        blocks=[
            Block(
                id=18,
                document_id=5,
                document_version=1,
                block_no=0,
                text="登录接口已经完成七成。",
            )
        ],
    )
    # 模型给了被改写的 quote，应被真实原文替换，而不是保留伪造来源。
    payload = json.dumps(
        [
            {
                "suggestion_type": "create_task",
                "proposed_payload": {"title": "完成登录接口"},
                "source_refs": [
                    {"document_id": 5, "version": 1, "block_ids": [18], "quote": "登录差不多做完了"}
                ],
            }
        ],
        ensure_ascii=False,
    )
    llm = ScriptedLLM([payload])
    workflow = WorkflowAdapter(llm=llm)
    result = workflow.extract(doc, [], "extract")
    ref = result.suggestions[0].source_refs[0]
    assert ref.quote == "登录接口已经完成七成。"


def _dependency_doc():
    return DocumentRef(
        project_id=1,
        document_id=5,
        version=1,
        blocks=[
            Block(
                id=18,
                document_id=5,
                document_version=1,
                block_no=0,
                text="登录完成后才能开始联调。",
            )
        ],
    )


def test_extract_calls_preview_risk_for_dependency():
    payload = json.dumps(
        [
            {
                "suggestion_type": "create_task",
                "proposed_payload": {"title": "完成登录接口"},
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录完成后才能开始联调。",
                    }
                ],
            },
            {
                "suggestion_type": "propose_dependency",
                "proposed_payload": {
                    "predecessor_task_id": 10,
                    "successor_task_id": 11,
                    "predecessor_required_progress": 100,
                    "successor_gate": "start",
                },
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录完成后才能开始联调。",
                    }
                ],
            },
        ],
        ensure_ascii=False,
    )
    tools = FakeTools()
    workflow = WorkflowAdapter(llm=ScriptedLLM([payload]))
    result = workflow.extract(_dependency_doc(), [], "extract", tools=tools)
    assert len(result.suggestions) == 2
    assert len(tools.preview_calls) == 1
    changes = tools.preview_calls[0]
    assert {c.suggestion.suggestion_type for c in changes} == {"create_task", "propose_dependency"}
    assert all(c.key for c in changes)
    assert len({c.key for c in changes}) == 2  # key 本批唯一


def test_extract_preview_risk_failure_is_recorded():
    payload = json.dumps(
        [
            {
                "suggestion_type": "propose_dependency",
                "proposed_payload": {"predecessor_task_id": 10, "successor_task_id": 11},
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录完成后才能开始联调。",
                    }
                ],
            }
        ],
        ensure_ascii=False,
    )
    tools = FakeTools(preview_error=AppError("module_unavailable", "候选依赖风险判断尚未接入", 503))
    workflow = WorkflowAdapter(llm=ScriptedLLM([payload]))
    result = workflow.extract(_dependency_doc(), [], "extract", tools=tools)
    assert len(result.suggestions) == 1  # 风险预览失败不阻断抽取
    dep = result.suggestions[0]
    assert dep.suggestion_type == "propose_dependency"
    assert any("风险预览不可用" in w for w in dep.validation_warnings)


def test_extract_create_task_only_skips_preview():
    payload = json.dumps(
        [
            {
                "suggestion_type": "create_task",
                "proposed_payload": {"title": "完成登录接口"},
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录完成后才能开始联调。",
                    }
                ],
            }
        ],
        ensure_ascii=False,
    )
    tools = FakeTools()
    workflow = WorkflowAdapter(llm=ScriptedLLM([payload]))
    workflow.extract(_dependency_doc(), [], "extract", tools=tools)
    assert tools.preview_calls == []  # 纯新建任务无依赖关系，不打扰风险模块


def test_extract_update_task_previews_existing_dependency_risk():
    payload = json.dumps(
        [
            {
                "suggestion_type": "update_task",
                "proposed_payload": {
                    "task_id": 10,
                    "expected_version": 1,
                    "changes": {"progress": 50},
                },
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录完成后才能开始联调。",
                    }
                ],
            }
        ],
        ensure_ascii=False,
    )
    tools = FakeTools()
    workflow = WorkflowAdapter(llm=ScriptedLLM([payload]))
    workflow.extract(_dependency_doc(), [], "extract", tools=tools)
    assert len(tools.preview_calls) == 1  # 进度更新也会影响已有依赖，必须按更新后的状态预览。


def test_extract_non_task_text_returns_empty():
    # 正文没有可提取内容时，模型输出空数组，应得到空建议而不是报错。
    workflow = WorkflowAdapter(llm=ScriptedLLM(["[]"]))
    result = workflow.extract(_dependency_doc(), [], "extract")
    assert result.suggestions == []


def test_extract_deduplicates_repeated_suggestions():
    ref = {"document_id": 5, "version": 1, "block_ids": [18], "quote": "登录完成后才能开始联调。"}
    payload = json.dumps(
        [
            {
                "suggestion_type": "create_task",
                "proposed_payload": {"title": "完成登录接口"},
                "source_refs": [ref],
            },
            {
                "suggestion_type": "create_task",
                "proposed_payload": {"title": "完成登录接口"},
                "source_refs": [ref],
            },
        ],
        ensure_ascii=False,
    )
    workflow = WorkflowAdapter(llm=ScriptedLLM([payload]))
    result = workflow.extract(_dependency_doc(), [], "extract")
    assert len(result.suggestions) == 1


def test_respond_clarify_on_ambiguous_entity():
    llm = ScriptedLLM(["query"])
    workflow = WorkflowAdapter(llm=llm)
    tools = FakeTools(
        resolution=Resolution(
            outcome="ambiguous",
            candidates=[
                Candidate(entity_type="task", entity_id=1, title="登录接口", score=0.9),
                Candidate(entity_type="task", entity_id=2, title="登录接口优化", score=0.85),
            ],
        )
    )
    result = workflow.respond(
        AssistantRequest(entry="project_assistant", text="登录接口进度如何"), tools
    )
    assert result.outcome == "clarify"
    assert len(result.candidates) == 2
    assert "ID 1" in result.answer and "ID 2" in result.answer
    assert len(llm.calls) == 1  # 只做了意图分类，没再调模型编答案


def test_respond_suggest_clarify_on_ambiguous_entity():
    # 更新/依赖/风险意图下实体歧义要返回 clarify，不猜 ID；且不再调用模型生成建议。
    llm = ScriptedLLM(["suggest", "update"])
    workflow = WorkflowAdapter(llm=llm)
    tools = FakeTools(
        resolution=Resolution(
            outcome="ambiguous",
            candidates=[
                Candidate(entity_type="task", entity_id=1, title="登录接口", score=0.9),
                Candidate(entity_type="task", entity_id=2, title="登录接口优化", score=0.85),
            ],
        )
    )
    result = workflow.respond(
        AssistantRequest(entry="task_assistant", text="把登录接口改成进行中"), tools
    )
    assert result.outcome == "clarify"
    assert len(result.candidates) == 2
    assert "ID 1" in result.answer and "ID 2" in result.answer
    assert len(llm.calls) == 2  # 意图分类 + 细分意图，没再生成


def test_suggest_includes_dependencies_in_context():
    snap = Snapshot(
        project_id=1,
        timezone="Asia/Shanghai",
        evaluation_date=date.today(),
        tasks=[],
        dependencies=[
            {
                "id": 9,
                "project_id": 1,
                "source_suggestion_id": None,
                "version": 1,
                "created_at": "2026-09-01T00:00:00",
                "updated_at": "2026-09-01T00:00:00",
                "predecessor_task_id": 10,
                "successor_task_id": 11,
                "predecessor_required_progress": 100,
                "successor_gate": "start",
            }
        ],
    )
    payload = json.dumps(
        [{"suggestion_type": "create_task", "proposed_payload": {"title": "完成任务"}}],
        ensure_ascii=False,
    )
    llm = ScriptedLLM(["suggest", "dependency", payload])
    workflow = WorkflowAdapter(llm=llm)
    workflow.respond(
        AssistantRequest(entry="task_assistant", text="安排依赖"), FakeTools(snapshot=snap)
    )
    user_content = llm.calls[2][1]["content"]
    assert "依赖" in user_content
    assert "predecessor_task_id" in user_content


def test_suggest_includes_resolve_candidates_in_context():
    snap = Snapshot(
        project_id=1,
        timezone="Asia/Shanghai",
        evaluation_date=date.today(),
        tasks=[],
        dependencies=[],
    )
    payload = json.dumps(
        [{"suggestion_type": "create_task", "proposed_payload": {"title": "完成任务"}}],
        ensure_ascii=False,
    )
    llm = ScriptedLLM(["suggest", "create", payload])
    tools = FakeTools(
        snapshot=snap,
        resolution=Resolution(
            outcome="resolved",
            candidates=[
                Candidate(entity_type="task", entity_id=10, title="完成登录接口", score=0.9)
            ],
        ),
    )
    workflow = WorkflowAdapter(llm=llm)
    workflow.respond(AssistantRequest(entry="task_assistant", text="新建任务"), tools)
    user_content = llm.calls[2][1]["content"]
    assert "实体候选" in user_content  # resolve 出的候选要喂给模型，而不是白算一次
    assert "完成登录接口" in user_content


def test_iter_batches_splits_long_document():
    blocks = [
        Block(id=i, document_id=1, document_version=1, block_no=i, text="x" * 100) for i in range(5)
    ]
    batches = list(WorkflowAdapter._iter_batches(blocks, budget=250))
    assert [len(b) for b in batches] == [2, 2, 1]


def test_extract_preserves_missing_fields():
    payload = json.dumps(
        [
            {
                "suggestion_type": "create_task",
                "proposed_payload": {"title": "完成登录接口"},
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录完成后才能开始联调。",
                    }
                ],
                "validation_warnings": ["原文未提负责人和日期"],
            }
        ],
        ensure_ascii=False,
    )
    workflow = WorkflowAdapter(llm=ScriptedLLM([payload]))
    result = workflow.extract(_dependency_doc(), [], "extract")
    p = result.suggestions[0].proposed_payload
    assert "assignee_id" not in p
    assert "planned_end" not in p
    assert result.suggestions[0].validation_warnings == ["原文未提负责人和日期"]


def test_extract_attaches_entity_candidates():
    payload = json.dumps(
        [
            {
                "suggestion_type": "update_task",
                "proposed_payload": {
                    "task_id": 10,
                    "expected_version": 1,
                    "changes": {"status": "in_progress", "progress": 50},
                },
                "source_refs": [
                    {
                        "document_id": 5,
                        "version": 1,
                        "block_ids": [18],
                        "quote": "登录完成后才能开始联调。",
                    }
                ],
            }
        ],
        ensure_ascii=False,
    )
    catalog = [
        EntityRecord(
            project_id=1,
            entity_type="task",
            entity_id=10,
            source_version=1,
            search_text="完成登录接口",
            is_active=True,
        )
    ]
    workflow = WorkflowAdapter(llm=ScriptedLLM([payload]))
    result = workflow.extract(_dependency_doc(), catalog, "extract")
    cands = result.suggestions[0].entity_candidates
    assert [c.entity_id for c in cands] == [10]
    assert cands[0].entity_type == "task"


def test_summarize():
    doc = DocumentRef(
        project_id=1,
        document_id=5,
        version=1,
        blocks=[
            Block(id=18, document_id=5, document_version=1, block_no=0, text="本周完成登录接口。")
        ],
    )
    llm = ScriptedLLM(["本周完成登录接口。"])
    workflow = WorkflowAdapter(llm=llm)
    result = workflow.extract(doc, [], "summary")
    assert result.summary == "本周完成登录接口。"
    assert result.suggestions == []


def test_extract_empty_document_fails():
    workflow = WorkflowAdapter(llm=ScriptedLLM([]))
    with pytest.raises(AppError) as exc:
        workflow.extract(
            DocumentRef(project_id=1, document_id=1, version=1, blocks=[]), [], "extract"
        )
    assert exc.value.code == "empty_document"


def test_unparseable_model_json_fails():
    workflow = WorkflowAdapter(llm=ScriptedLLM(["这不是 JSON"]))
    with pytest.raises(AppError) as exc:
        workflow.extract(
            DocumentRef(
                project_id=1,
                document_id=5,
                version=1,
                blocks=[Block(id=1, document_id=5, document_version=1, block_no=0, text="x")],
            ),
            [],
            "extract",
        )
    assert exc.value.code == "model_json_parse_failed"
