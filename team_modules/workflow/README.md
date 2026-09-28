> 公开版账号说明：所有账号样例均为虚构演示数据，不是真实学号。登录方式以根 README 为准；仓库不附带 .env 或业务数据。

# AI 工作流 + 轻 RAG（本组负责）

2026-09-22 整合说明：配置由后端工厂显式注入，导入模块不读取 `.env`；任务更新也会预览已有依赖风险，并将返回提示交给前端。本文后续的原提交测试数量和“仅依赖建议调用预览”描述以最新代码及 `docs/INTEGRATION_20260922.md` 为准。

> 本目录实现「工作流 + 轻 RAG」两个职责：把自然语言咨询转成**有事实依据的回答**，把文档/短文本转成**待审核的结构化任务建议**，并维护一个按名字找任务/成员的**实体索引**。
>
> 核心原则：**建议只生成、不直接写正式任务**。正式写入、审核、身份、权限全部由后端主干完成。

---

## 1. 模块做什么

本模块对外暴露两个适配器（都实现 `shared/contracts.py` 里的协议）：

| 适配器 | 协议 | 职责 |
| --- | --- | --- |
| `EntityAdapter` | `EntityResolver` | 任务/成员的**实体索引**：同步、按名字语义定位（`sync` / `resolve`） |
| `WorkflowAdapter` | `Workflow` | **助手对话**（`respond`）与**文档提取**（`extract`） |

一次典型请求的完整链路：

