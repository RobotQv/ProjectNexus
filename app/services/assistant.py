"""两种对话入口共用持久化和预审流程，语义理解留给工作流实现。"""

import hashlib

from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import AppError, conflict
from app.db import begin_write, utcnow
from app.models import Suggestion, Task, WorkflowRun
from app.services.common import project_row, public, require_project
from app.services.documents import validate_evidence
from app.services.suggestions import save_draft, validate_draft
from app.services.tools import BoundTools
from shared.contracts import AssistantRequest, AssistantResult


def assistant_response(db, run, actor):
    require_project(db, run.project_id, actor)
    if run.submitted_by != actor:
        raise AppError("submitter_required", "对话草稿仅提交者可查看", 403)
    if run.status != "succeeded":
        raise AppError(
            "assistant_not_ready",
            "该请求仍在处理或已失败；重新生成请使用新 request_key",
            409,
            {"run_id": run.id, "status": run.status, "error": run.error},
        )
    data = dict(run.response_data)
    facts = []
    warnings = list(data["warnings"])
    for tid in data.pop("task_ids", []):
        try:
            fact = public(project_row(db, Task, run.project_id, tid))
            facts.append(fact)
            if (
                str(tid) in data.get("fact_versions", {})
                and data["fact_versions"][str(tid)] != fact["version"]
            ):
                data["answer"], data["outcome"] = (
                    "任务数据已变化，请以当前任务字段为准并重新提问。",
                    "partial",
                )
        except AppError:
            data["answer"], data["outcome"] = "相关任务已失效，请重新提问。", "partial"
    refs = []
    for ref in data["evidence"]:
        try:
            refs.append(validate_evidence(db, run.project_id, ref).model_dump(mode="json"))
        except AppError:
            warnings.append("原引用已失效")
            data["answer"], data["outcome"] = "相关来源已失效，请重新提问。", "partial"
    data.pop("fact_versions", None)
    # 候选再次过滤，历史响应也不能暴露已移除的成员/任务。
    checked = validate_draft(
        db,
        run.project_id,
        {
            "suggestion_type": "create_task",
            "proposed_payload": {},
            "entity_candidates": data["candidates"],
        },
    )
    data["candidates"] = [c.model_dump(mode="json") for c in checked.entity_candidates]
    return {
        **data,
        "run_id": run.id,
        "facts": facts,
        "evidence": refs,
        "warnings": warnings,
        "suggestions": [
            public(s)
            for s in db.scalars(
                select(Suggestion).where(Suggestion.run_id == run.id).order_by(Suggestion.id)
            )
        ],
    }


def respond(db, pid, actor, data, sessions, modules):
    begin_write(db)
    require_project(db, pid, actor, write=True)
    existing = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.project_id == pid,
            WorkflowRun.submitted_by == actor,
            WorkflowRun.request_key == data.request_key,
        )
    )
    if existing:
        if existing.input_text != data.text or existing.source_kind != data.entry:
            raise conflict("request_key 已用于不同请求")
        return assistant_response(db, existing, actor)
    run = WorkflowRun(
        project_id=pid,
        submitted_by=actor,
        source_kind=data.entry,
        input_text=data.text,
        request_key=data.request_key,
        kind="assistant",
        status="running",
        input_hash=hashlib.sha256(data.text.encode()).hexdigest(),
        started_at=utcnow(),
    )
    db.add(run)
    db.commit()
    rid = run.id
    tools = BoundTools(sessions, pid, actor, modules)
    try:
        # 无写事务执行算法；工具不包含确认或任务修改方法。
        result = AssistantResult.model_validate(
            modules.workflow.respond(AssistantRequest(entry=data.entry, text=data.text), tools)
        )
        begin_write(db)
        require_project(db, pid, actor, write=True)
        run = project_row(db, WorkflowRun, pid, rid)
        for draft in result.suggestions:
            save_draft(db, run, validate_draft(db, pid, draft))
        for ref in result.evidence:
            validate_evidence(db, pid, ref)
        versions = {}
        for tid in result.task_ids:
            row = project_row(db, Task, pid, tid)
            versions[str(tid)] = tools.fact_versions.get(tid, row.version)
        response = result.model_dump(mode="json", exclude={"suggestions"})
        response.update(
            is_demo=modules.is_demo, risk_previews=tools.risk_previews, fact_versions=versions
        )
        run.response_data = response
        run.model_id, run.prompt_version = result.model_id, result.prompt_version
        run.summary, run.status, run.finished_at = result.answer, "succeeded", utcnow()
        db.commit()
    except Exception as error:
        begin_write(db)
        run = project_row(db, WorkflowRun, pid, rid)
        run.status, run.finished_at = "failed", utcnow()
        run.error = error.code if isinstance(error, AppError) else "module_execution_failed"
        db.commit()
        if isinstance(error, ValidationError):
            raise AppError("module_contract_invalid", "助手输出不符合结构化契约", 502) from None
        if isinstance(error, AppError):
            raise
        raise AppError("module_execution_failed", "助手模块执行失败，请检查模块实现", 502) from None
    return assistant_response(db, run, actor)
