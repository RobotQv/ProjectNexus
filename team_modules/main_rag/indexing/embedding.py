"""智谱 Embedding 客户端：调用 embedding-3，维度 2048。"""

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

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": EMBEDDING_MODEL, "input": texts}
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=60)
        except httpx.HTTPError as exc:
            raise AppError("embedding_unavailable", "Embedding 服务连接失败", 503) from exc
        if resp.status_code != 200:
            raise AppError("embedding_failed", "Embedding 服务返回错误", 503)
        data = resp.json().get("data", [])
        vectors = [item["embedding"] for item in data]
        if len(vectors) != len(texts):
            raise AppError("embedding_failed", "Embedding 返回数量不一致", 503)
        return vectors
