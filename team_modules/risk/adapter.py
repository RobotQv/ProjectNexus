"""依赖 / 风险模块接入实现。

职责：读取主干已取好的快照，输出确定性的关卡与日期判断，只做标记和提示。
约束：不连接数据库、不调用大模型、不读机器当天日期；正式 ID 只能来自输入快照。

规则细节、reason_codes 与冻结矩阵见 rules.py 与本目录 README.md。
"""

from shared.contracts import AnalysisResult, RiskPreview, Snapshot

from . import rules


class RiskAdapter:
    def analyze(self, snapshot: Snapshot) -> AnalysisResult:
        """正式快照分析：前置/后继关卡、日期风险、超期与预计冲突。"""
        return rules.analyze(snapshot)

    def analyze_candidates(self, preview: RiskPreview) -> AnalysisResult:
        """候选变更预览：候选以 key 引用，不伪造正式 ID，也不让候选自动生效。"""
        return rules.analyze_preview(preview)
