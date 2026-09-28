"""契约冒烟：风险模块可以脱离数据库与账号，只用内存里的 Snapshot 运行。

骨架期这里断言 module_unavailable；真实规则接入后改为断言"空快照返回空结论 + 明确提示"，
因为空结果不能伪装成"无风险"。
"""

from datetime import date

from shared.contracts import RiskPreview, Snapshot
from team_modules.risk.adapter import RiskAdapter


def empty_snapshot():
    return Snapshot(
        project_id=1,
        timezone="Asia/Shanghai",
        evaluation_date=date(2026, 9, 15),
        tasks=[],
        dependencies=[],
    )


def test_risk_snapshot_needs_no_database_or_account():
    result = RiskAdapter().analyze(empty_snapshot())

    assert result.rule_version == "risk-v1"
    assert result.findings == []
    # 必须明确说明空结果的含义，不能让人读成"项目没有风险"。
    assert any("不代表" in text for text in result.warnings)


def test_risk_preview_needs_no_database_or_account():
    result = RiskAdapter().analyze_candidates(RiskPreview(snapshot=empty_snapshot(), changes=[]))

    assert result.rule_version == "risk-v1"
    assert result.findings == []
    assert any("依赖类变更" in text for text in result.warnings)
