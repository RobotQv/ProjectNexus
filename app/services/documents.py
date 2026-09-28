import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.errors import AppError, conflict
from app.db import utcnow
from app.integrations.contracts import Block, DocumentRef, Evidence
from app.models import Document, DocumentBlock, Job, WorkflowRun
from app.services.common import audit, enqueue, project_row

MEDIA = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}


def storage_path(settings, key):
    root = settings.storage_dir.resolve()
    target = (root / key).resolve()
    if not target.is_relative_to(root) or target == root:
        raise AppError("invalid_storage_key", "文件存储标识无效", 500)
    return target


def save_upload(settings, upload):
    # 所有磁盘名称由后端生成；原文件名仅用于显示。
    name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in MEDIA or len(name) > 255 or not name or any(ord(c) < 32 for c in name):
        raise AppError(
            "unsupported_file", "仅支持 TXT、Markdown、DOCX、文本 PDF；文件名最长 255 字符"
        )
    key = uuid.uuid4().hex + suffix
    path = storage_path(settings, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    size, digest = 0, hashlib.sha256()
    try:
        with path.open("xb") as target:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise AppError(
                        "file_too_large", f"文件大小不能超过 {settings.max_upload_mb} MB", 413
                    )
                digest.update(chunk)
                target.write(chunk)
        if size == 0:
            raise AppError("empty_file", "不能上传空文件")
        # 轻量魔数检查；内容解析和安全解压由主 RAG 模块承担。
        with path.open("rb") as source:
            head = source.read(8)
        if suffix == ".pdf" and not head.startswith(b"%PDF-"):
            raise AppError("invalid_file", "文件内容不是有效 PDF")
        if suffix == ".docx" and not head.startswith(b"PK\x03\x04"):
            raise AppError("invalid_file", "文件内容不是有效 DOCX")
        return {
            "filename": name,
            "media_type": MEDIA[suffix],
            "size_bytes": size,
            "storage_key": key,
            "content_hash": digest.hexdigest(),
        }
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def register_upload(db, pid, actor, stored, document_type=None, document_date=None):
    existing = db.scalar(
        select(Document).where(
            Document.project_id == pid,
            Document.content_hash == stored["content_hash"],
            Document.deleted_at.is_(None),
        )
    )
    if existing:
        raise AppError(
            "duplicate_document", "当前项目已存在相同内容的文档", 409, {"document_id": existing.id}
        )
    doc = Document(
        project_id=pid,
        uploaded_by=actor,
        **stored,
        document_type=document_type,
        document_date=document_date,
    )
    db.add(doc)
    db.flush()
    job = enqueue(db, pid, "document_ingest", "document", doc.id, doc.version)
    audit(db, pid, actor, "document.upload", doc)
    return doc, job


def get_blocks(db, doc):
    rows = db.scalars(
        select(DocumentBlock)
        .where(DocumentBlock.document_id == doc.id, DocumentBlock.document_version == doc.version)
        .order_by(DocumentBlock.block_no)
    ).all()
    return [
        Block(
            id=b.id,
            document_id=b.document_id,
            document_version=b.document_version,
            block_no=b.block_no,
            text=b.text,
            page=b.page,
            heading=b.heading,
            locator=b.locator,
        )
        for b in rows
    ]


def document_ref(db, doc):
    return DocumentRef(
        project_id=doc.project_id,
        document_id=doc.id,
        version=doc.version,
        document_date=doc.document_date,
        filename=doc.filename,
        blocks=get_blocks(db, doc),
    )


def validate_evidence(db, pid, evidence, *, require_index=True):
    """供应商/算法返回的引用仍是不可信输入：按项目、版本和正文再次校验。"""
    valid = Evidence.model_validate(evidence)
    doc = project_row(db, Document, pid, valid.document_id)
    if doc.version != valid.version or doc.parse_status != "ready":
        raise AppError("stale_evidence", "来源版本不可用")
    if require_index and doc.index_status != "ready":
        raise AppError("stale_evidence", "来源尚未完成索引")
    blocks = {b.id: b for b in get_blocks(db, doc)}
    if any(key not in blocks for key in valid.block_ids):
        raise AppError("invalid_evidence", "引用锚点不属于该文档版本")
    quoted_text = "\n".join(blocks[key].text for key in valid.block_ids)
    if valid.quote not in quoted_text:
        raise AppError("invalid_evidence", "引用摘录与原文不一致")
    # 标题和日期回源覆盖，不能采信模型或索引伪造的来源元数据。
    return valid.model_copy(update={"filename": doc.filename, "document_date": doc.document_date})


def reset_failed_job(job):
    if job.status != "failed":
        return job
    job.status, job.error_message, job.finished_at = "queued", None, None
    job.lease_token = job.lease_expires_at = None
    return job


def retry_document(db, doc):
    job = db.scalar(
        select(Job).where(Job.dedup_key == f"document_ingest:document:{doc.id}:v{doc.version}")
    )
    if not job:
        job = enqueue(db, doc.project_id, "document_ingest", "document", doc.id, doc.version)
    # 连续点击重试只复用 Job，不把正在 running 的状态改回 pending。
    if job.status in {"queued", "running", "succeeded"}:
        return job
    reset_failed_job(job)
    doc.error_message = None
    if doc.parse_status == "failed":
        doc.parse_status = "pending"
    doc.index_status = "pending"
    return job


def delete_document(db, pid, actor, doc):
    if doc.deleted_at:
        return enqueue(db, pid, "document_delete", "document", doc.id, doc.version)
    doc.deleted_at = utcnow()
    job = enqueue(db, pid, "document_delete", "document", doc.id, doc.version)
    audit(db, pid, actor, "document.delete", doc)
    return job


def start_workflow(db, doc, kind, actor=None):
    if doc.parse_status != "ready":
        raise conflict("请等待文档解析完成后再启动工作流")
    run = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.document_id == doc.id,
            WorkflowRun.document_version == doc.version,
            WorkflowRun.kind == kind,
        )
    )
    if not run:
        run = WorkflowRun(
            project_id=doc.project_id,
            document_id=doc.id,
            document_version=doc.version,
            input_hash=doc.content_hash,
            kind=kind,
            submitted_by=actor,
        )
        db.add(run)
        db.flush()
    job = enqueue(db, doc.project_id, "workflow", "workflow_run", run.id, doc.version)
    if job.status == "failed":
        reset_failed_job(job)
        if run.status != "succeeded":
            run.status, run.error = "pending", None
    return run, job
