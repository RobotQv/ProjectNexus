"""结果独立验算：不调用主评分函数，不访问API，不改变冻结材料。"""

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

from team_modules.main_rag.retrieval import bm25, rrf
from tests.evaluation.run_retrieval_100 import catalog_for, file_hashes


def verify_lexical_candidates(keys, scores, saved):
    """Verify scores and ordering, disclosing only sub-picounit floating-point ties.

    Frozen BM25 sums a set of query terms. Different hash seeds may change the
    last bits of a sum. Preserve the historical ranking, never rewrite it.
    """
    lookup = dict(zip(keys, scores, strict=True))
    expected = sorted((key for key in keys if lookup[key] > 0), key=lambda k: (-lookup[k], k))[:20]
    actual = [row["chunk_id"] for row in saved]
    assert len(expected) == len(actual) == len(set(actual))
    changes = []
    for rank, (key, row) in enumerate(zip(expected, saved, strict=True), 1):
        stored_key = row["chunk_id"]
        assert stored_key in lookup and lookup[stored_key] > 0
        assert math.isclose(lookup[stored_key], row["score"], rel_tol=0, abs_tol=1e-12)
        assert math.isclose(lookup[key], lookup[stored_key], rel_tol=0, abs_tol=1e-12)
        if key != stored_key:
            changes.append(
                {
                    "rank": rank,
                    "recomputed_chunk_id": key,
                    "archived_chunk_id": stored_key,
                    "score_delta": abs(lookup[key] - lookup[stored_key]),
                }
            )
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()

    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))

    data = load(args.dataset_dir / "dataset.json")
    frozen = load(args.dataset_dir / "frozen_manifest.json")
    assert (
        hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        == frozen["dataset_sha256"]
    )
    assert file_hashes() == frozen["algorithm_sha256"]
    raw = load(args.run_dir / "raw.json")
    summary = load(args.run_dir / "summary.json")
    with (args.run_dir / "retrieval_results_100.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        table = list(csv.DictReader(file))
    assert len(raw) == len(table) == 500
    by_id = {(r["question_id"], r["method"]): r for r in raw}
    csv_ids = {(r["question_id"], r["method"]): r for r in table}
    assert len(by_id) == len(csv_ids) == 500
    methods = ["vector", "bm25", "hybrid_rrf", "title_bm25", "rrf_3"]
    assert Counter(r["method"] for r in raw) == dict.fromkeys(methods, 100)
    documents = {d["id"]: d for d in data["documents"]}
    catalog = catalog_for(data["documents"])
    checked = []
    floating_ties = []
    for q in data["questions"]:
        scope = {
            key: value for key, value in catalog.items() if value["project_id"] == q["project_id"]
        }
        keys = sorted(scope)
        # 单独从冻结原文、标题重算词法候选池，不能只信任保存的排名。
        for method, field in (("bm25", "quote"), ("title_bm25", "title_text")):
            scores = bm25(q["question"], [scope[k][field] for k in keys])
            changes = verify_lexical_candidates(
                keys, scores, by_id[q["question_id"], method]["ranks"]
            )
            if changes:
                floating_ties.append(
                    {"question_id": q["question_id"], "method": method, "changes": changes}
                )
        for method, sources in (
            ("hybrid_rrf", ("vector", "bm25")),
            ("rrf_3", ("vector", "bm25", "title_bm25")),
        ):
            fused = rrf(
                [[r["chunk_id"] for r in by_id[q["question_id"], s]["ranks"]] for s in sources],
                constant=60,
            )
            ordered = sorted(fused, key=lambda k: (-fused[k], k))[:20]
            assert ordered == [r["chunk_id"] for r in by_id[q["question_id"], method]["ranks"]]
        for method in methods:
            row = by_id[q["question_id"], method]
            csv_row = csv_ids[q["question_id"], method]
            assert row["status"] == "succeeded"  # 本次声称0失败，严格核对。
            for r in row["ranks"]:
                assert r["chunk_id"] in scope and r["quote"] == scope[r["chunk_id"]]["quote"]
            rank_list = []
            for t in q["relevant_anchors"]:
                d = documents[t["relevant_document_id"]]
                b = d["blocks"][t["relevant_block_no"]]
                start = b["text"].index(t["relevant_anchor_text"])
                matching = []
                for r in row["ranks"]:
                    if r["document_id"] != d["id"]:
                        continue
                    for s in r["source_spans"]:
                        if (
                            s["block_id"] == b["id"]
                            and s["start"] <= start
                            and s["end"] >= start + len(t["relevant_anchor_text"])
                        ):
                            matching.append(r["rank"])
                rank_list.append(min(matching, default=None))
            assert rank_list == row["target_ranks"]
            n = len(rank_list)
            hit_count = sum(r is not None and r <= 5 for r in rank_list)
            first = min((r for r in rank_list if r is not None), default=None)
            if not n:
                assert row["hit_at_5"] is None and row["reciprocal_rank"] is None
                assert csv_row["hit@5"] == csv_row["recall@5"] == csv_row["reciprocal_rank"] == ""
                continue
            hit = int(hit_count > 0)
            rr = 1 / first if first is not None and first <= 5 else 0
            recall = hit_count / n
            assert first == row["first_hit_rank"]
            assert row["hit_at_5"] == hit == int(csv_row["hit@5"])
            assert math.isclose(rr, row["reciprocal_rank"], abs_tol=1e-12)
            assert math.isclose(recall, float(csv_row["recall@5"]), abs_tol=1e-12)
            checked.append(
                {"batch": q["batch"], "method": method, "hit": hit, "rr": rr, "recall": recall}
            )
    for batch in ("A", "B", "Total"):
        for method in methods:
            subset = [
                r
                for r in checked
                if r["method"] == method and (batch == "Total" or r["batch"] == batch)
            ]
            assert len(subset) == {"A": 50, "B": 45, "Total": 95}[batch]
            for key, metric in (
                ("hit", "hit_at_5"),
                ("rr", "mrr_at_5"),
                ("recall", "macro_anchor_recall_at_5"),
            ):
                assert math.isclose(
                    sum(r[key] for r in subset) / len(subset),
                    summary[batch][method][metric],
                    abs_tol=1e-12,
                )
    report = {
        "status": "passed",
        "raw_rows": 500,
        "csv_rows": 500,
        "answerable_query_count": 95,
        "no_answer_query_count": 5,
        "no_answer_rows": 25,
        "failed": 0,
        "dataset_and_algorithm_hashes_unchanged": True,
        "lexical_score_absolute_tolerance": 1e-12,
        "floating_tie_reorderings": floating_ties,
        "historical_rankings_modified": False,
        "checks": [
            "anchor coverage independently recalculated",
            "CSV and summaries independently recalculated",
            "body/title BM25 candidates recomputed",
            "both RRF variants recomputed",
            "project isolation and unchanged source text",
            "all 500 rows accounted for",
        ],
    }
    (args.run_dir / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
