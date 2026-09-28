> 公开版账号说明：所有账号样例均为虚构演示数据，不是真实学号。登录方式以根 README 为准；仓库不附带 .env 或业务数据。

> 提交方旧环境记录，未在当前整合版上复现。本文模块状态、数量和缺陷结论不能作为当前验收结果。以 ../2026-09-28-integration-review.md 为准。

# 冻结评估集执行计划

## 1. 评估集概述

**位置：** `tests/evaluation/`

**用途：** 用于评估主 RAG、工作流和风险模块的真实功能质量，与开发集分离。

**组成：**

```
tests/evaluation/
├── project-a/              # Project A 隔离数据
│   └── README.md
├── project-b/              # Project B 隔离数据
│   └── README.md
├── questions.json          # 22 条资料问答测试问题
├── dependency-rules.json   # 8 条依赖规则样例
└── extraction-samples.json # 4 段会议抽取文本
```

## 2. 数据说明

### 2.1 questions.json（22 条）

**分类：**

| 类别 | 数量 | 说明 |
| --- | --- | --- |
| material_qa | 10 | 资料问答题（查询项目资料） |
| entity_status | 6 | 实体状态查询（任务/成员进度） |
| mixed | 4 | 混合查询（需结合资料和任务状态） |
| insufficient | 2 | 资料不足问题（应回答无法回答） |

**字段：**
- `id`: 唯一标识
- `project`: 所属项目（project-a / project-b）
- `question`: 问题文本
- `expected_task_id`: 预期关联任务 ID（如适用）
- `expected_evidence_anchors`: 预期证据锚点（原文片段）
- `category`: 问题类别
- `split`: 数据集划分（test）

**示例：**
```json
{
  "id": "q001",
  "project": "project-a",
  "question": "登录模块的当前进度是多少？",
  "expected_task_id": 10,
  "expected_evidence_anchors": ["登录接口已完成七成"],
  "category": "entity_status",
  "split": "test"
}
```

### 2.2 dependency-rules.json（8 条）

**覆盖场景：**

| ID | 前置任务 | 后置任务 | 关卡 | 预期 reason_code |
| --- | --- | --- | --- | --- |
| rule001 | 完成登录接口 | 开始前后端联调 | finish | blocked_now |
| rule002 | 数据库设计 | 后端 API 开发 | start | condition_unmet |
| rule003 | 需求分析 | 系统设计 | finish | satisfied |
| rule004 | 前端页面开发 | UI 测试 | finish | blocked_now |
| rule005 | 单元测试 | 集成测试 | finish | finish_condition_unmet |
| rule006 | 代码审查 | 部署上线 | finish | data_conflict |
| rule007 | 性能优化 | 压力测试 | start | timing_unknown |
| rule008 | 用户文档编写 | 用户培训 | finish | future_risk |

**用途：** 验证风险模块的关卡判断和日期分析逻辑。

### 2.3 extraction-samples.json（4 段）

**覆盖场景：**

| ID | 场景 | 预期输出 |
| --- | --- | --- |
| extract001 | 进度汇报 + 依赖关系 | 2 个任务（含进度和依赖） |
| extract002 | 完成汇报 + 新任务分配 | 2 个任务（1 个已完成，1 个待办） |
| extract003 | 任务分配 + 截止日期 | 2 个任务（含 deadline 和依赖） |
| extract004 | 会议总结 + 多任务 | 4 个任务（含状态和负责人） |

**用途：** 验证工作流 extract 方法的任务抽取能力。

## 3. 评估指标口径

### 3.1 资料问答（material_qa）

| 指标 | 计算公式 | 目标 |
| --- | --- | --- |
| 准确率 | 正确回答数 / 总问题数 | ≥ 80% |
| 证据召回率 | 找到正确证据的问题数 / 总问题数 | ≥ 90% |
| 拒绝编造率 | 资料不足时明确"无法回答"的比例 | 100% |

**评判标准：**
- ✅ 正确：回答包含预期证据锚点，且无编造信息
- ⚠️ 部分正确：回答正确但遗漏部分证据
- ❌ 错误：回答编造了不存在的信息，或与证据矛盾

### 3.2 实体状态查询（entity_status）

| 指标 | 计算公式 | 目标 |
| --- | --- | --- |
| 实体定位准确率 | 正确定位到预期任务的问题数 / 总问题数 | ≥ 90% |
| 状态提取准确率 | 正确提取进度/日期等字段的问题数 / 总问题数 | ≥ 85% |

**评判标准：**
- ✅ 正确：定位到 expected_task_id 指定的任务，且状态字段正确
- ❌ 错误：定位到错误任务，或状态字段提取错误

### 3.3 混合查询（mixed）

| 指标 | 计算公式 | 目标 |
| --- | --- | --- |
| 综合准确率 | 正确回答数 / 总问题数 | ≥ 75% |

**评判标准：**
- ✅ 正确：结合了资料和任务状态，推理正确
- ❌ 错误：仅使用部分信息，或推理错误

### 3.4 依赖风险分析（dependency-rules）

| 指标 | 计算公式 | 目标 |
| --- | --- | --- |
| 规则准确率 | reason_code 匹配的规则数 / 总规则数 | 100% |
| 解释合理性 | 人工评估 explanation 是否合理 | ≥ 90% |

