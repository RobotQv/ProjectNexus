# ProjectNexus 企业项目智能协作平台

大学课程项目。Vue 3 + Vite 前端、FastAPI 后端、SQLite 业务库；主 RAG、工作流/轻 RAG、任务依赖与风险模块以公共契约接入。

这是脱敏公开副本：只包含源码、接口说明和虚构测试资料，不包含组员真实姓名/学号、模型密钥、业务数据库、上传文件或内部截图。公开历史从本次初始提交开始。本项目用于本地展示，不作为生产部署方案。

## Alpha 更新（2026-09-29）

增加 BM25 / 向量 / RRF 检索、精确任务定位、DOCX 普通表格解析、有界切块、助手真实阶段反馈、来源对照及任务历史。窄屏助手页先展示事实与来源，再展示对话；桌面侧栏背景覆盖整页，导航保持吸顶。

旧环境更新前停止 API 和 Worker，执行 `python -m app.cli migrate` 升级至 0004，再执行 `python -m app.alpha_cli reindex` 建立默认有界切块索引。重建需要自己的 Embedding 权限；不改变原文块 ID 或审核历史。前端需要重新构建或启动开发服务。

详细配置、独立演示库和单地址启动方式见 [Alpha 使用说明](docs/ALPHA.md)。真实模型小样本对照与业务链验证记录见 [Alpha 验证记录](tests/records/2026-09-29-alpha-review.md)。阶段反馈不是逐字流；公网访问、手机真机及复杂表格/OCR 未验收。报告分值不是本项目的测试门槛。

## 检索评估补充（2026-09-29）

新增100题、五种方法的冻结检索对照，同时报告Hit@5、Recall@5和MRR@5，保留单/多锚点及无答案题。完整A、B、合并结果、原文材料、逐题排名和离线复核命令见 [100题检索评估](tests/records/retrieval-100/README.md)。这是合成资料上的检索实验，不代表生产效果或最终回答准确率。

同时修复助手请求结束时中间阶段记录被旧Session缓存覆盖的问题，成功和失败请求均保留已产生的进度事件。本次不修改生产检索默认参数。

## 从零本地启动

推荐 Python 3.13、Node.js 20.19+ 或 22.12+。下载后进入项目根目录，以下为 PowerShell 命令。路径均相对项目根目录。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.integration.lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m app.cli init-env
.\.venv\Scripts\python.exe -m app.cli migrate
.\.venv\Scripts\python.exe -m app.cli seed-students
```

`init-env` 生成本机随机 JWT 密钥，不覆盖已有 `.env`。公开版 `seed-students` 保留兼容命令名，但创建的是 **6 个虚构演示账号**，不是任何真实学生账号。

| 登录名 | 显示名 |
| --- | --- |
| 900000001 | 演示成员甲 |
| 900000002 | 演示成员乙 |
| 000000003 | 演示成员丙 |
| 900000004 | 演示成员丁 |
| 900000005 | 演示成员戊 |
| 900000006 | 演示成员己 |

初始密码与上述虚构登录名相同，仅限本机 development/test，production 禁止初始化。这些账号不会自动创建项目，也不会重置已有密码。需要自设密码时，用 `python -m app.cli create-user --login local-user --name 本地用户`，按提示输入至少 12 字符密码。

终端一（项目根目录）：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

终端二（项目根目录）：

```powershell
.\.venv\Scripts\python.exe -m app.worker
```

终端三：

```powershell
cd frontend/web
npm ci
npm run dev
```

打开前端终端显示的地址。页面默认使用内置演示数据；点“数据源 → 连接本机后端”，用本机账号登录并创建项目。要验证真实后端流程，API 和 Worker 都要运行；Job 返回 202 只表示已接收。

API 协议：[Swagger /docs](http://127.0.0.1:8000/docs)，机器可读协议：[OpenAPI](http://127.0.0.1:8000/openapi.json)。`POST /api/v1/auth/login` 用于应用登录，不是开发者协作账号。每人的数据库、账号和上传文件独立，不跨电脑同步。

## 启用智能模块

公开版不携带免费或付费 Key，`.env.example` 默认禁用模型。普通业务可离线运行。需要真实资料检索/工作流时，自行在本机 `.env` 配置：

```dotenv
NEXUS_MODULE_FACTORY=team_modules.factory:build_modules
NEXUS_LLM_MODE=glm
NEXUS_LLM_API_KEY=填写自己的密钥
```

聊天模型为智谱 BigModel `glm-4.7-flash`，Embedding 为独立接口 `embedding-3`，请自行确认权限与费用。配置后重启 API 和 Worker。模型输出必须经过人工审核才写入正式任务。未配置模块/密钥时明确报错或标记 Job 失败，不把演示结果冒充真实 AI。

## 模块与接口

| 目录 | 内容 |
| --- | --- |
| app/ | 后端业务、账号、审核事务、持久任务、模型出口 |
| shared/ | 公共数据模型、协议、任务结构化字段 |
| team_modules/main_rag/ | 文件清洗、分块、资料索引、检索 |
| team_modules/workflow/ | AI 助手、轻 RAG、建议抽取与工具编排 |
| team_modules/risk/ | 关卡阻塞和日期风险、候选预览 |
| frontend/web/ | 正式 Vue 前端 |
| tests/ | 提交验收、集成回归及评估草稿 |

各目录 README 说明职责。[数据契约](docs/DATA_CONTRACTS.md)、[模块接口](docs/MODULE_CONTRACTS.md)、[前端接口指引](docs/FRONTEND.md) 与 `/docs` 配合使用。

## 验证与已知限制

```powershell
pwsh -File tests/records/run_acceptance.ps1
.\.venv\Scripts\python.exe frontend/tests/原型交互自测.py
.\.venv\Scripts\python.exe frontend/tests/工程逻辑自测.py
npm --prefix frontend/web run build
```

验收脚本使用临时数据库，失败退出码为非零，默认不请求真实模型。运行前安装前后端依赖；日志在 `tests/records/runs/`，不提交仓库。

最新结果见 [Alpha 验证记录](tests/records/2026-09-29-alpha-review.md)，此前整合见 [整合复核](tests/records/2026-09-28-integration-review.md)。提交方旧报告位于 `tests/records/submitted-20260928/`，不能代表当前模块状态。旧版 24 条问题、8 条依赖场景、4 段抽取样例仍是待补齐的草稿；Alpha 新增合成检索对照及四款模型小样本实验，不等于通用模型准确率结论。

风险只做标记和提示，不自动改任务；AI 建议要人工确认；完整任务变更留存历史。长文、表格解析、真实模型效果和连续页面操作仍需进一步验收。

请勿上传 `.env`、数据库、向量库、真实资料、运行日志或个人账号信息。内部审计截图和材料不在公开副本中；公共仓库不包含旧私有 Git 历史。