```text
用户输入 / 上传文档
      │
      ▼
┌───────────────────────────── 后端主干（不归本组） ─────────────────────────────┐
│ 登录身份 → 项目权限 → 保存文件 → 装配 Modules → 调用本模块                     │
└──────────────────────────────────────────────────────────────────────────────┘
      │ 调用 respond / extract
      ▼
┌───────────────────────────── 本模块（本组） ──────────────────────────────────┐
│ ① 意图分类（query / suggest，或 extract / summary）                            │
│ ② 编排只读工具：search_tasks / retrieve / resolve / snapshot / entity_catalog │
│ ③ 调用注入的 LLM 生成回答或 JSON 建议                                          │
│ ④ 解析 JSON → 去重 → 重建真实原文证据 → 回填实体 → 依赖时预览风险              │
└──────────────────────────────────────────────────────────────────────────────┘
      │ 返回 AssistantResult / ExtractionResult（结构化的候选，不是最终写入）
      ▼
┌───────────────────────────── 后端主干 ────────────────────────────────────────┐
│ 校验 → 展示给用户审核 → 用户确认后正式写入数据库                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 职责边界（谁负责什么）

| 谁 | 负责什么 |
| --- | --- |
| **本模块** | 意图理解、工具编排、语义检索、实体定位、结构化提取、长文分批、去重、JSON 解析、来源重建 |
| **后端主干** | 登录身份、项目权限、文件保存、建议流转/审核、正式写入、历史快照、模型连接与装配 |
| **主 RAG** | 资料解析、清洗、分块、资料检索（`retrieve`）；本模块**复用**它清洗后的正文块 |
| **风险模块** | 依赖/风险规则（`preview_risk` / `analyze`）；本模块只在发现候选依赖时调用它 |

本模块只 import `shared/`、本目录和确认的第三方库：

- ❌ 不 import `app`、`main_rag`、`risk` 的实现（避免把别的组员代码拖进自己的装配，也别重复造轮子）。
- ❌ 不写数据库、不记录提交者/审核人身份、不调用批准/正式写入接口。
- ❌ 不在本模块硬编码密钥、不接聊天模型的 HTTP（聊天模型由后端注入的 `shared.llm.LLMProvider` 提供）。

---

## 3. 对外接口总览

所有类型的唯一定义在 [shared/contracts.py](../../shared/contracts.py)、[shared/task_data.py](../../shared/task_data.py)、[shared/structured.py](../../shared/structured.py)，**本模块不复制任何字段**。

### 3.1 实体索引 `EntityAdapter`

```python
def sync(self, entity: EntityRecord) -> None
def resolve(self, scope: Scope, text: str, entity_type: str, limit: int) -> Resolution
```

#### `sync(entity)` — 同步/清理一个实体

把任务或成员的搜索文本写入向量索引，**幂等**：同 key 重复同步只会覆盖成最新版本。

| 入参 `EntityRecord` 字段 | 类型 | 说明 |
| --- | --- | --- |
| `project_id` | int | 项目 ID |
| `entity_type` | `"task"` \| `"member"` | 实体类型 |
| `entity_id` | int | 实体 ID（`member` 用 `User.id`，不是 `ProjectMember.id`） |
| `source_version` | int | 来源版本号，用于**防旧覆盖新** |
| `search_text` | str | 被向量化的搜索文本（如任务名 + 别名） |
| `is_active` | bool | `false` 表示实体已失活，应清理出索引 |

行为规则：

- 索引 key = `{project_id}:{entity_type}:{entity_id}`，按项目 + 类型隔离。
- `is_active=false` → 从索引删除该实体，不留下脏数据。
- 新来的 `source_version` ≤ 已存版本 → 跳过（旧数据不能覆盖新数据）。
- 每次写入附带 `index_version`（当前 `embedding-3-2048`），模型/维度变了要换版本重建。

#### `resolve(scope, text, entity_type, limit)` — 按名字语义定位

把一段文本（通常是任务名/人名）转成候选实体，用于消歧和回填。

| 入参 | 类型 | 说明 |
| --- | --- | --- |
| `scope` | `Scope` | `project_id` 范围 |
| `text` | str | 要匹配的文本，非空（空串 → `AppError` 422） |
| `entity_type` | `"task"` \| `"member"` | 限定实体类型（非法值 → 422） |
| `limit` | int | 返回上限，1–50（越界 → 422） |

返回 `Resolution`：

| 字段 | 说明 |
| --- | --- |
| `outcome` | `resolved`（唯一/明显命中）\| `ambiguous`（多个接近候选）\| `not_found`（无候选） |
| `candidates` | `list[Candidate]`：`entity_type`、`entity_id`、`title`、`score`、`match_reason` |
| `index_version` | 当前索引版本 `embedding-3-2048` |

判定逻辑：

1. 对 `text` 打 embedding，在 `project_id` + `entity_type` 过滤下取候选池（按 `limit` 放大后截断）。
2. 余弦相似度 `score < MIN_MATCH_SCORE(0.60)` 的候选直接丢弃。
3. 按分数降序，截断到 `limit`。
4. 无候选 → `not_found`；只有 1 个、或第一名与第二名差距 ≥ `AMBIGUITY_MARGIN(0.10)` → `resolved`；否则 → `ambiguous`。

> ⚠️ `score` 是**相似度**，不是「正确概率」。0.60 / 0.10 这两个阈值是初步值，待用开发集校准（见第 13 节「仍未完成」）。

---

### 3.2 工作流 `WorkflowAdapter`

```python
def respond(self, request: AssistantRequest, tools: AssistantTools) -> AssistantResult
def extract(
    self,
    document: DocumentRef,
    entity_catalog: list[EntityRecord],
    kind: str,
    *,
    tools: AssistantTools | None = None,
) -> ExtractionResult
```

#### `respond(request, tools)` — 项目助手 / 任务助理对话

入参 `AssistantRequest`：`entry`（`project_assistant` \| `task_assistant`）+ `text`（1–4000 字）。

**第一步**：调用 LLM 做二分类（`CLASSIFY_SYSTEM` 提示词），只输出一个词 `query` / `suggest`。

**`query` 分支（想了解信息）——只读、先取事实再回答：**

1. `tools.search_tasks(...)` 查任务；
2. `tools.retrieve(...)` 查资料证据；
3. `tools.resolve(...)` 定位实体（若 `ambiguous`，直接返回 `clarify` 并列出候选，**不猜 ID、不再编答案**）；
4. `tools.snapshot()` 取项目快照（任务一览 + 依赖关系，用来回答「有哪些依赖/阻塞」这类问题）；
5. 把上面所有事实喂给 LLM，生成简洁中文回答。

结果 `outcome` 判定（事实优先，不编造）：

- 没有任何事实（任务/证据/候选/快照都空）→ `insufficient`；
- 有事实但快照等部分工具失败（记入 `warnings`）→ `partial`；
- 正常 → `answered`。

**`suggest` 分支（想新建/更新/安排依赖/记录风险）：**

1. LLM 五分类细分意图（`SUGGEST_INTENT_SYSTEM`）：`create` / `update` / `dependency` / `risk` / `other`；
2. 取项目快照 + 成员目录（`entity_catalog`）作为上下文；
3. 对输入里提到的实体 `resolve` 定位，把候选喂回上下文；
   - 若 `update`/`dependency`/`risk` 意图下实体 `ambiguous` → 直接返回 `clarify` 列出候选，**不猜 ID、不再生成建议**；
4. LLM 生成 JSON 建议数组（见第 6 节），解析成 `SuggestionDraft`；
5. 出现 `propose_dependency` 建议时，构建 `CandidateChange` 调 `tools.preview_risk(...)` 预览依赖/风险；失败只记 warning，**不伪装成已检查**。

#### `extract(document, entity_catalog, kind, *, tools)` — 资料库「提取任务」

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `document` | `DocumentRef` | 复用主 RAG 清洗后的**完整正文块**（`blocks`），非空 |
| `entity_catalog` | `list[EntityRecord]` | 当前项目实体目录，用于回填候选 ID |
| `kind` | `"extract"` \| `"summary"` | 提取建议 / 生成摘要，其他值 → 422 |
| `tools` | `AssistantTools \| None` | 提取时可选传入（依赖风险预览用） |

**`kind="extract"` 流程：**

1. 按约 `BATCH_CHAR_BUDGET(20000)` 字符把正文块分批（每块带 `[id]` 标注，供模型回填 `block_ids`）；
2. 每批单独调 LLM 生成 JSON 建议数组（`EXTRACT_SYSTEM` 提示词）；
3. 合并所有批次 → **去重** → 封顶 `MAX_SUGGESTIONS(300)`；
4. 逐条**重建真实来源**：`quote` 必须逐字摘自原文块，模型改写了就用原文兜底，不伪造 `Evidence`；
5. 把 payload 里引用的正式 ID（`task_id` 等）在 `entity_catalog` 里找到并回填成 `entity_candidates`；
6. 出现 `propose_dependency` 建议时调 `tools.preview_risk(...)` 预览，失败写 warning、不阻断。

**`kind="summary"` 流程：** 分批生成摘要 → 合并成一段文本，`suggestions` 恒为空。

---

## 4. 返回结果字段说明

### `AssistantResult`（`respond` 的返回）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `answer` | str ≤30000 | 助手回答文本 |
| `outcome` | `answered` \| `clarify` \| `insufficient` \| `partial` | 见上文判定逻辑 |
| `suggestions` | `list[SuggestionDraft]` ≤100 | 生成的候选建议（suggest 分支才有） |
| `task_ids` | `list[int]` ≤100 | 回答中涉及的任务 ID |
| `evidence` | `list[Evidence]` ≤30 | 回答所依据的资料证据 |
| `candidates` | `list[Candidate]` ≤50 | `clarify` 时返回的实体候选 |
| `warnings` | `list[str]` | 非致命告警（如快照不可用、风险预览失败） |
| `model_id` | str | 实际调用模型的标识 |
| `prompt_version` | str | 提示词版本（当前 `v2`） |

### `ExtractionResult`（`extract` 的返回）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `suggestions` | `list[SuggestionDraft]` ≤300 | 提取出的建议 |
| `summary` | `str \| None` | `kind="summary"` 时的摘要 |
| `model_id` | str | 模型标识 |
| `prompt_version` | str | 提示词版本 |

### `SuggestionDraft`（单条建议的通用外壳）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `suggestion_type` | `create_task` \| `update_task` \| `propose_dependency` \| `create_risk` | 建议类型 |
| `proposed_payload` | dict | 各类型专用字段（见第 6 节） |
| `source_refs` | `list[Evidence]` ≤30 | 引用原文块，逐字证据 |
| `entity_candidates` | `list[Candidate]` | 回填的正式实体候选 |
| `validation_warnings` | `list[str]` | 缺字段/需人工确认的提醒 |

### `Evidence`（来源证据）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `document_id` | int | 来源文档 |
| `version` | int | 文档版本 |
| `block_ids` | `list[int]` 1–20 | 引用的正文块 ID |
| `quote` | str 1–8000 | **逐字**摘自原文的引用文本 |

---

## 5. 建议的四种类型（JSON 格式）

提示词里注入的 schema 来自 [shared/structured.py](../../shared/structured.py) 的 `json_schemas()["suggestion"]`，与运行时校验共用同一套字段。四种类型的 `proposed_payload` 都用**宽松草稿**（字段全可选），后端正式写入时用严格版（`TaskCreate`/`DependencyCreate`/`RiskCreate`）再校验一遍。

### 5.1 `create_task` — 新建任务

`proposed_payload` = `TaskChanges`（全部可选，缺省 = 留空待人工）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` | str 1–200 | 任务名 |
| `description` | str ≤20000 | 描述 |
| `assignee_id` | int >0 | 负责人成员 ID |
| `module_name` | str ≤100 | 所属模块 |
| `tags` | str[] | 标签 |
| `aliases` | str[] | 别名 |
| `status` | `not_started` \| `in_progress` \| `done` \| `cancelled` | 状态 |
| `progress` | int 0–100 | 进度 |
| `planned_start` / `planned_end` | date | 计划起止 |
| `forecast_end` | date | 预测完成 |
| `deadline` | date | 截止日 |
| `actual_start_at` / `actual_end_at` | datetime | 实际起止 |