**评判标准：**
- ✅ 正确：reason_code 与预期完全匹配
- ❌ 错误：reason_code 与预期不匹配

### 3.5 任务抽取（extraction）

| 指标 | 计算公式 | 目标 |
| --- | --- | --- |
| 任务召回率 | 正确抽取的任务数 / 预期任务总数 | ≥ 90% |
| 字段准确率 | 正确提取的字段数 / 预期字段总数 | ≥ 85% |
| 依赖识别率 | 正确识别的依赖关系数 / 预期依赖总数 | ≥ 80% |

**评判标准：**
- ✅ 正确：抽取了所有预期任务，且字段（标题、负责人、进度、日期、依赖）正确
- ⚠️ 部分正确：遗漏个别任务或字段
- ❌ 错误：抽取了不存在的任务，或关键字段错误

## 4. 如何执行评估

### 4.1 准备工作

1. **配置环境：**
   ```powershell
   # 编辑 .env，确保以下配置：
   NEXUS_MODULE_FACTORY=team_modules.factory:build_modules
   NEXUS_MODULE_MODE=disabled
   NEXUS_LLM_MODE=glm
   NEXUS_LLM_API_KEY=你的智谱 API Key
   NEXUS_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
   NEXUS_LLM_MODEL=glm-4.7-flash
   ```

2. **安装依赖：**
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r team_modules/workflow/requirements.txt
   # 等待 main_rag 负责人确定选型后：
   # .\.venv\Scripts\python.exe -m pip install -r team_modules/main_rag/requirements.txt
   ```

3. **启动服务：**
   ```powershell
   # 终端 1
   .\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
   
   # 终端 2
   .\.venv\Scripts\python.exe -m app.worker
   ```

4. **准备测试数据：**
   - 登录系统（学号/学号）
   - 创建测试项目
   - 上传评估集文档（如 extraction-samples.json 中的文本转为 TXT 上传）

### 4.2 执行评估

#### 步骤 1：资料问答评估

使用 `questions.json` 中的 material_qa 和 mixed 类别问题：

1. 打开 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
2. 调用 `POST /api/v1/assistant/messages`
3. 对每个问题执行：
   ```json
   {
     "entry": "project_assistant",
     "text": "问题文本"
   }
   ```
4. 记录返回的 `answer`、`outcome`、`citations`
5. 对照 `expected_evidence_anchors` 评判

#### 步骤 2：实体状态查询评估

使用 `questions.json` 中的 entity_status 类别问题：

1. 同上调用 `/assistant/messages`
2. 检查返回是否定位到 `expected_task_id` 指定的任务
3. 验证状态字段（进度、日期等）提取是否正确

#### 步骤 3：依赖风险分析评估

使用 `dependency-rules.json`：

1. 在数据库中创建对应任务（按规则描述）
2. 调用 `POST /api/v1/analysis/preview`
   ```json
   {
     "project_id": 1,
     "snapshot": { ... },
     "changes": [ ... ]
   }
   ```
3. 或调用 `GET /api/v1/risk-status` 获取正式分析结果
4. 对比 `reason_code` 是否与预期匹配

#### 步骤 4：任务抽取评估

使用 `extraction-samples.json`：

1. 将 `text` 字段保存为 TXT 文件
2. 上传文档：`POST /api/v1/documents`
3. 等待 Worker 处理完成（查询 `GET /api/v1/jobs/{id}`）
4. 调用提取：`POST /api/v1/documents/{id}/extract`
5. 获取建议：`GET /api/v1/suggestions`
6. 对比 `expected_fields` 评判抽取结果

### 4.3 记录结果

创建评估结果文件：`tests/records/评估日期-evaluation-result.md`

**模板：**

```markdown
# 评估结果报告

## 基本信息
- 评估日期：YYYY-MM-DD
- 评估人：XXX
- 环境：Windows / Python 3.13 / 真实模型

## 资料问答（10 题）
| 问题 ID | 预期证据 | 实际回答 | 评判 |
| --- | --- | --- | --- |
| q001 | ... | ... | ✅/⚠️/❌ |

**准确率：** X/10 = XX%

## 实体状态查询（6 题）
...

## 混合查询（4 题）
...

## 依赖风险（8 条）
...

## 任务抽取（4 段）
...

## 总结
- 总评：XX% 准确率
- 主要问题：...
- 改进建议：...
```

## 5. 注意事项

1. **数据隔离：** project-a 和 project-b 数据不要混用，每次评估只使用一个项目的数据
2. **脱敏要求：** 所有测试数据均为脱敏假数据，不包含真实人名、学号、企业资料
3. **版本冻结：** 评估集一旦创建，不应随意修改。如需扩展，应创建新版本（v2.0）
4. **环境一致：** 评估和复评应使用相同的环境配置和代码版本
5. **人工复核：** 自动评判后，建议人工复核边界案例

## 6. 评估频率

- **开发阶段：** 每个模块完成后执行对应部分的评估
- **集成阶段：** 三个模块全部完成后执行完整评估
- **回归阶段：** 代码重大修改后重新执行全量评估

---

**维护人：** 测试负责人  
**创建日期：** 2026-09-28  
**版本：** v1.0
