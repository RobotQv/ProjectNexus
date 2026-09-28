> 提交方旧环境记录，未在当前整合版上复现。本文模块状态、数量和缺陷结论不能作为当前验收结果。以 ../2026-09-28-integration-review.md 为准。

# 缺陷记录汇总

**项目：** ProjectNexus  
**创建日期：** 2026-09-28  
**维护人：** 测试负责人

---

## 缺陷列表

### BUG-20260928-001

| 字段 | 内容 |
| --- | --- |
| 发现日期 | 2026-09-28 |
| 模块/负责人 | main_rag / 主 RAG 负责人 |
| 代码版本 | N/A（非 git 仓库） |
| 数据版本 | migrations 0003 |
| 环境 | Windows / Python 3.13 / SQLite |

**复现步骤：**

1. 执行 `.\.venv\Scripts\python.exe -m pytest team_modules/main_rag/tests`
2. 测试调用 `MainRAGAdapter().parse(reference)`

**期望结果：**

parse 方法应返回 ParsedDocument 对象，包含解析后的正文块列表。

**实际结果：**

抛出 AppError 异常，错误代码 `module_unavailable`，消息"尚未接入"。

**完整报错：**

```
AppError: module_unavailable - 尚未接入
```

**复现性：**

☑ 稳定复现

**影响范围：**

- 功能模块：主 RAG 资料解析
- 受影响接口：POST /documents、GET /documents/{id}/blocks
- 用户影响：中（资料上传后无法解析和检索）

**状态：**

☑ 新建  
☐ 已确认  
☐ 修复中  
☐ 待验证  
☐ 已关闭

**回归结果：**

| 验证日期 | 验证人 | 结果 | 备注 |
| --- | --- | --- | --- |
| | | ☐通过 ☐失败 | |

---

### BUG-20260928-002

| 字段 | 内容 |
| --- | --- |
| 发现日期 | 2026-09-28 |
| 模块/负责人 | workflow / 工作流负责人 |
| 代码版本 | N/A（非 git 仓库） |
| 数据版本 | migrations 0003 |
| 环境 | Windows / Python 3.13 / SQLite |

**复现步骤：**

1. 配置 `.env` 中 `NEXUS_MODULE_FACTORY=team_modules.factory:build_modules`
2. 启动 API 和 Worker
3. 调用 `POST /assistant/messages` 或 `POST /documents/{id}/extract`

**期望结果：**

- 实体索引应使用 Chroma 向量库存储和检索
- Embedding 应调用智谱 embedding-3 模型

**实际结果：**

测试显示 `test_entity_index.py` 中 1 个测试跳过（未安装 chromadb 时）。

**完整报错：**

```
跳过测试：需要 chromadb 和智谱 API Key
```

**复现性：**

☑ 稳定复现（在未配置完整环境时）

**影响范围：**

- 功能模块：工作流实体索引
- 受影响接口：语义检索、实体定位
- 用户影响：中（无法按名称语义定位任务/成员）

**状态：**

☑ 新建  
☐ 已确认  
☐ 修复中  
☐ 待验证  
☐ 已关闭

**回归结果：**

| 验证日期 | 验证人 | 结果 | 备注 |
| --- | --- | --- | --- |
| | | ☐通过 ☐失败 | |

---

### BUG-20260928-003

| 字段 | 内容 |
| --- | --- |
| 发现日期 | 2026-09-28 |
| 模块/负责人 | risk / 风险负责人 |
| 代码版本 | N/A（非 git 仓库） |
| 数据版本 | migrations 0003 |
| 环境 | Windows / Python 3.13 / SQLite |

**复现步骤：**

1. 执行 `.\.venv\Scripts\python.exe -m pytest team_modules/risk/tests`
2. 测试调用 `RiskAdapter().analyze(snapshot)`

**期望结果：**

analyze 方法应返回 AnalysisResult，包含依赖关卡和日期风险判断结果。

**实际结果：**

抛出 AppError 异常，错误代码 `module_unavailable`，消息"尚未接入"。

**完整报错：**

```
AppError: module_unavailable - 尚未接入
```

**复现性：**

☑ 稳定复现

**影响范围：**

- 功能模块：依赖与风险判断
- 受影响接口：POST /analysis、POST /analysis/preview、GET /risk-status
- 用户影响：中（无法获得依赖风险预警）

**状态：**

☑ 新建  
☐ 已确认  
☐ 修复中  
☐ 待验证  
☐ 已关闭

**回归结果：**

| 验证日期 | 验证人 | 结果 | 备注 |
| --- | --- | --- | --- |
| | | ☐通过 ☐失败 | |

---

## 汇总统计

| 状态 | 数量 |
| --- | --- |
| 新建 | 3 |
| 已确认 | 0 |
| 修复中 | 0 |
| 待验证 | 0 |
| 已关闭 | 0 |
| **总计** | **3** |

## 按模块分布

| 模块 | 缺陷数量 |
| --- | --- |
| main_rag | 1 |
| workflow | 1 |
| risk | 1 |
| app | 0 |
| **总计** | **3** |

---

**备注：**

1. 以上缺陷均为模块未实现功能的预期报错，属于开发中状态，非生产缺陷。
2. 所有缺陷需要各模块负责人完成实现后进行回归验证。
3. 测试使用独立临时数据库，不影响业务数据。
