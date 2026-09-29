"""标题检索/融合自检；没有真实外部请求。"""

import pytest

from tests.evaluation.title_retrieval import fuse_rankings, retrieve_titles, title_text


def test_title_deduplicates_filename_and_heading():
    assert title_text("支付回调-现行规范.md", "支付回调-现行规范.md") == "支付回调-现行规范"
    assert title_text("手册.pdf", "支付回调") == "手册 支付回调"


def test_title_ignores_body_and_zero_score():
    chunks = [
        {"chunk_id": "a", "title_text": "库存手册", "quote": "支付回调"},
        {"chunk_id": "b", "title_text": "支付回调", "quote": "无关文字"},
    ]
    assert [r["chunk_id"] for r in retrieve_titles("支付回调", chunks)] == ["b"]
    assert retrieve_titles("xyzunknown", chunks) == []


def test_fusion_allows_title_only_candidate_and_records_ranks():
    catalog = {key: {"chunk_id": key} for key in ("a", "b", "c")}
    rows = fuse_rankings(
        {"vector": [catalog["a"]], "bm25": [catalog["b"]], "title": [catalog["c"], catalog["b"]]},
        catalog,
        "rrf_3",
    )
    assert [r["chunk_id"] for r in rows] == ["b", "a", "c"]
    assert rows[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert rows[0]["title_rank"] == 2 and rows[0]["vector_rank"] is None


def test_empty_title_channel_does_not_change_dual():
    catalog = {key: {"chunk_id": key} for key in ("a", "b")}
    channels = {"vector": [catalog["b"], catalog["a"]], "bm25": [catalog["a"]]}
    dual = fuse_rankings(channels, catalog, "hybrid_rrf")
    triple = fuse_rankings({**channels, "title": []}, catalog, "rrf_3")
    assert [(r["chunk_id"], r["score"]) for r in dual] == [
        (r["chunk_id"], r["score"]) for r in triple
    ]


def test_title_ties_are_deterministic_and_pool_is_bounded():
    chunks = [{"chunk_id": f"{i:02}", "title_text": "支付回调"} for i in reversed(range(25))]
    ranked = retrieve_titles("支付回调", chunks)
    assert len(ranked) == 20
    assert [r["chunk_id"] for r in ranked] == [f"{i:02}" for i in range(20)]
