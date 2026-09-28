> 公开版账号说明：所有账号样例均为虚构演示数据，不是真实学号。登录方式以根 README 为准；仓库不附带 .env 或业务数据。

# Alpha 使用说明

## 更新现有环境

保留本机 `.env` 和数据库。先停止 API、Worker，再执行：

```powershell
.\.venv\Scripts\python.exe -m app.cli migrate
.\.venv\Scripts\python.exe -m app.alpha_cli reindex
```

迁移增加运行阶段字段，版本为 0004。重建需要已有 embedding 权限，复用已保存的正文，不删除业务数据。旧索引继续保留；如果只想维持旧策略，在 `.env` 设置 `NEXUS_RAG_CHUNK_STRATEGY=baseline` 和 `NEXUS_RAG_RETRIEVAL_MODE=vector` 后重建。更换分块策略后 API 与 Worker 必须使用同一配置并一起重启。

旧 DOCX 如果在旧解析器下上传过，其正文不包含表格；请上传新的文档版本/内容或使用新文档验证。不能重写已审核的来源锚点来补表格。

## 各自开发

仍按根 README 安装 Python 集成依赖，在两个终端运行 API 与 Worker；前端在 `frontend/web` 执行 `npm ci`、`npm run dev`。

前端 `.env.local` 使用 `VITE_API_BASE=/api/v1`，开发代理到 `127.0.0.1:8000`。看接口字段请打开后端 `/docs`。不需要团队成员连接同一数据库。

## 单地址演示

先安装依赖并配置本机模型密钥。PowerShell 7 从根目录执行：

```powershell
# 首次：在独立空库初始化 demo1—demo6，交互设置至少12位密码
pwsh -File scripts/start_demo.ps1 -Initialize
# 后续启动不加 Initialize
pwsh -File scripts/start_demo.ps1
pwsh -File scripts/check_demo.ps1
pwsh -File scripts/stop_demo.ps1
```

脚本构建前端、迁移独立的 `data/alpha-demo/demo.db`，启动 API 与 Worker。浏览器打开 `http://127.0.0.1:8000`，不再单独启动 Vite。端口占用时加 `-Port 18765`。数据库和日志不会被停止脚本删除；只结束经 PID、启动时间、程序路径核验的本次演示进程及子进程。

可用 `-Model glm-5.3-flash` 临时指定演示模型，仅传给本次进程，不修改 `.env`。已有模型可能限流，必须以界面显示的真实失败为准，不能把资料/风险缺失当成正常结果。

如使用 `python -m tests.evaluation.prepare_alpha_demo` 自动初始化合成验收环境，随机密码只保存在本机 `data/alpha-demo/local-credentials.json`，不要打包或公开。

手机和另一台电脑在同一局域网时，用 `-ListenAddress 0.0.0.0` 启动，再访问运行电脑的局域网 IP 与端口。脚本不自动修改防火墙、不申请公网隧道。不同网络访问仍需另行配置；未从外部设备验证前不能宣称公网可用。不要向外暴露学号同密码的开发库。

## 功能与配置

| 配置/能力 | 约定 |
| --- | --- |
| NEXUS_RAG_RETRIEVAL_MODE | vector、bm25、hybrid_rrf；默认 hybrid_rrf |
| NEXUS_RAG_CHUNK_STRATEGY | baseline、bounded、semantic；默认 bounded；semantic 为实验 |
| NEXUS_RAG_CANDIDATE_LIMIT | 两路候选池默认20；RRF常数60，名次从1开始 |
| NEXUS_LLM_MODEL | 可选 glm-4.5-air、glm-4.7、glm-5.3-flash、glm-5.3；不自动改变本机模型 |
| NEXUS_LLM_THINKING | auto 默认按智谱型号发送；其他兼容接口默认省略供应商扩展，也可显式 omit |
| NEXUS_LLM_REASONING_EFFORT | 默认 low；GLM-5.3 系列必须思考，小输出请求预留4096总输出预算 |
| GET /projects/{pid}/assistant/progress | request_key 查询真实阶段、耗时、状态、错误；仅原提交者可读 |
| GET /projects/{pid}/assistant/runs/{id} | 已完成结果；包含回答所依据的 fact_versions，facts 是回查后的当前记录 |

思考预算不是逐字流。第一版是阶段轮询；没有实现 SSE 或 token delta，也不会展示模型内部思考。失败后重新生成必须换 request_key；断网重连先读取原运行，不重复调用模型。

任务名称、别名精确命中不需要 embedding。常见操作外壳可解析，其他自然表达交语义回退，不声称规则覆盖所有表达。重名需要澄清。精确结果和语义结果都不能绕过项目权限、正式事实回查或人工审核。

引用仍是原文摘录。来源文件名和日期由后端回查，不采信模型自报。资料分歧在回答中分别列出，原文可展开；任务历史来自 TaskHistory，不由模型编造。

## 验证与证据

```powershell
pwsh -File tests/records/run_acceptance.ps1
python -m tests.evaluation.compare_models --compare --output artifacts/alpha_handoff/model_comparison_new.json
python -m tests.evaluation.run_alpha_retrieval
python -m tests.evaluation.run_alpha_entities
```

后面三个命令会调用真实官方 API，不属于日常离线测试。模型对照最多每型号1次兼容+4题；无自动重试。检索评估使用12份虚构资料、4开发题和8冻结题，缓存 embedding，不使用业务库。保存逐题排名、Recall@5、MRR@5、上下文字符数和失败；不预设混合检索一定更好。

评估、阶段轨迹、截图与演示脚本保存在被 Git 忽略的 `artifacts/alpha_handoff/`。这些文件只有运行后才存在。正式结论以实际结果为准，小样本不是通用能力榜单。不要把数据缓存、模型密钥、账号密码或本机业务库放入证据包。