约束：`title`/`status`/`progress`/`tags`/`aliases` 一旦出现**不能为 null**；正式写入 `TaskCreate` 时再校验「`done` 必须 `progress=100`、`not_started` 必须 `progress=0`」等一致性。

### 5.2 `update_task` — 更新已有任务

`proposed_payload` = `UpdateTaskProposal`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | int >0 | 要更新的任务 ID（**必须来自给定项目数据，禁止编造**） |
| `expected_version` | int ≥1 | 期望版本号（乐观锁，防止改到过期版本） |
| `changes` | `TaskChanges` | 只放要改的字段（**至少 1 个**），未出现的字段 = 不改 |

### 5.3 `propose_dependency` — 安排依赖

`proposed_payload` = `DependencyDraft`（全部可选）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `predecessor_task_id` | int >0 | 前驱任务 ID |
| `successor_task_id` | int >0 | 后继任务 ID |
| `predecessor_required_progress` | int 1–100 | 前驱需达到的进度 |
| `successor_gate` | `start` \| `progress` \| `finish` | 后继被解锁的关卡 |
| `successor_gate_progress` | int 1–99 | 仅 `gate="progress"` 时必填 |
| `gate_needed_on` | date | 关卡需要的日期 |
| `predecessor_forecast_ready_on` | date | 前驱预测就绪日 |
| `description` | str ≤10000 | 说明 |

