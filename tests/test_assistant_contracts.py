"""后端交付验证：替身工作流，不实现或验收真实轻 RAG 算法。"""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select

from app.core.security import issue_token
from app.integrations.adapters import Unavailable
from app.models import AnalysisRun, TaskHistory, WorkflowRun
from shared.contracts import (
    AnalysisResult,
    AssistantResult,
    Evidence,
    ExtractionResult,
    Finding,
    SuggestionDraft,
)
from shared.structured import StructuredSuggestion
from shared.task_data import TaskChanges, TaskCreate
from tests.conftest import drain, new_task, ready_document


def headers(env, actor):
    return {"Authorization": "Bearer " + issue_token(actor, env.settings)}


def generated(env, drafts, entry="task_assistant", key=None):
    def respond(request, tools):
        return AssistantResult(
            answer="请核对", suggestions=drafts, model_id="fake", prompt_version="test-v2"
        )

    env.app.state.modules.workflow.respond = respond
    response = env.client.post(
        env.prefix + "/assistant/messages",
        json={"entry": entry, "text": "测试文本", "request_key": key or uuid4().hex},
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit(env, suggestion):
    response = env.client.post(
        env.prefix + f"/suggestions/{suggestion['id']}/submit",
        json={"expected_version": suggestion["version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def review(env, suggestion, action="confirm", **extra):
    return env.client.post(
        env.prefix + f"/suggestions/{suggestion['id']}/review",
        json={"action": action, "expected_version": suggestion["version"], **extra},
    )


@pytest.mark.parametrize("entry", ["task_assistant", "project_assistant"])
def test_separate_submit_and_independent_review(env, entry):
    env.client.post(env.prefix + "/members", json={"login_name": "member"})
    key = uuid4().hex
    result = generated(
        env,
        [
            SuggestionDraft(suggestion_type="create_task", proposed_payload={"title": f"任务{i}"})
            for i in range(2)
        ],
        entry,
        key,
    )
    first, second = result["suggestions"]
    assert first["submitted_by"] == 1 and first["review_status"] == "draft"
    assert not env.client.get(env.prefix + "/tasks").json()["items"]
    assert review(env, first).status_code == 409
    assert (
        env.client.get(env.prefix + "/suggestions", headers=headers(env, 2)).json()["items"] == []
    )
    assert (
        env.client.get(
            env.prefix + f"/workflow-runs/{result['run_id']}", headers=headers(env, 2)
        ).status_code
        == 403
    )
    assert (
        env.client.post(
            env.prefix + f"/suggestions/{first['id']}/submit",
            json={"expected_version": 1},
            headers=headers(env, 2),
        ).status_code
        == 403
    )
    edit = env.client.patch(
        env.prefix + f"/suggestions/{first['id']}",
        json={"expected_version": 1, "proposed_payload": {"title": "核对后的标题"}},
    )
    assert edit.status_code == 200, edit.text
    first = submit(env, edit.json())
    second = submit(env, second)
    assert first["submitted_at"]
    assert not env.client.get(env.prefix + "/tasks").json()["items"]
    # 另一个成员正式审核；第二条由提交者本人驳回。
    approved = env.client.post(
        env.prefix + f"/suggestions/{first['id']}/review",
        json={"action": "confirm", "expected_version": first["version"], "note": "核对完毕"},
        headers=headers(env, 2),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["reviewed_by"] == 2 and approved.json()["review_note"] == "核对完毕"
    assert review(env, second, "reject").status_code == 200
    assert len(env.client.get(env.prefix + "/tasks").json()["items"]) == 1
    assert first["original_payload"]["title"] == "任务0"
    source = env.client.get(env.prefix + f"/suggestions/{first['id']}/source").json()
    assert source["input_text"] == "测试文本" and source["submitted_by"] == 1
    again = env.client.post(
        env.prefix + "/assistant/messages",
        json={"entry": entry, "text": "测试文本", "request_key": key},
    )
    assert again.status_code == 200 and again.json()["run_id"] == result["run_id"]
    assert (
        env.client.post(
            env.prefix + "/assistant/messages",
            json={"entry": entry, "text": "不同文本", "request_key": key},
        ).status_code
        == 409
    )


def test_update_all_fields_history_conflict_and_idempotency(env):
    task = new_task(env, description="旧描述")
    changes = {
        "title": "新标题",
        "description": None,
        "module_name": "模块",
        "tags": ["验收"],
        "aliases": ["任务别名"],
        "assignee_id": 1,
        "status": "in_progress",
        "progress": 70,
        "planned_start": "2026-09-01",
        "planned_end": "2026-09-30",
        "forecast_end": "2026-09-28",
        "deadline": "2026-10-01",
        "actual_start_at": "2026-09-02T00:00:00Z",
        "actual_end_at": None,
    }
    draft = SuggestionDraft(
        suggestion_type="update_task",
        proposed_payload={"task_id": task["id"], "expected_version": 1, "changes": changes},
    )
    suggestion = submit(env, generated(env, [draft])["suggestions"][0])
    url = env.prefix + f"/tasks/{task['id']}"
    env.client.patch(url, json={"expected_version": 1, "description": "别人刚编辑"})
    assert review(env, suggestion).status_code == 409
    assert env.client.get(url).json()["progress"] == 0
    payload = {
        "action": "confirm",
        "expected_version": suggestion["version"],
        "overrides": {"expected_version": 2},
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: env.client.post(
                    env.prefix + f"/suggestions/{suggestion['id']}/review", json=payload
                ),
                range(2),
            )
        )
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    final = env.client.get(url).json()
    assert final["version"] == 3 and final["progress"] == 70 and final["description"] is None
    history = env.client.get(url + "/history").json()["items"]
    assert [h["version"] for h in history] == [3, 2, 1]
    assert history[0]["snapshot"] == final
    assert history[0]["source"] == "ai_review" and history[0]["suggestion_id"] == suggestion["id"]
    assert history[1]["snapshot"]["description"] == "别人刚编辑"
    assert history[2]["snapshot"]["description"] == "旧描述"
    assert env.client.get(url + "/history", headers=headers(env, 3)).status_code == 404


def test_document_extraction_records_initiator_and_original_source(env):
    env.client.post(env.prefix + "/members", json={"login_name": "member"})
    doc = ready_document(env)
    task = new_task(env)

    def extract(reference, catalog, kind, *, tools=None):
        assert tools.search_tasks({"task_id": task["id"]})[0]["id"] == task["id"]
        ref = Evidence(
            document_id=doc["id"],
            version=1,
            block_ids=[reference.blocks[0].id],
            quote=reference.blocks[0].text,
        )
        return ExtractionResult(
            model_id="fake",
            prompt_version="test",
            suggestions=[
                SuggestionDraft(
                    suggestion_type="create_task",
                    proposed_payload={"title": "独立任务"},
                    source_refs=[ref],
                ),
                SuggestionDraft(
                    suggestion_type="update_task",
                    proposed_payload={
                        "task_id": task["id"],
                        "expected_version": 1,
                        "changes": {"status": "done", "progress": 100},
                    },
                    source_refs=[ref],
                ),
            ],
        )

    env.app.state.modules.workflow.extract = extract
    response = env.client.post(
        env.prefix + f"/documents/{doc['id']}/extract", json={}, headers=headers(env, 2)
    )
    assert response.status_code == 202
    drain(env)
    items = env.client.get(env.prefix + "/suggestions?status=pending").json()["items"]
    assert len(items) == 2 and all(s["submitted_by"] == 2 and s["submitted_at"] for s in items)
    source = env.client.get(env.prefix + f"/suggestions/{items[0]['id']}/source").json()
    assert source["documents"][0]["blocks"][0]["text"].startswith("需求原文")
    assert review(env, items[1]).status_code == 200
    assert review(env, items[0], "reject").status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"progress": 101},
        {"progress": True},
        {"status": "blocked"},
        {"id": 1},
        {"title": None},
        {"actual_start_at": "2026-09-01T00:00:00"},
    ],
)
def test_task_contract_rejects_bad_fields(changes):
    with pytest.raises(ValidationError):
        TaskChanges.model_validate(changes)


def test_public_schema_and_same_runtime_definitions(env):
    from app.schemas import TaskCreate as HttpTaskCreate

    assert HttpTaskCreate is TaskCreate
    schema = env.client.get("/api/v1/contracts/task-data").json()
    assert schema["contract_version"] == "2"
    assert "discriminator" in schema["suggestion"]
    sample = {
        "suggestion_type": "update_task",
        "proposed_payload": {
            "task_id": 1,
            "expected_version": 2,
            "changes": {"progress": 70, "status": "in_progress"},
        },
    }
    assert TypeAdapter(StructuredSuggestion).validate_python(sample)
    assert SuggestionDraft.model_validate(sample).proposed_payload == sample["proposed_payload"]


def test_invalid_workflow_output_rollback_and_no_secret_leak(env):
    def invalid(request, tools):
        return {
            "answer": "bad",
            "model_id": "fake",
            "prompt_version": "v1",
            "suggestions": [
                {"suggestion_type": "create_task", "proposed_payload": {"private-secret": 1}}
            ],
        }

    env.app.state.modules.workflow.respond = invalid
    response = env.client.post(
        env.prefix + "/assistant/messages",
        json={"entry": "task_assistant", "text": "输入", "request_key": uuid4().hex},
    )
    assert response.status_code == 502 and "private-secret" not in response.text
    assert not env.client.get(env.prefix + "/suggestions").json()["items"]
    assert not env.client.get(env.prefix + "/tasks").json()["items"]
    with env.app.state.sessions() as db:
        assert db.scalar(select(WorkflowRun)).status == "failed"


def test_candidate_risk_and_change_trigger_never_write_task_status(env):
    task = new_task(env)

    def candidates(preview):
        assert preview.changes[0].key == "new-a"
        return AnalysisResult(
            rule_version="fake-risk",
            findings=[
                Finding(
                    task_ids=[task["id"]],
                    candidate_keys=["new-a"],
                    timing_status="future_risk",
                    reason_codes=["sample"],
                    explanation="示例提示",
                )
            ],
        )

    env.app.state.modules.risk.analyze_candidates = candidates
    response = env.client.post(
        env.prefix + "/analysis/preview",
        json=[
            {
                "key": "new-a",
                "suggestion": {
                    "suggestion_type": "create_task",
                    "proposed_payload": {"title": "候选"},
                },
            }
        ],
    )
    assert response.status_code == 200, response.text
    assert len(env.client.get(env.prefix + "/tasks").json()["items"]) == 1
    drain(env)
    status = env.client.get(env.prefix + "/risk-status").json()
    assert status["job"]["status"] == "succeeded" and status["is_stale"] is False
    with env.app.state.sessions() as db:
        assert (
            len(
                db.scalars(select(AnalysisRun).where(AnalysisRun.trigger_job_id.is_not(None))).all()
            )
            == 1
        )
        assert len(db.scalars(select(TaskHistory)).all()) == 1
    assert env.worker.run_once() is False  # 无数据变更，不会定时再查。
    env.app.state.modules.risk = Unavailable()
    env.client.patch(
        env.prefix + f"/tasks/{task['id']}",
        json={"expected_version": 1, "status": "in_progress", "progress": 10},
    )
    drain(env)
    failed = env.client.get(env.prefix + "/risk-status").json()
    assert failed["job"]["status"] == "failed" and failed["is_stale"] is True
    assert env.client.get(env.prefix + f"/tasks/{task['id']}").json()["status"] == "in_progress"


def test_cross_project_tools_and_history_cannot_be_read(env):
    from app.core.errors import AppError
    from app.services.tools import BoundTools

    task = new_task(env)
    tools = BoundTools(env.app.state.sessions, env.pid, 3, env.app.state.modules)
    with pytest.raises(AppError):
        tools.search_tasks({"task_id": task["id"]})
    assert not hasattr(tools, "update_task") and not hasattr(tools, "approve")


def test_assistant_queries_tools_and_refreshes_old_facts(env):
    task = new_task(env, title="查询目标")

    def ask(request, tools):
        facts = tools.search_tasks({"task_id": task["id"]})
        assert facts[0]["progress"] == 0
        assert tools.retrieve("资料") == []  # demo 不伪造资料。
        return AssistantResult(
            answer="进度为 0", task_ids=[task["id"]], model_id="fake", prompt_version="v2"
        )

    env.app.state.modules.workflow.respond = ask
    result = env.client.post(
        env.prefix + "/assistant/messages",
        json={"entry": "project_assistant", "text": "进度呢", "request_key": uuid4().hex},
    )
    assert result.status_code == 200, result.text
    assert result.json()["facts"][0]["id"] == task["id"] and not result.json()["suggestions"]
    env.client.patch(
        env.prefix + f"/tasks/{task['id']}",
        json={"expected_version": 1, "status": "in_progress", "progress": 20},
    )
    refreshed = env.client.get(env.prefix + f"/assistant/runs/{result.json()['run_id']}").json()
    assert refreshed["outcome"] == "partial" and refreshed["facts"][0]["progress"] == 20
    assert "数据已变化" in refreshed["answer"]


def test_permission_removed_during_assistant_does_not_publish(env):
    from app.db import begin_write
    from app.models import ProjectMember

    def remove_permission(request, tools):
        with env.app.state.sessions() as db:
            begin_write(db)
            member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == 1))
            member.is_active = False
            db.commit()
        return AssistantResult(
            answer="候选",
            model_id="fake",
            prompt_version="v2",
            suggestions=[
                SuggestionDraft(
                    suggestion_type="create_task", proposed_payload={"title": "不能发布"}
                )
            ],
        )

    env.app.state.modules.workflow.respond = remove_permission
    response = env.client.post(
        env.prefix + "/assistant/messages",
        json={"entry": "task_assistant", "text": "新任务", "request_key": uuid4().hex},
    )
    assert response.status_code == 404
    from app.models import Suggestion

    with env.app.state.sessions() as db:
        assert not db.scalars(select(Suggestion)).all()


