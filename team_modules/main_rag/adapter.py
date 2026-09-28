"""主 RAG：解析正文、建立资料索引并返回可回查的原文证据。"""

from pathlib import Path
from typing import TYPE_CHECKING

from shared.contracts import DocumentRef, Evidence, FileRef, IngestResult, ParsedDocument, Scope
from shared.errors import AppError

from .indexing.embedding import EMBEDDING_DIM, EMBEDDING_MODEL, ZhipuEmbedding
from .parsing.docx import parse_docx
from .parsing.markdown import parse_markdown
from .parsing.pdf import parse_pdf
from .parsing.txt import parse_txt

INDEX_VERSION = f"{EMBEDDING_MODEL}-{EMBEDDING_DIM}"

if TYPE_CHECKING:
    from .indexing.store import VectorStore


class MainRAGAdapter:
    def __init__(self, *, api_key=None, base_url=None, store_dir: Path | None = None):
        self._embedding = None
        self._store = None
        self._api_key, self._base_url, self._store_dir = api_key, base_url, store_dir

    @property
    def embedding(self) -> ZhipuEmbedding:
        if self._embedding is None:
            self._embedding = ZhipuEmbedding(api_key=self._api_key, base_url=self._base_url)
        return self._embedding

    @property
    def store(self) -> "VectorStore":
        if self._store is None:
            from .indexing.store import VectorStore

            self._store = VectorStore(self._store_dir)
        return self._store

    def parse(self, file: FileRef) -> ParsedDocument:
        suffix = file.path.suffix.lower()
        if suffix == ".txt":
            return parse_txt(file)
        if suffix in {".md", ".markdown"}:
            return parse_markdown(file)
        if suffix == ".docx":
            return parse_docx(file)
        if suffix == ".pdf":
            return parse_pdf(file)
        raise AppError("unsupported_format", f"暂不支持的文件格式：{suffix}", 422)

    def ingest(self, document: DocumentRef) -> IngestResult:
        if not document.blocks:
            raise AppError("empty_document", "文档没有可索引的正文块", 422)

        texts = [block.text for block in document.blocks]
        vectors = self.embedding.embed(texts)

        ids = [f"{document.document_id}:{document.version}:{block.id}" for block in document.blocks]
        metadatas = [
            {
                "project_id": document.project_id,
                "document_id": document.document_id,
                "version": document.version,
                "block_id": block.id,
                "block_no": block.block_no,
                "index_version": INDEX_VERSION,
            }
            for block in document.blocks
        ]

        self.store.upsert(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
        )

        return IngestResult(index_version=INDEX_VERSION, chunk_count=len(document.blocks))

    def retrieve(self, scope: Scope, question: str, limit: int) -> list[Evidence]:
        if not question.strip():
            raise AppError("invalid_question", "问题不能为空", 422)
        if limit <= 0:
            raise AppError("invalid_limit", "limit 必须大于 0", 422)

        vectors = self.embedding.embed([question])
        query_vector = vectors[0]

        result = self.store.query(
            embedding=query_vector,
            project_id=scope.project_id,
            limit=limit,
        )

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]

        if not ids:
            return []

        # 按 document_id + version 分组，按 block_no 排序，再拼接 quote
        grouped: dict[tuple[int, int], list[tuple[int, int, str]]] = {}
        for i, _id in enumerate(ids):
            meta = metadatas[i]
            doc_id = meta["document_id"]
            version = meta["version"]
            block_id = meta["block_id"]
            block_no = meta["block_no"]
            text = documents[i]
            grouped.setdefault((doc_id, version), []).append((block_no, block_id, text))

        evidence_list: list[Evidence] = []
        for (doc_id, version), items in grouped.items():
            items.sort(key=lambda x: x[0])
            block_ids = [item[1] for item in items]
            quote = "\n".join(item[2] for item in items)[:8000]
            evidence_list.append(
                Evidence(
                    document_id=doc_id,
                    version=version,
                    block_ids=block_ids,
                    quote=quote,
                )
            )

        return evidence_list

    def delete(self, scope: Scope, document_id: int, version: int) -> None:
        self.store.delete_by_document(
            project_id=scope.project_id,
            document_id=document_id,
            version=version,
        )
