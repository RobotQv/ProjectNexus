"""阶段以短写事务落盘；同一个 run 可跨请求、跨进程读取，不逐 token 写 SQLite。"""

from sqlalchemy import select

from app.core.errors import AppError
from app.db import begin_write, utcnow
from app.models import WorkflowRun
from app.services.common import require_project

STAGES = {
    "accepted": "请求已接收",
    "interpreting": "正在分析问题",
    "resolving_entity": "正在定位任务",
    "retrieving": "正在查阅资料库",
    "fusing": "正在合并检索结果",
    "reading_facts": "正在读取当前记录",
    "generating": "正在组织回答或建议",
    "validating": "正在校验结果",
    "persisting": "正在保存结果",
    "completed": "已完成",
    "failed": "处理失败",
}


def append_event(run, stage):
    now = utcnow()
    events = list(run.progress_events or [])
    elapsed = max(0, int((now - run.started_at).total_seconds() * 1000))
    if events and events[-1]["state"] == "running":
        events[-1] = {
            **events[-1],
            "state": "failed" if stage == "failed" else "completed",
            "elapsed_ms": elapsed - events[-1]["started_ms"],
        }
    events.append(
        {
            "seq": len(events) + 1,
            "stage": stage,
            "message": STAGES[stage],
            "state": "failed"
            if stage == "failed"
            else "completed"
            if stage == "completed"
            else "running",
            "timestamp": now.isoformat(),
            "started_ms": elapsed,
            "elapsed_ms": 0,
        }
    )
    run.progress_events = events


def recorder(sessions, run_id):
    def record(stage):
        with sessions() as db:
            begin_write(db)
            run = db.get(WorkflowRun, run_id)
            if run and run.status == "running":
                append_event(run, stage)
                db.commit()

    return record


def progress_response(db, pid, actor, request_key):
    require_project(db, pid, actor)
    run = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.project_id == pid,
            WorkflowRun.submitted_by == actor,
            WorkflowRun.request_key == request_key,
            WorkflowRun.kind == "assistant",
        )
    )
    if not run:
        raise AppError("not_found", "该请求尚未接收或不存在", 404)
    end = run.finished_at or utcnow()
    return {
        "run_id": run.id,
        "request_key": request_key,
        "status": run.status,
        "events": run.progress_events or [],
        "error": run.error,
        "elapsed_ms": max(0, int((end - run.started_at).total_seconds() * 1000)),
        "terminal": run.status in {"succeeded", "failed"},
    }
