"""模型输出只创建候选。身份、来源类型与审核状态由后端决定。"""

from copy import deepcopy

from app.core.errors import AppError
from app.models import Suggestion, Task, User
from app.services.common import project_row, require_assignee
from app.services.documents import validate_evidence
from app.services.entities import entity_catalog
from shared.contracts import SuggestionDraft


def validate_draft(db, pid, draft, *, document=None):
    draft = SuggestionDraft.model_validate(draft)
    if document is not None and not draft.source_refs:
        raise AppError("missing_source", "文档提取建议必须包含来源原文锚点", 502)
    for ref in draft.source_refs:
        if document and (
            ref.document_id != document.document_id or ref.version != document.version
        ):
            raise AppError("invalid_source", "工作流来源不属于本次文档版本", 502)
        validate_evidence(db, pid, ref, require_index=False)
    data = draft.proposed_payload
    task_fields = data.get("changes", {}) if draft.suggestion_type == "update_task" else data
    if draft.suggestion_type in {"create_task", "update_task"}:
        require_assignee(db, pid, task_fields.get("assignee_id"))
    if draft.suggestion_type == "update_task":
        task = project_row(db, Task, pid, data["task_id"])
        if task.version != data["expected_version"]:
            draft.validation_warnings.append(
                "目标任务版本已变化；正式确认前请重新核对版本和修改内容"
            )
    for key in ("predecessor_task_id", "successor_task_id", "related_task_id"):
        if data.get(key) is not None:
            project_row(db, Task, pid, data[key])
    catalog = {(e.entity_type, e.entity_id) for e in entity_catalog(db, pid) if e.is_active}
    candidates = []
    for c in draft.entity_candidates:
        if (c.entity_type, c.entity_id) not in catalog:
            draft.validation_warnings.append("已过滤无效或项目范围外实体候选")
            continue
        row = db.get(Task if c.entity_type == "task" else User, c.entity_id)
        candidates.append(
            c.model_copy(
                update={"title": row.title if c.entity_type == "task" else row.display_name}
            )
        )
    draft.entity_candidates = candidates
    return draft


def save_draft(db, run, draft):
    from app.db import utcnow

    payload = draft.model_dump(mode="json")
    row = Suggestion(
        run_id=run.id,
        project_id=run.project_id,
        **payload,
        original_payload=deepcopy(payload["proposed_payload"]),
        submitted_by=run.submitted_by,
        source_kind=run.source_kind,
        review_status="pending" if run.source_kind == "document" else "draft",
        submitted_at=utcnow() if run.source_kind == "document" else None,
    )
    db.add(row)
    return row
