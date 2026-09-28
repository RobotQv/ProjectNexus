"""依赖关卡与日期风险的确定性规则引擎。

约束（依据 docs/MODULE_CONTRACTS.md 第 5 节、team_modules/risk/README.md）：
- 只依赖标准库与 shared，不访问数据库、不调用大模型、不读机器当天日期。
- 输入是后端同一读事务给出的 Snapshot；正式 ID 只能来自该快照，候选只能来自本批 changes。
- 输出只使用 Finding 允许的字段，不新增契约外的结构。

两个正交维度：
- 关卡维度 → dependency_status（后继到没到关卡 x 前置达标没有）
- 时间维度 → timing_status（前置预计就绪日 vs 后继需要日）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import ValidationError

from shared.contracts import AnalysisResult, Finding, RiskPreview, Snapshot
from shared.errors import AppError
from shared.task_data import TaskRecord

RULE_VERSION = "risk-v1"

# ------------------------------------------------------------------ 状态枚举
SATISFIED = "satisfied"
CONDITION_UNMET = "condition_unmet"
BLOCKED_NOW = "blocked_now"
FINISH_CONDITION_UNMET = "finish_condition_unmet"
DATA_CONFLICT = "data_conflict"

FUTURE_RISK = "future_risk"
TIMING_UNKNOWN = "timing_unknown"
ON_TIME = "on_time"

NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
DONE = "done"
CANCELLED = "cancelled"

GATE_START = "start"
GATE_PROGRESS = "progress"
GATE_FINISH = "finish"

# ---------------------------------------------------------------- reason_codes
GATE_NOT_REACHED = "GATE_NOT_REACHED"
PREDECESSOR_PROGRESS_UNMET = "PREDECESSOR_PROGRESS_UNMET"
FINISH_CONDITION_UNMET_CODE = "FINISH_CONDITION_UNMET"
SUCCESSOR_COMPLETED_CONFLICT = "SUCCESSOR_COMPLETED_CONFLICT"
PREDECESSOR_CANCELLED = "PREDECESSOR_CANCELLED"
GATE_NEEDED_DATE_MISSING = "GATE_NEEDED_DATE_MISSING"
FORECAST_READY_DATE_MISSING = "FORECAST_READY_DATE_MISSING"
FORECAST_READY_DATE_FROM_TASK = "FORECAST_READY_DATE_FROM_TASK"
PREDECESSOR_FORECAST_LATE = "PREDECESSOR_FORECAST_LATE"
TASK_OVERDUE = "TASK_OVERDUE"
FORECAST_AFTER_DEADLINE = "FORECAST_AFTER_DEADLINE"
DEPENDENCY_REFERENCE_INVALID = "DEPENDENCY_REFERENCE_INVALID"
DEPENDENCY_INFO_INCOMPLETE = "DEPENDENCY_INFO_INCOMPLETE"
CANDIDATE_PREVIEW = "CANDIDATE_PREVIEW"

STATUS_TEXT = {
    SATISFIED: "前置任务已达到要求的进度，该依赖条件满足。",
    CONDITION_UNMET: "尚未到需要前置成果的关卡，先记录条件未满足；等后继推进到关卡后再复核。",
    BLOCKED_NOW: "后继已到达关卡，但前置任务未达到要求，当前无法越过该关卡；这不表示后继的其他工作全部停工。",
    FINISH_CONDITION_UNMET: "完成条件尚未满足，且后继任务尚未完成；不表示当前已经停工。",
    DATA_CONFLICT: "已有记录与依赖条件矛盾（后继已启动或已完成，而前置条件未满足）；只提示冲突，不自动改写任务状态。",
}

TIMING_TEXT = {
    FUTURE_RISK: "前置任务的预计就绪日期晚于后继需要该成果的日期，提示未来关卡风险；这是预警，不是确定延期。",
    ON_TIME: "前置任务的预计就绪日期不晚于需要日期，当前未见时间冲突。",
    TIMING_UNKNOWN: "缺少必要日期，无法判断时间风险；信息不足不等于低风险。",
}

# ------------------------------------------------------------------ 取值辅助


def _field(record: Any, name: str, default: Any = None) -> Any:
    """兼容 dict（快照给的就是 dict）与对象两种取值方式。"""
    if record is None:
        return default
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def as_date(value: Any) -> date | None:
    """把快照里的 ISO 字符串 / date / datetime 统一成 date；无法解析返回 None。

    注意：Snapshot.tasks / dependencies 是 model_dump(mode="json") 之后的 dict，
    日期在里面是字符串；而 snapshot.evaluation_date 仍是 date 对象，两者不能直接比较。
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def progress_of(task: Any) -> int:
    """进度统一成 0—100 整数。0 是合法值，不能用真假判断。"""
    value = as_int(_field(task, "progress"))
    if value is None:
        return 0
    return max(0, min(100, value))