约束：不允许自依赖；`gate="progress"` ⇔ `successor_gate_progress` 非空。

### 5.4 `create_risk` — 记录风险

`proposed_payload` = `RiskDraft`（全部可选）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `title` | str 1–200 | 风险标题 |
| `description` | str 1–20000 | 风险描述 |
| `related_task_id` | int >0 | 关联任务 ID |
| `severity` | `unknown` \| `low` \| `medium` \| `high` | 严重度（缺省 `unknown`） |

### 5.5 完整示例

一条建议的完整 JSON（对 `proposed_payload` 会被 `SuggestionDraft` 用对应 schema 校验，省略的字段保持省略）：

```json
[
  {
    "suggestion_type": "create_task",
    "proposed_payload": {
      "title": "完成登录接口",
      "description": "支持学号登录",
      "planned_end": "2026-09-25"
    },
    "source_refs": [
      {"document_id": 5, "version": 1, "block_ids": [18], "quote": "登录接口已经完成七成。"}
    ],
    "entity_candidates": [],
    "validation_warnings": ["负责人未明确，请人工选择"]
  },
  {
    "suggestion_type": "update_task",
    "proposed_payload": {
      "task_id": 12,
      "expected_version": 3,
      "changes": {"status": "in_progress", "progress": 70}
    },
    "source_refs": [],
    "entity_candidates": [
      {"entity_type": "task", "entity_id": 12, "title": "登录接口", "score": 0.92}
    ],
    "validation_warnings": []
  },
  {
    "suggestion_type": "propose_dependency",
    "proposed_payload": {
      "predecessor_task_id": 10,
      "successor_task_id": 11,
      "predecessor_required_progress": 100,
      "successor_gate": "start"
    },
    "source_refs": [
      {"document_id": 5, "version": 1, "block_ids": [18], "quote": "登录完成后才能开始联调。"}
    ],
    "entity_candidates": [],
    "validation_warnings": []
  },
  {
    "suggestion_type": "create_risk",
    "proposed_payload": {
      "title": "登录接口可能延期",
      "description": "负责人请假，进度落后于计划",
      "related_task_id": 12,
      "severity": "high"
    },
    "source_refs": [],
    "entity_candidates": [],
    "validation_warnings": []
  }
]
```

