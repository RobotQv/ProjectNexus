"""依赖 / 风险规则的离线单测。

不需要数据库、账号、HTTP 或模型：全部用内存里的 Snapshot / RiskPreview 构造。
本文件不 import pytest，因此既能被 pytest 收集，也能被 run_tests_without_pytest.py 直接执行。
"""

from datetime import date

from shared.contracts import CandidateChange, RiskPreview, Snapshot, SuggestionDraft
from team_modules.risk import rules
from team_modules.risk.adapter import RiskAdapter

EVAL = date(2026, 9, 15)

VALID_STATUS = {
    "satisfied",
    "condition_unmet",
    "blocked_now",
    "finish_condition_unmet",
    "data_conflict",
}
VALID_TIMING = {"future_risk", "timing_unknown", "on_time"}


def task(
    task_id,
    *,
    status="in_progress",
    progress=0,
    planned_end=None,
    forecast_end=None,
    deadline=None,
    title=None,
    project_id=1,
):
    """构造一条能被 TaskRecord 校验通过的快照任务记录（字段必须齐全）。"""
    if status == "done":
        progress = 100
    if status == "not_started":
        progress = 0
    return {
        "id": task_id,
        "project_id": project_id,
        "title": title or f"任务{task_id}",
        "description": None,
        "assignee_id": None,
        "module_name": None,
        "tags": [],
        "aliases": [],
        "status": status,
        "progress": progress,
        "planned_start": None,
        "planned_end": planned_end,
        "forecast_end": forecast_end,
        "deadline": deadline,
        "actual_start_at": None,
        "actual_end_at": None,
        "forecast_updated_at": None,
        "forecast_by": None,
        "progress_updated_at": "2026-09-10T02:00:00Z",
        "source_suggestion_id": None,
        "version": 1,
        "created_at": "2026-09-01T02:00:00Z",
        "updated_at": "2026-09-10T02:00:00Z",
        "deleted_at": None,
    }


def dep(
    dep_id,
    pred,
    succ,
    *,
    required=100,
    gate="progress",
    gate_progress=90,
    needed=None,
    ready=None,
    project_id=1,
):
    return {
        "id": dep_id,
        "project_id": project_id,
        "predecessor_task_id": pred,
        "successor_task_id": succ,
        "predecessor_required_progress": required,
        "successor_gate": gate,
        "successor_gate_progress": gate_progress if gate == "progress" else None,
        "gate_needed_on": needed,
        "predecessor_forecast_ready_on": ready,
        "description": None,
        "source_suggestion_id": None,
        "version": 1,
        "created_at": "2026-09-01T02:00:00Z",
        "updated_at": "2026-09-10T02:00:00Z",
    }


def snapshot(tasks=(), deps=(), *, evaluation_date=EVAL):
    return Snapshot(
        project_id=1,
        timezone="Asia/Shanghai",
        evaluation_date=evaluation_date,
        tasks=list(tasks),
        dependencies=list(deps),
    )


def dependency_findings(result):
    return [item for item in result.findings if item.dependency_id is not None]


def only_dependency_finding(result):
    items = dependency_findings(result)
    assert len(items) == 1, f"期望恰好一条依赖结论项，实际 {len(items)}"
    return items[0]


def codes(finding):
    return list(finding.reason_codes)


# ---------------------------------------------------------------- 关卡维度判定


def test_progress_gate_not_reached_is_condition_unmet():
    """A70 / B80，关卡 90：尚未到关卡，不是当前阻塞。"""
    state = snapshot(
        [task(1, progress=70), task(2, progress=80)],
        [dep(10, 1, 2, gate_progress=90)],
    )
    finding = only_dependency_finding(RiskAdapter().analyze(state))

    assert finding.dependency_status == "condition_unmet"
    assert rules.GATE_NOT_REACHED in codes(finding)
    assert finding.task_ids == [1, 2]


