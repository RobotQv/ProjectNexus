"""结构约束：防止后续把算法实现耦合回业务库，或把公共契约复制出两个版本。"""

import ast
import inspect
from pathlib import Path

from app.core.errors import AppError as LegacyError
from app.integrations import contracts as legacy
from app.integrations.adapters import build_modules
from app.llm import DisabledLLM
from app.llm import LLMResult as LegacyResult
from shared import contracts
from shared.errors import AppError
from shared.llm import LLMResult
from team_modules.main_rag.adapter import MainRAGAdapter
from team_modules.risk.adapter import RiskAdapter
from team_modules.workflow.adapters import EntityAdapter, WorkflowAdapter

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_types_are_exactly_same_classes():
    assert legacy.Modules is contracts.Modules
    assert legacy.Snapshot is contracts.Snapshot
    assert legacy.Evidence is contracts.Evidence
    assert LegacyError is AppError
    assert LegacyResult is LLMResult


def test_shared_and_algorithm_import_boundaries():
    paths = list((ROOT / "shared").rglob("*.py"))
    for name in ("main_rag", "workflow", "risk"):
        paths.extend((ROOT / "team_modules" / name).rglob("*.py"))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        current = path.relative_to(ROOT).parts
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                # 相对导入可在本职责包内部使用，但不能跳到相邻职责或根 app。
                if node.level:
                    owner_depth = 2 if current[0] == "team_modules" else 1
                    assert node.level <= len(current) - owner_depth, str(path)
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                continue
            for name in names:
                assert name != "app" and not name.startswith("app."), (path, name)
                if current[0] == "shared":
                    assert name.split(".")[0] not in {
                        "fastapi",
                        "sqlalchemy",
                        "httpx",
                        "team_modules",
                    }, (path, name)
                if name.startswith("team_modules"):
                    assert current[0] == "team_modules", (path, name)
                    owner = "team_modules." + current[1]
                    assert name == owner or name.startswith(owner + "."), (path, name)


def test_adapter_methods_match_protocol_signatures():
    for protocol, adapter, methods in [
        (contracts.MainRAG, MainRAGAdapter, ["parse", "ingest", "retrieve", "delete"]),
        (contracts.EntityResolver, EntityAdapter, ["sync", "resolve"]),
        (contracts.Workflow, WorkflowAdapter, ["extract"]),
        (contracts.RiskAnalyzer, RiskAdapter, ["analyze"]),
    ]:
        for method in methods:
            assert inspect.signature(getattr(protocol, method), eval_str=True) == inspect.signature(
                getattr(adapter, method), eval_str=True
            )


def test_factory_loads_all_local_adapters(env):
    settings = env.settings.model_copy(
        update={"module_factory": "team_modules.factory:build_modules"}
    )
    modules = build_modules(settings, DisabledLLM())
    assert isinstance(modules.main_rag, MainRAGAdapter)
    assert isinstance(modules.entities, EntityAdapter)
    assert isinstance(modules.workflow, WorkflowAdapter)
    assert isinstance(modules.risk, RiskAdapter)
    assert modules.is_demo is False


def test_each_owner_has_readme():
    for directory in [
        "app",
        "frontend",
        "tests",
        "team_modules/main_rag",
        "team_modules/workflow",
        "team_modules/risk",
    ]:
        assert (ROOT / directory / "README.md").is_file()