参考文件：[examples/task_suggestions.json](../../examples/task_suggestions.json)。

---

## 6. 关键行为规则

1. **来源必须真实**：文档建议的 `quote` 逐字摘自正文块（模型改写就用原文兜底），**不伪造 `Evidence`**；对话建议的 `source_refs` 可为空（后端记录原始输入）。
2. **歧义澄清，不猜 ID**：query 入口实体歧义、以及 suggest 入口 `update`/`dependency`/`risk` 意图遇到同名任务歧义时，返回 `outcome=clarify` 并列出候选。
3. **候选依赖风险预览**：只有出现 `propose_dependency` 建议时才调 `tools.preview_risk(changes)`；风险模块未接入/失败时写进 warning，**不伪装成「已检查」**。
4. **长文分批 / 去重 / 封顶**：正文按约 20000 字符分批，抽取结果去重，建议封顶 300 条。
5. **缺失不编造**：原文没提的负责人/日期/依赖关卡保持缺失，并在 `validation_warnings` 里提醒；`done` 配 `progress=100` 等约束由 shared 在正式写入时校验。
6. **非任务文本返回空**：正文没有可提取内容时输出空数组 `[]`，不硬凑。
7. **事实不足不编造回答**：query 入口没有任何事实时 `outcome=insufficient`，明确说缺哪些信息。
8. **聊天模型只走注入接口**：只调 `llm.complete(messages, max_tokens=...)`，不硬编码密钥、不接聊天 HTTP。

---

## 7. 技术选型

| 项 | 选择 |
| --- | --- |
| 聊天模型 | 后端注入的智谱 GLM Provider（`shared.llm.LLMProvider.complete`） |
| Embedding | 智谱 `embedding-3`，维度 2048（与主 RAG 一致；**独立维护一份客户端**，不 import 对方实现） |
| 向量库 | Chroma 1.5.9，余弦距离 |
| 索引存储 | `data/workflow/`，集合名 `workflow_entities`（与主 RAG 的资料索引分开命名空间） |
| 索引版本 | `embedding-3-2048`（模型/维度变了要换版本重建） |
| 提示词版本 | `v2`（提示词改动必须 bump，新版本不能悄悄覆盖已审核建议） |

---

## 8. 参数 / 常量速查

集中在 [adapters.py](adapters.py) 与 [prompts.py](prompts.py)，改动前先看这里：

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `PROMPT_VERSION` | `"v2"` | 提示词版本 |
| `ENTITY_INDEX_VERSION` | `"embedding-3-2048"` | 实体索引版本 |
| `MIN_MATCH_SCORE` | `0.60` | 实体匹配最低相似度 |
| `AMBIGUITY_MARGIN` | `0.10` | 第一名与第二名差距不足此值判 `ambiguous` |
| `BATCH_CHAR_BUDGET` | `20000` | 长文分批的字符预算 |
| `MAX_SUGGESTIONS` | `300` | 建议封顶条数 |

---

## 9. 目录结构

```
workflow/
├── adapters.py        # EntityAdapter（sync/resolve）+ WorkflowAdapter（respond/extract）
├── prompts.py         # 所有提示词 + PROMPT_VERSION（提示词改动必须 bump 版本）
├── indexing/
│   ├── embedding.py   # 智谱 embedding-3 客户端（httpx POST，密钥从环境变量读）
│   └── store.py       # Chroma 实体集合封装（懒加载：聊天编排不依赖向量库也能跑）
├── requirements.txt   # 本模块第三方依赖
├── README.md          # 本文档
└── tests/             # 离线单测：脚本化假 LLM + 假工具，不请求真实模型/账号
    └── test_workflow.py
```

- `store.py` 用**懒加载**：`EntityStore` 在真正 `sync`/`resolve` 时才初始化 Chroma 客户端，所以后端启动、纯聊天问答不依赖向量库环境。

---

## 10. 依赖与运行前提

见 [requirements.txt](requirements.txt)：

