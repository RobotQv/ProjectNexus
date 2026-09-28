import json

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations.adapters import Unavailable
from app.integrations.contracts import AnalysisResult, Candidate, Evidence, Finding, Resolution
from app.llm import GLMProvider
from tests.conftest import new_task, ready_document


def test_queries_structured_collection_ambiguity_and_latest(env):
    a = new_task(env, title="退款接口", aliases=["退款"])
    url = env.prefix + "/queries"
    r = env.client.post(url, json={"question": "退款现在进度怎样", "route": "structured"})
    assert r.status_code == 200, r.text
    assert r.json()["facts"][0]["id"] == a["id"]
    env.client.patch(
        env.prefix + f"/tasks/{a['id']}",
        json={"expected_version": 1, "status": "in_progress", "progress": 60},
    )
    r = env.client.post(url, json={"question": "退款现在进度怎样", "route": "structured"}).json()
    assert r["facts"][0]["progress"] == 60
    new_task(env, title="退款页面", aliases=["退款"])
    ambiguous = env.client.post(url, json={"question": "退款", "route": "structured"}).json()
    assert ambiguous["outcome"] == "clarify" and not ambiguous["facts"]
    collection = env.client.post(url, json={"question": "所有未完成任务"}).json()
    assert len(collection["facts"]) == 2 and collection["route"] == "structured"
    empty = env.client.post(url, json={"question": "没有这份资料", "route": "document"}).json()
    assert empty["outcome"] == "insufficient" and not empty["evidence"]


def test_model_disabled_returns_facts_with_warning(env):
    task = new_task(env)
    result = env.client.post(
        env.prefix + "/queries",
        json={"question": "状态", "task_id": task["id"], "synthesize": True},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["outcome"] == "partial"
    assert any("llm_unavailable" in w for w in body["warnings"])


def test_validate_vector_evidence_and_scope(env):
    doc = ready_document(env)
    block = env.client.get(env.prefix + f"/documents/{doc['id']}/blocks?version=1").json()["items"][
        0
    ]
    valid = Evidence(document_id=doc["id"], version=1, block_ids=[block["id"]], quote=block["text"])
    env.app.state.modules.main_rag.retrieve = lambda *args: [
        valid,
        valid.model_copy(update={"document_id": 999}),
        valid.model_copy(update={"quote": "伪造的来源内容"}),
    ]
    result = env.client.post(
        env.prefix + "/queries", json={"question": "登录需求", "route": "document"}
    ).json()
    assert len(result["evidence"]) == 1 and len(result["warnings"]) >= 2


def test_entity_candidates_must_be_rechecked(env):
    task = new_task(env, title="有效任务")
    env.app.state.modules.entities.resolve = lambda *args: Resolution(
        outcome="resolved",
        candidates=[
            Candidate(entity_type="task", entity_id=999, title="跨项目的标题"),
            Candidate(entity_type="task", entity_id=task["id"], title="旧标题"),
        ],
    )
    response = env.client.post(
        env.prefix + "/queries", json={"question": "查询具体对象", "route": "structured"}
    )
    body = response.json()
    assert response.status_code == 200, response.text
    assert "跨项目的标题" not in response.text and "旧标题" not in response.text
    assert body["facts"][0]["title"] == "有效任务"


def test_analysis_snapshot_and_unavailable(env):
    task = new_task(env, progress=70, status="in_progress")
    snapshots = []

    def analyze(snapshot):
        snapshots.append(snapshot)
        return AnalysisResult(
            rule_version="test-rule-v1",
            findings=[
                Finding(
                    task_ids=[task["id"]],
                    reason_codes=["test_only"],
                    explanation="契约验证用例，不是真实规则",
                )
            ],
        )

    env.app.state.modules.risk.analyze = analyze
    result = env.client.post(env.prefix + "/analysis", json={"evaluation_date": "2026-09-15"})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["snapshot_hash"] and body["input_snapshot"]["tasks"][0]["version"] == 1
    assert snapshots[0].tasks[0]["progress"] == 70
    assert body["input_snapshot"]["evaluation_date"] == "2026-09-15"
    env.app.state.modules.risk = Unavailable()
    assert env.client.post(env.prefix + "/analysis", json={}).status_code == 503


def test_analysis_cannot_return_foreign_task(env):
    env.app.state.modules.risk.analyze = lambda snapshot: AnalysisResult(
        rule_version="bad",
        findings=[Finding(task_ids=[999], reason_codes=["invalid"], explanation="跨项目")],
    )
    response = env.client.post(env.prefix + "/analysis", json={})
    assert response.status_code == 502


def glm_settings():
    return Settings(
        _env_file=None, jwt_secret="s" * 40, llm_mode="glm", llm_api_key="not-a-real-key"
    )


def test_glm_payload_and_parsing():
    def respond(request):
        assert str(request.url) == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        assert request.headers["Authorization"] == "Bearer not-a-real-key"
        payload = json.loads(request.content)
        assert payload["model"] == "glm-4.7-flash"
        assert payload["thinking"] == {"type": "disabled"}
        assert not payload["stream"] and payload["max_tokens"] == 200
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "测试回答"}}], "usage": {"total_tokens": 10}},
        )

    provider = GLMProvider(glm_settings(), transport=httpx.MockTransport(respond))
    try:
        result = provider.complete([{"role": "user", "content": "你好"}], max_tokens=200)
        assert result.content == "测试回答" and result.usage["total_tokens"] == 10
    finally:
        provider.close()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "llm_upstream_error"),
        (429, "llm_rate_limited"),
        (500, "llm_upstream_error"),
        (302, "llm_upstream_error"),
    ],
)
def test_glm_errors_never_expose_upstream_body(status, code):
    provider = GLMProvider(
        glm_settings(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="not-a-real-key private upstream detail")
        ),
    )
    try:
        with pytest.raises(AppError) as info:
            provider.complete([{"role": "user", "content": "hello"}])
        assert info.value.code == code and "private" not in info.value.message
    finally:
        provider.close()


@pytest.mark.parametrize(
    "mode,code",
    [
        ("timeout", "llm_timeout"),
        ("connect", "llm_connection_error"),
        ("invalid", "llm_invalid_response"),
    ],
)
def test_glm_transport_failures(mode, code):
    def respond(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("private detail")
        if mode == "connect":
            raise httpx.ConnectError("private detail")
        return httpx.Response(200, json={"choices": []})

    provider = GLMProvider(glm_settings(), transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(AppError) as info:
            provider.complete([{"role": "user", "content": "hello"}])
        assert info.value.code == code
    finally:
        provider.close()
