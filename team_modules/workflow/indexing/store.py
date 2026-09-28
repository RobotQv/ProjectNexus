"""Chroma 向量库封装：实体索引持久化到 data/workflow/，与资料索引分开命名空间。

集合名 workflow_entities；每条实体以 (project_id, entity_type, entity_id) 为唯一键，
幂等 upsert，按项目与实体类型过滤查询。
"""

from pathlib import Path

import chromadb
from chromadb.config import Settings

from shared.errors import AppError

COLLECTION_NAME = "workflow_entities"
DEFAULT_STORE_DIR = Path("data/workflow")


class EntityStore:
    def __init__(self, store_dir: Path | None = None):
        self.store_dir = store_dir or DEFAULT_STORE_DIR
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.store_dir),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

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
            raise AppError("index_write_failed", "实体索引写入失败", 503) from exc

    def get_meta(self, entity_id: str) -> dict | None:
        """读取指定实体键的元数据；不存在返回 None。用于 source_version 陈旧校验。"""
        try:
            out = self.collection.get(ids=[entity_id])
        except Exception as exc:
            raise AppError("index_read_failed", "实体索引读取失败", 503) from exc
        metas = out.get("metadatas") or []
        if not metas or metas[0] is None:
            return None
        return metas[0]

    def delete_by_entity(self, project_id: int, entity_type: str, entity_id: int) -> None:
        try:
            self.collection.delete(
                where={
                    "$and": [
                        {"project_id": project_id},
                        {"entity_type": entity_type},
                        {"entity_id": entity_id},
                    ]
                }
            )
        except Exception as exc:
            raise AppError("index_delete_failed", "实体索引清理失败", 503) from exc

    def query(
        self,
        embedding: list[float],
        project_id: int,
        entity_type: str,
        limit: int,
    ) -> dict:
        try:
            return self.collection.query(
                query_embeddings=[embedding],
                n_results=limit,
                where={
                    "$and": [
                        {"project_id": project_id},
                        {"entity_type": entity_type},
                    ]
                },
            )
        except Exception as exc:
            raise AppError("index_query_failed", "实体索引查询失败", 503) from exc