def status_of(task: Any) -> str:
    return str(_field(task, "status") or NOT_STARTED)


def title_of(task: Any) -> str:
    title = _field(task, "title")
    return str(title) if title else "未命名任务"


def required_progress_of(dep: Any) -> int:
    value = as_int(_field(dep, "predecessor_required_progress"))
    if value is None:
        return 100
    return max(1, min(100, value))


def gate_kind_of(dep: Any) -> str:
    kind = _field(dep, "successor_gate")
    return kind if kind in {GATE_START, GATE_PROGRESS, GATE_FINISH} else GATE_PROGRESS


def gate_progress_of(dep: Any) -> int:
    """progress 关卡的目标百分比；正式依赖必有该字段，缺失时按"需完成"保守处理。"""
    value = as_int(_field(dep, "successor_gate_progress"))
    if value is None:
        return 100
    return max(1, min(100, value))


# ------------------------------------------------------------ 关卡维度判定


def successor_started(task: Any) -> bool:
    if status_of(task) in {IN_PROGRESS, DONE}:
        return True
    if _field(task, "actual_start_at") is not None:
        return True
    return progress_of(task) > 0


def successor_done(task: Any) -> bool:
    return status_of(task) == DONE or progress_of(task) >= 100


def gate_reached(kind: str, gate_progress: int, successor: Any) -> bool:
    """后继是否已经走到该关卡。"""
    if kind == GATE_START:
        return status_of(successor) != NOT_STARTED or progress_of(successor) > 0
    if kind == GATE_FINISH:
        return successor_done(successor)
    return progress_of(successor) >= gate_progress


def predecessor_ok(dep: Any, predecessor: Any) -> bool:
    """前置达标才 satisfied；已取消的前置任务不能自动算作达标。"""
    if status_of(predecessor) == CANCELLED:
        return False
    return progress_of(predecessor) >= required_progress_of(dep)


def judge_status(
    kind: str, gate_progress: int, dep: Any, predecessor: Any, successor: Any
) -> tuple[str, list[str]]:
    """判定 dependency_status。

    顺序即优先级：前置达标 > 已越过关卡却违约（数据冲突）> 未到关卡 > 完成条件 / 当前受阻。
    已冻结的对照：A70/B80 关卡90 -> condition_unmet；关卡80（恰好等于）-> blocked_now。
    """
    codes: list[str] = []
    if status_of(predecessor) == CANCELLED:
        codes.append(PREDECESSOR_CANCELLED)
    if predecessor_ok(dep, predecessor):
        return SATISFIED, codes
    if successor_done(successor):
        return DATA_CONFLICT, codes + [SUCCESSOR_COMPLETED_CONFLICT]
    if kind == GATE_START:
        if successor_started(successor):
            return DATA_CONFLICT, codes + [SUCCESSOR_COMPLETED_CONFLICT]
        return CONDITION_UNMET, codes + [GATE_NOT_REACHED]
    if kind == GATE_FINISH:
        return FINISH_CONDITION_UNMET, codes + [FINISH_CONDITION_UNMET_CODE]
    if not gate_reached(kind, gate_progress, successor):
        return CONDITION_UNMET, codes + [GATE_NOT_REACHED]
    return BLOCKED_NOW, codes + [PREDECESSOR_PROGRESS_UNMET]


# ------------------------------------------------------------ 时间维度判定


def readiness_date(dep: Any, predecessor: Any) -> tuple[date | None, list[str]]:
    """前置条件的预计就绪日期。

    优先用依赖自己的 predecessor_forecast_ready_on；只有要求达到 100% 时才允许回退到
    前置任务的整体 forecast_end（要求部分进度时禁止回退，否则必须报信息不足）。
    """
    direct = as_date(_field(dep, "predecessor_forecast_ready_on"))
    if direct is not None:
        return direct, []
    if required_progress_of(dep) < 100:
        return None, []
    fallback = as_date(_field(predecessor, "forecast_end"))
    if fallback is None:
        return None, []
    return fallback, [FORECAST_READY_DATE_FROM_TASK]


