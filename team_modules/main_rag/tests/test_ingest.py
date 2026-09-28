"""ingest 测试：用临时目录和假 Embedding，不请求真实 API。"""

from pathlib import Path

import pytest

from shared.contracts import Block, DocumentRef
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


def make_document() -> DocumentRef:
    return DocumentRef(
        project_id=1,
        document_id=5,
        version=1,
        filename="meeting.txt",
        blocks=[
            Block(
                id=18,
                document_id=5,
                document_version=1,
                block_no=0,
                text="登录接口已经完成七成。",
            ),
            Block(
                id=19,
                document_id=5,
                document_version=1,
                block_no=1,
                text="支付模块进度 70%。",
            ),
        ],
    )


def test_ingest_basic(adapter):
    result = adapter.ingest(make_document())
    assert result.index_version == "embedding-3-2048"
    assert result.chunk_count == 2


def test_ingest_idempotent(adapter):
    doc = make_document()
    adapter.ingest(doc)
    adapter.ingest(doc)
    assert adapter.store.collection.count() == 2


def test_ingest_empty(adapter):
    from shared.errors import AppError

    doc = DocumentRef(
        project_id=1,
        document_id=5,
        version=1,
        filename="empty.txt",
        blocks=[],
    )
    with pytest.raises(AppError) as exc:
        adapter.ingest(doc)
    assert exc.value.code == "empty_document"


def test_ingest_same_version_twice_does_not_duplicate(adapter):
    doc = make_document()
    adapter.ingest(doc)
    adapter.ingest(doc)
    assert adapter.store.collection.count() == 2


def test_index_version_contains_model_and_dim(adapter):
    result = adapter.ingest(make_document())
    assert result.index_version == "embedding-3-2048"
