/**
 * 按页面动作组织的接口清单；路径与 docs/FRONTEND.md 的表格一一对应。
 * {p} 为 project_id，{id} 为对应资源 ID。
 */
import { api } from './client.js'

const P = (pid) => `/projects/${pid}`

export const authApi = {
  login: (login_name, password) => api.post('/auth/login', { login_name, password }),
  me: () => api.get('/auth/me'),
}

export const projectApi = {
  list: (query) => api.get('/projects', query),
  create: (body) => api.post('/projects', body),
  get: (pid) => api.get(P(pid)),
  patch: (pid, body) => api.patch(P(pid), body),
  members: (pid) => api.get(`${P(pid)}/members`),
  addMember: (pid, body) => api.post(`${P(pid)}/members`, body),
  patchMember: (pid, userId, body) => api.patch(`${P(pid)}/members/${userId}`, body),
  removeMember: (pid, userId) => api.del(`${P(pid)}/members/${userId}`),
}

export const taskApi = {
  list: (pid, query) => api.get(`${P(pid)}/tasks`, query),
  create: (pid, body) => api.post(`${P(pid)}/tasks`, body),
  get: (pid, id) => api.get(`${P(pid)}/tasks/${id}`),
  patch: (pid, id, body) => api.patch(`${P(pid)}/tasks/${id}`, body),
  // 删除把 expected_version 放在查询参数。
  remove: (pid, id, expected_version) => api.del(`${P(pid)}/tasks/${id}`, { expected_version }),
  history: (pid, id, query) => api.get(`${P(pid)}/tasks/${id}/history`, query),
}

export const dependencyApi = {
  list: (pid, query) => api.get(`${P(pid)}/dependencies`, query),
  create: (pid, body) => api.post(`${P(pid)}/dependencies`, body),
  // PUT 必须提交完整依赖字段和 expected_version。
  replace: (pid, id, body) => api.put(`${P(pid)}/dependencies/${id}`, body),
  remove: (pid, id, expected_version) => api.del(`${P(pid)}/dependencies/${id}`, { expected_version }),
}

export const documentApi = {
  list: (pid, query) => api.get(`${P(pid)}/documents`, query),
  // 上传只返回 202 与 job_id，处理结果要靠轮询 Job。
  upload: (pid, formData) => api.form(`${P(pid)}/documents`, formData),
  get: (pid, id) => api.get(`${P(pid)}/documents/${id}`),
  remove: (pid, id) => api.del(`${P(pid)}/documents/${id}`),
  retry: (pid, id) => api.post(`${P(pid)}/documents/${id}/retry`),
  blocks: (pid, id, version, query) => api.get(`${P(pid)}/documents/${id}/blocks`, { version, ...query }),
  sourceUrl: (pid, id, version) => `${P(pid)}/documents/${id}/source?version=${version}`,
  extract: (pid, id, kind) => api.post(`${P(pid)}/documents/${id}/extract`, { kind }),
}

export const jobApi = {
  list: (pid, query) => api.get(`${P(pid)}/jobs`, query),
  get: (pid, id) => api.get(`${P(pid)}/jobs/${id}`),
  retry: (pid, id) => api.post(`${P(pid)}/jobs/${id}/retry`),
  workflowRun: (pid, runId) => api.get(`${P(pid)}/workflow-runs/${runId}`),
}

export const suggestionApi = {
  list: (pid, query) => api.get(`${P(pid)}/suggestions`, query),
  get: (pid, id) => api.get(`${P(pid)}/suggestions/${id}`),
  // PATCH 是完整替换 proposed_payload。
  edit: (pid, id, expected_version, proposed_payload) =>
    api.patch(`${P(pid)}/suggestions/${id}`, { expected_version, proposed_payload }),
  // 提交者核对后进入正式审核；此时仍不修改正式任务。
  submit: (pid, id, expected_version) => api.post(`${P(pid)}/suggestions/${id}/submit`, { expected_version }),
  // expected_version 是建议版本；overrides 是字段补丁。
  review: (pid, id, body) => api.post(`${P(pid)}/suggestions/${id}/review`, body),
  source: (pid, id) => api.get(`${P(pid)}/suggestions/${id}/source`),
}

export const assistantApi = {
  progress: (pid, request_key) => api.get(`${P(pid)}/assistant/progress`, { request_key }),
  // 两处入口共用，以 entry 区分：project_assistant / task_assistant。
  send: (pid, entry, text, request_key) =>
    api.post(`${P(pid)}/assistant/messages`, { entry, text, request_key }),
  run: (pid, runId) => api.get(`${P(pid)}/assistant/runs/${runId}`),
}

export const analysisApi = {
  run: (pid, evaluation_date) => api.post(`${P(pid)}/analysis`, { evaluation_date: evaluation_date || null }),
  get: (pid, runId) => api.get(`${P(pid)}/analysis/${runId}`),
  preview: (pid, changes) => api.post(`${P(pid)}/analysis/preview`, changes),
  riskStatus: (pid) => api.get(`${P(pid)}/risk-status`),
  risks: (pid, query) => api.get(`${P(pid)}/risks`, query),
  createRisk: (pid, body) => api.post(`${P(pid)}/risks`, body),
  patchRisk: (pid, id, body) => api.patch(`${P(pid)}/risks/${id}`, body),
}

export const queryApi = {
  ask: (pid, body) => api.post(`${P(pid)}/queries`, body),
}

/** 每次主动提问生成新 request_key；网络重试复用原值，同键不同内容会 409。 */
export function newRequestKey() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, '')
  return `req${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}