def judge_timing(dep: Any, predecessor: Any) -> tuple[str, list[str]]:
    """判定 timing_status，与关卡判断相互独立。缺任一必要日期都返回信息不足。"""
    needed = as_date(_field(dep, "gate_needed_on"))
    ready, codes = readiness_date(dep, predecessor)
    if ready is None:
        codes = [code for code in codes if code != FORECAST_READY_DATE_FROM_TASK]
        codes.append(FORECAST_READY_DATE_MISSING)
    if needed is None:
        codes.append(GATE_NEEDED_DATE_MISSING)
    if needed is None or ready is None:
        return TIMING_UNKNOWN, codes
    if ready > needed:
        return FUTURE_RISK, codes + [PREDECESSOR_FORECAST_LATE]
    return ON_TIME, codes


# ---------------------------------------------------------------- 说明文本


def gate_text(kind: str, gate_progress: int) -> str:
    if kind == GATE_START:
        return "开始即需要"
    if kind == GATE_FINISH:
        return "完成时"
    return f"到 {gate_progress}%"


def explain_dependency(
    dep: Any,
    predecessor: Any,
    successor: Any,
    kind: str,
    gate_progress: int,
    status: str,
    timing: str,
) -> str:
    return (
        f"依赖 #{_field(dep, 'id')}：前置《{title_of(predecessor)}》当前 {progress_of(predecessor)}%，"
        f"要求达到 {required_progress_of(dep)}%；后继《{title_of(successor)}》当前 "
        f"{progress_of(successor)}%，关卡为{gate_text(kind, gate_progress)}。"
        f"{STATUS_TEXT[status]}{TIMING_TEXT[timing]}"
    )


# ------------------------------------------------------- 任务级发现（非依赖类）


def task_findings(snapshot: Snapshot) -> list[Finding]:
    """任务超期与预计冲突。

    这两类不是依赖状态，按契约不填 dependency_status / timing_status，只用 reason_codes 说明。
    """
    today = as_date(snapshot.evaluation_date)
    findings: list[Finding] = []
    for task in snapshot.tasks:
        task_id = as_int(_field(task, "id"))
        if task_id is None:
            continue
        status = status_of(task)
        planned_end = as_date(_field(task, "planned_end"))
        forecast_end = as_date(_field(task, "forecast_end"))
        deadline = as_date(_field(task, "deadline"))
        # 日期相等不算超期；已完成 / 已取消的任务不判超期。
        if (
            today is not None
            and planned_end is not None
            and status not in {DONE, CANCELLED}
            and today > planned_end
        ):
            findings.append(
                Finding(
                    task_ids=[task_id],
                    reason_codes=[TASK_OVERDUE],
                    explanation=(
                        f"《{title_of(task)}》计划完成日 {planned_end.isoformat()} 早于评估日 "
                        f"{today.isoformat()}，当前状态为 {status}，已超过计划完成日期。"
                    ),
                )
            )
        # 预计冲突不等于已经逾期。
        if forecast_end is not None and deadline is not None and forecast_end > deadline:
            findings.append(
                Finding(
                    task_ids=[task_id],
                    reason_codes=[FORECAST_AFTER_DEADLINE],
                    explanation=(
                        f"《{title_of(task)}》预计完成日 {forecast_end.isoformat()} 晚于最晚截止日 "
                        f"{deadline.isoformat()}，属于预计冲突，不等于已经逾期。"
                    ),
                )
            )
    return findings


# ------------------------------------------------------------- 正式快照分析


def dependency_findings(snapshot: Snapshot) -> tuple[list[Finding], list[str]]:
    tasks: dict[int, Any] = {}
    for task in snapshot.tasks:
        task_id = as_int(_field(task, "id"))
        if task_id is not None:
            tasks[task_id] = task
    findings: list[Finding] = []
    warnings: list[str] = []
    seen: set[tuple] = set()
    for dep in snapshot.dependencies:
        dep_id = as_int(_field(dep, "id"))
        pred_id = as_int(_field(dep, "predecessor_task_id"))
        succ_id = as_int(_field(dep, "successor_task_id"))
        predecessor, successor = tasks.get(pred_id), tasks.get(succ_id)
        if pred_id is None or succ_id is None or predecessor is None or successor is None:
            warnings.append(
                f"依赖 #{dep_id} 引用的任务不在本快照内（可能任务已删除），已跳过，不产生结论项。"
            )
            continue
        if pred_id == succ_id:
            warnings.append(f"依赖 #{dep_id} 是自依赖，无法判断，已跳过。")
            continue
        kind = gate_kind_of(dep)
        gate_progress = gate_progress_of(dep)
        status, status_codes = judge_status(kind, gate_progress, dep, predecessor, successor)
        timing, timing_codes = judge_timing(dep, predecessor)
        key = (dep_id, status, timing)
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            Finding(
                task_ids=[pred_id, succ_id],
                dependency_id=dep_id,
                dependency_status=status,
                timing_status=timing,
                reason_codes=status_codes + [c for c in timing_codes if c not in status_codes],
                explanation=explain_dependency(
                    dep, predecessor, successor, kind, gate_progress, status, timing
                ),
            )
        )
    return findings, warnings


