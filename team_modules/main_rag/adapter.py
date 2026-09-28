"""主 RAG：保留原文锚点，支持可回退的分块与三种检索策略。"""

import hashlib
import json
from pathlib import Path

from shared.contracts import DocumentRef, Evidence, FileRef, IngestResult, ParsedDocument, Scope
from shared.errors import AppError
from shared.progress import emit

from .chunking import chunk_document, cosine
from .indexing.embedding import EMBEDDING_DIM, EMBEDDING_MODEL, ZhipuEmbedding
from .parsing.docx import parse_docx
from .parsing.markdown import parse_markdown
from .parsing.pdf import parse_pdf
from .parsing.txt import parse_txt
from .retrieval import bm25, rrf

INDEX_VERSION = f"{EMBEDDING_MODEL}-{EMBEDDING_DIM}"


class MainRAGAdapter:
    def __init__(
        self,
        *,
        api_key=None,
        base_url=None,
        store_dir: Path | None = None,
        retrieval_mode="vector",
        chunk_strategy="baseline",
        candidate_limit=20,
    ):
        if retrieval_mode not in {"vector", "bm25", "hybrid_rrf"}:
            raise ValueError("unknown retrieval mode")
        self._embedding = self._store = None
        self._api_key, self._base_url, self._store_dir = api_key, base_url, store_dir
        self.retrieval_mode, self.chunk_strategy = retrieval_mode, chunk_strategy
        self.candidate_limit = candidate_limit
        self.index_version = (
            INDEX_VERSION
            if chunk_strategy == "baseline"
            else (f"{INDEX_VERSION}-{chunk_strategy}-v1-1200-300-100-055")
        )

    @property
    def embedding(self):
        if self._embedding is None:
            self._embedding = ZhipuEmbedding(api_key=self._api_key, base_url=self._base_url)
        return self._embedding

    @property
    def store(self):
        if self._store is None:
            from .indexing.store import VectorStore

            name = (
                "main_rag_blocks"
                if self.chunk_strategy == "baseline"
                else ("main_rag_" + hashlib.sha256(self.index_version.encode()).hexdigest()[:16])
            )
            self._store = VectorStore(self._store_dir, collection_name=name)
        return self._store

    def parse(self, file: FileRef) -> ParsedDocument:
        parser = {
            ".txt": parse_txt,
            ".md": parse_markdown,
            ".markdown": parse_markdown,
            ".docx": parse_docx,
            ".pdf": parse_pdf,
        }.get(file.path.suffix.lower())
        if parser is None:
            raise AppError("unsupported_format", "暂不支持的文件格式", 422)
        return parser(file)

    def ingest(self, document: DocumentRef) -> IngestResult:
        if not document.blocks:
            raise AppError("empty_document", "文档没有可索引的正文块", 422)
        chunks, _trace = chunk_document(
            document.blocks,
            strategy=self.chunk_strategy,
            embedding=self.embedding if self.chunk_strategy == "semantic" else None,
        )
        texts = [chunk.text for chunk in chunks]
        ids = [
            f"{document.document_id}:{document.version}:{chunk.spans[0]['block_id'] if self.chunk_strategy == 'baseline' else i}"
            for i, chunk in enumerate(chunks)
        ]
        metas = [
            {
                "project_id": document.project_id,
                "document_id": document.document_id,
                "version": document.version,
                "block_id": chunk.spans[0]["block_id"],
                "block_no": chunk.spans[0]["block_no"],
                "index_version": self.index_version,
                "source_spans": json.dumps(chunk.spans, ensure_ascii=False),
            }
            for chunk in chunks
        ]
        # 大文档分批嵌入和写库，避免一份手册耗尽单请求/Chroma 的批量预算。
        for start in range(0, len(chunks), 16):
            end = start + 16
            vectors = self.embedding.embed(texts[start:end])
            self.store.upsert(
                ids=ids[start:end],
                embeddings=vectors,
                documents=texts[start:end],
                metadatas=metas[start:end],
            )
        return IngestResult(index_version=self.index_version, chunk_count=len(chunks))

    def retrieve_ranked(self, scope, question, limit=5, *, mode=None):
        """评估入口返回每个 chunk 的排名和锚点；业务入口仍返回 Evidence[]。"""
        if not question.strip():
            raise AppError("invalid_question", "问题不能为空", 422)
        if limit <= 0:
            raise AppError("invalid_limit", "limit 必须大于 0", 422)
        mode = mode or self.retrieval_mode
        if mode not in {"vector", "bm25", "hybrid_rrf"}:
            raise ValueError("unknown retrieval mode")
        data = self.store.snapshot(scope.project_id)
        rows = []
        for i, key in enumerate(data["ids"]):
            meta = data["metadatas"][i]
            if meta.get("index_version") != self.index_version:
                continue
            rows.append(
                {
                    "chunk_id": key,
                    "text": data["documents"][i],
                    "meta": meta,
                    "vector": data["embeddings"][i],
                }
            )
        if not rows:
            return []
        # 两条召回从同一次持久化快照评分，避免删除/重建期间两份语料不一致。
        lexical = bm25(question, [r["text"] for r in rows]) if mode != "vector" else [0] * len(rows)
        semantic = [0] * len(rows)
        if mode != "bm25":
            query = self.embedding.embed([question])[0]
            semantic = [cosine(query, row["vector"]) for row in rows]
        pool = max(limit, self.candidate_limit)
        vrank = sorted(range(len(rows)), key=lambda i: (-semantic[i], rows[i]["chunk_id"]))[:pool]
        brank = sorted(
            (i for i in range(len(rows)) if lexical[i] > 0),
            key=lambda i: (-lexical[i], rows[i]["chunk_id"]),
        )[:pool]
        if mode == "hybrid_rrf":
            emit("fusing")
        scores = (
            rrf([vrank, brank])
            if mode == "hybrid_rrf"
            else (
                {i: semantic[i] for i in vrank}
                if mode == "vector"
                else {i: lexical[i] for i in brank}
            )
        )
        ordered = sorted(scores, key=lambda i: (-scores[i], rows[i]["chunk_id"]))[:limit]
        result = []
        for rank, i in enumerate(ordered, 1):
            row, meta = rows[i], rows[i]["meta"]
            spans = (
                json.loads(meta["source_spans"])
                if "source_spans" in meta
                else [{"block_id": meta["block_id"], "start": 0, "end": len(row["text"])}]
            )
            result.append(
                {
                    "rank": rank,
                    "chunk_id": row["chunk_id"],
                    "score": scores[i],
                    "vector_rank": vrank.index(i) + 1 if mode != "bm25" and i in vrank else None,
                    "bm25_rank": brank.index(i) + 1 if mode != "vector" and i in brank else None,
                    "document_id": meta["document_id"],
                    "version": meta["version"],
                    "source_spans": spans,
                    "quote": row["text"][:8000],
                    "index_version": self.index_version,
                    "mode": mode,
                }
            )
        return result

    def retrieve(self, scope: Scope, question: str, limit: int) -> list[Evidence]:
        # 非连续摘录分别返回；禁止把不相邻片段拼成原文中不存在的 quote。
        return [
            Evidence(
                document_id=r["document_id"],
                version=r["version"],
                block_ids=list(dict.fromkeys(s["block_id"] for s in r["source_spans"])),
                quote=r["quote"],
            )
            for r in self.retrieve_ranked(scope, question, limit)
        ]

    def delete(self, scope: Scope, document_id: int, version: int) -> None:
        self.store.delete_by_document(
            project_id=scope.project_id, document_id=document_id, version=version
        )