def test_progress_gate_reached_and_unmet_is_blocked_now():
    """A70 / B80，关卡 80：恰好到关卡，当前无法越过。"""
    state = snapshot(
        [task(1, progress=70), task(2, progress=80)],
        [dep(10, 1, 2, gate_progress=80)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "blocked_now"
    assert rules.PREDECESSOR_PROGRESS_UNMET in codes(finding)
    assert "无法越过该关卡" in finding.explanation


def test_progress_gate_satisfied_when_predecessor_reaches_required():
    state = snapshot(
        [task(1, progress=100), task(2, progress=80)],
        [dep(10, 1, 2, gate_progress=80)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "satisfied"
    assert finding.dependency_id == 10


def test_partial_required_progress_is_enough_for_satisfied():
    state = snapshot(
        [task(1, progress=60), task(2, progress=80)],
        [dep(10, 1, 2, required=50, gate_progress=80)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "satisfied"


def test_start_gate_not_started_is_condition_unmet():
    state = snapshot(
        [task(1, progress=70), task(2, status="not_started")],
        [dep(10, 1, 2, gate="start")],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "condition_unmet"
    assert "开始即需要" in finding.explanation


# ------------------------------------------------------------------ 冲突与边界


def test_start_gate_started_without_condition_is_data_conflict():
    """已启动却违反 start 关卡：标数据冲突。"""
    state = snapshot(
        [task(1, progress=70), task(2, progress=30)],
        [dep(10, 1, 2, gate="start")],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "data_conflict"
    assert rules.SUCCESSOR_COMPLETED_CONFLICT in codes(finding)


def test_finish_gate_unfinished_is_finish_condition_unmet():
    state = snapshot(
        [task(1, progress=70), task(2, progress=80)],
        [dep(10, 1, 2, gate="finish")],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "finish_condition_unmet"
    assert rules.FINISH_CONDITION_UNMET_CODE in codes(finding)
    assert "不表示当前已经停工" in finding.explanation


def test_successor_done_without_condition_is_data_conflict():
    """后继已完成却违反前置条件：标冲突，不撤销它已完成的状态。"""
    state = snapshot(
        [task(1, progress=70), task(2, status="done")],
        [dep(10, 1, 2, gate_progress=90)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "data_conflict"
    assert "不自动改写" in finding.explanation


def test_cancelled_predecessor_never_satisfied():
    """取消的前置任务即使进度是 100，也不能算作达标。"""
    state = snapshot(
        [task(1, status="cancelled", progress=100), task(2, progress=80)],
        [dep(10, 1, 2, gate_progress=70)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status != "satisfied"
    assert rules.PREDECESSOR_CANCELLED in codes(finding)


def test_cancelled_predecessor_with_reached_gate_is_not_satisfied():
    state = snapshot(
        [task(1, status="cancelled", progress=100), task(2, progress=95)],
        [dep(10, 1, 2, gate_progress=90)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "blocked_now"
    assert rules.PREDECESSOR_CANCELLED in codes(finding)


def test_zero_progress_is_not_treated_as_missing():
    """进度 0 是合法值：不能因为 0 为假就当成"缺少进度"。"""
    state = snapshot(
        [task(1, status="not_started"), task(2, status="not_started")],
        [dep(10, 1, 2, gate_progress=50)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.dependency_status == "condition_unmet"
    assert "当前 0%" in finding.explanation


# ---------------------------------------------------------------- 时间维度判定


def test_future_risk_when_forecast_is_later_than_needed():
    state = snapshot(
        [task(1, progress=100), task(2, progress=80)],
        [
            dep(
                10,
                1,
                2,
                gate_progress=80,
                needed=date(2026, 9, 19),
                ready=date(2026, 9, 20),
            )
        ],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.timing_status == "future_risk"
    assert rules.PREDECESSOR_FORECAST_LATE in codes(finding)
    assert "预警" in finding.explanation


def test_on_time_when_forecast_is_not_later_than_needed():
    state = snapshot(
        [task(1, progress=100), task(2, progress=80)],
        [
            dep(
                10,
                1,
                2,
                gate_progress=80,
                needed=date(2026, 9, 19),
                ready=date(2026, 9, 19),
            )
        ],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.timing_status == "on_time"


def test_timing_unknown_when_needed_date_is_missing():
    state = snapshot(
        [task(1, progress=100), task(2, progress=80)],
        [dep(10, 1, 2, gate_progress=80, ready=date(2026, 9, 20))],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.timing_status == "timing_unknown"
    assert rules.GATE_NEEDED_DATE_MISSING in codes(finding)
    assert "不等于低风险" in finding.explanation


def test_partial_requirement_must_not_reuse_task_forecast_end():
    """前置只要求 50% 时，不能拿整个任务的 forecast_end 顶替条件就绪日期。"""
    state = snapshot(
        [task(1, progress=60, forecast_end=date(2026, 9, 25)), task(2, progress=80)],
        [dep(10, 1, 2, required=50, gate_progress=80, needed=date(2026, 9, 19))],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.timing_status == "timing_unknown"
    assert rules.FORECAST_READY_DATE_MISSING in codes(finding)
    assert rules.FORECAST_READY_DATE_FROM_TASK not in codes(finding)


def test_full_requirement_may_fall_back_to_task_forecast_end():
    """要求 100% 时才允许按审计规则回退，且必须标出用了回退来源。"""
    state = snapshot(
        [task(1, progress=60, forecast_end=date(2026, 9, 20)), task(2, progress=80)],
        [dep(10, 1, 2, required=100, gate_progress=80, needed=date(2026, 9, 19))],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.timing_status == "future_risk"
    assert rules.FORECAST_READY_DATE_FROM_TASK in codes(finding)
    assert rules.PREDECESSOR_FORECAST_LATE in codes(finding)


def test_timing_unknown_when_both_dates_are_missing():
    state = snapshot(
        [task(1, progress=100), task(2, progress=80)],
        [dep(10, 1, 2, gate_progress=80)],
    )
    finding = only_dependency_finding(rules.analyze(state))

    assert finding.timing_status == "timing_unknown"
    assert rules.GATE_NEEDED_DATE_MISSING in codes(finding)
    assert rules.FORECAST_READY_DATE_MISSING in codes(finding)


# ------------------------------------------------- 任务级发现与输入稳健性


def test_task_overdue_when_planned_end_is_before_evaluation_date():
    state = snapshot([task(1, progress=40, planned_end=date(2026, 9, 10))], [])
    result = rules.analyze(state)

    overdue = [item for item in result.findings if rules.TASK_OVERDUE in item.reason_codes]
    assert len(overdue) == 1
    assert overdue[0].task_ids == [1]
    # 超期不是依赖状态：两个状态字段留空，只用 reason_codes 表达。
    assert overdue[0].dependency_status is None
    assert overdue[0].timing_status is None


def test_task_on_the_evaluation_day_is_not_overdue():
    state = snapshot([task(1, progress=40, planned_end=EVAL)], [])
    result = rules.analyze(state)

    assert [item for item in result.findings if rules.TASK_OVERDUE in item.reason_codes] == []


def test_done_task_is_not_reported_overdue():
    state = snapshot([task(1, status="done", planned_end=date(2026, 8, 1))], [])
    result = rules.analyze(state)

    assert result.findings == []


def test_forecast_after_deadline_is_conflict_not_overdue():
    state = snapshot(
        [task(1, progress=40, forecast_end=date(2026, 9, 30), deadline=date(2026, 9, 20))],
        [],
    )
    items = [
        item
        for item in rules.analyze(state).findings
        if rules.FORECAST_AFTER_DEADLINE in item.reason_codes
    ]

    assert len(items) == 1
    assert "不等于已经逾期" in items[0].explanation


def test_dependency_referencing_missing_task_only_becomes_warning():
    """任务被删除但依赖仍在：只提示，不产生结论项，也不越界引用 ID。"""
    state = snapshot([task(1, progress=70)], [dep(10, 1, 999, gate_progress=80)])
    result = rules.analyze(state)

    assert result.findings == []
    assert any("不在本快照内" in text for text in result.warnings)


def test_empty_snapshot_returns_no_findings_and_explains():
    result = rules.analyze(snapshot())

    assert result.findings == []
    assert any("不代表项目没有风险" in text for text in result.warnings)


def test_every_finding_uses_only_contract_values_and_scope():
    state = snapshot(
        [task(1, progress=70, planned_end=date(2026, 9, 1)), task(2, status="done")],
        [dep(10, 1, 2, gate_progress=90, needed=date(2026, 9, 19), ready=date(2026, 9, 20))],
    )
    result = rules.analyze(state)
    task_ids = {item["id"] for item in state.tasks}
    dependency_ids = {item["id"] for item in state.dependencies}

    assert result.findings, "该样例应当产生结论项"
    for finding in result.findings:
        assert finding.dependency_status is None or finding.dependency_status in VALID_STATUS
        assert finding.timing_status is None or finding.timing_status in VALID_TIMING
        assert finding.reason_codes, "每条结论至少给出一个 reason_code"
        assert finding.explanation
        # 后端会校验：正式 ID 只能来自本快照，否则整次分析会被判为越界。
        assert set(finding.task_ids) <= task_ids
        assert finding.dependency_id is None or finding.dependency_id in dependency_ids
        assert finding.candidate_keys == []


def test_findings_are_deterministic_and_not_duplicated():
    state = snapshot(
        [task(1, progress=70), task(2, progress=80)],
        [dep(10, 1, 2, gate_progress=80), dep(11, 1, 2, gate_progress=80)],
    )
    first = rules.analyze(state)
    second = rules.analyze(state)

    keys = [
        (item.dependency_id, item.dependency_status, item.timing_status) for item in first.findings
    ]
    assert len(keys) == len(set(keys)), "同一条依赖不应重复出现"
    assert [item.model_dump() for item in first.findings] == [
        item.model_dump() for item in second.findings
    ]


def test_rule_version_is_frozen():
    assert rules.RULE_VERSION == "risk-v1"
    assert rules.analyze(snapshot()).rule_version == "risk-v1"


# ---------------------------------------------------------------- 候选变更预览


def suggestion(suggestion_type, payload):
    return SuggestionDraft(suggestion_type=suggestion_type, proposed_payload=payload)


def change(key, suggestion_type, payload, *, predecessor_key=None, successor_key=None):
    return CandidateChange(
        key=key,
        suggestion=suggestion(suggestion_type, payload),
        predecessor_key=predecessor_key,
        successor_key=successor_key,
    )


def preview(changes, tasks=(), deps=()):
    return RiskPreview(snapshot=snapshot(tasks, deps), changes=list(changes))


def test_preview_candidate_dependency_references_only_keys():
    """两侧都是本批新建任务：只能用 candidate_keys，不能编造正式 ID。"""
    state = preview(
        [
            change("new-a", "create_task", {"title": "新任务A"}),
            change("new-b", "create_task", {"title": "新任务B"}),
            change(
                "dep-1",
                "propose_dependency",
                {
                    "predecessor_required_progress": 100,
                    "successor_gate": "progress",
                    "successor_gate_progress": 50,
                },
                predecessor_key="new-a",
                successor_key="new-b",
            ),
        ]
    )
    result = rules.analyze_preview(state)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.task_ids == [], "候选任务没有正式 ID，不能放进 task_ids"
    assert set(finding.candidate_keys) == {"dep-1", "new-a", "new-b"}
    assert finding.dependency_status == "condition_unmet"
    assert rules.CANDIDATE_PREVIEW in codes(finding)
    assert any("尚未生效" in text for text in result.warnings)


def test_preview_formal_predecessor_keeps_task_id():
    state = preview(
        [
            change("new-b", "create_task", {"title": "新任务B"}),
            change(
                "dep-1",
                "propose_dependency",
                {
                    "predecessor_task_id": 1,
                    "predecessor_required_progress": 100,
                    "successor_gate": "start",
                },
                successor_key="new-b",
            ),
        ],
        tasks=[task(1, progress=100)],
    )
    finding = rules.analyze_preview(state).findings[0]

    assert finding.task_ids == [1], "正式任务仍用真实 ID"
    assert set(finding.candidate_keys) == {"dep-1", "new-b"}
    assert finding.dependency_status == "satisfied"


def test_preview_incomplete_candidate_is_not_guessed():
    state = preview([change("dep-1", "propose_dependency", {"description": "联调依赖"})])
    finding = rules.analyze_preview(state).findings[0]

    assert finding.dependency_status is None
    assert finding.timing_status is None
    assert rules.DEPENDENCY_INFO_INCOMPLETE in codes(finding)


def test_preview_without_dependency_changes_returns_empty():
    result = rules.analyze_preview(preview([change("new-a", "create_task", {"title": "新任务A"})]))

    assert result.findings == []
    assert any("依赖类变更" in text for text in result.warnings)


def test_preview_unknown_task_id_is_not_put_into_task_ids():
    """候选载荷写了快照里不存在的 ID：不能放进 task_ids，否则后端会判越界。"""
    state = preview(
        [
            change(
                "dep-1",
                "propose_dependency",
                {
                    "predecessor_task_id": 999,
                    "predecessor_required_progress": 100,
                    "successor_gate": "start",
                },
            )
        ]
    )
    finding = rules.analyze_preview(state).findings[0]

    assert finding.task_ids == []
    assert rules.DEPENDENCY_REFERENCE_INVALID in codes(finding)
