"""检索计分：按原文锚点，区分任何命中、逐题召回和全锚点召回。"""


def anchor_ranks(ranked, targets, documents):
    result = []
    for target in targets:
        did, bno = target["relevant_document_id"], target["relevant_block_no"]
        anchor = target["relevant_anchor_text"]
        block = documents[did]["blocks"][bno]
        assert block["text"].count(anchor) == 1, "锚点必须在标注原块中唯一"
        start = block["text"].index(anchor)
        hits = [
            r["rank"]
            for r in ranked
            if r["document_id"] == did
            and any(
                s["block_id"] == block["id"]
                and s["start"] <= start
                and s["end"] >= start + len(anchor)
                for s in r["source_spans"]
            )
        ]
        result.append(min(hits, default=None))
    return result


def score(ranks, *, status="succeeded"):
    if not ranks:
        return {
            "hit_at_5": None,
            "reciprocal_rank": None,
            "first_hit_rank": None,
            "macro_anchor_recall_at_5": None,
            "all_evidence_at_5": None,
            "relevant_anchor_count": 0,
            "recalled_anchor_count": 0,
        }
    if status != "succeeded":
        ranks = [None] * len(ranks)  # 有答案的失败查询留在分母，按未命中计。
    first = min((r for r in ranks if r is not None), default=None)
    count = sum(r is not None and r <= 5 for r in ranks)
    return {
        "hit_at_5": int(count > 0),
        "reciprocal_rank": 1 / first if first and first <= 5 else 0,
        "first_hit_rank": first,
        "macro_anchor_recall_at_5": count / len(ranks),
        "all_evidence_at_5": int(count == len(ranks)),
        "relevant_anchor_count": len(ranks),
        "recalled_anchor_count": count,
    }


def aggregate(rows):
    answerable = [r for r in rows if r["relevant_anchor_count"]]
    n = len(answerable)
    anchors = sum(r["relevant_anchor_count"] for r in answerable)
    return {
        "queries": len(rows),
        "answerable": n,
        "no_answer": len(rows) - n,
        "failed": sum(r.get("status", "succeeded") != "succeeded" for r in rows),
        "hits": sum(r["hit_at_5"] for r in answerable),
        "hit_at_5": sum(r["hit_at_5"] for r in answerable) / n if n else None,
        "mrr_at_5": sum(r["reciprocal_rank"] for r in answerable) / n if n else None,
        "macro_anchor_recall_at_5": sum(r["macro_anchor_recall_at_5"] for r in answerable) / n
        if n
        else None,
        "micro_anchor_recall_at_5": sum(r["recalled_anchor_count"] for r in answerable) / anchors
        if anchors
        else None,
        "all_evidence_at_5": sum(r["all_evidence_at_5"] for r in answerable) / n if n else None,
    }
