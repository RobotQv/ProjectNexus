"""实验性标题通道：只读已有文件名/标题，不读取答案标注或正文来补关键词。"""

from pathlib import Path

from team_modules.main_rag.retrieval import bm25, rrf


def title_text(filename, heading=""):
    """去掉扩展名；文件名和章节标题相同时只计一次，不人为重复加权。"""
    fields = [Path(filename).stem, Path(heading).stem if heading else ""]
    return " ".join(dict.fromkeys(field for field in fields if field))


def retrieve_titles(question, chunks, limit=20):
    scores = bm25(question, [row["title_text"] for row in chunks])
    ordered = sorted(
        (i for i, score in enumerate(scores) if score > 0),
        key=lambda i: (-scores[i], chunks[i]["chunk_id"]),
    )[:limit]
    return [
        {
            **chunks[i],
            "rank": rank,
            "score": scores[i],
            "title_rank": rank,
            "vector_rank": None,
            "bm25_rank": None,
            "mode": "title_bm25",
        }
        for rank, i in enumerate(ordered, 1)
    ]


def fuse_rankings(rankings, catalog, mode, limit=20):
    """各路20名、常数60、等权；只有命中通道贡献分数，不补零分候选。"""
    keys = {name: [row["chunk_id"] for row in rows] for name, rows in rankings.items()}
    scores = rrf(list(keys.values()), constant=60)
    ordered = sorted(scores, key=lambda key: (-scores[key], key))[:limit]
    return [
        {
            **catalog[key],
            "rank": rank,
            "score": scores[key],
            "mode": mode,
            **{
                f"{name}_rank": values.index(key) + 1 if key in values else None
                for name, values in keys.items()
            },
        }
        for rank, key in enumerate(ordered, 1)
    ]
