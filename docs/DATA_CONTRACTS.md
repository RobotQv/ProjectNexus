> 公开版账号说明：所有账号样例均为虚构演示数据，不是真实学号。登录方式以根 README 为准；仓库不附带 .env 或业务数据。

# 结构化任务与建议格式 v2

工作流、轻 RAG、后端和前端都按本文件及 shared 中的模型对接。不要在各目录复制另一套字段。

- 业务字段：`shared/task_data.py`，包含 TaskCreate、TaskChanges、TaskPatch、UpdateTaskProposal、TaskRecord、DependencyCreate。
- 模块输入输出：`shared/contracts.py`，包含 SuggestionDraft、AssistantRequest/Result/Tools、RiskPreview 等。
- 带类型分支的模型输出 JSON Schema：`shared/structured.py` 的 StructuredSuggestion / json_schemas()。
- 不启动后端也可以直接导入这些类型。启动后可 GET `/api/v1/contracts/task-data` 获取相同格式定义；不含项目数据，无需登录。
- JSON 示例见 `examples/task_suggestions.json`。示例中的数字 ID 只是占位，必须换成自己本机当前项目的真实 ID。

工作流拿到模型 JSON 后可以直接校验，再放入 AssistantResult 或 ExtractionResult：

```python
from shared.contracts import SuggestionDraft

draft = SuggestionDraft.model_validate(model_json)
payload = draft.model_dump(mode="json", exclude_unset=True)
```

使用 TaskChanges 或 StructuredSuggestion 自行序列化时也要带 exclude_unset=True，保留“省略不改”和“明确 null 清空”的区别。不要把所有未提及字段自动填成 null。

## 1. 正式任务的业务字段

| 字段 | 类型 / 约束 | 新建默认 |
| --- | --- | --- |
| title | 非空字符串，最多 200 字符 | 必填 |
| description | 字符串，最多 20000 字符，或 null | null |
| assignee_id | 项目有效成员的 User.id，正整数或 null，不是姓名/学号 | null |
| module_name | 字符串，最多 100 字符，或 null | null |
| tags、aliases | 字符串数组，最多 30 项，每项 1–100 字符 | [] |
| status | not_started / in_progress / done / cancelled | not_started |
| progress | 0–100 的整数，不是小数比例、字符串或布尔值 | 0 |
| planned_start、planned_end | 计划开始/完成日期，YYYY-MM-DD 或 null | null |
| forecast_end | 预计完成日期，YYYY-MM-DD 或 null | null |
| deadline | 最晚截止日期，YYYY-MM-DD 或 null | null |
| actual_start_at、actual_end_at | 带时区的 ISO 时间，如 2026-09-15T09:00:00+08:00，或 null | null |

done 必须配 progress=100；not_started 必须配 progress=0。计划开始不得晚于计划完成，实际开始不得晚于实际完成。不从百分比擅自推断并修改状态；提交更新时把需要变化的两个字段明确写出。

TaskRecord 是完整读取格式：在上述字段上增加 id、project_id、version、created_at、updated_at、deleted_at、progress_updated_at、forecast_updated_at、forecast_by、source_suggestion_id。这些系统字段由后端维护，不能放进 AI 的任务业务载荷。依赖是单独的关系记录，不是塞进任务 description 的文本字段。

## 2. 新建任务建议

```json
{
  "suggestion_type": "create_task",
  "proposed_payload": {
    "title": "完成登录接口",
    "description": "支持学号登录",
    "assignee_id": 1,
    "planned_end": "2026-09-25"
  },
  "source_refs": [],
  "entity_candidates": [],
  "validation_warnings": []
}
```

候选载荷使用 TaskChanges，允许缺字段，但不允许未知字段、越界进度或非法枚举。没识别出的人员/日期不要编造，省略并在 validation_warnings 提醒。正式确认时才按 TaskCreate 完整校验；缺标题的建议能保存，但不能直接通过。

## 3. 更新已有任务建议

```json
{
  "suggestion_type": "update_task",
  "proposed_payload": {
    "task_id": 12,
    "expected_version": 3,
    "changes": {
      "status": "in_progress",
      "progress": 70,
      "description": null,
      "planned_end": "2026-09-28"
    }
  },
  "source_refs": [],
  "entity_candidates": [],
  "validation_warnings": []
}
```

