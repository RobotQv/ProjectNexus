"""四份组员提交合并后的接口验证；数据库和 Chroma 使用临时目录，模型用固定返回值。"""

import json
from uuid import uuid4

import pytest

from app.services.tools import BoundTools
from shared.contracts import CandidateChange, RiskPreview, SuggestionDraft
from shared.errors import AppError
from shared.llm import LLMResult
from team_modules.factory import build_modules
from team_modules.main_rag.indexing.store import VectorStore
from team_modules.risk.adapter import RiskAdapter
from team_modules.workflow.indexing.store import EntityStore
from tests.conftest import drain, new_task


class OfflineEmbedding:
    def embed(self, texts):
        # 固定测试向量，仅验证索引持久化/项目隔离，不评价语义准确率。
        return [[1.0] + [0.0] * 2047 for _ in texts]


class ScriptedModel:
    def __init__(self):
        self.responses = []

    def complete(self, messages, *, max_tokens=1000):
        assert self.responses, "出现了计划外的模型请求"
        value = self.responses.pop(0)
        return LLMResult(content=value, model="integration-fake", usage={})


@pytest.fixture
def integrated(env):
    model = ScriptedModel()
    modules = build_modules(settings=env.settings, llm=model)
    modules.main_rag._embedding = OfflineEmbedding()
    modules.entities._embedding = OfflineEmbedding()
    env.app.state.modules = modules
    env.worker.modules = modules
    return env, modules, model


def post(env, path, data, status=200):
    response = env.client.post(env.prefix + path, json=data)
    assert response.status_code == status, response.text
    return response.json()


def test_real_modules_document_extraction_review_and_history(integrated):
    env, modules, model = integrated
    upload = env.client.post(
        env.prefix + "/documents",
        files={
            "file": ("meeting.txt", "需要新增登录接口测试任务。".encode(), "text/plain"),
        },
    )
    assert upload.status_code == 202, upload.text
    doc_id = upload.json()["document"]["id"]
    drain(env)
    doc = env.client.get(env.prefix + f"/documents/{doc_id}").json()
    assert doc["parse_status"] == doc["index_status"] == "ready"
    block = env.client.get(env.prefix + f"/documents/{doc_id}/blocks?version=1").json()["items"][0]
    model.responses = [
        json.dumps(
            [
                {
                    "suggestion_type": "create_task",
                    "proposed_payload": {"title": "登录接口测试"},
                    "source_refs": [
                        {
                            "document_id": doc_id,
                            "version": 1,
                            "block_ids": [block["id"]],
                            "quote": block["text"],
                        }
                    ],
                }
            ]
        )
    ]
    post(env, f"/documents/{doc_id}/extract", {"kind": "extract"}, 202)
    drain(env)
    draft = env.client.get(env.prefix + "/suggestions?status=pending").json()["items"][0]
    assert draft["submitted_by"] == 1
    assert env.client.get(env.prefix + "/tasks").json()["items"] == []
    source = env.client.get(env.prefix + f"/suggestions/{draft['id']}/source").json()
    assert source["documents"][0]["quote"] == block["text"]
    approved = post(
        env,
        f"/suggestions/{draft['id']}/review",
        {"action": "confirm", "expected_version": draft["version"]},
    )
    drain(env)
    task_id = approved["target_id"]
    history = env.client.get(env.prefix + f"/tasks/{task_id}/history").json()["items"]
    assert history[0]["snapshot"]["title"] == "登录接口测试"
    # 新的索引客户端可读同一目录，模拟 API 与 Worker 的独立实例。
    reopened = VectorStore(modules.main_rag._store_dir)
    assert reopened.collection.count() == 1
    assert EntityStore(modules.entities._store_dir).collection.count() >= 2
    assert not model.responses


