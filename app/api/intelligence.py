from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import or_, select

from app.api.deps import DB, Actor, write_scope
from app.models import AnalysisRun, AuditEvent, Job, QueryRun, Suggestion, WorkflowRun
from app.responses import (
    AnalysisOut,
    AssistantOut,
    AssistantProgressOut,
    Page,
    QueryOut,
    SuggestionOut,
)
from app.schemas import Analyze, AssistantStart, Review, SuggestionEdit, SuggestionSubmit
from app.schemas import Query as QueryInput
from app.services.assistant import assistant_response, respond
from app.services.common import project_row, public, require_project
from app.services.progress import progress_response
from app.services.queries import evaluate, query
from app.services.reviews import (
    edit_suggestion,
    review_suggestion,
    submit_suggestion,
    visible_suggestion,
)
from app.services.risk import fingerprint, snapshot
from app.services.tools import BoundTools
from shared.contracts import AnalysisResult, CandidateChange

router = APIRouter(prefix="/projects/{pid}", tags=["查询、建议审核与分析"])


@router.post("/queries", response_model=QueryOut)
def ask(pid: int, data: QueryInput, request: Request, db: DB, actor: Actor):
    result = query(db, pid, actor, data, request.app.state.modules, request.app.state.llm)
    return result | {"request_id": request.state.request_id}


@router.get("/queries/{query_id}")
def get_query(pid: int, query_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    return public(project_row(db, QueryRun, pid, query_id))


@router.post("/analysis", response_model=AnalysisOut)
def analyze(pid: int, data: Analyze, request: Request, db: DB, actor: Actor):
    return evaluate(db, pid, actor, request.app.state.modules, data.evaluation_date)


@router.get("/analysis/{run_id}", response_model=AnalysisOut)
def get_analysis(pid: int, run_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    return public(project_row(db, AnalysisRun, pid, run_id))


@router.get("/suggestions", response_model=Page[SuggestionOut])
def list_suggestions(
    pid: int,
    db: DB,
    actor: Actor,
    status: Literal["draft", "pending", "approved", "rejected"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    require_project(db, pid, actor)
    return {
        "items": [
            public(s)
            for s in db.scalars(
                select(Suggestion)
                .where(Suggestion.project_id == pid)
                .where(or_(Suggestion.review_status != "draft", Suggestion.submitted_by == actor))
                .where(Suggestion.review_status == status if status else True)
                .order_by(Suggestion.id)
                .offset(offset)
                .limit(limit)
            )
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/suggestions/{suggestion_id}", response_model=SuggestionOut)
def get_suggestion(pid: int, suggestion_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    return public(visible_suggestion(db, pid, actor, suggestion_id))


@router.patch("/suggestions/{suggestion_id}", response_model=SuggestionOut)
def edit(pid: int, suggestion_id: int, data: SuggestionEdit, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = edit_suggestion(db, pid, actor, suggestion_id, data)
    db.commit()
    return public(row)


@router.post("/suggestions/{suggestion_id}/submit", response_model=SuggestionOut)
def submit(pid: int, suggestion_id: int, data: SuggestionSubmit, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    row = submit_suggestion(db, pid, actor, suggestion_id, data)
    db.commit()
    return public(row)


@router.get("/suggestions/{suggestion_id}/source")
def suggestion_source(pid: int, suggestion_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    row = visible_suggestion(db, pid, actor, suggestion_id)
    run = project_row(db, WorkflowRun, pid, row.run_id)
    from app.models import Document
    from app.services.documents import get_blocks, validate_evidence

    sources = []
    for raw in row.source_refs:
        ref = validate_evidence(db, pid, raw, require_index=False)
        doc = project_row(db, Document, pid, ref.document_id)
        sources.append(
            {
                "document_id": doc.id,
                "version": ref.version,
                "filename": doc.filename,
                "quote": ref.quote,
                "blocks": [
                    b.model_dump(mode="json") for b in get_blocks(db, doc) if b.id in ref.block_ids
                ],
            }
        )
    return {
        "source_kind": row.source_kind,
        "submitted_by": row.submitted_by,
        "created_at": row.created_at,
        "submitted_at": row.submitted_at,
        "input_text": run.input_text,
        "documents": sources,
    }


@router.post("/assistant/messages", response_model=AssistantOut)
def assistant_message(pid: int, data: AssistantStart, request: Request, db: DB, actor: Actor):
    return respond(db, pid, actor, data, request.app.state.sessions, request.app.state.modules)


@router.get("/assistant/runs/{run_id}", response_model=AssistantOut)
def assistant_run(pid: int, run_id: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    return assistant_response(db, project_row(db, WorkflowRun, pid, run_id), actor)


@router.get("/assistant/progress", response_model=AssistantProgressOut)
def assistant_progress(
    pid: int, db: DB, actor: Actor, request_key: str = Query(min_length=1, max_length=64)
):
    """仅提交者可轮询；通过 request_key 查询，不会再次触发模型生成。"""
    return progress_response(db, pid, actor, request_key)


@router.post("/analysis/preview", response_model=AnalysisResult)
def preview(pid: int, changes: list[CandidateChange], request: Request, db: DB, actor: Actor):
    require_project(db, pid, actor)
    db.rollback()
    return BoundTools(
        request.app.state.sessions, pid, actor, request.app.state.modules
    ).preview_risk(changes)


@router.get("/risk-status")
def risk_status(pid: int, db: DB, actor: Actor):
    require_project(db, pid, actor)
    job = db.scalar(
        select(Job)
        .where(Job.project_id == pid, Job.kind == "risk_analysis")
        .order_by(Job.id.desc())
        .limit(1)
    )
    run = db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.project_id == pid)
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    )
    return {
        "job": public(job) if job else None,
        "analysis": public(run) if run else None,
        "is_stale": run is None or run.snapshot_hash != fingerprint(snapshot(db, pid)),
        "notice": "仅标记和提示；未运行或失败不能解释为无风险",
    }


@router.post("/suggestions/{suggestion_id}/review", response_model=SuggestionOut)
def review(pid: int, suggestion_id: int, data: Review, db: DB, actor: Actor):
    write_scope(db, pid, actor)
    suggestion = review_suggestion(db, pid, actor, suggestion_id, data)
    db.commit()
    return public(suggestion)


@router.get("/audit-events")
def list_events(
    pid: int,
    db: DB,
    actor: Actor,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    require_project(db, pid, actor, owner=True)
    return {
        "items": [
            public(e)
            for e in db.scalars(
                select(AuditEvent)
                .where(AuditEvent.project_id == pid)
                .order_by(AuditEvent.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ],
        "limit": limit,
        "offset": offset,
    }