```
chromadb==1.5.9
httpx==0.28.1
python-dotenv==1.2.3
```

- 聊天模型复用后端注入的 GLM Provider，**不额外引入**聊天模型 SDK。
- **实体索引需要智谱 key**：`sync`/`resolve`（以及 `respond`/`extract` 里做实体定位的部分）的 Embedding 客户端读取 `.env` 里的 `NEXUS_LLM_API_KEY`（可选 `NEXUS_LLM_BASE_URL`），未配置时返回 `embedding_unavailable`(503)。与聊天模型共用同一个智谱 key。
- **懒加载**：向量库和 Embedding 客户端只在真正用到实体索引时才初始化；只 import 模块、装配工厂或纯 LLM 问答不会触发，也不要求 chromadb 与 key。

---

## 11. 怎么测试

```powershell
.\.venv\Scripts\python.exe -m pytest team_modules/workflow/tests
```

- 离线单测用脚本化假 LLM 和假工具，**不联网、不用账号**，覆盖：意图分类、query 事实回答、suggest 生成、提取、去重、分批、来源重建、实体回填、歧义澄清、风险预览触发/失败等（当前 33 个用例）。
- 真实 Chroma 的集成冒烟测试在装了 `chromadb` 的环境自动运行。

---

## 12. 怎么接入联调

在 `.env` 设置（后端的 `MODULE_FACTORY` 装配点会加载本模块）：

```dotenv
NEXUS_MODULE_FACTORY=team_modules.factory:build_modules
NEXUS_MODULE_MODE=disabled
```

然后重启自己电脑的 API 和 Worker。非空 `MODULE_FACTORY` 优先于 `MODULE_MODE`；切回 demo 时清空 `MODULE_FACTORY`。

完整验收（登录 → 传文件 → 提取 → 逐条核对）由**测试负责人**执行，见根 README 与 [TESTING.md](../../docs/TESTING.md)。

> ⚠️ 注意：`MODULE_FACTORY` 在 import 时会把**所有组员模块**一起加载。若有组员模块缺第三方依赖（例如 main_rag 需要 `python-docx`、`pdfminer.six`），整条装配线（包括本模块）会加载失败——**缺哪个装哪个自己的 `requirements.txt`**，而不是改本组代码。

---

## 13. 完成情况

### 已完成

- **实体索引**：幂等同步、失活清理、`source_version` 防旧覆盖、按项目/类型过滤、同名歧义返回 `ambiguous`。
- **工作流**：意图分类（query/suggest + suggest 五分类细分）、query 事实回答（含项目快照）、suggest 生成待审建议（含依赖上下文与实体候选）、`extract`/`summary`、长文分批、JSON 围栏/片段解析、真实原文重建 `Evidence`、去重封顶。
- **候选依赖风险预览**：`propose_dependency` 时构建 `CandidateChange` 调 `preview_risk`，失败写 warning、不阻断。
- **意图澄清**：query 与 suggest 两个入口的实体歧义都返回 `clarify`。
- **实体回填**：把 payload 引用的正式 ID 回填成 `entity_candidates`。

### 仍未完成（后续迭代）

- 实体匹配阈值 `MIN_MATCH_SCORE=0.60`、`AMBIGUITY_MARGIN=0.10` 是初步值，须用开发集校准。
- 候选依赖引用「本批新建任务」的 key 映射未做：`predecessor_key`/`successor_key` 恒为 `None`，待与风险/后端对齐后补。
- 跨轮澄清未做：`clarify` 目前只列候选，不接后续轮次的追问。
- 索引版本切换/重建策略沿用主 RAG 约定，尚未单独演练。

---

## 14. 相关文档

- 需求依据：[REQUIREMENTS.md](../../docs/REQUIREMENTS.md)
- 模块契约：[MODULE_CONTRACTS.md](../../docs/MODULE_CONTRACTS.md)
- 数据格式：[DATA_CONTRACTS.md](../../docs/DATA_CONTRACTS.md)
- 测试验收：[TESTING.md](../../docs/TESTING.md)
- 共享契约与字段：[shared/contracts.py](../../shared/contracts.py)、[shared/task_data.py](../../shared/task_data.py)、[shared/structured.py](../../shared/structured.py)
- 建议示例：[examples/task_suggestions.json](../../examples/task_suggestions.json)
