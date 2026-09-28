from sqlalchemy import select

from app.integrations.contracts import EntityRecord
from app.models import ProjectMember, Task, User
from app.services.common import project_row


def entity_record(db, pid, kind, entity_id):
    if kind == "task":
        row = project_row(db, Task, pid, entity_id, include_deleted=True)
        text = " ".join(
            [row.title, row.description or "", row.module_name or "", *row.tags, *row.aliases]
        )
        return EntityRecord(
            project_id=pid,
            entity_type=kind,
            entity_id=row.id,
            source_version=row.version,
            search_text=text,
            is_active=row.deleted_at is None,
            title=row.title,
            aliases=row.aliases,
        )
    member = db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == pid, ProjectMember.user_id == entity_id
        )
    )
    user = db.get(User, entity_id)
    return EntityRecord(
        project_id=pid,
        entity_type="member",
        entity_id=entity_id,
        source_version=member.version,
        search_text=" ".join([user.display_name, *member.aliases]),
        is_active=member.is_active and user.is_active,
        title=user.display_name,
        aliases=member.aliases,
    )


def entity_catalog(db, pid):
    task_ids = db.scalars(
        select(Task.id).where(Task.project_id == pid, Task.deleted_at.is_(None))
    ).all()
    member_ids = db.scalars(
        select(ProjectMember.user_id).where(
            ProjectMember.project_id == pid, ProjectMember.is_active.is_(True)
        )
    ).all()
    return [entity_record(db, pid, "task", i) for i in task_ids] + [
        entity_record(db, pid, "member", i) for i in member_ids
    ]
