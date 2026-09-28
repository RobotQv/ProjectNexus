"""工作流的只读工具适配器：每次重新校验项目权限，不向模块暴露 Session。"""

from app.core.errors import AppError
from app.models import Task
from app.services.common import project_row, public, require_project, task_query
from app.services.documents import validate_evidence
from app.services.entities import entity_catalog
from app.services.risk import snapshot, validate_result
from app.services.suggestions import validate_draft
from shared.contracts import CandidateChange, Resolution, RiskPreview, Scope, TaskSearch


class BoundTools:
    def __init__(self, sessions, pid, actor, modules):
        self._sessions, self._pid, self._actor, self._modules = sessions, pid, actor, modules
        self._calls = 0
        self.fact_versions = {}
        self.risk_previews = []

    def _authorize(self, db):
        self._calls += 1
        if self._calls > 30:
            raise AppError("tool_budget_exceeded", "单次助手工具调用次数超过上限", 422)
        return require_project(db, self._pid, self._actor)

    def search_tasks(self, query):
        query = TaskSearch.model_validate(query)
        with self._sessions() as db:
            self._authorize(db)
            q = task_query(self._pid)
            if query.task_id is not None:
                project_row(db, Task, self._pid, query.task_id)
                q = q.where(Task.id == query.task_id)
            if query.status:
                q = q.where(Task.status == query.status)
            if query.assignee_id is not None:
                q = q.where(Task.assignee_id == query.assignee_id)
            if query.keyword:
                q = q.where(Task.title.contains(query.keyword, autoescape=True))
            rows = list(db.scalars(q.order_by(Task.id).offset(query.offset).limit(query.limit)))
            self.fact_versions.update({t.id: t.version for t in rows})
            return [public(t) for t in rows]

    def entity_catalog(self):
        with self._sessions() as db:
            self._authorize(db)
            return entity_catalog(db, self._pid)

    def snapshot(self):
        with self._sessions() as db:
            self._authorize(db)
            return snapshot(db, self._pid)

    def resolve(self, text, entity_type="task", limit=10):
        if (
            not isinstance(text, str)
            or not 1 <= len(text) <= 4000
            or entity_type not in {"task", "member"}
            or not 1 <= limit <= 50
        ):
            raise AppError("invalid_tool_input", "实体检索参数不合法")
        with self._sessions() as db:
            self._authorize(db)
        result = Resolution.model_validate(
            self._modules.entities.resolve(Scope(project_id=self._pid), text, entity_type, limit)
        )
        with self._sessions() as db:
            self._authorize(db)
            # 重用候选范围过滤和可信名称回查，不接受跨项目实体。
            from app.services.suggestions import validate_draft

            draft = validate_draft(
                db,
                self._pid,
                {
                    "suggestion_type": "create_task",
                    "proposed_payload": {},
                    "entity_candidates": [
                        c.model_dump() for c in result.candidates if c.entity_type == entity_type
                    ],
                },
            )
            result.candidates = draft.entity_candidates[:limit]
            result.outcome = (
                "not_found"
                if not result.candidates
                else "ambiguous"
                if len(result.candidates) > 1
                else result.outcome
            )
            return result

    def retrieve(self, question, limit=5):
        if not isinstance(question, str) or not 1 <= len(question) <= 4000 or not 1 <= limit <= 20:
            raise AppError("invalid_tool_input", "资料检索参数不合法")
        with self._sessions() as db:
            self._authorize(db)
        raw = self._modules.main_rag.retrieve(Scope(project_id=self._pid), question, limit)
        if not isinstance(raw, list):
            raise AppError("module_contract_invalid", "检索输出必须是引用列表", 502)
        with self._sessions() as db:
            self._authorize(db)
            return [validate_evidence(db, self._pid, ref) for ref in raw[:limit]]

    def preview_risk(self, changes):
        changes = [CandidateChange.model_validate(c) for c in changes]
        with self._sessions() as db:
            self._authorize(db)
            for c in changes:
                c.suggestion = validate_draft(db, self._pid, c.suggestion)
            state = snapshot(db, self._pid)
            preview = RiskPreview(snapshot=state, changes=changes)
        result = validate_result(
            self._modules.risk.analyze_candidates(preview), state, [c.key for c in changes]
        )
        with self._sessions() as db:
            self._authorize(db)
            if snapshot(db, self._pid).model_dump() != state.model_dump():
                result.warnings.append("分析期间项目数据已变化，候选风险仅供参考，请重新检查")
        self.risk_previews.append(
            {"input": preview.model_dump(mode="json"), "result": result.model_dump(mode="json")}
        )
        return result
