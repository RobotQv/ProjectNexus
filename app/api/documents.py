from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import DB, Actor, write_scope
from app.core.errors import AppError, conflict, not_found
from app.models import Document, Job, WorkflowRun
from app.responses import DocumentOut, JobOut, Page, UploadOut
from app.schemas import WorkflowStart
from app.services import documents as service
from app.services.common import project_row, public, require_project

router = APIRouter(prefix="/projects/{pid}", tags=["资料与后台任务"])


@router.post("/documents", status_code=202, response_model=UploadOut)
def upload_document(
    pid: int,
    request: Request,
    db: DB,
    actor: Actor,
    file: Annotated[UploadFile, File()],
    document_type: Annotated[str | None, Form(max_length=64)] = None,
    document_date: Annotated[date | None, Form()] = None,
):
    require_project(db, pid, actor, write=True)
    settings = request.app.state.settings
    # 文件写入不持有 DB 写锁；失败只清理本次新建的 UUID 文件，绝不删除用户原件。
    db.rollback()
    stored = service.save_upload(settings, file)
    try:
        write_scope(db, pid, actor)
        doc, job = service.register_upload(db, pid, actor, stored, document_type, document_date)
        db.commit()
    except BaseException:
        db.rollback()
        service.storage_path(settings, stored["storage_key"]).unlink(missing_ok=True)
        raise
    return {"document": public(doc), "job_id": job.id}


@router.get("/documents", response_model=Page[DocumentOut])
def list_documents(
    pid: int,
    db: DB,
    actor: Actor,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    require_project(db, pid, actor)
    return {
        "items": [
            public(d)
            for d in db.scalars(
                select(Document)
                .where(Document.project_id == pid, Document.deleted_at.is_(None))
                .order_by(Document.id)
                .offset(offset)
                .limit(limit)
            )
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(pid: int, document_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    return public(project_row(db, Document, pid, document_id))


@router.get("/documents/{document_id}/source")
def get_source(
    pid: int, document_id: int, request: Request, db: DB, actor: Actor, version: int = Query(ge=1)
):
    require_project(db, pid, actor)
    doc = project_row(db, Document, pid, document_id)
    if doc.version != version:
        raise not_found()
    path = service.storage_path(request.app.state.settings, doc.storage_key)
    if not path.is_file():
        raise AppError("source_missing", "原文件暂不可用，请检查存储", 503)
    return FileResponse(
        path,
        filename=doc.filename,
        media_type="application/octet-stream",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.get("/documents/{document_id}/blocks")
def get_blocks(
    pid: int,
    document_id: int,
    db: DB,
    actor: Actor,
    version: int = Query(ge=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    require_project(db, pid, actor)
    doc = project_row(db, Document, pid, document_id)
    if doc.version != version:
        raise not_found()
    blocks = service.get_blocks(db, doc)
    return {
        "items": [b.model_dump(mode="json") for b in blocks[offset : offset + limit]],
        "version": version,
        "limit": limit,
        "offset": offset,
    }


@router.post("/documents/{document_id}/retry", status_code=202, response_model=UploadOut)
def retry_document(pid: int, document_id: int, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    doc = project_row(db, Document, pid, document_id)
    job = service.retry_document(db, doc)
    db.commit()
    return {"document": public(doc), "job_id": job.id}


@router.delete("/documents/{document_id}", status_code=202)
def delete_document(pid: int, document_id: int, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    doc = project_row(db, Document, pid, document_id, include_deleted=True)
    job = service.delete_document(db, pid, actor, doc)
    db.commit()
    return {"deleted": True, "job_id": job.id, "cleanup_status": job.status}


@router.post("/documents/{document_id}/extract", status_code=202)
def start_workflow(pid: int, document_id: int, data: WorkflowStart, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    doc = project_row(db, Document, pid, document_id)
    run, job = service.start_workflow(db, doc, data.kind, actor)
    db.commit()
    return {"workflow_run_id": run.id, "job_id": job.id, "status": run.status}


@router.get("/workflow-runs/{run_id}")
def get_workflow(pid: int, run_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    run = project_row(db, WorkflowRun, pid, run_id)
    if run.source_kind != "document" and run.submitted_by != actor:
        raise AppError("submitter_required", "对话运行记录仅提交者可查看", 403)
    return public(run)


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(
    pid: int,
    db: DB,
    actor: Actor,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    require_project(db, pid, actor)
    return {
        "items": [
            public(j)
            for j in db.scalars(
                select(Job)
                .where(Job.project_id == pid)
                .order_by(Job.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(pid: int, job_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    return public(project_row(db, Job, pid, job_id))


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=JobOut)
def retry_job(pid: int, job_id: int, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    job = project_row(db, Job, pid, job_id)
    if job.status != "failed":
        raise conflict("仅失败任务可重试；运行中任务由租约超时机制恢复")
    if job.kind == "document_ingest":
        doc = project_row(db, Document, pid, job.resource_id)
        service.retry_document(db, doc)
    elif job.kind == "workflow":
        run = project_row(db, WorkflowRun, pid, job.resource_id)
        doc = project_row(db, Document, pid, run.document_id)
        service.start_workflow(db, doc, run.kind)
    else:
        service.reset_failed_job(job)
    db.commit()
    return public(job)
