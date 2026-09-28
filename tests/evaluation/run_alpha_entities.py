"""实体组别实测；精确目录优先，未命中再使用真实 embedding 的语义定位。"""

import csv
from pathlib import Path

from app.core.config import get_settings
from shared.contracts import EntityRecord, Scope
from shared.entity_matching import resolve_exact, target_phrase
from team_modules.main_rag.indexing.embedding import ZhipuEmbedding
from team_modules.workflow.adapters import EntityAdapter
from tests.evaluation.run_alpha_retrieval import CachedEmbedding


def main():
    settings = get_settings()
    root = Path("data/alpha-evaluation-v1")
    root.mkdir(parents=True, exist_ok=True)
    provider = ZhipuEmbedding(
        api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_base_url
    )
    embedding = CachedEmbedding(provider, root / "embeddings.db")
    catalog = [
        EntityRecord(
            project_id=1,
            entity_type="task",
            entity_id=i,
            title=title,
            source_version=1,
            aliases=aliases,
            search_text=" ".join([title, *aliases]),
            is_active=True,
        )
        for i, title, aliases in [
            (41, "登录接口", ["认证", "接口"]),
            (42, "支付接口", ["收款", "接口"]),
            (43, "C++ 1.2 兼容测试", ["编译验证"]),
        ]
    ]
    adapter = EntityAdapter(store_dir=root / "entities")
    adapter._embedding = embedding
    cases = [
        ("full", "登录接口", "resolved", 41),
        ("alias", "认证", "resolved", 41),
        ("command", "把认证进度改为70%", "resolved", 41),
        ("id", "TASK-42 进度", "resolved", 42),
        ("ambiguous", "接口", "ambiguous", None),
        ("fuzzy", "登录那部分的接口", "resolved", 41),
        ("none", "TASK-999 进度", "not_found", None),
        ("semantic_none", "月球采矿任务", "not_found", None),
    ]
    rows = []
    try:
        for entity in catalog:
            adapter.sync(entity)
        for group, text, expected, entity_id in cases:
            result = resolve_exact(catalog, text)
            path = "exact" if result is not None else "semantic"
            result = (
                result
                if result is not None
                else adapter.resolve(Scope(project_id=1), target_phrase(text), "task", 10)
            )
            ids = [c.entity_id for c in result.candidates]
            rows.append(
                {
                    "group": group,
                    "input": text,
                    "path": path,
                    "outcome": result.outcome,
                    "expected": expected,
                    "candidates": str(ids),
                    "reasons": ";".join(c.match_reason for c in result.candidates),
                    "passed": result.outcome == expected
                    and (entity_id is None or ids == [entity_id]),
                }
            )
    finally:
        provider.close()
        embedding.db.close()
    output = Path("artifacts/alpha_handoff/entity_results.csv")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"entity cases: {sum(r['passed'] for r in rows)}/{len(rows)}; failures preserved")


if __name__ == "__main__":
    main()
