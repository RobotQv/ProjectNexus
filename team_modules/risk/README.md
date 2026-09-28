# 项目依赖与风险判断负责人工作区

## 负责需求

实现可复现的依赖关卡、日期风险、信息不足和数据冲突判断，以及审计要求的潜在影响解释。输入是后端已经取好的项目快照，输出规则结果，不调用大模型代替确定性规则。

本目录 adapter.py 已预留 analyze；目前明确报未接入，不是“项目无风险”。算法写本目录，可拆 graph/、rules/ 等内部文件。

## 已提供的候选输入与自动触发接口

AI 可以识别潜在依赖，本模块重点判断这些依赖是否有阻塞风险。工作流应能通过注入的方法传入当前任务/依赖状态和候选变更，审核前即可得到风险提示；候选不必先存成正式任务或依赖。

相关正式任务/依赖变化后自动检查，只标记和提示当前阻塞、潜在风险或信息不足，不自动修改状态。不做定时检查、外部通知、复杂评分系统。

analyze(Snapshot) 覆盖正式快照，新增 analyze_candidates(RiskPreview) 分析 snapshot 与 changes。后端已接好工具、预览 HTTP 和正式变更检查 Job；本目录两个方法仍需你实现真实规则。未创建候选用 key 标识，不能假冒数据库 ID；工作流通过注入工具调用，不导入本目录实现。

## 接口输入输出

```text
analyze(snapshot: shared.contracts.Snapshot) → AnalysisResult
analyze_candidates(preview: shared.contracts.RiskPreview) → AnalysisResult
```

Snapshot 包含 project_id、timezone、evaluation_date、tasks、dependencies。同一次快照的两组记录来自同一数据库读事务，不再自行访问 SQLite，也不要调用主 RAG/工作流拼另一时刻的数据。

Task 记录包括 id/version、status/progress、planned_start/planned_end、forecast_end、deadline、actual_start_at/actual_end_at、progress_updated_at 等。Dependency 包括前置/后置任务 ID、前置要求进度、后置关卡及百分比、需要日期和条件预计就绪日期。完整字段可查公共契约及后端 /docs；不要在本目录重新定义不同语义的同名字段。

AnalysisResult 必须包含 rule_version、findings、warnings。Finding 包含 task_ids、可选 dependency_id、dependency_status、timing_status、reason_codes、explanation。所有正式 ID 必须来自输入快照，candidate_keys 必须来自本次 changes；输出不修改任务或写数据库。候选 key 引用新任务的格式见 [数据约定第 6 节](../../../docs/DATA_CONTRACTS.md)。

## 已有审计明确的规则

- 依赖方向 predecessor → successor；后端创建/编辑时已拒绝自依赖、重复、跨项目和环。算法仍需对异常输入作出可解释处理，不能把坏图当正常图。

---

## 实现说明（成员C / 演示成员己，2026-09-21）

本目录已接入真实规则：`adapter.py` 只做转发，规则实现与说明见 `rules.py`。
`rule_version = "risk-v1"`（后端 `analysis_runs.rule_version` 是 String(64)，版本号保持短字符串）。

- `analyze(snapshot)`：正式快照的依赖关卡、日期风险、任务超期与预计冲突。
- `analyze_candidates(preview)`：候选依赖预览；候选只用 `candidate_keys` 引用，不写库、不生效。
- 只使用标准库 `datetime` 与 `shared`，**无第三方依赖**，可脱离数据库与账号单测。

### 一、dependency_status 判定优先级

`前置达标` > `已越过关卡却违约（数据冲突）` > `未到关卡` > `完成条件 / 当前受阻`。

| 场景 | dependency_status | 主要 reason_code |
| --- | --- | --- |
| 前置进度 ≥ 要求进度（含恰好相等） | satisfied | — |
| 后继已完成，但前置不达标 | data_conflict | SUCCESSOR_COMPLETED_CONFLICT |
| start 关卡：后继已启动，前置不达标 | data_conflict | SUCCESSOR_COMPLETED_CONFLICT |
| progress 关卡：后继进度 < 关卡 | condition_unmet | GATE_NOT_REACHED |
| start 关卡：后继未启动 | condition_unmet | GATE_NOT_REACHED |
| progress 关卡：后继进度 = 关卡且前置不达标 | blocked_now | PREDECESSOR_PROGRESS_UNMET |
| finish 关卡：后继未完成且前置不达标 | finish_condition_unmet | FINISH_CONDITION_UNMET |
| 前置任务状态为 cancelled | 绝不 satisfied（其余同上） | PREDECESSOR_CANCELLED |

