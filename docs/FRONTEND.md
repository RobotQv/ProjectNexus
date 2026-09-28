> 公开版账号说明：所有账号样例均为虚构演示数据，不是真实学号。登录方式以根 README 为准；仓库不附带 .env 或业务数据。

# 前端接入速查

> 本文已同步 v2 后端接口；业务见 [前端职责](../frontend/README.md)，完整字段见 [结构化数据](DATA_CONTRACTS.md)。不要用手工任务写入接口代替 AI 正式审核。

正式审核逐条修正、通过或驳回；每条提取任务应是独立记录。对话建议先由提交者核对，文档提取直接正式待审并可查看来源原文。所有有效项目成员均可正式审核，包括提交者本人。

本地后端默认 `http://127.0.0.1:8000`，业务前缀 `/api/v1`。接口字段和主要响应类型可直接查看 `/docs` 或 `/openapi.json`。

这里的“本地”指前端同学自己的电脑，不是组长电脑。代码写在 frontend/，先读 frontend/README.md，在自己的数据库建测试账号。账号/令牌/数据不会跨电脑共享，无须部署公网。加入项目的所有登录用户均可编辑任务、上传资料、确认 AI 建议，不按开发分工限制。

## 登录与请求封装

```http
POST /api/v1/auth/login
Content-Type: application/json

{"login_name":"000000003","password":"000000003"}
```

返回 access_token、token_type、expires_in 和 user。后续请求加：

```http
Authorization: Bearer <access_token>
```

本机账号通过 `python -m app.cli seed-students` 初始化；上例演示前导零必须保留，日常请替换为示例登录名。login_name 和初始 password 均为字符串，学号初始密码仅限课设本地开发。前端不用写注册页面。令牌过期返回 401，跳回登录；不要把密钥或令牌写进代码仓库，不建议把登录令牌长期存放在 localStorage。

```javascript
// token 可来自内存状态管理；文件上传交给浏览器设置 multipart boundary。
async function api(path, { token, body, method = 'GET' } = {}) {
  const headers = { Authorization: `Bearer ${token}` };
  const isFile = body instanceof FormData;
  if (body && !isFile) headers['Content-Type'] = 'application/json';
  const response = await fetch(`http://127.0.0.1:8000/api/v1${path}`, {
    method, headers, body: body ? (isFile ? body : JSON.stringify(body)) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw data;
  return data;
}
```

上传的 FormData 中必填 `file`，可填 `document_type`、`document_date`。源文件下载接口不是 JSON，要使用 `response.blob()` 并带 Authorization，不能简单裸链接依赖 Cookie。

## 页面与接口

下表 `{p}` 为 project_id，`{id}` 为对应资源 ID。

| 页面动作 | 请求 |
| --- | --- |
| 获取 / 创建项目 | GET / POST `/projects` |
| 项目详情 / 修改或归档 | GET / PATCH `/projects/{p}` |
| 成员列表 / 添加已建账号 | GET / POST `/projects/{p}/members` |
| 成员别名 / 移除 | PATCH / DELETE `/projects/{p}/members/{user_id}` |
| 任务列表 / 新增 | GET / POST `/projects/{p}/tasks` |
| 任务完整历史快照 | GET `/projects/{p}/tasks/{id}/history` |
| 任务详情 / 编辑 / 软删除 | GET / PATCH / DELETE `/projects/{p}/tasks/{id}` |
| 依赖列表 / 新增 | GET / POST `/projects/{p}/dependencies` |
| 整体编辑依赖 / 删除 | PUT / DELETE `/projects/{p}/dependencies/{id}` |
| 文件列表 / 上传 | GET / POST `/projects/{p}/documents` |
| 资料详情 / 软删除 | GET / DELETE `/projects/{p}/documents/{id}` |
| 原文件 / 正文块 | GET `/projects/{p}/documents/{id}/source?version=1`、`/blocks?version=1` |
| 失败的资料入库重试 | POST `/projects/{p}/documents/{id}/retry` |
| 提取 / 摘要 | POST `/projects/{p}/documents/{id}/extract`，body 为 `{"kind":"extract"}` 或 `{"kind":"summary"}` |
| 工作流执行状态 / 摘要 | GET `/projects/{p}/workflow-runs/{id}` |
| 两处 AI 对话入口 | POST `/projects/{p}/assistant/messages` |
| 对话结果回看（提交者） | GET `/projects/{p}/assistant/runs/{id}` |
| 编辑建议 / 提交预审 | PATCH `/projects/{p}/suggestions/{id}`、POST `/projects/{p}/suggestions/{id}/submit` |
| 建议详情 / 来源原文 | GET `/projects/{p}/suggestions/{id}`、`/suggestions/{id}/source` |
| 候选风险预览 / 当前检查状态 | POST `/projects/{p}/analysis/preview`、GET `/projects/{p}/risk-status` |
| 待审建议 / 审核 | GET `/projects/{p}/suggestions`、POST `/projects/{p}/suggestions/{id}/review` |
| 项目问答 | POST `/projects/{p}/queries` |
| 规则分析 / 历史分析 | POST `/projects/{p}/analysis`、GET `/projects/{p}/analysis/{id}` |
| 人工风险列表 / 登记 / 解决 | GET / POST `/projects/{p}/risks`、PATCH `/projects/{p}/risks/{id}` |
| 后台列表 / 状态 / 重试 | GET `/projects/{p}/jobs`、GET `/projects/{p}/jobs/{id}`、POST `/projects/{p}/jobs/{id}/retry` |
| 操作审计（负责人） | GET `/projects/{p}/audit-events` |

大部分列表采用 `{items, limit, offset}`；成员列表为 `{items}`。分页默认 50、最大200；依赖列表默认100、最大500；正文块默认100、最大500。无需依赖返回总数，少于 limit 时可停止加载。

## 创建和编辑任务

```json
{
  "title": "后端登录接口",
  "description": "完成登录与项目权限校验",
  "assignee_id": 1,
  "module_name": "后端",
  "tags": ["FastAPI"],
  "aliases": ["登录"],
  "status": "not_started",
  "progress": 0,
  "planned_end": "2026-09-25"
}
```

`assignee_id` 是 User.id，必须是有效项目成员。拿任务响应中的 version，PATCH 时带 expected_version：

```json
{"expected_version":1,"status":"in_progress","progress":40}
```

进度滑块和状态控件需成对检查：done/100、not_started/0；后端不会自动纠正矛盾字段。422 展示校验信息；409 提醒“数据已更新，请刷新”，不要默默覆盖重试。

可空字段使用 `null` 清除；省略字段表示不改。title/status/progress/tags/aliases 不允许显式 null。删除任务、删除依赖把 expected_version 放在查询参数；依赖编辑 PUT 必须提交完整依赖字段和 expected_version。

## 上传和审核的页面状态

```text
上传返回 202：document + job_id
  → 每隔约 2 秒 GET /jobs/{job_id}
    → queued / running：继续等待
    → failed：展示 error_message 与重试按钮
    → succeeded：刷新文档的 parse_status、index_status
      → /extract 返回 workflow_run_id + job_id
      → 等待 Job 后刷新建议列表 / 工作流摘要
      → 逐条人工编辑、确认或拒绝
