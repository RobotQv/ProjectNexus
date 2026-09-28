> 提交方旧环境记录，未在当前整合版上复现。本文模块状态、数量和缺陷结论不能作为当前验收结果。以 ../2026-09-28-integration-review.md 为准。

# 三模块集成验收报告

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 编号 | INT-20260928-001 |
| 模块/负责人 | main_rag + workflow + risk / 各模块负责人 |
| 验收日期 | 2026-09-28 |
| 代码版本 | N/A（非 git 仓库） |
| 数据版本 | migrations 0003 |
| 环境 | Windows / Python 3.13 / SQLite |
| 验收人 | 测试负责人 |

## 三个模块验收结果汇总

| 模块 | 测试用例 | 通过 | 失败 | 跳过 | 状态 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| main_rag | 1 | 1 | 0 | 0 | ✅ 骨架正确 | 有条件通过 |
| workflow | 33 | 32 | 0 | 1 | ✅ 功能完整 | 通过 |
| risk | 1 | 1 | 0 | 0 | ✅ 骨架正确 | 有条件通过 |
| **总计** | **35** | **34** | **0** | **1** | **✅ 全部通过** | - |

### 各模块详细结果

详见：
- [主 RAG 验收报告](2026-09-28-main-rag-acceptance.md)
- [工作流验收报告](2026-09-28-workflow-acceptance.md)
- [风险模块验收报告](2026-09-28-risk-acceptance.md)

## 未覆盖项

### 1. 根 tests 目录全量测试

**原因：** pytest 全量执行（60 个用例）超时，仅完成模块测试（35 个用例）

**未执行的 tests 目录用例：**
- tests/test_assistant_contracts.py (19)
- tests/test_core.py (26)
- tests/test_dependencies.py (8)
- tests/test_documents_workflow.py (12)
- tests/test_hardening.py (7)
- tests/test_live_smoke.py (1)
- tests/test_migrations.py (1)
- tests/test_module_boundaries.py (5)
- tests/test_queries_llm.py (14)
- tests/test_student_accounts.py (5)

**建议：** 单独执行各测试文件，或增加 pytest 超时时间

### 2. 手工接口验收

**原因：** 需要启动 API 和 Worker 服务

**待验收接口：** 见各模块验收报告中的接口清单

**前置条件：**
- `.env` 配置完整（NEXUS_MODULE_FACTORY、NEXUS_LLM_API_KEY）
- 启动 API：`uvicorn app.main:create_app --factory`
- 启动 Worker：`python -m app.worker`

### 3. 真实模型测试

**原因：** 未配置真实智谱 API Key 或使用脱敏测试资料

**待验证：**
- 智谱 GLM-4.7-Flash 聊天接口
- 智谱 embedding-3 向量接口
- 真实文档解析和检索质量

### 4. 前端联调

**原因：** 前端应用尚未创建

**待验证：**
- 页面与 HTTP 接口对接
- 用户上传文档→等待→提取→建议→审核流程
- 任务建议的查看、修改、提交、审核

## 限制

1. **Git 版本追踪缺失：** 当前目录非 git 仓库，无法记录精确代码版本
2. **模块实现不完整：**
   - main_rag：解析、索引、检索未实现
   - risk：风险规则未实现
   - workflow：实体索引需要完整配置才能运行集成测试
3. **测试数据限制：** 使用小型脱敏样例，未验证大部头资料、复杂文档
4. **并发/性能：** 未执行并发测试、压力测试
5. **浏览器自动化：** 未执行端到端浏览器测试（如 Playwright）

## 模块间依赖关系

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  main_rag   │     │  workflow   │     │    risk     │
│  (未实现)   │     │  (已完成)   │     │  (未实现)   │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                  ┌────────▼────────┐
                  │  shared (协议)  │
                  └─────────────────┘
```

- workflow 依赖 shared.contracts 和 shared.llm
- main_rag 和 risk 仅依赖 shared
- 三个模块不互相导入实现
- 后端通过 `team_modules.factory:build_modules` 装配

## 缺陷汇总

详见 [defects.md](defects.md)

| 编号 | 模块 | 描述 | 状态 |
| --- | --- | --- | --- |
| BUG-20260928-001 | main_rag | 模块未实现 | 新建 |
| BUG-20260928-002 | workflow | 实体索引需完整配置 | 新建 |
| BUG-20260928-003 | risk | 模块未实现 | 新建 |

## 结论

☑ 有条件通过（模块骨架正确，部分功能待实现）

**总体评价：**
- 代码风格（ruff）和数据库迁移（alembic）检查全部通过
- 模块骨架和协议定义正确，单测验证了边界行为
- workflow 模块功能完整，测试充分
- main_rag 和 risk 模块待实现真实功能
- 集成测试和手工验收需配置完整环境后执行

**后续工作优先级：**
1. **高：** main_rag 完成选型并实现 parse/ingest/retrieve/delete
2. **高：** risk 实现analyze和analyze_candidates 方法
3. **中：** 配置智谱 API Key，验证实体索引集成
4. **中：** 执行根 tests 目录全量测试
5. **低：** 启动服务执行手工接口验收

---

**验收人签字：** ________________  
**日期：** 2026-09-28
