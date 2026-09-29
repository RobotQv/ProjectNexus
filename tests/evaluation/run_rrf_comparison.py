"""50 题固定参数实测；只调用 embedding-3，使用正式 MainRAGAdapter 检索路径。"""

import argparse
import csv
import hashlib
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings
from shared.contracts import Block, DocumentRef, Scope
from team_modules.main_rag.adapter import MainRAGAdapter
from team_modules.main_rag.indexing.embedding import ZhipuEmbedding
from tests.evaluation.rrf_dataset_v2 import dataset
from tests.evaluation.run_alpha_retrieval import CachedEmbedding

MODES = ("vector", "bm25", "hybrid_rrf")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def target_ranks(ranked, targets, documents):
    """按原文锚点匹配，不用关键词相似度充当答案；每个目标最多计一次。"""
    result = []
    for target in targets:
        did, anchor = target["document_id"], target["anchor"]
        start = documents[did]["text"].index(anchor)
        hit = next(
            (
                row["rank"]
                for row in ranked
                if row["document_id"] == did
                and any(
                    span["block_id"] == did * 100
                    and span["start"] <= start
                    and span["end"] >= start + len(anchor)
                    for span in row["source_spans"]
                )
            ),
            None,
        )
        result.append(hit)
    return result


def metrics(ranks):
    hits = sorted({rank for rank in ranks if rank is not None and rank <= 5})
    best = min((rank for rank in ranks if rank is not None), default=None)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(ranks), 5)))
    return {
        **{
            f"recall_at_{k}": sum(r is not None and r <= k for r in ranks) / len(ranks)
            for k in (1, 3, 5)
        },
        "mrr_at_5": 1 / best if best is not None and best <= 5 else 0,
        "ndcg_at_5": sum(1 / math.log2(r + 1) for r in hits) / ideal,
        "all_targets_at_5": int(all(r is not None and r <= 5 for r in ranks)),
    }


def summarize(rows):
    result = {}
    for category in ["all", "exact", "semantic", "mixed", "version", "multi"]:
        result[category] = {}
        for mode in MODES:
            subset = [
                r
                for r in rows
                if r["mode"] == mode and (category == "all" or r["category"] == category)
            ]
            result[category][mode] = {
                "count": len(subset),
                **{
                    key: sum(r[key] for r in subset) / len(subset)
                    for key in (
                        "recall_at_1",
                        "recall_at_3",
                        "recall_at_5",
                        "mrr_at_5",
                        "ndcg_at_5",
                        "all_targets_at_5",
                        "context_chars",
                        "elapsed_ms",
                    )
                },
            }
    return result


def comparison(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["question_id"], {})[row["mode"]] = row
    result = []
    for qid, modes in grouped.items():
        rrf = modes["hybrid_rrf"]
        result.append(
            {
                "question_id": qid,
                "category": rrf["category"],
                "question": rrf["question"],
                "vector_ranks": modes["vector"]["target_ranks"],
                "bm25_ranks": modes["bm25"]["target_ranks"],
                "rrf_ranks": rrf["target_ranks"],
                **{
                    f"{metric}_delta_vs_{base}": rrf[metric] - modes[base][metric]
                    for base in ("vector", "bm25")
                    for metric in ("recall_at_5", "mrr_at_5", "ndcg_at_5")
                },
                "top5_changed_vs_vector": [x["chunk_id"] for x in rrf["ranks"][:5]]
                != [x["chunk_id"] for x in modes["vector"]["ranks"][:5]],
            }
        )
    return result


