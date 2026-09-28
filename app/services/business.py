"""纯业务写入服务。调用前由 API / ReviewService 开启写事务，内部不擅自 commit。"""

from sqlalchemy import select

from app.core.errors import AppError, conflict
from app.db import utcnow
from app.models import RiskItem, Task, TaskDependency
from app.schemas import DependencyCreate, TaskCreate
from app.services.common import audit, enqueue, project_row, require_assignee
from app.services.history import record_task
from app.services.risk import queue_risk


def check_start_gate(
    db, pid, task_id, new_status, new_progress, old_status="not_started", old_progress=0
):
    # 启动是一项业务约束；复杂风险分析由规则模块负责。已存在的不一致不倒写状态。
    starting = old_status in {"not_started", "cancelled"} and (
        new_status in {"in_progress", "done"} or new_progress > old_progress
    )
    if not starting:
        return
    edges = db.scalars(
        select(TaskDependency).where(
            TaskDependency.project_id == pid,
            TaskDependency.successor_task_id == task_id,
            TaskDependency.successor_gate == "start",
        )
    ).all()
    blocked = []
    for edge in edges:
        task = project_row(db, Task, pid, edge.predecessor_task_id)
        if task.status == "cancelled" or task.progress < edge.predecessor_required_progress:
            blocked.append(edge.id)
    if blocked:
        raise AppError("start_blocked", "前置开始条件未满足", 409, {"dependency_ids": blocked})


def create_task(db, pid, actor, data: TaskCreate, source=None):
    require_assignee(db, pid, data.assignee_id)
    task = Task(project_id=pid, **data.model_dump(), source_suggestion_id=source)
    if data.forecast_end:
        task.forecast_updated_at, task.forecast_by = utcnow(), actor
    db.add(task)
    db.flush()
    enqueue(db, pid, "entity_sync", "task", task.id, task.version)
    audit(db, pid, actor, "task.create", task)
    record_task(db, task, actor, source="ai_review" if source else "manual", suggestion_id=source)
    queue_risk(db, pid)
    return task


def update_task(db, pid, actor, task, patch, source=None):
    if task.version != patch.expected_version:
        raise conflict()
    changes = patch.model_dump(exclude_unset=True, exclude={"expected_version"})
    merged = {name: getattr(task, name) for name in TaskCreate.model_fields}
    merged.update(changes)
    valid = TaskCreate.model_validate(merged)
    if "assignee_id" in changes:
        require_assignee(db, pid, valid.assignee_id)
    check_start_gate(db, pid, task.id, valid.status, valid.progress, task.status, task.progress)
    previous = task.version
    text_changed = any(
        key in changes and changes[key] != getattr(task, key)
        for key in {"title", "description", "tags", "aliases", "module_name"}
    )
    if "forecast_end" in changes and changes["forecast_end"] != task.forecast_end:
        task.forecast_updated_at, task.forecast_by = utcnow(), actor
    if {"status", "progress"} & changes.keys():
        task.progress_updated_at = utcnow()
    for key, value in changes.items():
        setattr(task, key, value)
    task.version += 1
    db.flush()
    if text_changed:
        enqueue(db, pid, "entity_sync", "task", task.id, task.version)
    audit(db, pid, actor, "task.update", task, previous)
    record_task(db, task, actor, source="ai_review" if source else "manual", suggestion_id=source)
    queue_risk(db, pid)
    return task


def delete_task(db, pid, actor, task, expected_version):
    if task.version != expected_version:
        raise conflict()
    linked = db.scalar(
        select(TaskDependency.id).where(
            TaskDependency.project_id == pid,
            (TaskDependency.predecessor_task_id == task.id)
            | (TaskDependency.successor_task_id == task.id),
        )
    )
    if linked:
        raise conflict("请先移除该任务的依赖边，再删除任务")
    before = task.version
    task.deleted_at, task.version = utcnow(), task.version + 1
    enqueue(db, pid, "entity_sync", "task", task.id, task.version)
    audit(db, pid, actor, "task.delete", task, before)
    record_task(db, task, actor, source="manual_delete")
    queue_risk(db, pid)


def validate_edge(db, pid, data: DependencyCreate, exclude_id=None):
    project_row(db, Task, pid, data.predecessor_task_id)
    project_row(db, Task, pid, data.successor_task_id)
    edges = db.scalars(select(TaskDependency).where(TaskDependency.project_id == pid)).all()
    graph = {}
    for edge in edges:
        if edge.id == exclude_id:
            continue
        if (edge.predecessor_task_id, edge.successor_task_id) == (
            data.predecessor_task_id,
            data.successor_task_id,
        ):
            raise conflict("该依赖关系已存在")
        graph.setdefault(edge.predecessor_task_id, []).append(edge.successor_task_id)
    # 添加 A→B 前寻找 B→A；非递归遍历避免长链触发递归深度限制。
    stack = [(data.successor_task_id, [data.successor_task_id])]
    visited = set()
    while stack:
        node, path = stack.pop()
        if node == data.predecessor_task_id:
            raise AppError(
                "dependency_cycle",
                "该依赖会形成循环",
                409,
                {"cycle": [data.predecessor_task_id] + path},
            )
        if node in visited:
            continue
        visited.add(node)
        stack.extend((n, path + [n]) for n in graph.get(node, []))


def create_dependency(db, pid, actor, data, source=None):
    validate_edge(db, pid, data)
    edge = TaskDependency(project_id=pid, **data.model_dump(), source_suggestion_id=source)
    db.add(edge)
    db.flush()
    audit(db, pid, actor, "dependency.create", edge)
    queue_risk(db, pid)
    return edge


def replace_dependency(db, pid, actor, edge, data):
    if edge.version != data.expected_version:
        raise conflict()
    valid = DependencyCreate.model_validate(data.model_dump(exclude={"expected_version"}))
    validate_edge(db, pid, valid, edge.id)
    before = edge.version
    for key, value in valid.model_dump().items():
        setattr(edge, key, value)
    edge.version += 1
    audit(db, pid, actor, "dependency.update", edge, before)
    queue_risk(db, pid)
    return edge


def create_risk(db, pid, actor, data, source=None):
    if data.related_task_id:
        project_row(db, Task, pid, data.related_task_id)
    risk = RiskItem(
        project_id=pid,
        **data.model_dump(),
        source_suggestion_id=source,
        origin="extracted" if source else "manual",
    )
    db.add(risk)
    db.flush()
    audit(db, pid, actor, "risk.create", risk)
    return risk