@pytest.mark.parametrize("entry", ["task_assistant", "project_assistant"])
def test_real_workflow_assistant_update_requires_both_reviews(integrated, entry):
    env, modules, model = integrated
    task = new_task(env, title="登录接口", status="in_progress", progress=20)
    drain(env)
    proposal = {
        "suggestion_type": "update_task",
        "proposed_payload": {
            "task_id": task["id"],
            "expected_version": task["version"],
            "changes": {"progress": 70},
        },
    }
    model.responses = ["suggest", "update", json.dumps([proposal])]
    request = {"entry": entry, "text": "登录接口进度更新到七成", "request_key": uuid4().hex}
    out = post(env, "/assistant/messages", request)
    suggestion = out["suggestions"][0]
    assert suggestion["review_status"] == "draft"
    assert env.client.get(env.prefix + f"/tasks/{task['id']}").json()["progress"] == 20
    duplicate = post(env, "/assistant/messages", request)
    assert duplicate["suggestions"][0]["id"] == suggestion["id"]
    pending = post(
        env, f"/suggestions/{suggestion['id']}/submit", {"expected_version": suggestion["version"]}
    )
    assert env.client.get(env.prefix + f"/tasks/{task['id']}").json()["progress"] == 20
    post(
        env,
        f"/suggestions/{pending['id']}/review",
        {"action": "confirm", "expected_version": pending["version"]},
    )
    assert env.client.get(env.prefix + f"/tasks/{task['id']}").json()["progress"] == 70
    assert len(env.client.get(env.prefix + f"/tasks/{task['id']}/history").json()["items"]) == 2
    drain(env)
    status = env.client.get(env.prefix + "/risk-status").json()
    assert status["analysis"]["rule_version"] == "risk-v1"
    assert status["is_stale"] is False


def test_preview_uses_updated_task_without_changing_database(integrated):
    env, modules, model = integrated
    a = new_task(env, title="A", status="in_progress", progress=70)
    b = new_task(env, title="B", status="in_progress", progress=80)
    dependency = {
        "predecessor_task_id": a["id"],
        "successor_task_id": b["id"],
        "predecessor_required_progress": 100,
        "successor_gate": "progress",
        "successor_gate_progress": 80,
    }
    post(env, "/dependencies", dependency, 201)
    changes = [
        CandidateChange(
            key="update-a",
            suggestion=SuggestionDraft(
                suggestion_type="update_task",
                proposed_payload={
                    "task_id": a["id"],
                    "expected_version": a["version"],
                    "changes": {"status": "done", "progress": 100},
                },
            ),
        )
    ]
    result = post(env, "/analysis/preview", [c.model_dump(mode="json") for c in changes])
    assert result["findings"][0]["dependency_status"] == "satisfied"
    assert result["findings"][0]["candidate_keys"] == ["update-a"]
    assert env.client.get(env.prefix + f"/tasks/{a['id']}").json()["progress"] == 70
    # 同一更新也应用于本批尚未保存的依赖。
    changes.append(
        CandidateChange(
            key="new-edge",
            suggestion=SuggestionDraft(
                suggestion_type="propose_dependency", proposed_payload=dependency
            ),
        )
    )
    state = BoundTools(env.app.state.sessions, env.pid, 1, modules).snapshot()
    before = state.model_dump(mode="json")
    assert all(
        f.dependency_status == "satisfied"
        for f in RiskAdapter()
        .analyze_candidates(RiskPreview(snapshot=state, changes=changes))
        .findings
    )
    assert state.model_dump(mode="json") == before
    changes[0].suggestion.proposed_payload["expected_version"] = 999
    with pytest.raises(AppError) as exc:
        RiskAdapter().analyze_candidates(RiskPreview(snapshot=state, changes=changes))
    assert exc.value.code == "candidate_version_conflict"


def test_factory_injects_key_without_exporting_it_to_environment(env, monkeypatch):
    monkeypatch.setenv("NEXUS_LLM_API_KEY", "different-env-value")
    from pydantic import SecretStr

    settings = env.settings.model_copy(update={"llm_api_key": SecretStr("config-only-test-key")})
    modules = build_modules(settings=settings, llm=ScriptedModel())
    assert modules.main_rag.embedding.api_key == "config-only-test-key"
    assert modules.entities.embedding.api_key == "config-only-test-key"
    assert modules.main_rag._store_dir == env.tmp_path / "main_rag"
    assert modules.entities._store_dir == env.tmp_path / "workflow"
