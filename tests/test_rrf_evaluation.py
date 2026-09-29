"""扩展检索集的标注和计分自检，不调用真实模型。"""

from collections import Counter

import pytest

from tests.evaluation.rrf_dataset_v2 import dataset
from tests.evaluation.run_rrf_comparison import metrics, target_ranks


def test_frozen_rrf_dataset():
    data = dataset()
    docs = {d["id"]: d for d in data["documents"]}
    assert len(docs) == 80
    assert len(data["questions"]) == 50
    assert len({q["id"] for q in data["questions"]}) == 50
    assert len({q["question"] for q in data["questions"]}) == 50
    assert Counter(q["category"] for q in data["questions"]) == dict.fromkeys(
        ["exact", "semantic", "mixed", "version", "multi"], 10
    )
    for q in data["questions"]:
        assert len(q["targets"]) == (2 if q["category"] == "multi" else 1)
        for target in q["targets"]:
            assert docs[target["document_id"]]["text"].count(target["anchor"]) == 1


def test_metrics_count_all_sources_and_top5_cutoff():
    assert metrics([1, 6])["recall_at_5"] == 0.5
    assert metrics([1, 6])["mrr_at_5"] == 1
    assert metrics([1, 6])["all_targets_at_5"] == 0
    assert metrics([None])["mrr_at_5"] == 0
    assert metrics([6])["ndcg_at_5"] == 0
    assert metrics([1, 2])["ndcg_at_5"] == pytest.approx(1)
    assert metrics([2])["mrr_at_5"] == 0.5


def test_partial_source_span_does_not_count_as_evidence():
    docs = {1: {"text": "前言答案后记"}}
    targets = [{"document_id": 1, "anchor": "答案"}]
    row = {"document_id": 1, "rank": 1, "source_spans": [{"block_id": 100, "start": 2, "end": 3}]}
    assert target_ranks([row], targets, docs) == [None]
    row["source_spans"][0]["end"] = 4
    assert target_ranks([row], targets, docs) == [1]
