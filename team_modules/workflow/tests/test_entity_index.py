"""实体索引（轻 RAG）单测。

逻辑用内存版假向量库 + 可区分的假 Embedding 验证，不请求真实 API；
真实 Chroma 集成单独一个冒烟测试，装了 chromadb 的环境会自动运行。
"""

import math

import pytest

from shared.contracts import EntityRecord, Scope
from team_modules.workflow.adapters import EntityAdapter


class CharEmbedding:
    """基于字符与二元组构造可区分的向量，让相似文本得到更高余弦相似度（仅测试用）。"""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for ch in text:
            v[ord(ch) % self.dim] += 1.0
        for a, b in zip(text, text[1:]):
            v[(ord(a) * 31 + ord(b)) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class FakeStore:
    """内存版实体索引，接口与 Chroma 封装一致，供离线验证 resolve 逻辑。"""

    def __init__(self):
        self.data: dict = {}

    def upsert(self, ids, embeddings, documents, metadatas):
        for i, key in enumerate(ids):
            self.data[key] = {"emb": embeddings[i], "doc": documents[i], "meta": metadatas[i]}

    def get_meta(self, entity_id: str):
        rec = self.data.get(entity_id)
        return rec["meta"] if rec else None

    def delete_by_entity(self, project_id, entity_type, entity_id):
        for key in [
            k
            for k, r in self.data.items()
            if r["meta"]["project_id"] == project_id
            and r["meta"]["entity_type"] == entity_type
            and r["meta"]["entity_id"] == entity_id
        ]:
            self.data.pop(key)

    def query(self, embedding, project_id, entity_type, limit):
        rows = []
        for key, rec in self.data.items():
            m = rec["meta"]
            if m["project_id"] != project_id or m["entity_type"] != entity_type:
                continue
            rows.append((_cosine(embedding, rec["emb"]), key, rec))
        rows.sort(key=lambda r: -r[0])
        rows = rows[:limit]
        return {
            "ids": [[r[1] for r in rows]],
            "documents": [[r[2]["doc"] for r in rows]],
            "metadatas": [[r[2]["meta"] for r in rows]],
            "distances": [[1.0 - r[0] for r in rows]],
        }


@pytest.fixture
def adapter():
    a = EntityAdapter()
    a._embedding = CharEmbedding()
    a._store = FakeStore()
    return a


def task(project_id=1, entity_id=1, text="完成登录接口", version=1, active=True):
    return EntityRecord(
        project_id=project_id,
        entity_type="task",
        entity_id=entity_id,
        source_version=version,
        search_text=text,
        is_active=active,
    )


def test_sync_then_resolve(adapter):
    adapter.sync(task())
    res = adapter.resolve(Scope(project_id=1), "登录接口", "task", 5)
    assert res.outcome == "resolved"
    assert res.candidates[0].entity_id == 1


def test_resolve_project_isolation(adapter):
    adapter.sync(task(project_id=1))
    res = adapter.resolve(Scope(project_id=2), "登录接口", "task", 5)
    assert res.outcome == "not_found"
    assert res.candidates == []


def test_resolve_entity_type_isolation(adapter):
    adapter.sync(task())
    res = adapter.resolve(Scope(project_id=1), "登录接口", "member", 5)
    assert res.outcome == "not_found"


def test_resolve_not_found_below_threshold(adapter):
    adapter.sync(task(text="完成登录接口"))
    res = adapter.resolve(Scope(project_id=1), "支付模块风险排查", "task", 5)
    assert res.outcome == "not_found"


def test_deactivate_cleans_index(adapter):
    adapter.sync(task())
    adapter.sync(task(active=False))
    res = adapter.resolve(Scope(project_id=1), "登录接口", "task", 5)
    assert res.outcome == "not_found"


def test_stale_sync_does_not_overwrite(adapter):
    adapter.sync(task(text="旧标题", version=2))
    adapter.sync(task(text="更新后的标题", version=3))
    adapter.sync(task(text="旧标题再来", version=2))
    assert adapter.store.get_meta("1:task:1")["source_version"] == 3


def test_sync_idempotent(adapter):
    adapter.sync(task())
    adapter.sync(task())
    res = adapter.resolve(Scope(project_id=1), "登录接口", "task", 5)
    assert len(res.candidates) == 1


def test_resolve_same_name_is_ambiguous(adapter):
    # 同名任务（不同 entity_id 的 search_text 完全相同）应返回 ambiguous，不强行二选一。
    adapter.sync(task(entity_id=1, text="完成登录接口"))
    adapter.sync(task(entity_id=2, text="完成登录接口"))
    res = adapter.resolve(Scope(project_id=1), "完成登录接口", "task", 5)
    assert res.outcome == "ambiguous"
    assert {c.entity_id for c in res.candidates} == {1, 2}


def test_resolve_member_entity_type(adapter):
    adapter.sync(
        EntityRecord(
            project_id=1,
            entity_type="member",
            entity_id=42,
            source_version=1,
            search_text="张三",
            is_active=True,
        )
    )
    res = adapter.resolve(Scope(project_id=1), "张三", "member", 5)
    assert res.outcome == "resolved"
    assert res.candidates[0].entity_id == 42


def test_real_chroma_store_smoke(tmp_path):
    # 只有装了 chromadb 的环境才跑；未装时跳过，不影响其它逻辑测试。
    pytest.importorskip("chromadb")
    from team_modules.workflow.indexing.store import EntityStore

    store = EntityStore(store_dir=tmp_path / "workflow")
    store.upsert(
        ids=["1:task:1"],
        embeddings=[[0.1] * 2048],
        documents=["完成登录接口"],
        metadatas=[
            {
                "project_id": 1,
                "entity_type": "task",
                "entity_id": 1,
                "source_version": 1,
                "index_version": "embedding-3-2048",
            }
        ],
    )
    out = store.query([0.1] * 2048, 1, "task", 5)
    assert out["ids"][0][0] == "1:task:1"
    assert store.get_meta("1:task:1")["entity_id"] == 1
    store.delete_by_entity(1, "task", 1)
    assert store.query([0.1] * 2048, 1, "task", 5)["ids"][0] == []
