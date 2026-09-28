"""disabled 默认不假装处理成功；demo 仅供联调，绝不视为算法交付。"""

import importlib

from app.core.errors import AppError
from app.integrations.contracts import (
    AnalysisResult,
    Evidence,
    ExtractionResult,
    IngestResult,
    Modules,
    ParsedBlock,
    ParsedDocument,
    Resolution,
    SuggestionDraft,
)


class Unavailable:
    def __getattr__(self, name):
        def missing(*args, **kwargs):
            raise AppError("module_unavailable", "对应算法模块尚未接入；请联系模块负责人", 503)

        return missing


class DemoAdapter:
    """无向量库、无模型调用。检索返回空；演示抽取首段生成一条明确标记的建议。"""

    def parse(self, file):
        if file.path.suffix.lower() not in {".txt", ".md"}:
            raise AppError(
                "demo_format_unsupported",
                "demo 仅解析 UTF-8 TXT/Markdown；DOCX/PDF 等待主 RAG 接入",
            )
        try:
            text = file.path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            raise AppError("invalid_encoding", "demo 仅支持 UTF-8 文本") from None
        blocks = [
            ParsedBlock(block_no=i, text=t.strip(), locator=f"paragraph:{i}")
            for i, t in enumerate(text.split("\n\n"))
            if t.strip()
        ]
        if not blocks:
            raise AppError("empty_document", "文件没有可解析正文")
        return ParsedDocument(blocks=blocks)

    def ingest(self, document):
        return IngestResult(index_version="demo-no-vector-index", chunk_count=0)

    def retrieve(self, scope, question, limit):
        return []

    def delete(self, scope, document_id, version):
        pass

    def sync(self, entity):
        pass

    def resolve(self, scope, text, entity_type, limit):
        return Resolution(outcome="not_found", index_version="demo-no-entity-index")

    def respond(self, request, tools):
        from shared.contracts import AssistantResult

        return AssistantResult(
            answer="[DEMO] 以下是固定联调建议，不是语义识别结果；请先核对再提交正式审核。",
            suggestions=[
                SuggestionDraft(
                    suggestion_type="create_task",
                    proposed_payload={
                        "title": "[DEMO] 请修改此对话任务",
                        "description": request.text,
                    },
                    validation_warnings=["固定示例，不是模型提取结果"],
                )
            ],
            model_id="demo-no-llm",
            prompt_version="demo-v2",
        )

    def analyze_candidates(self, preview):
        return self.analyze(preview.snapshot)

    def extract(self, document, entity_catalog, kind, *, tools=None):
        block = document.blocks[0]
        return ExtractionResult(
            suggestions=[]
            if kind == "summary"
            else [
                SuggestionDraft(
                    suggestion_type="create_task",
                    proposed_payload={"title": "[DEMO] 请人工编辑此联调任务"},
                    source_refs=[
                        Evidence(
                            document_id=document.document_id,
                            version=document.version,
                            block_ids=[block.id],
                            quote=block.text[:200],
                        )
                    ],
                    validation_warnings=["固定示例，不是模型提取结果"],
                )
            ],
            summary="[DEMO] 摘要模块尚未接入" if kind == "summary" else None,
            model_id="demo-no-llm",
            prompt_version="demo-v1",
        )

    def analyze(self, snapshot):
        return AnalysisResult(
            rule_version="demo-no-rules",
            findings=[],
            warnings=["仅返回接口示例，未执行风险规则，不能解读为无风险"],
        )


def build_modules(settings, llm):
    if settings.module_factory:
        module, name = settings.module_factory.split(":", 1)
        result = getattr(importlib.import_module(module), name)(settings=settings, llm=llm)
        if not isinstance(result, Modules):
            raise TypeError("MODULE_FACTORY 必须返回 Modules")
        if settings.environment == "production" and result.is_demo:
            raise ValueError("生产环境不能加载 demo 模块工厂")
        return result
    adapter = DemoAdapter() if settings.module_mode == "demo" else Unavailable()
    return Modules(adapter, adapter, adapter, adapter, settings.module_mode == "demo")
