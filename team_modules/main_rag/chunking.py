"""检索块与原始正文分离。长度单位为字符；每段保留原块内 [start, end) 锚点。"""

from dataclasses import dataclass
from math import sqrt


@dataclass
class Chunk:
    text: str
    spans: list[dict]
    heading: str | None


def cosine(left, right):
    denominator = sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0


def chunk_document(
    blocks,
    *,
    strategy="bounded",
    maximum=1200,
    minimum=300,
    overlap=100,
    embedding=None,
    threshold=0.55,
):
    """语义策略只在有界小段之间比较，不突破标题/页码/长度/锚点上限。"""
    if not 0 <= overlap < maximum or not 0 < minimum <= maximum:
        raise ValueError("invalid chunk bounds")
    if strategy not in {"baseline", "bounded", "semantic"}:
        raise ValueError("unknown chunk strategy")
    segments, trace = [], []
    for block in blocks:
        step = maximum - overlap
        starts = [0] if strategy == "baseline" else range(0, len(block.text), step)
        for start in starts:
            end = (
                len(block.text) if strategy == "baseline" else min(start + maximum, len(block.text))
            )
            segments.append(
                (
                    Chunk(
                        block.text[start:end],
                        [
                            {
                                "block_id": block.id,
                                "block_no": block.block_no,
                                "start": start,
                                "end": end,
                                "locator": block.locator,
                            }
                        ],
                        block.heading,
                    ),
                    block.page,
                )
            )
            if end == len(block.text):
                break
    vectors = None
    if strategy == "semantic" and segments:
        if embedding is None:
            raise ValueError("semantic chunking requires embeddings")
        vectors = embedding.embed([s.text for s, _ in segments])
    chunks = []
    previous_page = None
    for i, (segment, page) in enumerate(segments):
        previous = chunks[-1] if chunks else None
        similarity = cosine(vectors[i - 1], vectors[i]) if vectors is not None and i else None
        adjacent = previous and previous.spans[-1]["block_id"] != segment.spans[0]["block_id"]
        same_structure = previous and previous.heading == segment.heading and previous_page == page
        fits = (
            previous
            and len(previous.text) + 1 + len(segment.text) <= maximum
            and len(previous.spans) < 20
        )
        merge = strategy != "baseline" and adjacent and same_structure and fits
        merge = bool(
            merge
            and (
                similarity >= threshold if strategy == "semantic" else len(previous.text) < minimum
            )
        )
        if not previous:
            reason = "first"
        elif strategy == "baseline":
            reason = "original_block"
        elif not adjacent:
            reason = "long_block_overlap"
        elif not same_structure:
            reason = "heading_or_page_boundary"
        elif not fits:
            reason = "length_or_anchor_bound"
        elif strategy == "semantic" and not merge:
            reason = "similarity_below_threshold"
        else:
            reason = "merge" if merge else "previous_block_already_long_enough"
        trace.append(
            {
                "segment": i,
                "text": segment.text,
                "source_spans": segment.spans,
                "similarity_previous": similarity,
                "threshold": threshold if vectors else None,
                "decision": reason,
            }
        )
        if merge:
            previous.text += "\n" + segment.text
            previous.spans.extend(segment.spans)
        else:
            chunks.append(segment)
        previous_page = page
    return chunks, {
        "strategy": strategy,
        "length_unit": "characters",
        "maximum": maximum,
        "overlap": overlap,
        "segments": trace,
        "chunks": [{"text": c.text, "source_spans": c.spans} for c in chunks],
    }
