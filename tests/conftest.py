from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.cli import migrate
from app.core.config import Settings
from app.core.security import hash_password, issue_token
from app.db import begin_write
from app.main import create_app
from app.models import User
from app.worker import Worker


@pytest.fixture(autouse=True)
def isolate_local_model_config(monkeypatch):
    """迁移会加载 .env；离线测试不继承随包的真实模型凭证和模块工厂。"""
    monkeypatch.setenv("NEXUS_LLM_MODE", "disabled")
    monkeypatch.setenv("NEXUS_LLM_API_KEY", "")
    monkeypatch.setenv("NEXUS_MODULE_FACTORY", "")


@pytest.fixture(scope="session")
def password_hash():
    return hash_password("test-password-123")


@pytest.fixture
def env(tmp_path, password_hash):
    settings = Settings(
        _env_file=None,
        environment="test",
        jwt_secret="s" * 40,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        storage_dir=tmp_path / "files",
        module_mode="demo",
        max_upload_mb=1,
    )
    migrate(settings.database_url)
    app = create_app(settings)
    with app.state.sessions() as db:
        begin_write(db)
        db.add_all(
            [
                User(login_name=name, display_name=name, password_hash=password_hash)
                for name in ("owner", "member", "stranger")
            ]
        )
        db.commit()
    headers = {"Authorization": "Bearer " + issue_token(1, settings)}
    with TestClient(app) as client:
        client.headers.update(headers)
        project = client.post("/api/v1/projects", json={"name": "测试项目"})
        assert project.status_code == 201, project.text
        pid = project.json()["id"]
        yield SimpleNamespace(
            app=app,
            client=client,
            pid=pid,
            prefix=f"/api/v1/projects/{pid}",
            settings=settings,
            headers=headers,
            worker=Worker(app.state.sessions, settings, app.state.modules),
            tmp_path=tmp_path,
        )


def new_task(env, **fields):
    response = env.client.post(env.prefix + "/tasks", json={"title": "后端任务", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def drain(env):
    for _ in range(100):
        if not env.worker.run_once():
            return
    raise AssertionError("任务队列未能排空")


def ready_document(env, text="需求原文：需要完成后端登录。", name="meeting.txt"):
    response = env.client.post(
        env.prefix + "/documents", files={"file": (name, text.encode(), "text/plain")}
    )
    assert response.status_code == 202, response.text
    drain(env)
    did = response.json()["document"]["id"]
    doc = env.client.get(env.prefix + f"/documents/{did}").json()
    assert doc["parse_status"] == doc["index_status"] == "ready", doc
    return doc


def pending_suggestion(env):
    doc = ready_document(env)
    response = env.client.post(env.prefix + f"/documents/{doc['id']}/extract", json={})
    assert response.status_code == 202, response.text
    drain(env)
    return env.client.get(env.prefix + "/suggestions").json()["items"][0]
