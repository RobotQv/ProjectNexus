"""AI 工作流与轻 RAG 的实现。

- 轻 RAG（EntityAdapter）：实体索引的同步与语义定位，复用智谱 embedding-3 + Chroma。
- 工作流（WorkflowAdapter）：两个助手入口的意图理解、工具编排与文档抽取/摘要。

本模块只依赖 shared 与本目录，不导入 app、main_rag、risk 的实现。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import ValidationError

from shared.contracts import (
    AssistantRequest,
    AssistantResult,
    AssistantTools,
    Candidate,
    CandidateChange,
    DocumentRef,
    EntityRecord,
    Evidence,
    ExtractionResult,
    Resolution,
    Scope,
    SuggestionDraft,
    TaskSearch,
)
from shared.errors import AppError
from shared.llm import LLMProvider
from shared.progress import emit
from shared.structured import json_schemas

from .indexing.embedding import EMBEDDING_DIM, EMBEDDING_MODEL, ZhipuEmbedding
from .prompts import (
    ANSWER_SYSTEM,
    CLASSIFY_SYSTEM,
    EXTRACT_SYSTEM,
    PROMPT_VERSION,
    SUGGEST_INTENT_SYSTEM,
    SUGGEST_SYSTEM,
    SUMMARY_SYSTEM,
)

if TYPE_CHECKING:
    from .indexing.store import EntityStore

ENTITY_INDEX_VERSION = f"{EMBEDDING_MODEL}-{EMBEDDING_DIM}"

# 实体匹配的初步阈值：上线前须用开发集校准。score 是匹配相似度，不是“正确概率”。
MIN_MATCH_SCORE = 0.60
AMBIGUITY_MARGIN = 0.10
RESOLVE_POOL_MULTIPLIER = 3

# 长文分批与输出的本地预算（后端单次模型输入上限 60000 字符，输出上限 4096 tokens）。
BATCH_CHAR_BUDGET = 20000
MAX_SUGGESTIONS = 300


class EntityAdapter:
    """轻 RAG 实体索引：同步后端下发的任务/成员文本，语义定位返回候选。"""

    def __init__(self, *, api_key=None, base_url=None, store_dir=None):
        self._embedding = None
        self._store = None
        self._api_key, self._base_url, self._store_dir = api_key, base_url, store_dir

    @property
    def embedding(self) -> ZhipuEmbedding:
        if self._embedding is None:
            self._embedding = ZhipuEmbedding(api_key=self._api_key, base_url=self._base_url)
        return self._embedding

    @property
    def store(self) -> "EntityStore":
        if self._store is None:
            # 惰性导入：聊天编排（WorkflowAdapter）不依赖向量库，只有实体索引用到时才加载 chromadb。
            from .indexing.store import EntityStore

            self._store = EntityStore(self._store_dir)
        return self._store

    def sync(self, entity: EntityRecord) -> None:
        entity = entity if isinstance(entity, EntityRecord) else EntityRecord.model_validate(entity)
        key = f"{entity.project_id}:{entity.entity_type}:{entity.entity_id}"
        current = self.store.get_meta(key)
        if current and int(current.get("source_version", 0)) > entity.source_version:
            return
        if not entity.is_active:
            # 删除/移除：清理索引，幂等。
            self.store.delete_by_entity(entity.project_id, entity.entity_type, entity.entity_id)
            return
        # source_version 防止旧同步覆盖新索引；索引是派生数据，可整体重建。
        vector = self.embedding.embed([entity.search_text])[0]
        self.store.upsert(
            ids=[key],
            embeddings=[vector],
            documents=[entity.search_text],
            metadatas=[
                {
                    "project_id": entity.project_id,
                    "entity_type": entity.entity_type,
                    "entity_id": entity.entity_id,
                    "source_version": entity.source_version,
                    "index_version": ENTITY_INDEX_VERSION,
                }
            ],
        )

    def resolve(self, scope: Scope, text: str, entity_type: str, limit: int) -> Resolution:
        text = (text or "").strip()
        if not text:
            raise AppError("invalid_entity_query", "实体检索文本不能为空", 422)
        if entity_type not in {"task", "member"}:
            raise AppError("invalid_entity_type", "实体类型只支持 task 或 member", 422)
        if not 1 <= limit <= 50:
            raise AppError("invalid_limit", "limit 应在 1—50 之间", 422)

        query_vector = self.embedding.embed([text])[0]
        pool = min(limit * RESOLVE_POOL_MULTIPLIER, 50)
        result = self.store.query(query_vector, scope.project_id, entity_type, pool)

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        candidates: list[Candidate] = []
        for i, _id in enumerate(ids):
            meta = metadatas[i] or {}
            # Chroma 余弦距离：distance = 1 - 相似度，越小越像；转成“越大越像”的 score。
            score = 1.0 - float(distances[i]) if i < len(distances) else 0.0
            if score < MIN_MATCH_SCORE:
                continue
            candidates.append(
                Candidate(
                    entity_type=meta.get("entity_type", entity_type),
                    entity_id=int(meta.get("entity_id")),
                    # 索引只存 search_text（后端未单独下发标题）；权威名称由后端回查覆盖。
                    title=documents[i] if i < len(documents) else "",
                    score=round(score, 4),
                    match_reason=f"余弦相似度约 {score:.3f}",
                )
            )
        candidates.sort(key=lambda c: c.score or 0, reverse=True)
        if not candidates:
            return Resolution(
                outcome="not_found", candidates=[], index_version=ENTITY_INDEX_VERSION
            )
        if len(candidates) == 1 or (
            (candidates[0].score or 0) - (candidates[1].score or 0) >= AMBIGUITY_MARGIN
        ):
            outcome = "resolved"
            candidates = candidates[:1]
        else:
            outcome = "ambiguous"
        return Resolution(
            outcome=outcome, candidates=candidates[:limit], index_version=ENTITY_INDEX_VERSION
        )


class WorkflowAdapter:
    def __init__(self, llm: LLMProvider):
        # 独立测试传入假 Provider；完整联调由后端注入已配置的 GLM Provider。
        self.llm = llm

    # ------------------------------------------------------------------ respond
    def respond(self, request: AssistantRequest, tools: AssistantTools) -> AssistantResult:
        """两个入口共用：理解意图，调用只读工具取事实，返回回答或待审建议。"""
        text = request.text.strip()
        emit("interpreting")
        if self._classify_intent(text) == "suggest":
            return self._suggest(request, tools)
        return self._answer(request, tools)

    def _classify_intent(self, text: str) -> str:
        result = self.llm.complete(
            [
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user", "content": text},
            ],
            max_tokens=16,
        )
        word = result.content.strip().lower()
        return "suggest" if "suggest" in word else "query"

    def _classify_suggest_intent(self, text: str) -> str:
        """生成建议前的细分意图：create/update/dependency/risk/other，用于决定是否澄清歧义。"""
        result = self.llm.complete(
            [
                {"role": "system", "content": SUGGEST_INTENT_SYSTEM},
                {"role": "user", "content": text},
            ],
            max_tokens=16,
        )
        word = result.content.strip().lower()
        for label in ("create", "update", "dependency", "risk", "other"):
            if label in word:
                return label
        return "other"

    def _answer(self, request: AssistantRequest, tools: AssistantTools) -> AssistantResult:
        warnings: list[str] = []
        facts: dict = {"tasks": [], "documents": [], "entities": []}
        task_ids: list[int] = []
        evidence: list[Evidence] = []
        candidates: list[Candidate] = []

        try:
            tasks = tools.search_tasks(TaskSearch(keyword=request.text[:200], limit=10))
            task_ids = [t["id"] for t in tasks if isinstance(t, dict) and "id" in t]
            facts["tasks"] = tasks
        except AppError as exc:
            warnings.append(f"任务检索不可用：{exc.message}")

        try:
            refs = tools.retrieve(request.text, limit=5)
            evidence = [r for r in refs if isinstance(r, Evidence)]
            facts["documents"] = [r.model_dump(mode="json") for r in evidence]
        except AppError as exc:
            warnings.append(f"资料检索不可用：{exc.message}")

        resolution: Resolution | None = None
        try:
            resolution = tools.resolve(request.text, "task", 10)
            candidates = resolution.candidates
            facts["entities"] = [c.model_dump(mode="json") for c in candidates]
        except AppError as exc:
            warnings.append(f"实体定位不可用：{exc.message}")

        # 语义索引只用于定位，事实字段必须再次从业务库读取。
        if resolution is not None and resolution.outcome == "resolved" and resolution.candidates:
            try:
                rows = tools.search_tasks(TaskSearch(task_id=resolution.candidates[0].entity_id))
                known = {t["id"]: t for t in facts["tasks"]}
                known.update({t["id"]: t for t in rows})
                facts["tasks"] = list(known.values())
                task_ids = list(known)
            except AppError as exc:
                warnings.append(f"任务事实回查不可用：{exc.message}")

        if resolution is not None and resolution.outcome == "ambiguous" and not evidence:
            lines = "\n".join(
                f"- {c.title or f'ID {c.entity_id}'}（ID {c.entity_id}）" for c in candidates
            )
            return AssistantResult(
                answer=f"你的问题匹配到多个候选，请指明是哪一个：\n{lines}",
                outcome="clarify",
                candidates=candidates,
                warnings=warnings,
                model_id="",
                prompt_version=f"respond-clarify-{PROMPT_VERSION}",
            )

        # 项目快照：补充依赖与任务概览，回答“有哪些任务/依赖/阻塞风险”类问题。
        has_overview = False
        try:
            snapshot = tools.snapshot()
            facts["dependencies"] = [
                {
                    "predecessor_task_id": d.get("predecessor_task_id"),
                    "successor_task_id": d.get("successor_task_id"),
                    "predecessor_required_progress": d.get("predecessor_required_progress"),
                    "successor_gate": d.get("successor_gate"),
                    "successor_gate_progress": d.get("successor_gate_progress"),
                }
                for d in snapshot.dependencies
            ]
            facts["task_overview"] = [
                {
                    "task_id": t.get("id"),
                    "title": t.get("title"),
                    "status": t.get("status"),
                    "progress": t.get("progress"),
                }
                for t in snapshot.tasks
            ]
            has_overview = bool(snapshot.tasks or snapshot.dependencies)
        except AppError as exc:
            warnings.append(f"项目快照不可用：{exc.message}")

        emit("generating")
        result = self.llm.complete(
            [
                {"role": "system", "content": ANSWER_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"问题": request.text, "事实": facts}, ensure_ascii=False
                    ),
                },
            ],
            max_tokens=1000,
        )
        has_facts = bool(task_ids or evidence or candidates or has_overview)
        outcome = "insufficient" if not has_facts else ("partial" if warnings else "answered")
        return AssistantResult(
            answer=result.content.strip(),
            outcome=outcome,
            task_ids=task_ids,
            evidence=evidence,
            candidates=candidates,
            warnings=warnings,
            model_id=result.model,
            prompt_version=f"respond-answer-{PROMPT_VERSION}",
        )

    def _suggest(self, request: AssistantRequest, tools: AssistantTools) -> AssistantResult:
        warnings: list[str] = []
        tasks_hint: list[dict] = []
        deps_hint: list[dict] = []
        members_hint: list[dict] = []
        candidates: list[Candidate] = []

        # 先判断这次“生成建议”要动什么，决定是否需要澄清已有任务歧义。
        intent = self._classify_suggest_intent(request.text)

        try:
            snapshot = tools.snapshot()
            for t in snapshot.tasks:
                tasks_hint.append(
                    {
                        "task_id": t.get("id"),
                        "title": t.get("title"),
                        "status": t.get("status"),
                        "version": t.get("version"),
                        "assignee_id": t.get("assignee_id"),
                    }
                )
            for d in snapshot.dependencies:
                deps_hint.append(
                    {
                        "predecessor_task_id": d.get("predecessor_task_id"),
                        "successor_task_id": d.get("successor_task_id"),
                        "predecessor_required_progress": d.get("predecessor_required_progress"),
                        "successor_gate": d.get("successor_gate"),
                        "successor_gate_progress": d.get("successor_gate_progress"),
                    }
                )
        except AppError as exc:
            warnings.append(f"项目快照不可用：{exc.message}")

        try:
            for e in tools.entity_catalog():
                if e.entity_type == "member":
                    members_hint.append(
                        {"member_id": e.entity_id, "search_text": e.search_text[:80]}
                    )
        except AppError as exc:
            warnings.append(f"成员目录不可用：{exc.message}")

        resolution: Resolution | None = None
        try:
            resolution = tools.resolve(request.text, "task", 10)
            candidates = resolution.candidates
        except AppError as exc:
            warnings.append(f"实体定位不可用：{exc.message}")

        # 更新/依赖/风险都要引用已有任务 ID；名字有歧义时不能猜，先让用户指明。
        if (
            resolution is not None
            and resolution.outcome == "ambiguous"
            and intent in {"update", "dependency", "risk"}
        ):
            lines = "\n".join(
                f"- {c.title or f'ID {c.entity_id}'}（ID {c.entity_id}）" for c in candidates
            )
            return AssistantResult(
                answer=f"你提到的任务有多个候选，请指明是哪一个：\n{lines}",
                outcome="clarify",
                candidates=candidates,
                warnings=warnings,
                model_id="",
                prompt_version=f"respond-suggest-clarify-{PROMPT_VERSION}",
            )

        context = {
            "任务": tasks_hint,
            "依赖": deps_hint,
            "成员": members_hint,
            "实体候选": [c.model_dump(mode="json") for c in candidates],
            "schema": json_schemas()["suggestion"],
        }
        emit("generating")
        result = self.llm.complete(
            [
                {"role": "system", "content": SUGGEST_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"用户输入": request.text, "项目数据": context}, ensure_ascii=False
                    ),
                },
            ],
            max_tokens=4096,
        )
        suggestions = self._parse_suggestions(result.content, warnings)
        warnings += self._preview_dependency_risk(suggestions, tools)
        return AssistantResult(
            answer=f"已生成 {len(suggestions)} 条任务建议，请核对后提交审核。",
            outcome="answered",
            suggestions=suggestions,
            candidates=candidates,
            warnings=warnings,
            model_id=result.model,
            prompt_version=f"respond-suggest-{PROMPT_VERSION}",
        )

    # ------------------------------------------------------------------ extract
    def extract(
        self,
        document: DocumentRef,
        entity_catalog: list[EntityRecord],
        kind: str,
        *,
        tools: AssistantTools | None = None,
    ) -> ExtractionResult:
        if kind == "summary":
            return self._summarize(document)
        if kind == "extract":
            return self._extract(document, entity_catalog, tools)
        raise AppError("invalid_kind", "kind 只支持 extract 或 summary", 422)

    def _summarize(self, document: DocumentRef) -> ExtractionResult:
        if not document.blocks:
            raise AppError("empty_document", "文档没有可摘要的正文", 422)
        parts: list[str] = []
        last = None
        for batch in self._iter_batches(document.blocks):
            batch_text = "\n".join(b.text for b in batch)
            result = self.llm.complete(
                [
                    {"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user", "content": batch_text},
                ],
                max_tokens=1200,
            )
            parts.append(result.content.strip())
            last = result
        if len(parts) == 1:
            summary = parts[0]
        else:
            merge = self.llm.complete(
                [
                    {"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user", "content": "\n\n".join(parts)},
                ],
                max_tokens=1200,
            )
            summary = merge.content.strip()
            last = merge
        return ExtractionResult(
            suggestions=[],
            summary=summary,
            model_id=last.model if last else "",
            prompt_version=f"summary-{PROMPT_VERSION}",
        )

    def _extract(
        self,
        document: DocumentRef,
        entity_catalog: list[EntityRecord],
        tools: AssistantTools | None = None,
    ) -> ExtractionResult:
        if not document.blocks:
            raise AppError("empty_document", "文档没有可抽取的正文", 422)
        entity_hints = [
            {
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "source_version": e.source_version,
                "search_text": e.search_text[:120],
            }
            for e in entity_catalog
        ]
        raw: list[tuple[list[int], SuggestionDraft]] = []
        last = None
        for batch in self._iter_batches(document.blocks):
            batch_ids = [b.id for b in batch]
            numbered = "\n".join(f"[{b.id}] {b.text}" for b in batch)
            result = self.llm.complete(
                [
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "文档名": document.filename,
                                "文档日期": (
                                    document.document_date.isoformat()
                                    if document.document_date
                                    else None
                                ),
                                "正文块编号": batch_ids,
                                "正文": numbered,
                                "已有实体": entity_hints,
                                "schema": json_schemas()["suggestion"],
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=4096,
            )
            # 单批输出整体不可用会在此抛出；个别不合法条目被丢弃（见 _parse_suggestions）。
            parsed = self._parse_suggestions(result.content, None, allow_empty=True)
            raw.extend((batch_ids, s) for s in parsed)
            last = result
        suggestions = self._merge_suggestions(document, raw)
        self._attach_entity_candidates(suggestions, entity_catalog)
        if tools is not None:
            for note in self._preview_dependency_risk(suggestions, tools):
                for s in suggestions:
                    if s.suggestion_type in {"propose_dependency", "update_task"}:
                        s.validation_warnings.append(note)
        return ExtractionResult(
            suggestions=suggestions,
            summary=None,
            model_id=last.model if last else "",
            prompt_version=f"extract-{PROMPT_VERSION}",
        )

    # -------------------------------------------------------------- shared utils
    def _parse_suggestions(
        self, content: str, warnings: list[str] | None, *, allow_empty: bool = False
    ) -> list[SuggestionDraft]:
        data = _extract_json(content)
        if isinstance(data, dict):
            if "suggestions" in data:
                data = data["suggestions"]
            elif "suggestion_type" in data:
                data = [data]
        if not isinstance(data, list):
            raise AppError("model_json_invalid", "模型输出不是建议列表", 502)
        suggestions: list[SuggestionDraft] = []
        for item in data:
            try:
                suggestions.append(SuggestionDraft.model_validate(item))
            except ValidationError as exc:
                # 个别坏条目跳过并记录；全部不可用则整体失败，不静默吞错。
                if warnings is not None:
                    warnings.append(f"跳过一条不合法建议：{exc.errors()[:1]}")
        if not suggestions:
            if allow_empty and not data:
                return []  # 明确返回空数组：正文无可提取内容，属合法空结果
            raise AppError("model_json_invalid", "模型返回的建议全部不合法", 502)
        return suggestions

    def _merge_suggestions(
        self, document: DocumentRef, raw: list[tuple[list[int], SuggestionDraft]]
    ) -> list[SuggestionDraft]:
        """用真实正文块重建 Evidence，去掉无来源建议，去重并封顶。"""
        by_id = {b.id: b.text for b in document.blocks}

        def sanitize(sugg: SuggestionDraft) -> SuggestionDraft | None:
            refs: list[Evidence] = []
            for ref in sugg.source_refs:
                valid_ids: list[int] = []
                for i in ref.block_ids:
                    if i in by_id and i not in valid_ids:
                        valid_ids.append(i)
                if not valid_ids:
                    continue
                valid_ids = valid_ids[:20]
                joined = "\n".join(by_id[i] for i in valid_ids)
                # 模型给出的 quote 若不在原文里，就用真实原文兜底，不伪造来源。
                quote = ref.quote if (ref.quote and ref.quote in joined) else joined
                quote = quote[:8000]
                if not quote:
                    continue
                refs.append(
                    Evidence(
                        document_id=document.document_id,
                        version=document.version,
                        block_ids=valid_ids,
                        quote=quote,
                    )
                )
            if not refs:
                return None
            return sugg.model_copy(update={"source_refs": refs})

        merged: list[SuggestionDraft] = []
        seen: set = set()
        for _batch_ids, sugg in raw:
            s = sanitize(sugg)
            if s is None:
                continue
            key = _suggestion_key(s)
            if key in seen:
                continue
            seen.add(key)
            merged.append(s)
        return merged[:MAX_SUGGESTIONS]

    # ------------------------------------------------------------------ risk
    @staticmethod
    def _build_changes(suggestions: list[SuggestionDraft]) -> list[CandidateChange]:
        """风险预览只关心任务/依赖图的变化；风险条目本身不改变依赖图。"""
        changes: list[CandidateChange] = []
        for i, s in enumerate(suggestions, 1):
            if s.suggestion_type in {"create_task", "update_task", "propose_dependency"}:
                changes.append(CandidateChange(key=f"c{i}", suggestion=s))
        return changes

    def _preview_dependency_risk(
        self, suggestions: list[SuggestionDraft], tools: AssistantTools
    ) -> list[str]:
        """有任务变更或依赖建议时，调风险模块预览阻塞风险；结果由后端存入运行记录。

        返回空列表表示无需预览或预览成功；失败返回一条可读提示，不能伪装成“已检查”。
        """
        if not any(s.suggestion_type in {"propose_dependency", "update_task"} for s in suggestions):
            return []
        changes = self._build_changes(suggestions)
        if not changes:
            return []
        try:
            result = tools.preview_risk(changes)
        except AppError as exc:
            return [f"候选依赖风险预览不可用：{exc.message}"]
        if result is None:  # 兼容组员的离线假工具；真实后端总是返回 AnalysisResult。
            return []
        return list(result.warnings) + [
            f.explanation
            for f in result.findings
            if f.dependency_status not in {None, "satisfied"}
            or f.timing_status in {"future_risk", "timing_unknown"}
            or "TASK_OVERDUE" in f.reason_codes
            or "FORECAST_AFTER_DEADLINE" in f.reason_codes
        ]

    @staticmethod
    def _attach_entity_candidates(
        suggestions: list[SuggestionDraft], entity_catalog: list[EntityRecord]
    ) -> None:
        """把 payload 引用的正式 ID（负责人/任务/依赖两端/风险关联）回填成候选。

        仅当模型没给 entity_candidates 时才回填；权威名称由后端回查覆盖，这里用 search_text 占位。
        """
        by_key = {(e.entity_type, e.entity_id): e for e in entity_catalog}

        def add(refs: list[Candidate], entity_type: str, entity_id) -> None:
            if not entity_id:
                return
            rec = by_key.get((entity_type, entity_id))
            if rec is None:
                return
            refs.append(
                Candidate(
                    entity_type=rec.entity_type,
                    entity_id=rec.entity_id,
                    title=rec.search_text[:80],
                    match_reason="引用实体目录",
                )
            )

        for s in suggestions:
            if s.entity_candidates:
                continue
            p = s.proposed_payload
            refs: list[Candidate] = []
            if s.suggestion_type == "create_task":
                add(refs, "member", p.get("assignee_id"))
            elif s.suggestion_type == "update_task":
                add(refs, "task", p.get("task_id"))
            elif s.suggestion_type == "propose_dependency":
                add(refs, "task", p.get("predecessor_task_id"))
                add(refs, "task", p.get("successor_task_id"))
            elif s.suggestion_type == "create_risk":
                add(refs, "task", p.get("related_task_id"))
            if refs:
                s.entity_candidates = refs

    @staticmethod
    def _iter_batches(blocks, budget: int = BATCH_CHAR_BUDGET):
        current: list = []
        size = 0
        for b in blocks:
            if current and size + len(b.text) + 1 > budget:
                yield current
                current, size = [], 0
            current.append(b)
            size += len(b.text) + 1
        if current:
            yield current


def _suggestion_key(sugg: SuggestionDraft) -> tuple:
    p = sugg.proposed_payload
    if sugg.suggestion_type == "create_task":
        return ("create_task", (p.get("title") or "").strip())
    if sugg.suggestion_type == "update_task":
        return (
            "update_task",
            p.get("task_id"),
            p.get("expected_version"),
            json.dumps(p.get("changes"), ensure_ascii=False, sort_keys=True),
        )
    return (sugg.suggestion_type, json.dumps(p, ensure_ascii=False, sort_keys=True))


def _extract_json(content: str):
    """解析模型输出：容忍 ```json 围栏，失败时截取首个配对片段，仍失败则报可读错误。"""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise AppError("model_json_parse_failed", "模型输出不是可解析的 JSON", 502)
