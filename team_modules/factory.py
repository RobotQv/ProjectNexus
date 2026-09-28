"""后端负责人维护的唯一装配点。各组员只需完成自己目录里的实现。"""

from pathlib import Path

from shared.contracts import Modules
from team_modules.main_rag.adapter import MainRAGAdapter
from team_modules.risk.adapter import RiskAdapter
from team_modules.workflow.adapters import EntityAdapter, WorkflowAdapter


def build_modules(*, settings, llm):
    # 显式传递配置；向量库和网络客户端仍延迟到真正使用时创建。
    root = Path(settings.storage_dir).parent
    embedding = {
        "api_key": settings.llm_api_key.get_secret_value(),
        "base_url": settings.llm_base_url,
    }
    return Modules(
        main_rag=MainRAGAdapter(
            **embedding,
            store_dir=root / "main_rag",
            retrieval_mode=settings.rag_retrieval_mode,
            chunk_strategy=settings.rag_chunk_strategy,
            candidate_limit=settings.rag_candidate_limit,
        ),
        entities=EntityAdapter(**embedding, store_dir=root / "workflow"),
        workflow=WorkflowAdapter(llm=llm),
        risk=RiskAdapter(),
    )
