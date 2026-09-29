"""审计、冻结、执行100题检索评估。prepare与run分开，执行后不改资料/参数。"""

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import get_settings
from shared.contracts import Block, DocumentRef, Scope
from team_modules.main_rag.adapter import MainRAGAdapter
from team_modules.main_rag.chunking import chunk_document
from team_modules.main_rag.indexing.embedding import ZhipuEmbedding
from tests.evaluation.audit_batch_a import METHODS, audit
from tests.evaluation.batch_b_dataset import batch_b
from tests.evaluation.retrieval_metrics import aggregate, anchor_ranks, score
from tests.evaluation.run_rrf_comparison import save
from tests.evaluation.title_retrieval import fuse_rankings, retrieve_titles, title_text

ALGORITHM_FILES = [
    "team_modules/main_rag/retrieval.py",
    "team_modules/main_rag/adapter.py",
    "team_modules/main_rag/chunking.py",
    "team_modules/main_rag/indexing/embedding.py",
    "tests/evaluation/title_retrieval.py",
    "tests/evaluation/retrieval_metrics.py",
    "tests/evaluation/run_retrieval_100.py",
]
PARAMETERS = {
    "rrf_constant": 60,
    "candidate_limit_per_channel": 20,
    "weights": [1, 1, 1],
    "chunk_strategy": "bounded",
    "embedding": "embedding-3-2048",
    "top_k": 5,
    "rank_inspection_depth": 20,
    "no_answer_in_hit_mrr": False,
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def file_hashes():
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in ALGORITHM_FILES}


def blocks(document):
    return [Block(**b, document_id=document["id"], document_version=1) for b in document["blocks"]]


def catalog_for(documents):
    catalog = {}
    for d in documents:
        chunks, _ = chunk_document(blocks(d), strategy="bounded")
        for i, chunk in enumerate(chunks):
            key = f"{d['id']}:1:{i}"
            catalog[key] = {
                "chunk_id": key,
                "document_id": d["id"],
                "project_id": d["project_id"],
                "version": 1,
                "source_spans": chunk.spans,
                "quote": chunk.text,
                "filename": d["filename"],
                "title_text": title_text(d["filename"], chunk.heading or ""),
            }
    return catalog


def validate_dataset(data):
    docs = {d["id"]: d for d in data["documents"]}
    assert len(docs) == len(data["documents"])
    assert len(data["questions"]) == 100
    assert len({q["question_id"] for q in data["questions"]}) == 100
    assert len({q["question"] for q in data["questions"]}) == 100
    assert Counter(q["batch"] for q in data["questions"]) == {"A": 50, "B": 50}
    assert Counter(q["category"] for q in data["questions"] if q["batch"] == "B") == {
        "semantic": 10,
        "exact": 10,
        "mixed": 10,
        "distractor": 10,
        "cross_document": 5,
        "no_answer": 5,
    }
    for q in data["questions"]:
        assert bool(q["relevant_anchors"]) == (q["category"] != "no_answer")
        for t in q["relevant_anchors"]:
            d = docs[t["relevant_document_id"]]
            assert d["project_id"] == q["project_id"]
            assert d["blocks"][t["relevant_block_no"]]["text"].count(t["relevant_anchor_text"]) == 1
    return docs