```

`parse_status=ready` 不等于 `index_status=ready`。202 不等于处理成功；页面离开后应停止轮询。示例模式要展示 DEMO 标识，不能把 `chunk_count=0 / demo-no-vector-index` 当真实索引。

```json
{
  "action": "confirm",
  "expected_version": 1,
  "overrides": {"title":"确认后的任务名称","assignee_id":1}
}
```

reject 请求无需 overrides。已经确认的建议再次 confirm 返回同一个 target_id，不创建重复任务。显示 source_refs 的文档版本和引用，通过鉴权接口查看原文。

## 两处 AI 入口与逐条审核

两处入口共用 POST `/projects/{p}/assistant/messages`：

```json
{"entry":"task_assistant","text":"登录接口完成七成，请更新进度","request_key":"a5ef31524ad6480a838e62f4e171c096"}
```

完整助手用 entry=project_assistant。每次主动提问生成新 request_key（如 UUID），网络重试复用原值；同键不同内容 409。接口同步返回 AssistantOut，真实理解由工作流实现；demo 返回固定标记建议。失败运行状态可在 `/workflow-runs/{run_id}` 查看；如果客户端未取得 run_id，可重新提交原 request_key 查询状态，错误 details 包含 run_id/status。

返回建议最初是 draft，前端在对话中核对并调用 `/suggestions/{id}/submit`，body 是 `{"expected_version":1}`；后端变为 pending，仍不修改任务。PATCH 建议时 body 为 `{"expected_version":1,"proposed_payload":{...完整候选载荷...}}`。正式审核页查询 `/suggestions?status=pending`；每条任务独立卡片、独立确认或拒绝。文档结果直接 pending。不同建议不使用一个全有或全无的批量审核请求。

显示 submitted_by、created_at、submitted_at、reviewed_by、reviewed_at、review_note 和 source_kind；名字可从项目成员映射，不用开发分工限制按钮。draft 仅提交者可见/编辑，pending 任意有效成员可审核。

更新任务建议的审核有两种版本：最外层 expected_version 是建议版本，proposed_payload.expected_version 是目标任务版本。遇到冲突必须展示最新任务让人重新核对，不自动替换目标版本。完整格式和 overrides 合并规则见 DATA_CONTRACTS.md。

GET `/risk-status` 的 job 表示变更后的自动检查，analysis 是最近保存的结果，is_stale=true 时不能当成最新结论；Worker 未启动会 queued，模块未接入会 failed，不展示成无风险。无定时风险扫描，不增加外部通知。

## 兼容查询的最小约定（旧 /queries）

```json
{"question":"所有未完成任务","route":"structured","limit":20}
```

```json
{"question":"退款这块现在怎样","route":"mixed","task_id":12,"synthesize":true,"include_analysis":false}
```

支持 route=auto/structured/document/mixed，task_id、assignee_id、status、overdue、entity_type(task/member) 和 limit。明确的筛选条件优先；复杂自然语言暂不能保证自动路由正确。

- answered：有数据可答；优先展示 facts / evidence / analysis。
- clarify：有歧义，展示 candidates 供用户选择，再携带明确 ID 查询。
- insufficient：没有足够数据，不展示虚构的原因。
- partial：只找到部分数据或模型/模块不可用，展示 warnings。

facts 是数据库任务快照；evidence 是核验过的原文引用；analysis 是带日期/快照哈希的规则结论；RiskItem 则是人工事项，页面分开显示。即使模型回答包含额外来源文字，也不要把它当成 evidence。

## 统一错误

```json
{
  "error": {"code":"conflict","message":"数据已发生变化，请刷新后重试","details":null},
  "request_id":"后端生成的请求编号"
}
```

401 未登录/令牌失效；403 项目内操作权限不足；404 不存在或不在项目范围；409 版本、状态或重复冲突；413 文件/请求过大；422 字段或业务规则错误；429 登录限流；502/503/504 外部服务错误、未配置或超时。反馈问题时附 request_id，不附密码或令牌。
