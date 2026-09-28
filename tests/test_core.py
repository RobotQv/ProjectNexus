from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text

from app.core.security import issue_token
from app.models import AuditEvent, Job
from tests.conftest import new_task


def test_health_openapi_and_login(env):
    c = env.client
    assert c.get("/health/ready").status_code == 200
    assert len(c.get("/openapi.json").json()["paths"]) >= 30
    login = c.post(
        "/api/v1/auth/login", json={"login_name": "owner", "password": "test-password-123"}
    )
    assert login.status_code == 200
    assert "password_hash" not in login.text
    assert login.json()["token_type"] == "bearer"
    bad = c.post("/api/v1/auth/login", json={"login_name": "owner", "password": "bad-secret"})
    assert bad.status_code == 401 and "bad-secret" not in bad.text
    assert bad.json()["request_id"] == bad.headers["X-Request-ID"]
    assert c.get("/api/v1/projects", headers={"Authorization": "Bearer invalid"}).status_code == 401
    with env.app.state.sessions() as db:
        assert db.scalar(text("PRAGMA foreign_keys")) == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"status": "done", "progress": 30},
        {"status": "not_started", "progress": 10},
        {"progress": -1},
        {"progress": 101},
        {"progress": True},
        {"title": " "},
        {"status": "blocked"},
        {"planned_start": "2026-09-20", "planned_end": "2026-09-19"},
        {"actual_start_at": "2026-09-20T00:00:00Z", "actual_end_at": "2026-09-19T00:00:00Z"},
        {"actual_start_at": "2026-09-20T00:00:00"},
        {"assignee_id": 3},
        {"unknown_field": 1},
    ],
)
def test_task_validation(env, fields):
    response = env.client.post(env.prefix + "/tasks", json={"title": "任务", **fields})
    assert response.status_code == 422, response.text


def test_task_update_version_audit_and_entity_jobs(env):
    task = new_task(env)
    c, url = env.client, env.prefix + f"/tasks/{task['id']}"
    first = c.patch(url, json={"expected_version": 1, "status": "in_progress", "progress": 30})
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 2
    assert first.json()["updated_at"].endswith(("Z", "+00:00"))
    assert c.patch(url, json={"expected_version": 1, "progress": 20}).status_code == 409
    assert c.patch(url, json={"expected_version": 2, "progress": None}).status_code == 422
    assert c.patch(url, json={"expected_version": 2, "status": "done"}).status_code == 422
    with env.app.state.sessions() as db:
        assert len(db.scalars(select(Job).where(Job.resource_type == "task")).all()) == 1
        assert (
            len(db.scalars(select(AuditEvent).where(AuditEvent.action == "task.update")).all()) == 1
        )
    assert c.patch(url, json={"expected_version": 2, "title": "改名"}).status_code == 200
    with env.app.state.sessions() as db:
        assert len(db.scalars(select(Job).where(Job.resource_type == "task")).all()) == 2


def test_concurrent_task_edits_only_one_wins(env):
    task = new_task(env)

    def update(n):
        return env.client.patch(
            env.prefix + f"/tasks/{task['id']}", json={"expected_version": 1, "title": f"标题{n}"}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(update, [1, 2]))
    assert sorted(statuses) == [200, 409]


@pytest.mark.parametrize(
    "path",
    ["", "/tasks", "/documents", "/members", "/dependencies", "/risks", "/suggestions", "/jobs"],
)
def test_nonmember_cannot_access_project(env, path):
    headers = {"Authorization": "Bearer " + issue_token(3, env.settings)}
    assert env.client.get(env.prefix + path, headers=headers).status_code == 404


def test_cross_project_ids_are_not_authority(env):
    other = env.client.post("/api/v1/projects", json={"name": "另外项目"}).json()["id"]
    other_task = env.client.post(
        f"/api/v1/projects/{other}/tasks", json={"title": "其他项目任务"}
    ).json()
    assert env.client.get(env.prefix + f"/tasks/{other_task['id']}").status_code == 404
    local = new_task(env)
    bad = {
        "predecessor_task_id": local["id"],
        "successor_task_id": other_task["id"],
        "predecessor_required_progress": 100,
        "successor_gate": "start",
    }
    assert env.client.post(env.prefix + "/dependencies", json=bad).status_code == 404
    assert (
        env.client.post(
            env.prefix + "/risks",
            json={"title": "风险", "description": "说明", "related_task_id": other_task["id"]},
        ).status_code
        == 404
    )
    assert (
        env.client.post(
            env.prefix + "/queries", json={"question": "状态", "task_id": other_task["id"]}
        ).status_code
        == 404
    )


def test_members_and_archived_readonly(env):
    c = env.client
    assert (
        c.post(
            env.prefix + "/members", json={"login_name": "member", "aliases": ["小李"]}
        ).status_code
        == 201
    )
    member_headers = {"Authorization": "Bearer " + issue_token(2, env.settings)}
    assert c.get(env.prefix, headers=member_headers).status_code == 200
    assert (
        c.post(
            env.prefix + "/members", json={"login_name": "stranger"}, headers=member_headers
        ).status_code
        == 403
    )
    assert c.delete(env.prefix + "/members/1").status_code == 409
    assert c.delete(env.prefix + "/members/2").status_code == 200
    assert c.get(env.prefix, headers=member_headers).status_code == 404
    assert c.patch(env.prefix, json={"status": "archived"}).status_code == 200
    assert c.post(env.prefix + "/tasks", json={"title": "不可写"}).status_code == 409
    assert c.get(env.prefix + "/tasks").status_code == 200
    assert c.patch(env.prefix, json={"status": "active"}).status_code == 200


def test_risk_and_soft_delete(env):
    task = new_task(env)
    risk = env.client.post(
        env.prefix + "/risks",
        json={"title": "测试账号", "description": "尚未开通", "related_task_id": task["id"]},
    ).json()
    done = env.client.patch(
        env.prefix + f"/risks/{risk['id']}", json={"expected_version": 1, "status": "resolved"}
    )
    assert done.status_code == 200 and done.json()["resolved_at"]
    assert (
        env.client.delete(env.prefix + f"/tasks/{task['id']}?expected_version=1").status_code == 200
    )
    assert env.client.get(env.prefix + f"/tasks/{task['id']}").status_code == 404
