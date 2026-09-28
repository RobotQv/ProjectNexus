"""真实 Embedding API 测试：需要 NEXUS_LLM_API_KEY，默认跳过。"""

import os

import pytest

from team_modules.main_rag.indexing.embedding import EMBEDDING_DIM, ZhipuEmbedding


@pytest.mark.skipif(
    os.getenv("NEXUS_RUN_LIVE_TESTS") != "1" or not os.getenv("NEXUS_LLM_API_KEY"),
    reason="仅显式设置 NEXUS_RUN_LIVE_TESTS=1 且提供 Key 时运行真实 API 测试",
)
def test_embedding_live():
    client = ZhipuEmbedding()
    vectors = client.embed(["登录接口已经完成七成。"])
    assert len(vectors) == 1
    assert len(vectors[0]) == EMBEDDING_DIM