def report(output, summary, differences, corpus_hash):
    lines = [
        "# RRF 扩展实测：50 题",
        "",
        "80 份虚构资料，10 类业务场景，每类 5 题。当前制度、故障处置、待审会议、旧版、相近业务、目录、术语及台账同时进入索引。",
        "这是开发者构造的检索压力样例，不是生产随机样本，也不是独立人工评测。题目与锚点在首次调用前冻结，没有按结果挑题或调参。",
        "",
        f"数据 SHA256：`{corpus_hash}`。正式 bounded 分块，embedding-3 / 2048维；两路候选各20，RRF常数60、等权。三组共享语料及向量。",
        "不调用聊天模型；测量的是证据检索，不是最终回答正确率。多来源题的 Recall 按目标原文数量计算，MRR只看第一条相关证据。",
        "",
        "## 总体结果",
        "",
        "| 方法 | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 | 全部证据进入前5 | 平均上下文字符 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for mode, row in summary["all"].items():
        lines.append(
            f"| {mode} | "
            + " | ".join(
                f"{row[k]:.4f}"
                for k in (
                    "recall_at_1",
                    "recall_at_3",
                    "recall_at_5",
                    "mrr_at_5",
                    "ndcg_at_5",
                    "all_targets_at_5",
                )
            )
            + f" | {row['context_chars']:.0f} |"
        )
    lines.extend(["", "## RRF 带来的逐题变化", ""])
    for base in ("vector", "bm25"):
        for metric in ("recall_at_5", "mrr_at_5", "ndcg_at_5"):
            values = [row[f"{metric}_delta_vs_{base}"] for row in differences]
            lines.append(
                f"- 相比 {base}，{metric}：提高 {sum(v > 1e-9 for v in values)} 题，"
                f"下降 {sum(v < -1e-9 for v in values)} 题，"
                f"相同 {sum(abs(v) <= 1e-9 for v in values)} 题。"
            )
    lines.extend(
        [
            f"- 相比向量检索，前5有序列表发生变化：{sum(r['top5_changed_vs_vector'] for r in differences)}/50 题。列表变化本身不代表质量提高。",
            "",
            "## 分类型结果",
            "",
            "| 类型 | 方法 | 题数 | Recall@5 | MRR@5 | nDCG@5 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for category, modes in summary.items():
        if category == "all":
            continue
        for mode, row in modes.items():
            lines.append(
                f"| {category} | {mode} | {row['count']} | {row['recall_at_5']:.4f} | {row['mrr_at_5']:.4f} | {row['ndcg_at_5']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## 全部题目排名",
            "",
            "exact=编号精确；semantic=口语改写；mixed=编号+语义；version=适用范围/版本；multi=需要两份证据。",
            "数字按目标锚点顺序排列，—表示未进入该方法前20；大于5仍按未进前5计分。",
            "",
            "| ID | 类型 | 问题 | Vector目标排名 | BM25目标排名 | RRF目标排名 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in differences:
        ranks = [
            ", ".join(str(n) if n is not None else "—" for n in row[k])
            for k in ("vector_ranks", "bm25_ranks", "rrf_ranks")
        ]
        lines.append(
            f"| {row['question_id']} | {row['category']} | {row['question']} | "
            + " | ".join(ranks)
            + " |"
        )
    lines.extend(
        [
            "",
            "## 边界与复现",
            "",
            "RRF只组合排名，不识别文件权威性；旧制度等干扰文档可能被错误提前。合成集较小，长文、真实用户分布和人工多相关性标注仍需另测。",
            "本轮缓存全部资料与查询向量后测排序耗时，因此 elapsed_ms 不含网络嵌入耗时，不能当作端到端响应速度对比。",
            "原文见 materials.md，冻结答案见 dataset.json；raw.json保存三组完整前20、两路原始名次和来源锚点，differences.csv保存逐题变化。",
            "复现：`python -m tests.evaluation.run_rrf_comparison`。需要本机官方 Embedding 权限，脚本不会打印密钥、不会读取业务库或改生产配置。",
        ]
    )
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    corpus = dataset()
    blob = json.dumps(corpus, ensure_ascii=False, sort_keys=True).encode()
    digest = hashlib.sha256(blob).hexdigest()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = Path("artifacts/rrf-v2-50") / stamp
    output.mkdir(parents=True, exist_ok=False)
    save(output / "dataset.json", corpus)
    manifest = {
        "created_utc": stamp,
        "dataset_sha256": digest,
        "questions": 50,
        "documents": len(corpus["documents"]),
        "embedding": "embedding-3-2048",
        "chunk_strategy": "bounded",
        "candidate_limit": 20,
        "rrf_constant": 60,
        "chat_model": None,
        "status": "prepared",
    }
    save(output / "manifest.json", manifest)
    (output / "materials.md").write_text(
        "# 合成资料（不是真实企业制度）\n\n"
        + "\n\n".join(
            f"## D{d['id']:02} {d['filename']}\n\n{d['text']}" for d in corpus["documents"]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Frozen dataset: {digest}; output: {output}", flush=True)
    if args.prepare_only:
        return
    settings = get_settings()
    if urlparse(settings.llm_base_url).hostname != "open.bigmodel.cn":
        raise ValueError("This experiment only sends synthetic text to official BigModel")
    cache = Path("data/rrf-v2-50") / digest[:16]
    cache.mkdir(parents=True, exist_ok=True)
    provider = ZhipuEmbedding(
        api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_base_url
    )
    embedding = CachedEmbedding(provider, cache / "embeddings.db")
    rows = []
    try:
        # 预热：每批最多16条，成功立即落盘；没有自动重试或隐含聊天调用。
        texts = list(
            dict.fromkeys(
                [d["text"] for d in corpus["documents"]]
                + [q["question"] for q in corpus["questions"]]
            )
        )
        missing = [
            (hashlib.sha256(("embedding-3-2048:" + text).encode()).hexdigest(), text)
            for text in texts
        ]
        missing = [
            (key, text)
            for key, text in missing
            if not embedding.db.execute("SELECT 1 FROM vectors WHERE key=?", (key,)).fetchone()
        ]
        manifest["uncached_texts"] = len(missing)
        for i in range(0, len(missing), 16):
            batch = missing[i : i + 16]
            vectors = provider.embed([text for _, text in batch])
            embedding.db.executemany(
                "INSERT INTO vectors VALUES (?,?)",
                [
                    (key, json.dumps(vector))
                    for (key, _), vector in zip(batch, vectors, strict=True)
                ],
            )
            embedding.db.commit()
            print(f"Embedding: {min(i + 16, len(missing))}/{len(missing)} new texts", flush=True)
        adapter = MainRAGAdapter(
            store_dir=cache / "index", chunk_strategy="bounded", candidate_limit=20
        )
        adapter._embedding = embedding
        documents = {d["id"]: d for d in corpus["documents"]}
        for did, document in documents.items():
            adapter.ingest(
                DocumentRef(
                    project_id=1,
                    document_id=did,
                    version=1,
                    filename=document["filename"],
                    blocks=[
                        Block(
                            id=did * 100,
                            block_no=0,
                            document_id=did,
                            document_version=1,
                            heading=document["filename"],
                            text=document["text"],
                        )
                    ],
                )
            )
        manifest["chunks"] = len(adapter.store.snapshot(1)["ids"])
        for question in corpus["questions"]:
            for mode in MODES:
                started = time.perf_counter()
                ranked = adapter.retrieve_ranked(
                    Scope(project_id=1), question["question"], 20, mode=mode
                )
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
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                        "ranks": ranked,
                    }
                )
            print(
                f"{question['id']}: "
                + "; ".join(f"{r['mode']}={r['target_ranks']}" for r in rows[-3:]),
                flush=True,
            )
        summary, differences = summarize(rows), comparison(rows)
        save(output / "summary.json", summary)
        save(output / "differences.json", differences)
        with (output / "differences.csv").open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(differences[0]))
            writer.writeheader()
            writer.writerows(differences)
        report(output, summary, differences, digest)
        manifest["status"] = "succeeded"
        manifest["category_counts"] = dict(Counter(q["category"] for q in corpus["questions"]))
        print(json.dumps(summary["all"], ensure_ascii=False), flush=True)
    except Exception as error:
        manifest.update(status="failed", error=getattr(error, "code", type(error).__name__))
        raise
    finally:
        save(output / "raw.json", rows)
        save(output / "manifest.json", manifest)
        embedding.db.close()
        provider.close()


if __name__ == "__main__":
    main()
