"""在冻结50题上新增标题单路与三路RRF；复用上次真实检索排名，不调用外部API。"""

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from shared.contracts import Block
from team_modules.main_rag.chunking import chunk_document
from tests.evaluation.run_rrf_comparison import metrics, save, target_ranks
from tests.evaluation.title_retrieval import fuse_rankings, retrieve_titles, title_text

MODES = ("vector", "bm25", "hybrid_rrf", "title_bm25", "rrf_3")
METRICS = (
    "recall_at_1",
    "recall_at_3",
    "recall_at_5",
    "mrr_at_5",
    "ndcg_at_5",
    "all_targets_at_5",
    "context_chars",
)


def make_catalog(documents):
    catalog = {}
    for d in documents:
        did = d["id"]
        blocks = [
            Block(
                id=did * 100,
                block_no=0,
                document_id=did,
                document_version=1,
                heading=d["filename"],
                text=d["text"],
            )
        ]
        chunks, _ = chunk_document(blocks, strategy="bounded")
        for i, chunk in enumerate(chunks):
            key = f"{did}:1:{i}"
            catalog[key] = {
                "chunk_id": key,
                "document_id": did,
                "version": 1,
                "source_spans": chunk.spans,
                "quote": chunk.text,
                "filename": d["filename"],
                "title_text": title_text(d["filename"], chunk.heading or ""),
            }
    return catalog


