from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select

from app.core.security import issue_token
from app.db import begin_write, utcnow
from app.integrations.contracts import Candidate, Evidence, ExtractionResult, SuggestionDraft
from app.llm import LLMResult
from app.models import Document, ProjectMember, Task
from app.worker import Worker
from tests.conftest import drain, new_task, ready_document


def test_request_body_limit_before_storage(env):
    response = env.client.post(
        env.prefix + "/documents", files={"file": ("large.txt", b"x" * (3 * 1024 * 1024))}
    )
    assert response.status_code == 413, response.text
    assert "request_id" in response.json()
    assert not env.settings.storage_dir.exists()


def test_index_failure_retry_reuses_blocks(env):
    rag = env.app.state.modules.main_rag
    original_ingest = rag.ingest
    attempts = []

    def fail_once(reference):
        attempts.append([block.id for block in reference.blocks])
        if len(attempts) == 1:
            raise RuntimeError("supplier-private-key-must-not-appear")
        return original_ingest(reference)

    rag.ingest = fail_once
    result = env.client.post(
        env.prefix + "/documents", files={"file": ("a.txt", b"first\n\nsecond")}
    ).json()
    drain(env)
    url = env.prefix + f"/documents/{result['document']['id']}"
    failed = env.client.get(url)
    assert failed.json()["parse_status"] == "ready" and failed.json()["index_status"] == "failed"
    assert "supplier-private-key" not in failed.text
    env.client.post(url + "/retry")
    drain(env)
    assert env.client.get(url).json()["index_status"] == "ready"
    assert attempts[0] == attempts[1]


def test_two_workers_cannot_claim_at_same_time(env):
    second = Worker(env.app.state.sessions, env.settings, env.app.state.modules)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda w: w.claim(), [env.worker, second]))
    assert sum(result is not None for result in results) == 1


def test_workflow_filters_foreign_candidates(env):
    task = new_task(env, title="正确标题")
    doc = ready_document(env)

    def extract(reference, catalog, kind):
        first = reference.blocks[0]
        return ExtractionResult(
            model_id="test",
            prompt_version="test-v1",
            suggestions=[
                SuggestionDraft(
                    suggestion_type="create_task",
                    proposed_payload={"title": "建议任务"},
                    source_refs=[
                        Evidence(
                            document_id=doc["id"], version=1, block_ids=[first.id], quote=first.text
                        )
                    ],
                    entity_candidates=[
                        Candidate(entity_type="task", entity_id=999, title="范围外标题"),
                        Candidate(entity_type="task", entity_id=task["id"], title="过期标题"),
                    ],
                )
            ],
        )

    env.app.state.modules.workflow.extract = extract
    env.client.post(env.prefix + f"/documents/{doc['id']}/extract", json={})
    drain(env)
    response = env.client.get(env.prefix + "/suggestions")
    assert "范围外标题" not in response.text and "过期标题" not in response.text
    assert response.json()["items"][0]["entity_candidates"][0]["title"] == "正确标题"


def test_query_rechecks_permissions_after_model_call(env):
    task = new_task(env)
    env.client.post(env.prefix + "/members", json={"login_name": "member"})

    def complete(*args, **kwargs):
        with env.app.state.sessions() as db:
            begin_write(db)
            member = db.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == env.pid, ProjectMember.user_id == 2
                )
            )
            member.is_active = False
            db.commit()
        return LLMResult(content="不应发送给被移除成员", model="test", usage={})

    env.app.state.llm.complete = complete
    headers = {"Authorization": "Bearer " + issue_token(2, env.settings)}
    response = env.client.post(
        env.prefix + "/queries",
        headers=headers,
        json={"question": "进度", "task_id": task["id"], "synthesize": True},
    )
    assert response.status_code == 404 and "不应发送" not in response.text


def test_query_refreshes_changed_task_and_rejects_stale_synthesis(env):
    task = new_task(env)

    def complete(*args, **kwargs):
        with env.app.state.sessions() as db:
            begin_write(db)
            row = db.get(Task, task["id"])
            row.status, row.progress, row.version = "in_progress", 55, 2
            db.commit()
        return LLMResult(content="旧状态回答", model="test", usage={})

    env.app.state.llm.complete = complete
    response = env.client.post(
        env.prefix + "/queries",
        json={"question": "进度", "task_id": task["id"], "synthesize": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["facts"][0]["progress"] == 55
    assert "旧状态回答" not in response.text and response.json()["model_id"] is None


def test_deleted_during_ingest_cannot_become_ready(env):
    original = env.app.state.modules.main_rag.ingest

    def ingest(reference):
        with env.app.state.sessions() as db:
            begin_write(db)
            db.get(Document, reference.document_id).deleted_at = utcnow()
            db.commit()
        return original(reference)

    env.app.state.modules.main_rag.ingest = ingest
    upload = env.client.post(env.prefix + "/documents", files={"file": ("a.txt", b"sample")}).json()
    drain(env)
    did = upload["document"]["id"]
    assert env.client.get(env.prefix + f"/documents/{did}").status_code == 404
    assert env.client.get(env.prefix + f"/jobs/{upload['job_id']}").json()["status"] == "failed"