- 先调用 tools.resolve / tools.search_tasks 找到真实任务并读取 version，再生成更新建议。名称有歧义时返回 clarify 与候选，用户明确目标后重新提问；不能猜一个 ID。
- task_id、expected_version 是必填正整数，changes 至少一个字段。expected_version 是目标任务版本，与建议自己的 version 不是一回事。
- changes 中省略表示不改；null 表示清空可空字段。title/status/progress/tags/aliases 不可设 null。
- 审核时目标版本不一致返回 409，不自动覆盖。审核人先对照最新任务确认改动，再明确修正 expected_version；前端不能静默刷新版本重试。
- 未通过正式审核前不改任务，审核生效后和手动修改一样追加完整历史。

## 4. 来源与身份

对话建议 source_refs 可以为空，后端自动保留原始输入与入口；文档提取的每条建议必须有至少一个真实引用：

```json
{"document_id": 5, "version": 1, "block_ids": [18], "quote": "登录接口已经完成七成。"}
```

quote 必须是相应正文块的连续原文，不是模型摘要；后端核验项目、文档版本、块 ID 和摘录。主 RAG 清洗结果由后端保存并分配块 ID，轻 RAG 直接复用。文档建议可用 `/suggestions/{id}/source` 查看原文块、位置、文件名和版本；下载原文件继续使用资料接口。

提交者、提交/生成时间、来源类型、审核人、审核时间、审核结果都由后端记录，模型不要输出这些身份字段。文档发起提取者不一定是上传者。旧数据中无法可靠还原的身份为 null，不编造历史人员。

## 5. 两阶段与逐条审核

对话：`draft → pending → approved / rejected`。draft 仅提交者可查看和修改；提交者调用 submit 后进入正式审核。资料提取直接 `pending → approved / rejected`，没有 draft 阶段。

每条建议是独立记录，有独立 id/version/status。pending 建议可由任意有效项目成员修正和审核，包括提交者本人。审核后不能再次编辑；重复同结果审核返回原结果，不重复写任务。

审核请求：

```json
{"action":"confirm","expected_version":2,"overrides":{"changes":{"progress":80}},"note":"已核对原文"}
```

这里 expected_version 是建议版本。overrides 对新建任务是字段补丁；对更新建议，overrides.changes 与原 changes 按字段合并，overrides.expected_version 可明确更新目标任务版本。PATCH 建议的 proposed_payload 则是完整替换载荷。拒绝使用 action=reject；审核备注 note 可选。

original_payload 留存初始提取载荷，proposed_payload 保存当前修正/通过的载荷。正式任务快照 GET `/tasks/{id}/history`，按版本倒序，记录操作人、来源与关联建议；无回滚接口。迁移只补已有任务的当前基线，无法恢复迁移前未保存的历史。

## 6. 依赖与风险

propose_dependency 的载荷字段：predecessor_task_id、successor_task_id、predecessor_required_progress(1–100)、successor_gate(start/progress/finish)、successor_gate_progress(仅 progress 时 1–99)、gate_needed_on、predecessor_forecast_ready_on、description。草稿可以缺信息，审核时严格校验，不能无依据补成 100%/start。

工作流调用 `tools.preview_risk(changes)`，changes 是 CandidateChange 列表，每项含唯一 key 和 suggestion。风险模块接到 `RiskPreview(snapshot, changes)`：snapshot 是正式数据，changes 还未生效，不可把两者混为已经提交的项目事实。

如果依赖涉及同批新任务，预览项可以用 predecessor_key / successor_key 指向本批 create_task 的 key；不可同时指定相同一侧的正式 ID。风险输出可用 candidate_keys 引用候选，task_ids/dependency_id 只能引用正式快照。正式依赖审核仍需实际任务 ID：先批准新任务，再为依赖建议选择实际任务；不自动捆绑批准多条建议。

风险模块实现 analyze(snapshot) 与 analyze_candidates(preview)。返回 AnalysisResult(rule_version, findings, warnings)；Finding 含 task_ids、candidate_keys、dependency_id、dependency_status、timing_status、reason_codes、explanation。信息不足应说明，不给伪造风险概率。

任务/依赖的正式写入与 risk_analysis Job 同事务提交，Worker 自动消费；无定时检查。GET `/risk-status` 返回检查状态、最新结果及是否过期。未接入/失败和过期不能解释为“无风险”。只提示，不自动改状态、不发送外部通知。
