"""数据库持久队列：独立进程串行执行，租约 + 心跳 + 完成前校验防止旧 Worker 发布结果。

算法调用期间不持有数据库事务；同一 Job 为至少一次执行，适配器必须幂等 upsert/delete。
运行：python -m app.worker；联调单步：python -m app.worker --once。
"""

import argparse
import inspect
import logging
import threading
import uuid
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import AppError
from app.db import begin_write, build_engine, session_factory, utcnow
from app.integrations.adapters import build_modules
from app.integrations.contracts import (
    ExtractionResult,
    FileRef,
    IngestResult,
    ParsedDocument,
    Scope,
)
from app.llm import build_llm
from app.models import AnalysisRun, Document, DocumentBlock, Job, Project, WorkflowRun
from app.services.common import project_row, require_project
from app.services.documents import document_ref, storage_path
from app.services.entities import entity_catalog, entity_record
from app.services.risk import fingerprint, snapshot, validate_result
from app.services.suggestions import save_draft, validate_draft
from app.services.tools import BoundTools

log = logging.getLogger(__name__)
LEASE_SECONDS = 120


class Worker:
    def __init__(self, sessions, settings, modules):
        self.sessions, self.settings, self.modules = sessions, settings, modules

    def claim(self):
        with self.sessions() as db:
            begin_write(db)
            # 串行消费保证小组项目资源开销可控；并行启动两个 worker 也不会同时领新任务。
            running = db.scalars(select(Job).where(Job.status == "running")).all()
            for old in running:
                if old.lease_expires_at and old.lease_expires_at > utcnow():
                    return None
                self.fail_resource(db, old, "worker_lease_expired：执行中断，请手动重试")
                old.status, old.finished_at = "failed", utcnow()
                old.error_message = "worker_lease_expired：执行中断，请手动重试"
                old.lease_token, old.lease_expires_at = None, None
            job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.id).limit(1))
            if not job:
                db.commit()
                return None
            job.status, job.started_at, job.finished_at = "running", utcnow(), None
            job.attempts += 1
            job.lease_token = uuid.uuid4().hex
            job.lease_expires_at = utcnow() + timedelta(seconds=LEASE_SECONDS)
            job.error_message = None
            db.commit()
            return job.id, job.lease_token

    def current_job(self, db, job_id, token):
        job = db.get(Job, job_id)
        if job.status != "running" or job.lease_token != token:
            raise AppError("lease_lost", "任务租约已失效", 409)
        return job

    def heartbeat(self, job_id, token, stop):
        while not stop.wait(30):
            try:
                with self.sessions() as db:
                    begin_write(db)
                    job = self.current_job(db, job_id, token)
                    job.lease_expires_at = utcnow() + timedelta(seconds=LEASE_SECONDS)
                    db.commit()
            except Exception:
                log.warning("job=%s heartbeat failed", job_id)
                return

    def run_once(self):
        claimed = self.claim()
        if not claimed:
            return False
        job_id, token = claimed
        stop = threading.Event()
        heartbeat = threading.Thread(target=self.heartbeat, args=(job_id, token, stop), daemon=True)
        heartbeat.start()
        try:
            self.execute(job_id, token)
            with self.sessions() as db:
                begin_write(db)
                job = self.current_job(db, job_id, token)
                job.status, job.finished_at = "succeeded", utcnow()
                job.lease_token, job.lease_expires_at = None, None
                db.commit()
        except Exception as error:
            # 不记录任意供应商异常文本，避免正文 / 密钥进入日志与 HTTP 错误。
            message = (
                f"{error.code}：{error.message}"
                if isinstance(error, AppError)
                else "module_execution_failed：模块执行失败，请检查模块实现"
            )
            if isinstance(error, ValidationError):
                message = "module_contract_invalid：模块返回值不符合接口契约"
            log.warning("job=%s failed type=%s", job_id, type(error).__name__)
            with self.sessions() as db:
                begin_write(db)
                job = db.get(Job, job_id)
                if job.status == "running" and job.lease_token == token:
                    self.fail_resource(db, job, message)
                    job.status, job.error_message, job.finished_at = "failed", message, utcnow()
                    job.lease_token, job.lease_expires_at = None, None
                    db.commit()
        finally:
            stop.set()
            heartbeat.join(timeout=2)
        return True

    @staticmethod
    def fail_resource(db, job, message):
        if job.kind == "document_ingest":
            doc = db.get(Document, job.resource_id)
            if doc and not doc.deleted_at:
                if doc.parse_status != "ready":
                    doc.parse_status = "failed"
                doc.index_status, doc.error_message = "failed", message
        elif job.kind == "workflow":
            run = db.get(WorkflowRun, job.resource_id)
            if run and run.status != "succeeded":
                run.status, run.error, run.finished_at = "failed", message, utcnow()

    def execute(self, job_id, token):
        with self.sessions() as db:
            job = self.current_job(db, job_id, token)
            project = db.get(Project, job.project_id)
            if not project or project.deleted_at:
                raise AppError("project_unavailable", "项目不可用")
            if project.status != "active" and job.kind not in {"document_delete", "entity_sync"}:
                raise AppError("project_archived", "已归档项目暂停文档处理与工作流")
            kind, pid, rid = job.kind, job.project_id, job.resource_id
        if kind == "document_ingest":
            self.ingest(job_id, token, pid, rid)
        elif kind == "document_delete":
            with self.sessions() as db:
                doc = project_row(db, Document, pid, rid, include_deleted=True)
                version = doc.version
            self.modules.main_rag.delete(Scope(project_id=pid), rid, version)
            # 原始文件和 Block 留作审计；API 已不可访问。向量清理由适配器幂等执行。
        elif kind == "entity_sync":
            with self.sessions() as db:
                job = self.current_job(db, job_id, token)
                entity = entity_record(db, pid, job.resource_type, rid)
            self.modules.entities.sync(entity)
        elif kind == "workflow":
            self.workflow(job_id, token, pid, rid)
        elif kind == "risk_analysis":
            self.risk_analysis(job_id, token, pid)
        else:
            raise AppError("unknown_job", "任务类型未注册")

    def risk_analysis(self, job_id, token, pid):
        with self.sessions() as db:
            self.current_job(db, job_id, token)
            if db.scalar(select(AnalysisRun.id).where(AnalysisRun.trigger_job_id == job_id)):
                return
            state = snapshot(db, pid)
        result = validate_result(self.modules.risk.analyze(state), state)
        with self.sessions() as db:
            begin_write(db)
            self.current_job(db, job_id, token)
            project = db.get(Project, pid)
            if not project or project.deleted_at or project.status != "active":
                raise AppError("project_unavailable", "项目已不可写")
            # 结果绑定输入快照；计算期间的后续修改有自己的检查 Job。
            if fingerprint(snapshot(db, pid)) != fingerprint(state):
                result.warnings.append("计算期间数据已变化；此结果是历史快照，请等待后续检查")
            db.add(
                AnalysisRun(
                    project_id=pid,
                    trigger_job_id=job_id,
                    snapshot_hash=fingerprint(state),
                    input_snapshot=state.model_dump(mode="json"),
                    **result.model_dump(mode="json"),
                    is_demo=self.modules.is_demo,
                )
            )
            db.commit()

    def ingest(self, job_id, token, pid, did):
        with self.sessions() as db:
            begin_write(db)
            self.current_job(db, job_id, token)
            doc = project_row(db, Document, pid, did)
            needs_parse = doc.parse_status != "ready"
            file = FileRef(
                project_id=pid,
                document_id=did,
                version=doc.version,
                path=storage_path(self.settings, doc.storage_key),
                filename=doc.filename,
                content_hash=doc.content_hash,
            )
            if needs_parse:
                doc.parse_status = "running"
            doc.index_status = "running"
            db.commit()
        if needs_parse:
            parsed = ParsedDocument.model_validate(self.modules.main_rag.parse(file))
            numbers = [b.block_no for b in parsed.blocks]
            if len(numbers) != len(set(numbers)):
                raise AppError("duplicate_blocks", "解析结果的段落编号重复")
            with self.sessions() as db:
                begin_write(db)
                self.current_job(db, job_id, token)
                doc = project_row(db, Document, pid, did)
                for block in parsed.blocks:
                    db.add(
                        DocumentBlock(
                            document_id=did, document_version=doc.version, **block.model_dump()
                        )
                    )
                doc.parse_status = "ready"
                db.commit()
        with self.sessions() as db:
            doc = project_row(db, Document, pid, did)
            reference = document_ref(db, doc)
        result = IngestResult.model_validate(self.modules.main_rag.ingest(reference))
        with self.sessions() as db:
            begin_write(db)
            self.current_job(db, job_id, token)
            doc = project_row(db, Document, pid, did)
            doc.index_status, doc.error_message = "ready", None
            doc.index_version, doc.chunk_count = result.index_version, result.chunk_count
            doc.created_by_demo = self.modules.is_demo
            db.commit()

    def workflow(self, job_id, token, pid, rid):
        with self.sessions() as db:
            begin_write(db)
            self.current_job(db, job_id, token)
            run = project_row(db, WorkflowRun, pid, rid)
            if run.status == "succeeded":
                return
            doc = project_row(db, Document, pid, run.document_id)
            reference, catalog, kind = document_ref(db, doc), entity_catalog(db, pid), run.kind
            actor = run.submitted_by
            if actor is not None:
                require_project(db, pid, actor, write=True)
            run.status, run.started_at = "running", utcnow()
            db.commit()
        tools = BoundTools(self.sessions, pid, actor, self.modules) if actor is not None else None
        # v1 的三个位置参数保持兼容；新适配器通过可选 tools 使用风险与业务读取。
        kwargs = (
            {"tools": tools}
            if "tools" in inspect.signature(self.modules.workflow.extract).parameters
            else {}
        )
        result = ExtractionResult.model_validate(
            self.modules.workflow.extract(reference, catalog, kind, **kwargs)
        )
        with self.sessions() as db:
            begin_write(db)
            self.current_job(db, job_id, token)
            project_row(db, Document, pid, reference.document_id)
            if actor is not None:
                require_project(db, pid, actor, write=True)
            # 候选也须验证；模型不能把范围外人员 / 任务带入待审列表。
            for draft in result.suggestions:
                validate_draft(db, pid, draft, document=reference)
            # 同 run 的结果一次性事务发布；重试已发布结果时不能重复插入。
            run = project_row(db, WorkflowRun, pid, rid)
            if run.status != "succeeded":
                for draft in result.suggestions:
                    save_draft(db, run, draft)
                run.response_data = {"risk_previews": tools.risk_previews if tools else []}
                run.status, run.finished_at = "succeeded", utcnow()
                run.model_id, run.prompt_version, run.summary = (
                    result.model_id,
                    result.prompt_version,
                    result.summary,
                )
            db.commit()


def main():
    parser = argparse.ArgumentParser(description="ProjectNexus 后台任务执行器")
    parser.add_argument("--once", action="store_true", help="最多执行一个 Job 后退出")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    engine = build_engine(settings.database_url)
    llm = build_llm(settings)
    worker = Worker(session_factory(engine), settings, build_modules(settings, llm))
    try:
        if args.once:
            worker.run_once()
        else:
            stop = threading.Event()
            while True:
                if not worker.run_once():
                    stop.wait(2)
    except KeyboardInterrupt:
        pass
    finally:
        llm.close()
        engine.dispose()


if __name__ == "__main__":
    main()
