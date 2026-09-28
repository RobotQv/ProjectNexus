"""delete 测试：用假 Embedding 和临时向量库。"""

from pathlib import Path

import pytest

from shared.contracts import Block, DocumentRef, Scope
from team_modules.main_rag.adapter import MainRAGAdapter
from team_modules.main_rag.indexing import store as store_module


class FakeEmbedding:
    def embed(self, texts):
        return [[0.1] * 2048 for _ in texts]


@pytest.fixture
def adapter(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(store_module, "DEFAULT_STORE_DIR", tmp_path / "main_rag")
    a = MainRAGAdapter()
    a._embedding = FakeEmbedding()
    a._store = store_module.VectorStore(store_dir=tmp_path / "main_rag")
    return a


def make_document(project_id: int = 1, document_id: int = 5, version: int = 1) -> DocumentRef:
    return DocumentRef(
        project_id=project_id,
        document_id=document_id,
        version=version,
        filename="meeting.txt",
        blocks=[
            Block(
                id=18,
                document_id=document_id,
                document_version=version,
                block_no=0,
                text="登录接口已经完成七成。",
            ),
            Block(
                id=19,
                document_id=document_id,
                document_version=version,
                block_no=1,
                text="支付模块进度 70%。",
            ),
        ],
    )


def test_delete_removes_index(adapter):
    adapter.ingest(make_document())
    assert adapter.store.collection.count() == 2

    adapter.delete(Scope(project_id=1), document_id=5, version=1)
    assert adapter.store.collection.count() == 0

    results = adapter.retrieve(Scope(project_id=1), "登录接口进度", limit=2)
    assert results == []


def test_delete_idempotent(adapter):
    adapter.ingest(make_document())
    adapter.delete(Scope(project_id=1), document_id=5, version=1)
    adapter.delete(Scope(project_id=1), document_id=5, version=1)
    assert adapter.store.collection.count() == 0


def test_delete_does_not_affect_other_project(adapter):
    adapter.ingest(make_document(project_id=1, document_id=5))
    adapter.ingest(make_document(project_id=2, document_id=6))

    adapter.delete(Scope(project_id=1), document_id=5, version=1)
    assert adapter.store.collection.count() == 2

    results = adapter.retrieve(Scope(project_id=2), "登录接口进度", limit=2)
    assert len(results) >= 1


def test_delete_does_not_affect_other_version(adapter):
    adapter.ingest(make_document(version=1))
    adapter.ingest(make_document(version=2))

    adapter.delete(Scope(project_id=1), document_id=5, version=1)
    assert adapter.store.collection.count() == 2

    results = adapter.retrieve(Scope(project_id=1), "登录接口进度", limit=2)
    assert all(r.version == 2 for r in results)


def test_delete_then_reingest(adapter):
    adapter.ingest(make_document())
    adapter.delete(Scope(project_id=1), document_id=5, version=1)
    adapter.ingest(make_document())
    assert adapter.store.collection.count() == 2