def analyze(snapshot: Snapshot) -> AnalysisResult:
    """正式快照分析：只读输入，返回标记与解释，不修改任何任务或依赖。"""
    state = snapshot if isinstance(snapshot, Snapshot) else Snapshot.model_validate(snapshot)
    findings, warnings = dependency_findings(state)
    findings = findings + task_findings(state)
    if not state.tasks and not state.dependencies:
        warnings.append("项目当前没有任务或依赖记录，未产生结论项；空结果不代表项目没有风险。")
    return AnalysisResult(rule_version=RULE_VERSION, findings=findings, warnings=warnings)


# ------------------------------------------------------------- 候选变更预览


def candidate_tasks(changes) -> dict[str, dict]:
    """把本批 create_task 候选变成临时任务，用于判断候选依赖；它们还没有正式 ID。"""
    tasks: dict[str, dict] = {}
    for change in changes:
        suggestion = change.suggestion
        if suggestion.suggestion_type != "create_task":
            continue
        payload = suggestion.proposed_payload or {}
        progress = payload.get("progress")
        tasks[change.key] = {
            "id": None,
            "title": payload.get("title") or "候选新任务",
            "status": payload.get("status") or NOT_STARTED,
            "progress": 0 if progress is None else progress,
            "planned_end": payload.get("planned_end"),
            "forecast_end": payload.get("forecast_end"),
            "deadline": payload.get("deadline"),
            "actual_start_at": payload.get("actual_start_at"),
        }
    return tasks


def _resolve_side(payload_id, key, formal: dict, candidates: dict):
    """返回 (任务, 候选 key, 正式 ID)；不在快照内的 ID 不放进 task_ids，避免越界引用。"""
    if payload_id is not None:
        task_id = as_int(payload_id)
        if task_id in formal:
            return formal[task_id], None, task_id
        return None, None, None
    if key is not None:
        return candidates.get(key), key, None
    return None, None, None


def judge_candidate_dependency(change, formal: dict, candidates: dict) -> Finding:
    payload = change.suggestion.proposed_payload or {}
    codes = [CANDIDATE_PREVIEW]
    predecessor, pred_key, pred_id = _resolve_side(
        payload.get("predecessor_task_id"), change.predecessor_key, formal, candidates
    )
    successor, succ_key, succ_id = _resolve_side(
        payload.get("successor_task_id"), change.successor_key, formal, candidates
    )
    candidate_keys = [change.key]
    for key in (pred_key, succ_key):
        if key and key not in candidate_keys:
            candidate_keys.append(key)
    task_ids = [value for value in (pred_id, succ_id) if value is not None]

    provided_predecessor = (
        payload.get("predecessor_task_id") is not None or change.predecessor_key is not None
    )
    provided_successor = (
        payload.get("successor_task_id") is not None or change.successor_key is not None
    )
    if predecessor is None or successor is None:
        # 给了引用却找不到 -> 数据不一致；根本没给引用 -> 信息还不完整，等审核时补齐。
        broken_reference = (provided_predecessor and predecessor is None) or (
            provided_successor and successor is None
        )
        return Finding(
            task_ids=task_ids,
            candidate_keys=candidate_keys,
            reason_codes=codes
            + [DEPENDENCY_REFERENCE_INVALID if broken_reference else DEPENDENCY_INFO_INCOMPLETE],
            explanation=(
                "候选依赖引用的任务不在本批候选中，也不在当前项目快照内，无法判断阻塞风险。"
                if broken_reference
                else "候选依赖缺少前置或后继任务信息，无法判断阻塞风险；请在正式审核时补齐后再判断。"
            ),
        )
    required = as_int(payload.get("predecessor_required_progress"))
    kind = payload.get("successor_gate")
    if (
        required is None
        or kind not in {GATE_START, GATE_PROGRESS, GATE_FINISH}
        or (kind == GATE_PROGRESS and payload.get("successor_gate_progress") is None)
    ):
        return Finding(
            task_ids=task_ids,
            candidate_keys=candidate_keys,
            reason_codes=codes + [DEPENDENCY_INFO_INCOMPLETE],
            explanation="候选依赖缺少关卡或前置要求进度，无法判断阻塞风险；请在正式审核时补齐后再判断。",
        )
    dep = {
        "id": None,
        "predecessor_task_id": pred_id,
        "successor_task_id": succ_id,
        "predecessor_required_progress": required,
        "successor_gate": kind,
        "successor_gate_progress": payload.get("successor_gate_progress"),
        "gate_needed_on": payload.get("gate_needed_on"),
        "predecessor_forecast_ready_on": payload.get("predecessor_forecast_ready_on"),
    }
    gate_progress = gate_progress_of(dep)
    status, status_codes = judge_status(kind, gate_progress, dep, predecessor, successor)
    timing, timing_codes = judge_timing(dep, predecessor)
    return Finding(
        task_ids=task_ids,
        candidate_keys=candidate_keys,
        dependency_status=status,
        timing_status=timing,
        reason_codes=codes
        + status_codes
        + [code for code in timing_codes if code not in status_codes],
        explanation=(
            f"候选依赖（尚未生效）：前置《{title_of(predecessor)}》当前 {progress_of(predecessor)}%，"
            f"要求达到 {required}%；后继《{title_of(successor)}》当前 {progress_of(successor)}%，"
            f"关卡为{gate_text(kind, gate_progress)}。{STATUS_TEXT[status]}{TIMING_TEXT[timing]}"
        ),
    )


