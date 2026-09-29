> 公开版账号说明：所有账号样例均为虚构演示数据，不是真实学号。登录方式以根 README 为准；仓库不附带 .env 或业务数据。

# 前端工程（Vue 3 + Vite）

Alpha 默认 `VITE_API_BASE=/api/v1`。开发时 Vite 代理到本机 8000；构建后由后端同源提供，不再把其他设备的请求指向它自己的 localhost。原有 `.env.local` 如果写了绝对 localhost 地址，需要同步改成 `/api/v1`。

单地址启动、隔离演示库与跨设备限制见 [Alpha 使用说明](../../docs/ALPHA.md)。两个助手用 `/assistant/progress?request_key=...` 读取真实阶段，非模型逐字输出；回答可以打开真实任务历史。

`frontend/` 下的正式前端。同一份界面的单文件交互原型在 `../prototype/`，
用于无环境演示；本目录是需要 Node 才能跑起来的工程版本。

## 启动

```bash
cd frontend/web
npm ci
cp .env.example .env.local     # Windows: copy .env.example .env.local
npm run dev                    # http://localhost:5173
```

默认端口 5173 与后端 `.env` 的 `CORS_ORIGINS` 一致。换端口要改**自己电脑**的
`CORS_ORIGINS`，不要改别人的配置。

`npm run build` 产出 `dist/`；不要提交 `node_modules/` 与 `dist/`。

## 两种数据源

`.env.local` 里的 `VITE_DEFAULT_MODE` 决定启动时的模式，页面右上角「数据源」可随时切换：

- **demo（默认）** — 使用 `src/demo/` 的内置示例数据，不需要后端就能走完所有页面，
  顶部显示「演示数据 · 非实际运行结果」。依赖与风险按 6.1 口径在前端试算，并明确标注
  「演示规则」。**这是演示与交互验收时用的模式。**
- **live** — 登录本机后端，所有页面走真实 HTTP 接口。切到这个模式需要先按根目录 README
  启动后端并执行 `python -m app.cli seed-students`，用示例登录名登录（初始密码同学号）。

真实 AI 需要后端设置 `NEXUS_MODULE_FACTORY=team_modules.factory:build_modules`、配置模型并启动 Worker；后端 demo 仅返回固定示例。没有项目时先在页面创建或让创建者添加成员，不默认访问项目 1。

## 目录

```text
src/
├── api/
│   ├── client.js        统一请求封装：Bearer 令牌、错误体解析、blob 下载
│   └── resources.js     按页面动作组织的接口清单，与 docs/FRONTEND.md 表格一一对应
├── demo/
│   ├── data.js          内置示例数据（与开题报告第六块的截图一致）
│   ├── risk.js          依赖关卡与时间判断的演示规则
│   └── backend.js       内存演示后端，方法签名与 resources.js 对齐
├── stores/
│   ├── session.js       会话与数据源切换；令牌只放内存，不写 localStorage
│   ├── workspace.js     当前项目的数据与业务操作，demo / live 在这里合流
│   └── toasts.js        轻提示
├── composables/
│   └── useJobPolling.js 后台任务轮询，组件卸载自动停表
├── components/          共享组件（含任务 AI 助理、建议卡、上传与来源弹层）
├── views/               六个页面 + 登录页
├── router.js            左侧导航与路由
└── styles.css           设计令牌与样式
```

页面只调用 `stores/workspace.js` 的方法，不关心底层是演示后端还是真实接口。

## 与后端的约定（照做，不要绕开）

- 请求带本机登录得到的 Bearer 令牌；不直连业务库、向量库，不接触模型密钥。
- 编辑任务/依赖带 `expected_version`；`409` 提示刷新后重新核对，不静默覆盖重试；
  `422` 把逐字段的校验信息展示出来。
- 上传返回 `202` 只表示排队：轮询 Job，离开页面停止；失败展示 `error_message` 与重试，
  不假装已成功。`parse_status=ready` 不等于 `index_status=ready`。
- 建议确认前可编辑，确认后展示正式 `target_id`；**重复确认由后端返回原目标，
  前端不自己再建一份任务**。
- 问答区分 answered / clarify / insufficient / partial；引用只展示 `evidence`，
  不把模型自行生成的来源当成真实引用。
- 规则分析与人工登记风险分开展示；不用平均进度画「真实完成率」或健康分。
- 权限以本机后端响应为准，开发分工不限制谁能点哪个功能。

## 新增任务里的 AI 助理

任务管理页有「新建任务」和「AI 助理」两个入口：

- 「新建任务」走 `POST /projects/{p}/tasks`，是人工录入。
- 「AI 助理」走 `POST /projects/{p}/assistant/messages`，`entry=task_assistant`。
  返回的是**草稿**：只有提交者可见，核对并修改字段后调用
  `PATCH /suggestions/{id}` + `POST /suggestions/{id}/submit` 进入正式审核，
  在正式审核通过前不会创建任何任务。

这条链路不能用 `POST /tasks` 绕过——直接建任务会跳过人工确认与审核记录。

## 自测

### 助手对话视窗

项目助手与任务AI助理共用`AssistantConversation.vue`：高度由视口决定，消息和执行阶段只在内部滚动，输入区始终留在视窗底部。默认跟随最新内容，手动上翻后暂停跟随，点击“回到最新消息”恢复。正式回答出现后自动折叠执行阶段，仍可手动展开；失败保留错误与原输入。

以下浏览器回归使用合成HTTP响应，不调用模型或业务数据库。先以演示模式启动Vite，再从项目根目录运行（Playwright需由本机提供）：

```powershell
node tests/evaluation/check_assistant_conversation.mjs <playwright模块路径> http://127.0.0.1:5173
```

覆盖两处入口的桌面/手机固定高度、长回答、阶段更新、自动滚动、上翻历史、完成折叠、手动展开与失败重试。截图和结果写入被Git忽略的`artifacts/assistant_conversation/`。

### 原有交互与逻辑检查

```bash
pip install dukpy
python frontend/tests/原型交互自测.py     # 63 项
python frontend/tests/工程逻辑自测.py     # 36 项
```

上述测试在项目根目录执行。工程逻辑测试使用现有 Node.js，不再依赖 Windows/Python 3.13 没有可用 wheel 的 QuickJS。根目录 `pytest tests/test_frontend_live.py` 还会用临时后端验证前端真实请求与状态管理代码，不连接个人业务库。

覆盖 6.1 的五条交互验收。真实接口联调仍需启动后端后手工走查。

## 边界

提交页面源码、依赖清单、准确的启动命令与移动端适配；不提交 `node_modules`、构建产物、
密钥或账号令牌。API 字段对不上先联系后端，不能绕过后端业务校验。