已冻结对照（对齐开题报告 2.4 与本目录既有说明）：A70/B80 关卡 90 → `condition_unmet`；
A70/B80 关卡 80 → `blocked_now`（恰好到关卡，当前无法越过）。

### 二、timing_status 判定

| 条件 | timing_status | reason_code |
| --- | --- | --- |
| 缺 `gate_needed_on` 或缺预计就绪日期 | timing_unknown | GATE_NEEDED_DATE_MISSING / FORECAST_READY_DATE_MISSING |
| 预计就绪日 严格晚于 需要日 | future_risk | PREDECESSOR_FORECAST_LATE |
| 预计就绪日 ≤ 需要日 | on_time | — |

预计就绪日优先取依赖自己的 `predecessor_forecast_ready_on`；只有 `predecessor_required_progress = 100`
时才允许回退到前置任务的 `forecast_end`，并额外标 `FORECAST_READY_DATE_FROM_TASK` 说明来源。
要求部分进度时**禁止**回退，必须报信息不足。

### 三、任务级发现（非依赖）

| 发现 | 判定 | reason_code |
| --- | --- | --- |
| 任务超期 | `evaluation_date` 严格晚于 `planned_end`，且状态不是 done/cancelled（当天不算超期） | TASK_OVERDUE |
| 预计冲突 | `forecast_end` 晚于 `deadline`（不等于已经逾期） | FORECAST_AFTER_DEADLINE |

这两类不是依赖状态，按契约**不填** `dependency_status` / `timing_status`，只用 reason_codes 说明。

### 四、reason_codes 速查

| reason_code | 含义 |
| --- | --- |
| GATE_NOT_REACHED | 后继尚未到关卡，暂不判定受阻 |
| PREDECESSOR_PROGRESS_UNMET | 已到关卡但前置未达到要求进度 |
| FINISH_CONDITION_UNMET | finish 关卡条件未满足且后继未完成 |
| SUCCESSOR_COMPLETED_CONFLICT | 后继已启动或已完成，却违反前置条件（数据冲突） |
| PREDECESSOR_CANCELLED | 前置任务已取消，不能视为达标 |
| GATE_NEEDED_DATE_MISSING | 缺"后继需要该成果的日期" |
| FORECAST_READY_DATE_MISSING | 缺"前置条件预计就绪日期" |
| FORECAST_READY_DATE_FROM_TASK | 预计就绪日期按审计规则回退自前置任务整体 forecast_end |
| PREDECESSOR_FORECAST_LATE | 预计就绪晚于需要日期（未来关卡风险） |
| TASK_OVERDUE | 任务已超过计划完成日期 |
| FORECAST_AFTER_DEADLINE | 预计完成晚于最晚截止（预计冲突） |
| DEPENDENCY_REFERENCE_INVALID | 依赖引用的任务不在快照内（任务可能已删除） |
| DEPENDENCY_INFO_INCOMPLETE | 候选依赖信息不全，无法判断 |
| CANDIDATE_PREVIEW | 该结论针对尚未生效的候选变更 |

### 五、实现取舍（已冻结，改口径前先与负责人确认）

1. **不使用机器当天日期**：一律使用 `snapshot.evaluation_date`。
2. **日期统一转换**：`Snapshot.tasks/dependencies` 是 `model_dump(mode="json")` 后的 dict，日期在
   里面是字符串；`snapshot.evaluation_date` 仍是 `date` 对象。两者不能直接比较，统一用 `as_date()`。
3. **进度 0 是合法值**：全部用 `is not None` 判断，不用真假判断。
4. **不新增契约外字段**：只使用 `Finding` 已有的 7 个字段；影响路径等扩展先与后端确认再改契约。
5. **输出范围自检**：`task_ids` 只含快照内任务、`dependency_id` 只含快照内依赖，正式分析
   `candidate_keys` 恒为空。
