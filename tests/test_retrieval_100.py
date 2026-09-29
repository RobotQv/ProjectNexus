"""100题评估的标注、分母、首命中和作用域检查；不调用外部模型。"""

from collections import Counter

import pytest

from tests.evaluation.batch_b_dataset import batch_b
from tests.evaluation.retrieval_metrics import aggregate, anchor_ranks, score
from tests.evaluation.rrf_dataset_v2 import dataset
from tests.evaluation.run_retrieval_100 import catalog_for, validate_dataset
from tests.evaluation.title_retrieval import retrieve_titles


def fixture_data():
    old, new = dataset(), batch_b()
    docs = [
        {
            "id": d["id"],
            "project_id": 1,
            "filename": d["filename"],
            "blocks": [
                {"id": d["id"] * 100, "block_no": 0, "heading": d["filename"], "text": d["text"]}
            ],
        }
        for d in old["documents"]
    ]
    questions = [
        {
            "question_id": "A" + q["id"][1:],
            "batch": "A",
            "category": q["category"],
            "project_id": 1,
            "question": q["question"],
            "relevant_anchors": [
                {
                    "relevant_document_id": t["document_id"],
                    "relevant_block_no": 0,
                    "relevant_anchor_text": t["anchor"],
                }
                for t in q["targets"]
            ],
        }
        for q in old["questions"]
    ]
    return {"documents": docs + new["documents"], "questions": questions + new["questions"]}


def test_batch_b_distribution_and_source_annotations():
    data = fixture_data()
    validate_dataset(data)
    counts = Counter(len(q["relevant_anchors"]) for q in batch_b()["questions"])
    assert counts[0] == 5 and counts[1] > 0 and counts[2] > 5
    catalog = catalog_for(data["documents"])
    documents = {d["id"]: d for d in data["documents"]}
    ranked = [{**row, "rank": i} for i, row in enumerate(catalog.values(), 1)]
    for q in data["questions"]:
        assert all(r is not None for r in anchor_ranks(ranked, q["relevant_anchors"], documents))


def test_macro_recall_is_not_hit_or_micro_recall():
    # 模拟A向量：40单题中1漏召；10双题中3题仅命中一半。
    rows = [score([1])] * 39 + [score([None])] + [score([1, 2])] * 7 + [score([1, 6])] * 3
    total = aggregate(rows)
    assert total["hit_at_5"] == 0.98
    assert total["macro_anchor_recall_at_5"] == 0.95
    assert total["micro_anchor_recall_at_5"] == pytest.approx(56 / 60)


def test_first_hit_uses_best_anchor_and_truncates_at_five():
    assert score([5, 2])["first_hit_rank"] == 2
    assert score([5, 2])["reciprocal_rank"] == 0.5
    assert score([6])["first_hit_rank"] == 6
    assert score([6])["reciprocal_rank"] == 0
    assert score([None])["first_hit_rank"] is None
    assert score([1, 1])["macro_anchor_recall_at_5"] == 1  # 同一块可覆盖两个必需锚点。


def test_no_answer_excluded_but_failed_answerable_stays_in_denominator():
    rows = [score([1]), {**score([1], status="failed"), "status": "failed"}, score([])]
    total = aggregate(rows)
    assert total["queries"] == 3 and total["answerable"] == 2 and total["no_answer"] == 1
    assert total["failed"] == 1 and total["hit_at_5"] == 0.5 and total["mrr_at_5"] == 0.5
    assert rows[-1]["hit_at_5"] is None and rows[-1]["macro_anchor_recall_at_5"] is None


def test_anchor_requires_correct_document_block_and_full_span():
    docs = {1: {"blocks": [{"id": 100, "text": "前言答案后记"}]}}
    targets = [{"relevant_document_id": 1, "relevant_block_no": 0, "relevant_anchor_text": "答案"}]
    ranked = [
        {"rank": 1, "document_id": 1, "source_spans": [{"block_id": 101, "start": 0, "end": 6}]}
    ]
    assert anchor_ranks(ranked, targets, docs) == [None]
    ranked[0]["source_spans"][0].update(block_id=100, end=3)
    assert anchor_ranks(ranked, targets, docs) == [None]
    ranked[0]["source_spans"][0]["end"] = 4
    assert anchor_ranks(ranked, targets, docs) == [1]


def test_project_filter_applies_to_title_candidates():
    catalog = catalog_for(batch_b()["documents"])
    scoped = [r for r in catalog.values() if r["project_id"] == 1]
    assert not any(r["document_id"] == 119 for r in retrieve_titles("远帆接口更新", scoped))
