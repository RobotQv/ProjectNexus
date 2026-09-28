from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DB, Actor, write_scope
from app.core.errors import AppError, conflict, not_found
from app.db import begin_write
from app.models import Project, ProjectMember, User
from app.responses import Page, ProjectOut
from app.schemas import MemberAdd, MemberPatch, ProjectCreate, ProjectPatch
from app.services.common import audit, enqueue, public, require_project

router = APIRouter(prefix="/projects", tags=["项目与成员"])


@router.post("", status_code=201, response_model=ProjectOut)
def create_project(data: ProjectCreate, db: DB, actor: Actor):
    begin_write(db)
    project = Project(**data.model_dump(), owner_id=actor)
    db.add(project)
    db.flush()
    member = ProjectMember(project_id=project.id, user_id=actor, role="owner")
    db.add(member)
    db.flush()
    enqueue(
        db,
        project.id,
        "entity_sync",
        "member",
        actor,
        member.version,
        key=f"member:{project.id}:{actor}:v{member.version}",
    )
    audit(db, project.id, actor, "project.create", project)
    db.commit()
    return public(project)


@router.get("", response_model=Page[ProjectOut])
def list_projects(
    db: DB, actor: Actor, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
):
    rows = db.scalars(
        select(Project)
        .join(ProjectMember)
        .where(
            ProjectMember.user_id == actor,
            ProjectMember.is_active.is_(True),
            Project.deleted_at.is_(None),
        )
        .order_by(Project.id)
        .offset(offset)
        .limit(limit)
    )
    return {"items": [public(p) for p in rows], "limit": limit, "offset": offset}


@router.get("/{pid}", response_model=ProjectOut)
def get_project(pid: int, db: DB, actor: Actor):
    return public(require_project(db, pid, actor))


@router.patch("/{pid}", response_model=ProjectOut)
def update_project(pid: int, data: ProjectPatch, db: DB, actor: Actor):
    project = write_scope(db, pid, actor, owner=True, allow_archived=True)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key != "description" and value is None:
            raise AppError("invalid_field", f"{key} 不能为 null")
        setattr(project, key, value)
    audit(db, pid, actor, "project.update", project)
    db.commit()
    return public(project)


@router.get("/{pid}/members")
def list_members(pid: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, ProjectMember.user_id == User.id)
        .where(ProjectMember.project_id == pid, ProjectMember.is_active.is_(True))
        .order_by(ProjectMember.id)
    )
    return {
        "items": [
            public(m) | {"display_name": u.display_name, "login_name": u.login_name}
            for m, u in rows
        ]
    }


@router.post("/{pid}/members", status_code=201)
def add_member(pid: int, data: MemberAdd, db: DB, actor: Actor):
    write_scope(db, pid, actor, owner=True)
    user = db.scalar(
        select(User).where(User.login_name == data.login_name, User.is_active.is_(True))
    )
    if not user:
        raise not_found()
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == pid, ProjectMember.user_id == user.id
        )
    )
    if member and member.is_active:
        raise conflict("该用户已经是项目成员")
    if member:
        member.is_active, member.aliases, member.version = True, data.aliases, member.version + 1
    else:
        member = ProjectMember(project_id=pid, user_id=user.id, aliases=data.aliases)
        db.add(member)
        db.flush()
    enqueue(
        db,
        pid,
        "entity_sync",
        "member",
        user.id,
        member.version,
        key=f"member:{pid}:{user.id}:v{member.version}",
    )
    audit(db, pid, actor, "member.add", member)
    db.commit()
    return public(member)


@router.patch("/{pid}/members/{user_id}")
def update_member(pid: int, user_id: int, data: MemberPatch, db: DB, actor: Actor):
    write_scope(db, pid, actor, owner=True)
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == pid,
            ProjectMember.user_id == user_id,
            ProjectMember.is_active.is_(True),
        )
    )
    if not member:
        raise not_found()
    member.aliases, member.version = data.aliases, member.version + 1
    enqueue(
        db,
        pid,
        "entity_sync",
        "member",
        user_id,
        member.version,
        key=f"member:{pid}:{user_id}:v{member.version}",
    )
    audit(db, pid, actor, "member.update", member)
    db.commit()
    return public(member)


@router.delete("/{pid}/members/{user_id}")
def remove_member(pid: int, user_id: int, db: DB, actor: Actor):
    project = write_scope(db, pid, actor, owner=True)
    if project.owner_id == user_id:
        raise conflict("不能移除项目负责人")
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == pid, ProjectMember.user_id == user_id
        )
    )
    if not member:
        raise not_found()
    if member.is_active:
        member.is_active, member.version = False, member.version + 1
        enqueue(
            db,
            pid,
            "entity_sync",
            "member",
            user_id,
            member.version,
            key=f"member:{pid}:{user_id}:v{member.version}",
        )
        audit(db, pid, actor, "member.remove", member)
    db.commit()
    return {"removed": True, "user_id": user_id}
