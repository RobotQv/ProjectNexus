"""小型语料的确定性 BM25 与排名融合；分数不是概率，不混加向量原始分数。"""

import math
import re
import unicodedata
from collections import Counter


def tokenize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    tokens = re.findall(r"[a-z0-9]+(?:[.+#_-][a-z0-9+#]+)*|[\u3400-\u9fff]+", text)
    result = []
    for token in tokens:
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            result.extend(token)
            result.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            result.append(token)
    return result


def bm25(query, documents):
    counts = [Counter(tokenize(doc)) for doc in documents]
    terms = set(tokenize(query))
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / max(len(lengths), 1) or 1
    scores = [0.0] * len(counts)
    for term in terms:
        df = sum(term in c for c in counts)
        idf = math.log(1 + (len(counts) - df + 0.5) / (df + 0.5))
        for i, count in enumerate(counts):
            tf = count[term]
            scores[i] += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * lengths[i] / average))
    return scores


def rrf(rankings, constant=60):
    scores = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            scores[key] = scores.get(key, 0.0) + 1 / (constant + rank)
    return scores
