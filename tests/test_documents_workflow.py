from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.security import issue_token
from app.db import begin_write, utcnow
from app.integrations.adapters import Unavailable
from app.models import Job
from tests.conftest import drain, pending_suggestion, ready_document


def test_document_upload_dedup_source_and_deletion(env):
    doc = ready_document(env, name="../../report.txt")
    assert doc["filename"] == "report.txt" and "storage_key" not in doc
    dupe = env.client.post(
        env.prefix + "/documents",
        files={"file": ("another.txt", "需求原文：需要完成后端登录。".encode())},
    )
    assert dupe.status_code == 409
    assert len(list(env.settings.storage_dir.iterdir())) == 1
    url = env.prefix + f"/documents/{doc['id']}"
    assert env.client.get(url + "/source?version=1").status_code == 200
    assert env.client.get(url + "/source?version=2").status_code == 404
    assert (
        env.client.get(url + "/blocks?version=1").json()["items"][0]["text"].startswith("需求原文")
    )
    headers = {"Authorization": "Bearer " + issue_token(3, env.settings)}
    assert env.client.get(url + "/source?version=1", headers=headers).status_code == 404
    assert env.client.delete(url).status_code == 202
    assert env.client.get(url + "/source?version=1").status_code == 404
    drain(env)
    assert env.client.delete(url).json()["cleanup_status"] == "succeeded"


@pytest.mark.parametrize(
    "name,body,status",
    [
        ("a.exe", b"x", 422),
        ("a.txt", b"", 422),
        ("a.pdf", b"not a PDF", 422),
        ("a.docx", b"not docx", 422),
        ("a.txt", b"x" * (1024 * 1024 + 1), 413),
    ],
    ids=["extension", "empty", "fake_pdf", "fake_docx", "oversize"],
)
def test_upload_validation(env, name, body, status):
    result = env.client.post(env.prefix + "/documents", files={"file": (name, body)})
    assert result.status_code == status, result.text
    assert not env.settings.storage_dir.exists() or not list(env.settings.storage_dir.iterdir())


def test_missing_module_fails_visibly_and_can_retry(env):
    env.app.state.modules.main_rag = Unavailable()
    result = env.client.post(
        env.prefix + "/documents", files={"file": ("a.txt", b"some content")}
    ).json()
    drain(env)
    doc = env.client.get(env.prefix + f"/documents/{result['document']['id']}").json()
    assert doc["parse_status"] == doc["index_status"] == "failed"
    assert "module_unavailable" in doc["error_message"]
    retry = env.client.post(env.prefix + f"/documents/{doc['id']}/retry").json()
    assert retry["job_id"] == result["job_id"]
    retry2 = env.client.post(env.prefix + f"/documents/{doc['id']}/retry").json()
    assert retry2["job_id"] == result["job_id"]


def test_review_transaction_idempotency_and_rejection(env):
    suggestion = pending_suggestion(env)
    url = env.prefix + f"/suggestions/{suggestion['id']}/review"
    invalid = env.client.post(
        url, json={"action": "confirm", "expected_version": 1, "overrides": {"assignee_id": 3}}
    )
    assert invalid.status_code == 422
    assert not env.client.get(env.prefix + "/tasks").json()["items"]
    payload = {"action": "confirm", "expected_version": 1, "overrides": {"title": "人工确认任务"}}
    first, second = [env.client.post(url, json=payload) for _ in range(2)]
    assert first.status_code == second.status_code == 200
    assert first.json()["target_id"] == second.json()["target_id"]
    tasks = env.client.get(env.prefix + "/tasks").json()["items"]
    assert len(tasks) == 1 and tasks[0]["source_suggestion_id"] == suggestion["id"]
    assert env.client.post(url, json={"action": "reject", "expected_version": 2}).status_code == 409


def test_concurrent_confirmation_creates_one_task(env):
    suggestion = pending_suggestion(env)

    def review(_):
        return env.client.post(
            env.prefix + f"/suggestions/{suggestion['id']}/review",
            json={"action": "confirm", "expected_version": 1},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(review, [1, 2]))
    assert all(r.status_code == 200 for r in replies), [r.text for r in replies]
    assert len({r.json()["target_id"] for r in replies}) == 1
    assert len(env.client.get(env.prefix + "/tasks").json()["items"]) == 1


def test_deleted_source_cannot_be_approved(env):
    suggestion = pending_suggestion(env)
    did = suggestion["source_refs"][0]["document_id"]
    env.client.delete(env.prefix + f"/documents/{did}")
    assert (
        env.client.post(
            env.prefix + f"/suggestions/{suggestion['id']}/review",
            json={"action": "confirm", "expected_version": 1},
        ).status_code
        == 404
    )


def test_worker_lease_expiry_is_visible(env):
    with env.app.state.sessions() as db:
        begin_write(db)
        job = db.scalar(select(Job))
        job.status, job.lease_token = "running", "stale-token"
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        jid = job.id
        db.commit()
    env.worker.run_once()
    result = env.client.get(env.prefix + f"/jobs/{jid}").json()
    assert result["status"] == "failed" and "worker_lease_expired" in result["error_message"]
    assert "lease_token" not in result


def test_workflow_summary_and_job_retry_after_commit(env):
    doc = ready_document(env)
    start = env.client.post(
        env.prefix + f"/documents/{doc['id']}/extract", json={"kind": "summary"}
    ).json()
    drain(env)
    run = env.client.get(env.prefix + f"/workflow-runs/{start['workflow_run_id']}").json()
    assert run["status"] == "succeeded" and run["summary"].startswith("[DEMO]")
    suggestion = pending_suggestion_after_ready(env, doc)
    # 模拟结果已提交但 Job 完成标记前进程中断，再重试不得重复生成建议。
    with env.app.state.sessions() as db:
        begin_write(db)
        job = db.scalar(
            select(Job).where(
                Job.resource_type == "workflow_run", Job.resource_id == suggestion["run_id"]
            )
        )
        job.status = "failed"
        jid = job.id
        db.commit()
    assert env.client.post(env.prefix + f"/jobs/{jid}/retry").status_code == 202
    drain(env)
    assert len(env.client.get(env.prefix + "/suggestions").json()["items"]) == 1


def pending_suggestion_after_ready(env, doc):
    env.client.post(env.prefix + f"/documents/{doc['id']}/extract", json={})
    drain(env)
    return env.client.get(env.prefix + "/suggestions").json()["items"][0]
