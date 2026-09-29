"""独立重算旧50题；不读取旧结果中的 target_ranks 作为真值。"""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from tests.evaluation.retrieval_metrics import aggregate, anchor_ranks, score

METHODS = ("vector", "bm25", "hybrid_rrf", "title_bm25", "rrf_3")


def audit(source):
    corpus = json.loads((source / "dataset.json").read_text(encoding="utf-8"))
    raw = json.loads((source / "raw.json").read_text(encoding="utf-8"))
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(
        json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    assert manifest["status"] == "succeeded" and manifest["dataset_sha256"] == digest
    documents = {
        d["id"]: {**d, "blocks": [{"id": d["id"] * 100, "text": d["text"]}]}
        for d in corpus["documents"]
    }
    questions = {q["id"]: q for q in corpus["questions"]}
    assert len(questions) == len(corpus["questions"]) == 50
    expected = {(qid, mode) for qid in questions for mode in METHODS}
    assert len(raw) == len(expected) == 250
    assert {(r["question_id"], r["mode"]) for r in raw} == expected
    corrected = []
    for row in raw:
        q = questions[row["question_id"]]
        assert row["question"] == q["question"]
        assert [r["rank"] for r in row["ranks"]] == list(range(1, len(row["ranks"]) + 1))
        assert len({r["chunk_id"] for r in row["ranks"]}) == len(row["ranks"])
        targets = [
            {
                "relevant_document_id": t["document_id"],
                "relevant_block_no": 0,
                "relevant_anchor_text": t["anchor"],
            }
            for t in q["targets"]
        ]
        ranks = anchor_ranks(row["ranks"], targets, documents)
        status = row.get("status", "succeeded")
        assert status == "succeeded" and not row.get("error")
        values = score(ranks, status=status)
        assert abs(values["macro_anchor_recall_at_5"] - row["recall_at_5"]) < 1e-12
        assert abs(values["reciprocal_rank"] - row["mrr_at_5"]) < 1e-12
        corrected.append(
            {
                "question_id": q["id"],
                "method": row["mode"],
                "status": status,
                "target_ranks_recomputed": ranks,
                **values,
            }
        )
    summary = {m: aggregate([r for r in corrected if r["method"] == m]) for m in METHODS}
    result = {
        "queries": 50,
        "rows": 250,
        "methods": list(METHODS),
        "dataset_sha256": digest,
        "anchor_count_distribution": dict(Counter(len(q["targets"]) for q in questions.values())),
        "total_relevant_anchors": sum(len(q["targets"]) for q in questions.values()),
        "failed": 0,
        "skipped": 0,
        "summary": summary,
        "corrected_rows": corrected,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.source)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "batch_a_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Batch A 指标审计",
        "",
        "原始数据：50个query、五种方法各50条结果，共250条；40题单锚点、10题双锚点，共60个相关锚点。没有失败、跳过或缺失条目。",
        "",
        "独立根据文档ID、原块ID、原文字符区间和锚点重新定位，不把旧target_ranks作为真值。原Recall和MRR均能复现。",
        "",
        "## 95%为什么合法，但不能叫命中率",
        "",
        "旧Recall@5是逐题计算（前5覆盖的锚点数/该题相关锚点数），然后对50题平均，即macro anchor recall。双锚点题只找回一条时计0.5；因此步长可以是1%，并非只能2%。",
        "纯向量：46题找齐、3题各找回一半、1题完全未命中，(46+3×0.5)/50=95%。其Hit@5是49/50=98%；按全部锚点计算的micro recall则是56/60≈93.33%。三者不能混用。",
        "单一标注锚点条件下，Recall@5与Hit@5等价；本集并非全部单锚点。此前95%并非算错，但不能把它称为总体命中率。",
        "",
        "## 本次统一口径",
        "",
        "- Hit@5：每题前5中至少覆盖一个相关原文锚点计1，否则0，再按题平均。",
        "- MRR@5：多个锚点中最早命中的rank取最小值；若rank≤5计1/rank，否则0。查找至前20，未出现则first_hit_rank为空。",
        "- Recall@5与Hit@5、MRR@5同时报告，默认指macro anchor recall；另外保留micro anchor recall和全证据覆盖率作为辅助指标。",
        "- 无答案题没有合法相关锚点，单列，不混入Hit/MRR；有答案但检索失败的题不删除，按0计且单列错误。",
        "",
        "## 修正命名后的历史A表（原80份语料）",
        "",
        "| 方法 | Hit@5 | MRR@5 | Macro anchor Recall@5 | Micro anchor Recall@5 | 全证据覆盖 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for method, values in result["summary"].items():
        lines.append(
            f"| {method} | {values['hits']}/50 = {values['hit_at_5']:.2%} | {values['mrr_at_5']:.4f} | {values['macro_anchor_recall_at_5']:.2%} | {values['micro_anchor_recall_at_5']:.2%} | {values['all_evidence_at_5']:.2%} |"
        )
    lines.extend(
        [
            "",
            "扩展100题时，A和B将在同一个扩展语料快照上重跑；历史A表不与不同语料上的B直接拼接。重跑后的A可能因干扰资料增加而变化，两个版本均保留。",
        ]
    )
    (args.output / "A_指标审计.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps({k: v for k, v in result.items() if k != "corrected_rows"}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
