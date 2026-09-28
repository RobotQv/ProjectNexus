from app.core.errors import AppError, conflict
from app.db import utcnow
from app.models import Suggestion, Task
from app.schemas import DependencyCreate, RiskCreate, TaskCreate, TaskPatch
from app.services.business import create_dependency, create_risk, create_task, update_task
from app.services.common import audit, project_row
from app.services.documents import validate_evidence
from app.services.suggestions import validate_draft
from shared.task_data import UpdateTaskProposal


def visible_suggestion(db, pid, actor, sid):
    row = project_row(db, Suggestion, pid, sid)
    if row.review_status == "draft" and row.submitted_by != actor:
        raise AppError("submitter_required", "该草稿仅提交者可操作", 403)
    return row


def edit_suggestion(db, pid, actor, sid, request):
    row = visible_suggestion(db, pid, actor, sid)
    if row.review_status not in {"draft", "pending"} or row.version != request.expected_version:
        raise conflict("建议已审核或版本已更新")
    checked = validate_draft(
        db,
        pid,
        {
            "suggestion_type": row.suggestion_type,
            "proposed_payload": request.proposed_payload,
            "source_refs": row.source_refs,
        },
    )
    before = row.version
    row.proposed_payload, row.version = checked.proposed_payload, row.version + 1
    audit(db, pid, actor, "suggestion.edit", row, before)
    return row


def submit_suggestion(db, pid, actor, sid, request):
    row = project_row(db, Suggestion, pid, sid)
    if row.submitted_by != actor:
        raise AppError("submitter_required", "仅提交者可核对并提交对话建议", 403)
    if row.source_kind == "document":
        raise conflict("文档提取已直接进入正式审核")
    if row.review_status == "pending":
        return row
    if row.review_status != "draft" or row.version != request.expected_version:
        raise conflict("建议状态或版本已变化")
    before = row.version
    row.review_status, row.submitted_at, row.version = "pending", utcnow(), row.version + 1
    audit(db, pid, actor, "suggestion.submit", row, before)
    return row


def review_suggestion(db, pid, actor, sid, request):
    suggestion = project_row(db, Suggestion, pid, sid)
    desired = "approved" if request.action == "confirm" else "rejected"
    # 同结果重试返回原目标；即使请求仍带旧版本，也不会重新创建对象。
    if suggestion.review_status == desired:
        return suggestion
    if suggestion.review_status != "pending" or suggestion.version != request.expected_version:
        raise conflict("该建议已被处理或版本已更新")
    if request.action == "confirm":
        for ref in suggestion.source_refs:
            validate_evidence(db, pid, ref, require_index=False)
        payload = suggestion.proposed_payload | request.overrides
        # changes 是业务字段补丁；审核 overrides.changes 只覆盖指定项。
        if suggestion.suggestion_type == "update_task" and "changes" in request.overrides:
            if not isinstance(request.overrides["changes"], dict):
                raise AppError("invalid_changes", "changes 必须是字段对象")
            payload["changes"] = (
                suggestion.proposed_payload["changes"] | request.overrides["changes"]
            )
        handlers = {
            "create_task": (TaskCreate, create_task, "task"),
            "propose_dependency": (DependencyCreate, create_dependency, "dependency"),
            "create_risk": (RiskCreate, create_risk, "risk"),
        }
        if suggestion.suggestion_type == "update_task":
            proposal = UpdateTaskProposal.model_validate(payload)
            target = project_row(db, Task, pid, proposal.task_id)
            patch = TaskPatch(
                expected_version=proposal.expected_version,
                **proposal.changes.model_dump(exclude_unset=True),
            )
            target = update_task(db, pid, actor, target, patch, source=suggestion.id)
            target_type = "task"
        else:
            schema, create, target_type = handlers[suggestion.suggestion_type]
            target = create(db, pid, actor, schema.model_validate(payload), source=suggestion.id)
        suggestion.proposed_payload = payload
        suggestion.target_type, suggestion.target_id = target_type, target.id
    before = suggestion.version
    suggestion.review_status, suggestion.reviewed_by = desired, actor
    suggestion.reviewed_at, suggestion.version = utcnow(), suggestion.version + 1
    suggestion.review_note = request.note
    audit(db, pid, actor, "suggestion." + request.action, suggestion, before)
    return suggestion