6. **引用不到的任务只报警告**：不产生结论项，也不把该 ID 放进 `task_ids`（否则后端判越界并 502）。
7. **进度越界的历史数据按 0—100 截断**，避免规则崩溃。
8. **cancelled 前置永不达标**，但不倒写任何任务状态。
9. **候选预览先应用任务更新副本**，再判断候选依赖及受更新影响的已有依赖和日期风险；不修改输入快照。整合版拒绝过期任务版本和同批冲突更新。
10. **每次调用新建 findings / warnings 列表**，不复用模块级列表（Worker 会原地追加"快照已变化"提示）。
11. 结论按输入顺序输出，并按 `(dependency_id, status, timing)` 去重，保证可复现。

### 六、测试与复现

```powershell
# 在项目包根（含 shared/ 与 app/）
.\.venv\Scripts\python.exe -m pytest team_modules/risk/tests
```

- 共 33 项。覆盖：双侧关卡矩阵（含 A70/B80 × 关卡 90/80）、start 与 finish 关卡、数据冲突、
  取消前置、进度 0、日期缺失两种、future_risk / on_time、条件 <100 禁止回退、100% 允许回退并标注
  来源、超期边界（当天不算）、预计冲突、引用不到任务、空快照、契约取值范围与范围自检、可复现性，
  以及候选预览（只用 key / 正式 ID / 信息不全 / 无依赖候选）。
- 本目录另附 `run_tests_without_pytest.py`：无需 pytest 也能执行同一批用例，
  已在本机 Python 3.10 与 3.13 双版本各通过 33 项。

- 前置达标才 satisfied；取消任务不能自动视为达标。
- A70/B80，关卡90：condition_unmet；关卡80：blocked_now，表示无法越过此关卡，不表示所有工作停工。
- finish 条件不足且 B 未完成：finish_condition_unmet，不能随意标正在停工。
- 已启动/已完成却违背依赖条件：data_conflict，不倒写已记录任务状态。
- start 条件的启动操作阻止已在后端；静态分析未启动时只标未满足，已启动违反条件标冲突。
- timing_status 独立于当前关卡判断；允许 future_risk / timing_unknown / on_time。
- 条件预计就绪晚于需要日期才是 future_risk；缺任一必要日期是 unknown。
- 前置要求不到100%时不能拿整个任务 forecast_end 代替条件就绪日期；要求100%时才可按审计规则回退。
- evaluation_date 严格晚于 planned_end、且任务未完成才是超过计划，当天不是超期。
- forecast_end > deadline 是预估冲突，不等于已经逾期。
- 潜在下游路径不是“所有后继都已阻塞”；没有权重/工时依据不输出真实完成百分比、自动预测或健康分。

dependency_status 仅限 satisfied/condition_unmet/blocked_now/finish_condition_unmet/data_conflict。非依赖超期发现可不填 dependency_status，使用明确 reason_codes 和 explanation。如影响路径需要新增结构化字段，先给后端说明并经负责人确认扩展契约，不把未知字段塞入返回值。

## 本地开发、测试与交付

只依赖 shared 和自己的内部实现/第三方库；不依赖账号、HTTP、GLM、app 数据库、主 RAG 或工作流运行。用小型 Snapshot 直接单测，日期从输入读取，不偷偷调用机器今天日期。

```powershell
.\.venv\Scripts\python.exe -m pytest team_modules/risk/tests
```

当前 smoke 只验证骨架与样例；上面命令是已有验证，不另行要求自测文件交付。提交实现、运行说明、reason_codes/rule_version 含义和必要样例，测试负责人验收关卡/日期判断、候选依赖预判和数据变化后的提示。不把“尚未接入”当成“没有风险”。

完整联调时后端工厂装配此实现，前端可调用 /analysis、/analysis/preview 和 /risk-status；正式任务/依赖变化会排 risk_analysis Job，启动 Worker 后消费。后端保存正式快照与结果，is_stale 表示过期，不要把旧结果当最新。正式 RiskItem 是人工确认事项，不能被本算法覆盖成另一种状态。

新增风险类型、影响传播含义、日期阈值、评分规则有疑问时先询问负责人。无需为“看起来完整”增加审计没有确认的业务。
