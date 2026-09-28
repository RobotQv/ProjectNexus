"""显式真实 embedding 检索对照；冻结语料、原文锚点和阈值，不调用聊天模型。"""

import csv
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from shared.contracts import Block, DocumentRef, Scope
from shared.errors import AppError
from team_modules.main_rag.adapter import MainRAGAdapter
from team_modules.main_rag.chunking import chunk_document
from team_modules.main_rag.indexing.embedding import ZhipuEmbedding
from tests.evaluation.alpha_dataset import DOCUMENTS, QUESTIONS


class CachedEmbedding:
    """只缓存这套合成语料；每条成功结果立刻保存，失败不自动重试。"""

    def __init__(self, provider, path):
        self.provider = provider
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector TEXT)")

    def embed(self, texts):
        result = []
        for text in texts:
            key = hashlib.sha256(("embedding-3-2048:" + text).encode()).hexdigest()
            row = self.db.execute("SELECT vector FROM vectors WHERE key=?", (key,)).fetchone()
            if row:
                vector = json.loads(row[0])
            else:
                vector = self.provider.embed([text])[0]
                self.db.execute("INSERT INTO vectors VALUES (?,?)", (key, json.dumps(vector)))
                self.db.commit()
            result.append(vector)
        return result


def make_documents():
    return [
        DocumentRef(
            project_id=1,
            document_id=did,
            version=1,
            filename=name,
            blocks=[
                Block(
                    id=did * 100 + i,
                    block_no=i,
                    document_id=did,
                    document_version=1,
                    heading=name,
                    text=text,
                )
                for i, text in enumerate(texts)
            ],
        )
        for did, (name, texts) in enumerate(DOCUMENTS, 1)
    ]


def covers(row, did, block_no, anchor):
    if row["document_id"] != did:
        return False
    text = DOCUMENTS[did - 1][1][block_no]
    start = text.index(anchor)
    return any(
        s["block_id"] == did * 100 + block_no
        and s["start"] <= start
        and s["end"] >= start + len(anchor)
        for s in row["source_spans"]
    )


def main():
    output = Path("artifacts/alpha_handoff")
    output.mkdir(parents=True, exist_ok=True)
    records = output / "records"
    records.mkdir(exist_ok=True)
    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    cache_dir = Path("data/alpha-evaluation-v1")
    cache_dir.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    provider = ZhipuEmbedding(
        api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_base_url
    )
    embedding = CachedEmbedding(provider, cache_dir / "embeddings.db")
    rows, traces = [], []
    manifest = {
        "actual_date": datetime.now(timezone.utc).isoformat(),
        "data_version": "alpha-v1",
        "dataset_hash": hashlib.sha256(
            json.dumps([DOCUMENTS, QUESTIONS], sort_keys=True).encode()
        ).hexdigest(),
        "embedding": "embedding-3-2048",
        "chat_model": None,
        "candidate_limit": 20,
        "rrf_constant": 60,
        "semantic_threshold": 0.55,
        "note": "4开发题+8冻结题；合成小样本，不外推普遍效果",
    }
    (output / "retrieval_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    attempt = {"id": attempt_id, "status": "running"}
    try:
        for strategy in ("baseline", "bounded", "semantic"):
            adapter = MainRAGAdapter(store_dir=cache_dir / "index", chunk_strategy=strategy)
            adapter._embedding = embedding
            for document in make_documents():
                adapter.ingest(document)
                _, trace = chunk_document(
                    document.blocks,
                    strategy=strategy,
                    embedding=embedding if strategy == "semantic" else None,
                )
                traces.append({"document_id": document.document_id, **trace})
            for mode in ("vector", "bm25", "hybrid_rrf"):
                for qid, split, question, did, block_no, anchor in QUESTIONS:
                    started = time.perf_counter()
                    row = {
                        "strategy": strategy,
                        "mode": mode,
                        "question_id": qid,
                        "split": split,
                        "question": question,
                        "anchor": anchor,
                        "status": "succeeded",
                    }
                    try:
                        ranks = adapter.retrieve_ranked(Scope(project_id=1), question, 5, mode=mode)
                        hit = next(
                            (r["rank"] for r in ranks if covers(r, did, block_no, anchor)), None
                        )
                        row.update(
                            recall_at_5=int(hit is not None),
                            mrr_at_5=1 / hit if hit else 0,
                            context_chars=sum(len(r["quote"]) for r in ranks),
                            ranks=ranks,
                        )
                    except AppError as error:
                        row.update(status="failed", error=error.code, ranks=[])
                    row["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
                    rows.append(row)
                print(strategy, mode, "finished", flush=True)
            (output / "retrieval_raw.json").write_text(
                json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (output / "chunk_trace.json").write_text(
                json.dumps(traces, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        attempt["status"] = "succeeded"
    except AppError as error:
        attempt.update(
            status="failed",
            error=error.code,
            phase=f"{strategy}:index_or_query",
            completed_questions=len(rows),
        )
        print("retrieval evaluation failed:", error.code, flush=True)
        raise
    finally:
        embedding.db.close()
        provider.close()
        (records / f"retrieval-attempt-{attempt_id}.json").write_text(
            json.dumps(attempt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output / "retrieval_raw.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    fields = [
        "strategy",
        "mode",
        "question_id",
        "split",
        "status",
        "recall_at_5",
        "mrr_at_5",
        "context_chars",
        "elapsed_ms",
        "error",
    ]
    with (output / "retrieval_results.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
