from fastapi.encoders import jsonable_encoder
from sqlalchemy import inspect, select

from app.core.errors import AppError, not_found
from app.models import AuditEvent, Job, Project, ProjectMember, Task, User


def public(row):
    """响应序列化白名单由模型列组成；以下内部字段永不进入普通 API。"""
    hidden = {"password_hash", "storage_key", "lease_token", "lease_expires_at"}
    return jsonable_encoder(
        {
            c.key: getattr(row, c.key)
            for c in inspect(row).mapper.column_attrs
            if c.key not in hidden
        }
    )


def require_project(db, project_id, actor_id, *, write=False, owner=False):
    project = db.get(Project, project_id)
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == actor_id,
            ProjectMember.is_active.is_(True),
        )
    )
    user = db.get(User, actor_id)
    if not project or project.deleted_at or not member or not user or not user.is_active:
        # 对范围外 ID 一律 404，避免枚举别人的项目是否存在。
        raise not_found()
    if owner and project.owner_id != actor_id:
        raise AppError("owner_required", "该操作仅限项目负责人", 403)
    if write and project.status != "active":
        raise AppError("project_archived", "已归档项目只读，请由负责人先恢复", 409)
    return project


def project_row(db, model, project_id, row_id, *, include_deleted=False):
    row = db.get(model, row_id)
    if not row or row.project_id != project_id:
        raise not_found()
    if not include_deleted and getattr(row, "deleted_at", None):
        raise not_found()
    return row


def require_assignee(db, project_id, user_id):
    if user_id is None:
        return
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    user = db.get(User, user_id)
    if not member or not user or not user.is_active:
        raise AppError("invalid_assignee", "负责人必须是当前项目的有效成员")


def audit(db, pid, actor, action, row, before=None):
    db.add(
        AuditEvent(
            project_id=pid,
            actor_id=actor,
            action=action,
            resource_type=row.__tablename__,
            resource_id=row.id,
            before_version=before,
            after_version=getattr(row, "version", None),
        )
    )


def enqueue(db, pid, kind, resource_type, resource_id, version, *, key=None):
    key = key or f"{kind}:{resource_type}:{resource_id}:v{version}"
    job = db.scalar(select(Job).where(Job.dedup_key == key))
    if job:
        return job
    job = Job(
        project_id=pid,
        kind=kind,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_version=version,
        dedup_key=key,
    )
    db.add(job)
    db.flush()
    return job


def task_query(pid):
    return select(Task).where(Task.project_id == pid, Task.deleted_at.is_(None))