def test_draft_invalid_edits_and_incomplete_creation(env):
    draft = generated(env, [SuggestionDraft(suggestion_type="create_task", proposed_payload={})])[
        "suggestions"
    ][0]
    assert (
        env.client.patch(
            env.prefix + f"/suggestions/{draft['id']}",
            json={"expected_version": 1, "proposed_payload": {"submitted_by": 2}},
        ).status_code
        == 422
    )
    pending = submit(env, draft)
    assert review(env, pending).status_code == 422  # 草稿可缺标题，正式任务不可缺。
    good = review(env, pending, overrides={"title": "补齐标题"})
    assert good.status_code == 200
    task_id = good.json()["target_id"]
    deleted = env.client.delete(env.prefix + f"/tasks/{task_id}?expected_version=1")
    assert deleted.status_code == 200
    history = env.client.get(env.prefix + f"/tasks/{task_id}/history").json()["items"]
    assert len(history) == 2 and history[0]["snapshot"]["deleted_at"]


def test_candidate_preview_links_new_tasks_without_database_ids(env):
    changes = [
        {
            "key": "new-a",
            "suggestion": {"suggestion_type": "create_task", "proposed_payload": {"title": "A"}},
        },
        {
            "key": "new-b",
            "suggestion": {"suggestion_type": "create_task", "proposed_payload": {"title": "B"}},
        },
        {
            "key": "edge",
            "predecessor_key": "new-a",
            "successor_key": "new-b",
            "suggestion": {
                "suggestion_type": "propose_dependency",
                "proposed_payload": {
                    "predecessor_required_progress": 100,
                    "successor_gate": "start",
                },
            },
        },
    ]
    assert env.client.post(env.prefix + "/analysis/preview", json=changes).status_code == 200
    changes[2]["predecessor_key"] = "does-not-exist"
    assert env.client.post(env.prefix + "/analysis/preview", json=changes).status_code == 422
    assert not env.client.get(env.prefix + "/tasks").json()["items"]


def test_migration_preserves_linked_business_data_and_backfills_only_current(env):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.cli import ROOT
    from tests.conftest import pending_suggestion

    suggestion = pending_suggestion(env)
    approved = review(env, suggestion).json()
    tid = approved["target_id"]
    env.client.patch(
        env.prefix + f"/tasks/{tid}", json={"expected_version": 1, "title": "迁移前版本二"}
    )
    before = env.client.get(env.prefix + f"/tasks/{tid}").json()
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = env.settings.database_url
    # 仅临时测试库模拟已有 0002 数据，不对用户业务库执行回退。
    command.downgrade(config, "0002")
    command.upgrade(config, "head")
    command.check(config)
    assert env.client.get(env.prefix + f"/tasks/{tid}").json() == before
    history = env.client.get(env.prefix + f"/tasks/{tid}/history").json()["items"]
    assert len(history) == 1 and history[0]["version"] == 2
    assert history[0]["source"] == "migration_baseline" and history[0]["actor_id"] is None
    with env.app.state.sessions() as db:
        assert not db.execute(text("PRAGMA foreign_key_check")).all()
        assert db.scalar(text("PRAGMA foreign_keys")) == 1
