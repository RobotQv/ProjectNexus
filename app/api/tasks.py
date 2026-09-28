from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DB, Actor, write_scope
from app.core.errors import conflict
from app.db import utcnow
from app.models import RiskItem, Task, TaskDependency
from app.responses import DependencyOut, Page, RiskOut, TaskHistoryOut, TaskOut
from app.schemas import (
    DependencyCreate,
    DependencyReplace,
    RiskCreate,
    RiskPatch,
    TaskCreate,
    TaskPatch,
    TaskStatus,
)
from app.services import business
from app.services.common import audit, project_row, public, require_project, task_query

router = APIRouter(prefix="/projects/{pid}", tags=["任务、依赖与风险事项"])


@router.get("/tasks", response_model=Page[TaskOut])
def list_tasks(
    pid: int,
    db: DB,
    actor: Actor,
    status: TaskStatus | None = None,
    assignee_id: int | None = None,
    keyword: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    require_project(db, pid, actor)
    q = task_query(pid)
    if status:
        q = q.where(Task.status == status)
    if assignee_id is not None:
        q = q.where(Task.assignee_id == assignee_id)
    if keyword:
        q = q.where(Task.title.contains(keyword, autoescape=True))
    rows = db.scalars(q.order_by(Task.id).offset(offset).limit(limit))
    return {"items": [public(t) for t in rows], "limit": limit, "offset": offset}


@router.post("/tasks", status_code=201, response_model=TaskOut)
def create_task(pid: int, data: TaskCreate, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = business.create_task(db, pid, actor, data)
    db.commit()
    return public(row)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(pid: int, task_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    return public(project_row(db, Task, pid, task_id))


@router.get("/tasks/{task_id}/history", response_model=Page[TaskHistoryOut])
def task_history(
    pid: int,
    task_id: int,
    db: DB,
    actor: Actor,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    from app.models import TaskHistory
    from app.responses import TaskHistoryOut

    require_project(db, pid, actor)
    project_row(db, Task, pid, task_id, include_deleted=True)
    rows = db.scalars(
        select(TaskHistory)
        .where(TaskHistory.project_id == pid, TaskHistory.task_id == task_id)
        .order_by(TaskHistory.version.desc())
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [TaskHistoryOut.model_validate(public(row)) for row in rows],
        "limit": limit,
        "offset": offset,
    }


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def patch_task(pid: int, task_id: int, data: TaskPatch, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = business.update_task(db, pid, actor, project_row(db, Task, pid, task_id), data)
    db.commit()
    return public(row)


@router.delete("/tasks/{task_id}")
def delete_task(pid: int, task_id: int, db: DB, actor: Actor, expected_version: int = Query(ge=1)):
    write_scope(db, pid, actor)
    business.delete_task(db, pid, actor, project_row(db, Task, pid, task_id), expected_version)
    db.commit()
    return {"deleted": True, "task_id": task_id}


@router.get("/dependencies", response_model=Page[DependencyOut])
def list_dependencies(
    pid: int,
    db: DB,
    actor: Actor,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    require_project(db, pid, actor)
    return {
        "items": [
            public(d)
            for d in db.scalars(
                select(TaskDependency)
                .where(TaskDependency.project_id == pid)
                .order_by(TaskDependency.id)
                .offset(offset)
                .limit(limit)
            )
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/dependencies", status_code=201, response_model=DependencyOut)
def create_dependency(pid: int, data: DependencyCreate, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = business.create_dependency(db, pid, actor, data)
    db.commit()
    return public(row)


@router.put("/dependencies/{dependency_id}", response_model=DependencyOut)
def replace_dependency(pid: int, dependency_id: int, data: DependencyReplace, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = business.replace_dependency(
        db, pid, actor, project_row(db, TaskDependency, pid, dependency_id), data
    )
    db.commit()
    return public(row)


@router.delete("/dependencies/{dependency_id}")
def delete_dependency(
    pid: int, dependency_id: int, db: DB, actor: Actor, expected_version: int = Query(ge=1)
):
    write_scope(db, pid, actor)
    row = project_row(db, TaskDependency, pid, dependency_id)
    if row.version != expected_version:
        raise conflict()
    audit(db, pid, actor, "dependency.delete", row, row.version)
    db.delete(row)
    business.queue_risk(db, pid)
    db.commit()
    return {"deleted": True, "dependency_id": dependency_id}


@router.get("/risks", response_model=Page[RiskOut])
def list_risks(
    pid: int,
    db: DB,
    actor: Actor,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    require_project(db, pid, actor)
    return {
        "items": [
            public(r)
            for r in db.scalars(
                select(RiskItem)
                .where(RiskItem.project_id == pid)
                .order_by(RiskItem.id)
                .offset(offset)
                .limit(limit)
            )
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/risks", status_code=201, response_model=RiskOut)
def create_risk(pid: int, data: RiskCreate, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = business.create_risk(db, pid, actor, data)
    db.commit()
    return public(row)


@router.patch("/risks/{risk_id}", response_model=RiskOut)
def patch_risk(pid: int, risk_id: int, data: RiskPatch, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = project_row(db, RiskItem, pid, risk_id)
    if row.version != data.expected_version:
        raise conflict()
    before = row.version
    row.status, row.version = data.status, row.version + 1
    row.resolved_at = utcnow() if data.status == "resolved" else None
    audit(db, pid, actor, "risk.update", row, before)
    db.commit()
    return public(row)