def prepare(source, output):
    old_audit = audit(source)
    old = json.loads((source / "dataset.json").read_text(encoding="utf-8"))
    new = batch_b()
    a_documents = [
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
    a_questions = [
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
            "distractor_note": "保留Batch A原标注，不按扩展结果改写。",
        }
        for q in old["questions"]
    ]
    data = {
        "version": "retrieval-100-v1",
        "documents": a_documents + new["documents"],
        "questions": a_questions + new["questions"],
    }
    validate_dataset(data)
    output.mkdir(parents=True, exist_ok=False)
    save(output / "dataset.json", data)
    save(output / "batch_a_audit.json", old_audit)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "frozen",
        "dataset_sha256": digest(data),
        "parameters": PARAMETERS,
        "algorithm_sha256": file_hashes(),
        "source_a_dataset_sha256": old_audit["dataset_sha256"],
        "scope": "shared expanded corpus; per-query project filter",
        "answerable_queries": sum(bool(q["relevant_anchors"]) for q in data["questions"]),
        "batch_b_anchor_distribution": dict(
            Counter(len(q["relevant_anchors"]) for q in new["questions"])
        ),
        "note": "A已看过结果；B在本次运行前冻结，开发者合成，非独立人工盲测。未调参。",
    }
    save(output / "frozen_manifest.json", manifest)
    text = [
        "# Batch B 设计及完整标注",
        "",
        "同一套虚构澄川设备维保项目资料，远帆作项目隔离对照。A原文与标注不改。",
        "B：语义10、精确技术词10、混合10、高相似干扰10、跨文档/项目5、无答案5。类别不预设哪种检索会赢。",
        "多锚点按实际所需证据标注，包括同块多处信息和跨文档证据；不是强制一题一锚点。无答案题单列。",
        "",
        f"冻结哈希：`{digest(data)}`。",
        "",
        "| ID | 类别 | 项目 | 问题 | 正确原文锚点（文档/块） |",
        "| --- | --- | --- | --- | --- |",
    ]
    for q in new["questions"]:
        targets = (
            "；".join(
                f"D{t['relevant_document_id']}/B{t['relevant_block_no']}：{t['relevant_anchor_text']}"
                for t in q["relevant_anchors"]
            )
            or "无；材料不足，不指定假锚点"
        )
        text.append(
            f"| {q['question_id']} | {q['category']} | {q['project_id']} | {q['question']} | {targets} |"
        )
    (output / "C_Batch_B设计.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    material = ["# 固定语料（全部虚构）"]
    for d in data["documents"]:
        material += [f"\n## D{d['id']} 项目{d['project_id']} {d['filename']}"]
        material += [
            f"\n### block_no={b['block_no']} {b['heading']}\n\n{b['text']}" for b in d["blocks"]
        ]
    (output / "materials.md").write_text("\n".join(material) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


class FrozenCache:
    """只读复用A缓存；本轮新向量独立存储。缺缓存就失败，不暗中在线重试。"""

    def __init__(self, path, old_path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector TEXT)")
        self.old = (
            sqlite3.connect(old_path.resolve().as_uri() + "?mode=ro", uri=True)
            if old_path.exists()
            else None
        )

    def lookup(self, text):
        key = hashlib.sha256(("embedding-3-2048:" + text).encode()).hexdigest()
        row = self.db.execute("SELECT vector FROM vectors WHERE key=?", (key,)).fetchone()
        if row is None and self.old:
            row = self.old.execute("SELECT vector FROM vectors WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def embed(self, texts):
        vectors = [self.lookup(text) for text in texts]
        if any(v is None for v in vectors):
            raise ValueError("embedding_cache_miss")
        return vectors

    def populate(self, texts, provider):
        missing = [text for text in dict.fromkeys(texts) if self.lookup(text) is None]
        for start in range(0, len(missing), 16):
            batch = missing[start : start + 16]
            vectors = provider.embed(batch)
            self.db.executemany(
                "INSERT INTO vectors VALUES (?,?)",
                [
                    (hashlib.sha256(("embedding-3-2048:" + t).encode()).hexdigest(), json.dumps(v))
                    for t, v in zip(batch, vectors, strict=True)
                ],
            )
            self.db.commit()
            print(f"Embedding {min(start + 16, len(missing))}/{len(missing)}", flush=True)
        return len(missing)

    def close(self):
        self.db.close()
        if self.old:
            self.old.close()


def csv_write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                for k, v in row.items()
            }
            for row in rows
        )


def build_cases(rows, questions):
    by_key = {(r["question_id"], r["method"]): r for r in rows}
    cases = {name: [] for name in ("improved", "same", "worsened")}
    rank23_to1 = []
    for q in questions:
        if not q["relevant_anchors"]:
            continue
        selected = {m: by_key[q["question_id"], m] for m in METHODS}
        if any(r["status"] != "succeeded" for r in selected.values()):
            continue
        v, r = selected["vector"]["first_hit_rank"], selected["hybrid_rrf"]["first_hit_rank"]
        delta = (v or 21) - (r or 21)
        category = "improved" if delta > 0 else "worsened" if delta < 0 else "same"
        case = {
            "question_id": q["question_id"],
            "batch": q["batch"],
            "category": q["category"],
            "query": q["question"],
            "correct_evidence": q["relevant_anchors"],
            "first_hit_rank": {m: x["first_hit_rank"] for m, x in selected.items()},
            "rank_change": delta,
            "top5": {m: x["ranks"][:5] for m, x in selected.items()},
        }
        cases[category].append(case)
        if v in (2, 3) and r == 1:
            rank23_to1.append(case)
    # 规则固定：按变化幅度降序、ID升序选3例，同时完整保留全部案例，数量不足不造假。
    for values in cases.values():
        values.sort(key=lambda x: (-abs(x["rank_change"]), x["question_id"]))
    return {
        "selection_rule": "sort by absolute first-hit rank change descending, question ID ascending; all cases retained",
        "groups": {
            k: {"count": len(v), "examples": v[:3], "all_cases": v} for k, v in cases.items()
        },
        "vector_rank2or3_to_dual_rank1": rank23_to1,
    }


def finalize(output, data, rows):
    summary = {
        batch: {
            method: aggregate(
                [
                    r
                    for r in rows
                    if r["method"] == method and (batch == "Total" or r["batch"] == batch)
                ]
            )
            for method in METHODS
        }
        for batch in ("A", "B", "Total")
    }
    save(output / "summary.json", summary)
    results = []
    for row in rows:
        results.append(
            {
                "question_id": row["question_id"],
                "batch": row["batch"],
                "category": row["category"],
                "method": row["method"],
                "status": row["status"],
                "error": row.get("error"),
                "answerable": bool(row["relevant_anchor_count"]),
                "hit@5": row["hit_at_5"],
                "recall@5": row["macro_anchor_recall_at_5"],
                "reciprocal_rank": row["reciprocal_rank"],
                "first_hit_rank": row["first_hit_rank"],
                "all_evidence@5": row["all_evidence_at_5"],
                "relevant_anchor_count": row["relevant_anchor_count"],
                "recalled_anchor_count": row["recalled_anchor_count"],
                "top5_chunk_ids": [r["chunk_id"] for r in row["ranks"][:5]],
                "top5_document_ids": [r["document_id"] for r in row["ranks"][:5]],
            }
        )
    csv_write(output / "retrieval_results_100.csv", results)
    csv_write(
        output / "retrieval_summary_100.csv",
        [
            {
                "method": method,
                **{
                    f"{batch}_{key}": summary[batch][method][key]
                    for batch in ("A", "B", "Total")
                    for key in (
                        "queries",
                        "answerable",
                        "no_answer",
                        "failed",
                        "hits",
                        "hit_at_5",
                        "mrr_at_5",
                        "macro_anchor_recall_at_5",
                        "micro_anchor_recall_at_5",
                        "all_evidence_at_5",
                    )
                },
            }
            for method in METHODS
        ],
    )
    cases = build_cases(rows, data["questions"])
    save(output / "rrf_case_studies.json", cases)
    save(output / "no_answer_results.json", [r for r in rows if not r["relevant_anchor_count"]])
    lines = [
        "# 100题检索对照结果",
        "",
        "A和B在同一扩展语料快照重跑；A历史80份资料的审计表另存，不与新语料分数混拼。",
        "100个query × 5方法 = 500条记录。A有答案50题；B有答案45题、无答案5题。合并Hit/Recall/MRR的分母是95道有答案题，不是100。",
        "Hit@5=至少一个相关锚点进入前5；Recall@5=逐题相关锚点覆盖比例的平均；MRR@5=第一条命中倒数（超过5则0）。保留多锚点，不强制单锚点。",
        "有答案的失败查询留在分母按0计，无答案的5题单列且相关指标为空。不把检索器返回非空列表当作其声称可回答，也不据此算拒答准确率。",
        "",
        "| 方法 | A Hit@5 | A Recall@5 | A MRR@5 | B Hit@5 | B Recall@5 | B MRR@5 | Total Hit@5 | Total Recall@5 | Total MRR@5 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for method in METHODS:
        values = []
        for batch in ("A", "B", "Total"):
            s = summary[batch][method]
            values += [
                f"{s['hits']}/{s['answerable']}={s['hit_at_5']:.2%}",
                f"{s['macro_anchor_recall_at_5']:.2%}",
                f"{s['mrr_at_5']:.4f}",
            ]
        lines.append(f"| {method} | " + " | ".join(values) + " |")
    lines += ["", "## 双路相对向量的Top5覆盖", ""]
    keyed = {(r["question_id"], r["method"]): r for r in rows}
    for batch in ("A", "B", "Total"):
        eligible = [
            q
            for q in data["questions"]
            if q["relevant_anchors"] and (batch == "Total" or q["batch"] == batch)
        ]
        rescued = [
            q["question_id"]
            for q in eligible
            if keyed[q["question_id"], "vector"]["hit_at_5"] == 0
            and keyed[q["question_id"], "hybrid_rrf"]["hit_at_5"] == 1
        ]
        lost = [
            q["question_id"]
            for q in eligible
            if keyed[q["question_id"], "vector"]["hit_at_5"] == 1
            and keyed[q["question_id"], "hybrid_rrf"]["hit_at_5"] == 0
        ]
        lines.append(f"- {batch}：补回 {len(rescued)} 题 {rescued}；丢失 {len(lost)} 题 {lost}。")
    lines += [
        "",
        "## 案例索引",
        "",
        f"向量Rank2/3升到双路Rank1：{[c['question_id'] for c in cases['vector_rank2or3_to_dual_rank1']]}。若为空即没有观察到，不补造样例。",
    ]
    for group, item in cases["groups"].items():
        lines.append(
            f"- {group} 共{item['count']}题，自动展示{[c['question_id'] for c in item['examples']]}；全部案例保留在JSON。"
        )
    lines += ["", "## 标注、失败与范围", ""]
    for batch in ("A", "B"):
        qs = [q for q in data["questions"] if q["batch"] == batch]
        lines.append(
            f"- {batch}锚点数分布：{dict(Counter(len(q['relevant_anchors']) for q in qs))}。"
        )
    lines += [
        f"- 每种方法错误数：{ {m: summary['Total'][m]['failed'] for m in METHODS} }。",
        "- frozen_manifest.json在任何B查询运行前保存语料、答案、参数和算法文件哈希；运行前后检查相同，不对B调参。RRF常数60，BM25分词和权重不变。",
        "- Title通道与Body BM25可能相关；等权融合不识别权威版本。三路候选并集最多60，双路最多40。",
        "- 本集为开发者合成资料，不是生产随机抽样或独立人工盲测。A已多次查看结果；B为新题但并非外部标注。本轮只评价检索，不评价最终回答或拒答准确率。",
        "- 原文位置由文档、原块编号、字符锚点标注；切块不是标签。角色与材料均虚构，没有读取业务库。",
    ]
    (output / "D_100题对比.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def run(output):
    data = json.loads((output / "dataset.json").read_text(encoding="utf-8"))
    frozen = json.loads((output / "frozen_manifest.json").read_text(encoding="utf-8"))
    assert digest(data) == frozen["dataset_sha256"] and PARAMETERS == frozen["parameters"]
    assert file_hashes() == frozen["algorithm_sha256"], "冻结后算法发生变化；拒绝运行"
    documents = validate_dataset(data)
    catalog = catalog_for(data["documents"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    attempt = output / "runs" / stamp
    attempt.mkdir(parents=True, exist_ok=False)
    state = {"status": "running", "dataset_sha256": digest(data), "started_utc": stamp}
    save(attempt / "run.json", state)
    cache_dir = Path("data/retrieval-100") / digest(data)[:16]
    cache_dir.mkdir(parents=True, exist_ok=True)
    old_path = Path("data/rrf-v2-50") / frozen["source_a_dataset_sha256"][:16] / "embeddings.db"
    cache = FrozenCache(cache_dir / "embeddings.db", old_path)
    provider = None
    rows = []
    try:
        texts = [c["quote"] for c in catalog.values()] + [q["question"] for q in data["questions"]]
        if any(cache.lookup(t) is None for t in texts):
            settings = get_settings()
            assert urlparse(settings.llm_base_url).hostname == "open.bigmodel.cn"
            provider = ZhipuEmbedding(
                api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_base_url
            )
            state["new_embeddings"] = cache.populate(texts, provider)
        else:
            state["new_embeddings"] = 0
        adapter = MainRAGAdapter(
            store_dir=cache_dir / "index", chunk_strategy="bounded", candidate_limit=20
        )
        adapter._embedding = cache
        for d in data["documents"]:
            adapter.ingest(
                DocumentRef(
                    project_id=d["project_id"],
                    document_id=d["id"],
                    version=1,
                    filename=d["filename"],
                    blocks=blocks(d),
                )
            )
        for q in data["questions"]:
            scope = Scope(project_id=q["project_id"])
            scoped_catalog = {
                k: c for k, c in catalog.items() if c["project_id"] == q["project_id"]
            }
            rankings, errors = {}, {}
            for mode in ("vector", "bm25"):
                try:
                    rankings[mode] = adapter.retrieve_ranked(scope, q["question"], 20, mode=mode)
                except Exception as exc:
                    rankings[mode], errors[mode] = [], getattr(exc, "code", type(exc).__name__)
            rankings["title_bm25"] = retrieve_titles(
                q["question"], list(scoped_catalog.values()), 20
            )
            for mode, channels in (
                ("hybrid_rrf", {"vector": rankings["vector"], "bm25": rankings["bm25"]}),
                (
                    "rrf_3",
                    {
                        "vector": rankings["vector"],
                        "bm25": rankings["bm25"],
                        "title": rankings["title_bm25"],
                    },
                ),
            ):
                if errors:
                    errors[mode], rankings[mode] = "upstream_retrieval_failed", []
                else:
                    rankings[mode] = fuse_rankings(channels, scoped_catalog, mode)
            for method in METHODS:
                ranked = [
                    {**r, "filename": documents[r["document_id"]]["filename"]}
                    for r in rankings[method]
                ]
                assert all(
                    r["document_id"] in documents
                    and documents[r["document_id"]]["project_id"] == q["project_id"]
                    for r in ranked
                )
                ranks = anchor_ranks(ranked, q["relevant_anchors"], documents)
                status = "failed" if method in errors else "succeeded"
                rows.append(
                    {
                        "question_id": q["question_id"],
                        "batch": q["batch"],
                        "category": q["category"],
                        "project_id": q["project_id"],
                        "question": q["question"],
                        "method": method,
                        "status": status,
                        "error": errors.get(method),
                        "target_ranks": ranks,
                        **score(ranks, status=status),
                        "ranks": ranked,
                    }
                )
            # 逐题保留结果，失败不可悄悄删题；断电也不丢已完成部分。
            save(attempt / "raw.json", rows)
            print(
                q["question_id"]
                + " "
                + "; ".join(f"{r['method']}={r['first_hit_rank']}" for r in rows[-5:]),
                flush=True,
            )
        assert len(rows) == 500
        assert (
            digest(json.loads((output / "dataset.json").read_text(encoding="utf-8")))
            == frozen["dataset_sha256"]
        )
        assert file_hashes() == frozen["algorithm_sha256"]
        finalize(attempt, data, rows)
        state.update(
            status="succeeded",
            retrieval_rows=len(rows),
            failed=sum(r["status"] != "succeeded" for r in rows),
            completed_utc=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as exc:
        state.update(
            status="failed",
            error=getattr(exc, "code", type(exc).__name__),
            completed_rows=len(rows),
        )
        raise
    finally:
        save(attempt / "raw.json", rows)
        save(attempt / "run.json", state)
        cache.close()
        if provider:
            provider.close()
    print(f"RESULT_DIR={attempt}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-a", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.source_a is None:
            parser.error("prepare requires --source-a")
        prepare(args.source_a, args.output)
    else:
        run(args.output)


if __name__ == "__main__":
    main()