def validate_baseline(corpus, manifest, rows, catalog):
    digest = hashlib.sha256(
        json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    assert manifest["status"] == "succeeded"
    assert digest == manifest["dataset_sha256"], "冻结资料与哈希不一致"
    assert manifest["candidate_limit"] == 20 and manifest["rrf_constant"] == 60
    assert manifest["chunk_strategy"] == "bounded" and manifest["chunks"] == len(catalog)
    grouped = {}
    for row in rows:
        modes = grouped.setdefault(row["question_id"], {})
        assert row["mode"] not in modes, "重复结果"
        modes[row["mode"]] = row
        assert [r["rank"] for r in row["ranks"]] == list(range(1, len(row["ranks"]) + 1))
        assert len(row["ranks"]) <= 20
        for rank in row["ranks"]:
            original = catalog[rank["chunk_id"]]
            assert rank["quote"] == original["quote"]
            assert rank["source_spans"] == original["source_spans"]
    assert set(grouped) == {q["id"] for q in corpus["questions"]}
    docs = {d["id"]: d for d in corpus["documents"]}
    for question in corpus["questions"]:
        modes = grouped[question["id"]]
        assert set(modes) == {"vector", "bm25", "hybrid_rrf"}
        for row in modes.values():
            assert row["question"] == question["question"]
            ranks = target_ranks(row["ranks"], question["targets"], docs)
            assert ranks == row["target_ranks"]
            assert all(abs(row[k] - v) < 1e-12 for k, v in metrics(ranks).items())
        dual = fuse_rankings(
            {name: modes[name]["ranks"] for name in ("vector", "bm25")}, catalog, "hybrid_rrf"
        )
        assert [r["chunk_id"] for r in dual] == [
            r["chunk_id"] for r in modes["hybrid_rrf"]["ranks"]
        ], "原双路RRF未能复现"
    return digest, grouped


def analyze(rows, questions):
    summary, differences = {}, []
    for category in ("all", "exact", "semantic", "mixed", "version", "multi"):
        summary[category] = {}
        for mode in MODES:
            subset = [
                r
                for r in rows
                if r["mode"] == mode and (category == "all" or r["category"] == category)
            ]
            summary[category][mode] = {
                "count": len(subset),
                **{key: sum(r[key] for r in subset) / len(subset) for key in METRICS},
            }
    grouped = {(r["question_id"], r["mode"]): r for r in rows}
    for q in questions:
        triple = grouped[q["id"], "rrf_3"]
        differences.append(
            {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                **{f"{mode}_ranks": grouped[q["id"], mode]["target_ranks"] for mode in MODES},
                **{
                    f"{key}_delta_vs_{base}": triple[key] - grouped[q["id"], base][key]
                    for base in ("hybrid_rrf", "vector")
                    for key in ("recall_at_5", "mrr_at_5", "ndcg_at_5")
                },
                "top5_changed_vs_dual": [r["chunk_id"] for r in triple["ranks"][:5]]
                != [r["chunk_id"] for r in grouped[q["id"], "hybrid_rrf"]["ranks"][:5]],
            }
        )
    return summary, differences


def write_report(output, summary, differences, digest):
    lines = [
        "# 标题检索与三路 RRF：同一组50题",
        "",
        "新增：对已有文件名和章节标题执行BM25。重复标题只计一次，去掉扩展名；没有从正文或答案标注提取、补写关键词。原语料文件名没有业务编号，所以本轮不额外给标题添加编号。",
        "复用上轮真实 embedding-3 的前20名和正文BM25前20名；逐题重新计算双路RRF并核对原结果，再加入标题路融合。每路20候选、常数60、等权，没有调整权重。标题路检索全部80个块，未限制在原两路候选中。",
        "",
        f"冻结资料 SHA256：`{digest}`。原文、题目、标注不变。本轮无新API调用。所有指标按同一答案锚点计算。",
        "",
        "## 总体结果",
        "",
        "| 方法 | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 | 全部证据进入前5 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mode, row in summary["all"].items():
        lines.append(f"| {mode} | " + " | ".join(f"{row[k]:.4f}" for k in METRICS[:-1]) + " |")
    lines.extend(["", "## 三路相对双路的变化", ""])
    for key in ("recall_at_5", "mrr_at_5", "ndcg_at_5"):
        values = [r[f"{key}_delta_vs_hybrid_rrf"] for r in differences]
        lines.append(
            f"- {key}：提高 {sum(v > 1e-9 for v in values)} 题，下降 {sum(v < -1e-9 for v in values)} 题，相同 {sum(abs(v) <= 1e-9 for v in values)} 题。"
        )
    lines.extend(
        [
            f"- 前5有序列表改变 {sum(r['top5_changed_vs_dual'] for r in differences)}/50 题；变化本身不代表改善。",
            "",
            "## 分类型结果",
            "",
            "| 类型 | 方法 | Recall@5 | MRR@5 | nDCG@5 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for category, modes in summary.items():
        if category == "all":
            continue
        for mode, row in modes.items():
            lines.append(
                f"| {category} | {mode} | {row['recall_at_5']:.4f} | {row['mrr_at_5']:.4f} | {row['ndcg_at_5']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## 全部50题目标排名",
            "",
            "顺序按原答案锚点；—表示未进前20，排名大于5仍按前5未召回计算。",
            "",
            "| ID | 问题 | 向量 | 正文BM25 | 双路RRF | 标题BM25 | 三路RRF |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in differences:
        values = [
            ", ".join(str(n) if n is not None else "—" for n in row[f"{mode}_ranks"])
            for mode in MODES
        ]
        lines.append(f"| {row['id']} | {row['question']} | " + " | ".join(values) + " |")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "标题通道与正文BM25并非完全独立。标题很短、模板化，可能产生大量同分，统一以chunk_id字典序决定同分次序；该序号不具有业务含义。所有通道都保持相同同分规则。",
            "三路融合的候选并集最多60条，双路最多40条；每路预算相同，但总候选预算不同。RRF不识别版本权威性，也不能保证增加通道一定改善排序。",
            "本轮沿用已看过结果的合成开发压力集，不是新盲测集。80份均为短资料，不能外推真实长文或回答准确率。多来源题Recall按目标证据数量计算，再逐题平均。",
            "保留全部改善和退步，不改生产默认模式。raw.json保存五组排名；title_catalog.json列出实际标题字段；dataset.json保留原文及标注。",
        ]
    )
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    corpus = json.loads((args.baseline / "dataset.json").read_text(encoding="utf-8"))
    manifest = json.loads((args.baseline / "manifest.json").read_text(encoding="utf-8"))
    previous = json.loads((args.baseline / "raw.json").read_text(encoding="utf-8"))
    catalog = make_catalog(corpus["documents"])
    digest, grouped = validate_baseline(corpus, manifest, previous, catalog)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path("artifacts/rrf-title-50") / stamp
    output.mkdir(parents=True, exist_ok=False)
    save(output / "dataset.json", corpus)
    save(output / "title_catalog.json", list(catalog.values()))
    run_manifest = {
        "created_utc": stamp,
        "dataset_sha256": digest,
        "questions": len(corpus["questions"]),
        "chunks": len(catalog),
        "baseline_run": args.baseline.name,
        "baseline_raw_sha256": hashlib.sha256(
            (args.baseline / "raw.json").read_bytes()
        ).hexdigest(),
        "candidate_limit_per_channel": 20,
        "rrf_constant": 60,
        "weights": [1, 1, 1],
        "title_rule": "existing filename stem + distinct existing heading; BM25; positive scores only",
        "external_api_calls": 0,
        "dual_reproduction_verified": True,
        "status": "prepared",
    }
    save(output / "manifest.json", run_manifest)
    rows = list(previous)
    documents = {d["id"]: d for d in corpus["documents"]}
    for question in corpus["questions"]:
        modes = grouped[question["id"]]
        titles = retrieve_titles(question["question"], list(catalog.values()))
        triple = fuse_rankings(
            {"vector": modes["vector"]["ranks"], "bm25": modes["bm25"]["ranks"], "title": titles},
            catalog,
            "rrf_3",
        )
        for mode, ranked in (("title_bm25", titles), ("rrf_3", triple)):
            ranks = target_ranks(ranked, question["targets"], documents)
            rows.append(
                {
                    "question_id": question["id"],
                    "category": question["category"],
                    "question": question["question"],
                    "mode": mode,
                    "target_ranks": ranks,
                    **metrics(ranks),
                    "context_chars": sum(len(r["quote"]) for r in ranked[:5]),
                    "ranks": ranked,
                }
            )
    summary, differences = analyze(rows, corpus["questions"])
    save(output / "raw.json", rows)
    save(output / "summary.json", summary)
    save(output / "differences.json", differences)
    with (output / "differences.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(differences[0]))
        writer.writeheader()
        writer.writerows(differences)
    write_report(output, summary, differences, digest)
    run_manifest["status"] = "succeeded"
    save(output / "manifest.json", run_manifest)
    print(f"Output: {output}")
    print(json.dumps(summary["all"], ensure_ascii=False))


if __name__ == "__main__":
    main()
