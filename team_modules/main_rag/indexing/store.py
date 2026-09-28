"""Chroma 向量库封装：持久化到 data/main_rag/，支持幂等 upsert 和按项目过滤。"""

from pathlib import Path

import chromadb
from chromadb.config import Settings

from shared.errors import AppError

COLLECTION_NAME = "main_rag_blocks"
DEFAULT_STORE_DIR = Path("data/main_rag")


class VectorStore:
    def __init__(self, store_dir: Path | None = None, *, collection_name=COLLECTION_NAME):
        self.store_dir = store_dir or DEFAULT_STORE_DIR
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.store_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def snapshot(self, project_id):
        """每次读持久化集合，API 和 Worker 不维护各自易过期的 BM25 缓存。"""
        try:
            return self.collection.get(
                where={"project_id": project_id}, include=["documents", "metadatas", "embeddings"]
            )
        except Exception as exc:
            raise AppError("index_query_failed", "索引读取失败", 503) from exc

    def upsert(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        if not ids:
            return
        try:
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        except Exception as exc:
            raise AppError("index_write_failed", "向量索引写入失败", 503) from exc

    def delete_by_document(self, project_id: int, document_id: int, version: int) -> None:
        try:
            self.collection.delete(
                where={
                    "$and": [
                        {"project_id": project_id},
                        {"document_id": document_id},
                        {"version": version},
                    ]
                }
            )
        except Exception as exc:
            raise AppError("index_delete_failed", "向量索引清理失败", 503) from exc

    def query(
        self,
        embedding: list[float],
        project_id: int,
        limit: int,
    ) -> dict:
        try:
            return self.collection.query(
                query_embeddings=[embedding],
                n_results=limit,
                where={"project_id": project_id},
            )
        except Exception as exc:
            raise AppError("index_query_failed", "向量索引查询失败", 503) from exc
