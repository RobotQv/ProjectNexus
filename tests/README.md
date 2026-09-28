# 测试负责人工作区

## 2026-09-28 提交整合

本次新增评估草稿、验收记录模板及可执行脚本。先读 [本次复核](records/2026-09-28-integration-review.md)。`records/submitted-20260928/` 是提交方旧环境记录，不代表当前模块状态；评估资料的缺项见 [评估说明](evaluation/README.md)。

在项目根目录执行 `pwsh -File tests/records/run_acceptance.ps1`。脚本使用临时 SQLite 做迁移检查，失败返回非零退出码，日志写入已忽略的 `tests/records/runs/`。不调用真实模型，不改业务库。也支持 `-Python` 指定已装好依赖的 Python 路径。

本目录供测试负责人开展模块提交验收、后续集成/系统测试与缺陷验证。已有文件是前期后端实现时的验证基线，保留但不代表测试同学的交付已完成。开发者自测是日常活动，不要求每人专门交付单测文件；下面的命令只说明怎样使用现有测试。

## 新增后端接口的验收范围

- AI 项目助手与任务 AI 助理都可生成独立建议，提交者核对只提交、不修改正式任务。
- 文档提取直接进入正式审核，可查看准确版本的来源原文。
- 多条任务建议独立保存、修正、通过或驳回；允许提交者本人或其他有效项目成员正式审核，非成员不可操作。
- 提交者、提交时间、来源和审核信息可追溯；文档发起提取者与上传者可以不同。
- 经审核更新已有任务各项业务字段；手动/AI 修改均保留完整历史快照，重复审核不能重复写入。
- 工作流可分析候选依赖风险，相关正式数据变化后自动提示；无定时检查、外部通知或自动状态改写。

后端接口已实现，tests/test_assistant_contracts.py 用替身验证边界与流转；真实算法和页面还需对应成员接入后，由测试负责人开展功能验收。后端测试通过不等于真实 RAG/助手质量已达标。

## 负责需求

本机登录/项目隔离、CRUD、状态日期约束、并发版本、依赖关系、文档生命周期、Job恢复、来源可追溯、人工审核幂等、查询降级，以及各模块接入后的端到端测试。冻结算法评测与开发集分离；数量和分类按原审计，业务预期不清时询问负责人。

## 本地执行

仓库根安装依赖后运行 pytest；不需要给自动单测建账号，夹具会建立临时库/测试用户。手工浏览器验证才需按根 README 启动自己本机服务和创建本机账号。

```powershell
# 全部回归和模块单测
.\.venv\Scripts\python.exe -m pytest
# 当前测试负责人的集成/回归
.\.venv\Scripts\python.exe -m pytest tests
# 模块作者自己的测试
.\.venv\Scripts\python.exe -m pytest team_modules/main_rag/tests
.\.venv\Scripts\python.exe -m pytest team_modules/workflow/tests
.\.venv\Scripts\python.exe -m pytest team_modules/risk/tests
```

tests/test_live_smoke.py 启动随机本机端口，结束后关闭自己创建的进程；网络受限时可先 --ignore=tests/test_live_smoke.py，不能把未执行的启动测试算作通过。

## 输入输出与隔离

- 契约样例使用 shared 的模型，集成入口是 create_app(modules=..., llm=...)；不依赖组长正在运行的后端。
- Module 测试只检查作者输入输出；集成测试另验证业务校验能否拒绝无效候选/引用。
- 样例 ID 仅在对应临时库有效，不把甲电脑的 ID 写成乙电脑的固定依赖。
- 模型与网络默认替身；真实模型验证须显式配置本地 key，用脱敏资料，单独报告结果。
- pytest 的默认目录同时包含根 tests 与 team_modules，各模块 tests 包保留 __init__.py，避免重名文件导入冲突。

## 交付

提交测试源码、小型脱敏样例、输入/预期 reason_code、执行环境/结果、缺陷复现。主干回归通过不等于真实 RAG 准确率达标，demo 空 findings 不等于无风险。总体测试策略见 ../docs/TESTING.md；接口变化要同步契约和所有相关测试。