def analyze_preview(preview: RiskPreview) -> AnalysisResult:
    """分析尚未生效的候选变更；候选只用 candidate_keys 引用，不编造正式 ID。

    先在副本中应用任务更新，再判断候选依赖及受更新影响的正式依赖。
    """
    state = preview if isinstance(preview, RiskPreview) else RiskPreview.model_validate(preview)
    formal: dict[int, Any] = {}
    for task in state.snapshot.tasks:
        task_id = as_int(_field(task, "id"))
        if task_id is not None:
            formal[task_id] = task
    candidates = candidate_tasks(state.changes)
    warnings: list[str] = []
    updated: dict[int, list[str]] = {}
    touched: dict[int, dict] = {}
    for change in state.changes:
        if change.suggestion.suggestion_type != "update_task":
            continue
        payload = change.suggestion.proposed_payload
        task_id = payload["task_id"]
        if task_id not in formal:
            raise AppError("candidate_task_missing", "候选更新目标不在项目快照内", 422)
        if formal[task_id]["version"] != payload["expected_version"]:
            raise AppError(
                "candidate_version_conflict", "候选更新的任务版本已变化，请重新核对", 409
            )
        previous = touched.setdefault(task_id, {})
        changes = payload["changes"]
        if any(k in previous and previous[k] != v for k, v in changes.items()):
            raise AppError("candidate_update_conflict", "同批任务更新包含冲突字段，请分别预览", 422)
        previous.update(changes)
        try:
            formal[task_id] = TaskRecord.model_validate(formal[task_id] | changes).model_dump(
                mode="json"
            )
        except ValidationError:
            raise AppError(
                "candidate_task_invalid", "候选更新后的任务字段不一致，请核对状态、进度和日期", 422
            ) from None
        updated.setdefault(task_id, []).append(change.key)

    changed_findings: list[Finding] = []
    if updated:
        changed_state = state.snapshot.model_copy(
            update={
                "tasks": list(formal.values()),
                "dependencies": [
                    d
                    for d in state.snapshot.dependencies
                    if d["predecessor_task_id"] in updated or d["successor_task_id"] in updated
                ],
            }
        )
        changed_findings, dep_warnings = dependency_findings(changed_state)
        warnings.extend(dep_warnings)
        changed_findings.extend(
            f for f in task_findings(changed_state) if any(i in updated for i in f.task_ids)
        )
        for finding in changed_findings:
            finding.candidate_keys = [key for i in finding.task_ids for key in updated.get(i, [])]
            finding.reason_codes.insert(0, CANDIDATE_PREVIEW)
            finding.explanation = "候选更新预览（尚未生效）：" + finding.explanation
    if candidates:
        warnings.append(
            "候选新建任务尚未创建，按候选载荷中的初始状态参与判断（未开始或载荷给出的进度与日期）。"
        )
    dependency_changes = [
        change
        for change in state.changes
        if change.suggestion.suggestion_type == "propose_dependency"
    ]
    if not dependency_changes and not updated:
        warnings.append("本批候选没有依赖类变更，未产生依赖结论项；这不代表候选变更没有风险。")
        return AnalysisResult(rule_version=RULE_VERSION, findings=[], warnings=warnings)
    warnings.append("以下结论针对尚未生效的候选变更，仅供审核参考，不代表已经写入项目。")
    findings = changed_findings + [
        judge_candidate_dependency(change, formal, candidates) for change in dependency_changes
    ]
    return AnalysisResult(rule_version=RULE_VERSION, findings=findings, warnings=warnings)
