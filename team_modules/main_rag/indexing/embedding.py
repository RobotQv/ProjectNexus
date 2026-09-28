"""智谱 Embedding 客户端：调用 embedding-3，维度 2048。"""

import math
import os

import httpx

from shared.errors import AppError

# 后端工厂显式注入配置；独立使用时允许读取环境变量。导入不修改进程环境。

EMBEDDING_MODEL = "embedding-3"
EMBEDDING_DIM = 2048
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


class ZhipuEmbedding:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key if api_key is not None else os.getenv("NEXUS_LLM_API_KEY")
        self.base_url = (base_url or os.getenv("NEXUS_LLM_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        if not self.api_key:
            raise AppError("embedding_unavailable", "未配置 Embedding API Key", 503)
        self.client = httpx.Client(timeout=60, follow_redirects=False)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), 16):
            vectors.extend(self._batch(texts[start : start + 16]))
        return vectors

    def _batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": EMBEDDING_MODEL, "input": texts}
        try:
            resp = self.client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise AppError("embedding_unavailable", "Embedding 服务连接失败", 503) from exc
        if resp.status_code != 200:
            raise AppError("embedding_failed", "Embedding 服务返回错误", 503)
        try:
            data = sorted(resp.json()["data"], key=lambda item: item["index"])
            if [item["index"] for item in data] != list(range(len(texts))):
                raise ValueError("indices")
            vectors = [item["embedding"] for item in data]
            if any(
                len(vector) != EMBEDDING_DIM or not all(math.isfinite(x) for x in vector)
                for vector in vectors
            ):
                raise ValueError("dimensions")
        except (ValueError, KeyError, TypeError):
            raise AppError("embedding_failed", "Embedding 返回维度或顺序不合法", 503) from None
        return vectors

    def close(self):
        self.client.close()
