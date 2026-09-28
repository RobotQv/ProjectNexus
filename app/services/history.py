"""和正式修改同事务写入，外部算法永远不能独立插入或覆盖历史。"""

from app.models import TaskHistory
from app.services.common import public


def record_task(db, task, actor, *, source="manual", suggestion_id=None):
    db.flush()
    db.add(
        TaskHistory(
            project_id=task.project_id,
            task_id=task.id,
            version=task.version,
            snapshot=public(task),
            actor_id=actor,
            source=source,
            suggestion_id=suggestion_id,
        )
    )
