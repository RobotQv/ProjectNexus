"""风险是提示，不是任务状态。自动检查只由业务变更排队，不设定时扫描。"""

import hashlib
import json
import uuid
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select

from app.core.errors import AppError
from app.db import utcnow
from app.models import Project, Task, TaskDependency
from app.services.common import enqueue, public, task_query
from shared.contracts import AnalysisResult, Snapshot


def queue_risk(db, pid):
    return enqueue(
        db, pid, "risk_analysis", "project", pid, 1, key="risk_change:" + uuid.uuid4().hex
    )


def snapshot(db, pid, evaluation_date=None):
    project = db.get(Project, pid)
    return Snapshot(
        project_id=pid,
        timezone=project.timezone,
        evaluation_date=evaluation_date or utcnow().astimezone(ZoneInfo(project.timezone)).date(),
        tasks=[public(t) for t in db.scalars(task_query(pid).order_by(Task.id))],
        dependencies=[
            public(e)
            for e in db.scalars(
                select(TaskDependency)
                .where(TaskDependency.project_id == pid)
                .order_by(TaskDependency.id)
            )
        ],
    )


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def validate_result(raw, state, candidate_keys=()):
    try:
        result = AnalysisResult.model_validate(raw)
    except ValidationError:
        raise AppError("module_contract_invalid", "风险模块返回格式不符合契约", 502) from None
    tasks = {t["id"] for t in state.tasks}
    edges = {e["id"] for e in state.dependencies}
    for finding in result.findings:
        if (
            not set(finding.task_ids) <= tasks
            or not set(finding.candidate_keys) <= set(candidate_keys)
            or (finding.dependency_id is not None and finding.dependency_id not in edges)
        ):
            raise AppError("invalid_analysis_scope", "风险结果包含输入范围外引用", 502)
    return result
