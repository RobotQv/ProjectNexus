"""retrieve 测试：用假 Embedding 和临时向量库，不请求真实 API。"""

from pathlib import Path

import pytest

from shared.contracts import Block, DocumentRef, Scope
from shared.errors import AppError
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


def make_document(project_id: int = 1, document_id: int = 5) -> DocumentRef:
    return DocumentRef(
        project_id=project_id,
        document_id=document_id,
        version=1,
        filename="meeting.txt",
        blocks=[
            Block(
                id=18,
                document_id=document_id,
                document_version=1,
                block_no=0,
                text="登录接口已经完成七成。",
            ),
            Block(
                id=19,
                document_id=document_id,
                document_version=1,
                block_no=1,
                text="支付模块进度 70%。",
            ),
        ],
    )


def test_retrieve_basic(adapter):
    adapter.ingest(make_document())
    results = adapter.retrieve(Scope(project_id=1), "登录接口进度", limit=2)
    assert len(results) >= 1
    assert results[0].document_id == 5
    assert results[0].version == 1
    assert "登录接口" in results[0].quote


def test_retrieve_project_isolation(adapter):
    adapter.ingest(make_document(project_id=1, document_id=5))
    results = adapter.retrieve(Scope(project_id=2), "登录接口进度", limit=2)
    assert results == []


def test_retrieve_empty_question(adapter):
    with pytest.raises(AppError) as exc:
        adapter.retrieve(Scope(project_id=1), "  ", limit=2)
    assert exc.value.code == "invalid_question"


def test_retrieve_invalid_limit(adapter):
    with pytest.raises(AppError) as exc:
        adapter.retrieve(Scope(project_id=1), "测试", limit=0)
    assert exc.value.code == "invalid_limit"
