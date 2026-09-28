/**
 * 统一请求封装。
 *
 * 约定来自 docs/FRONTEND.md：
 * - 业务前缀 /api/v1，请求带 Bearer token；
 * - 错误体为 { error: { code, message, details }, request_id }；
 * - 文件下载不是 JSON，要带 Authorization 用 blob；
 * - 不把令牌写进 localStorage。
 */

export const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000/api/v1').replace(/\/+$/, '')

/** 后端统一错误体。保留 request_id，便于反馈问题时附带。 */
export class ApiError extends Error {
  constructor(status, payload) {
    const detail = payload && payload.error
    super((detail && detail.message) || `请求失败（${status}）`)
    this.name = 'ApiError'
    this.status = status
    this.code = (detail && detail.code) || 'unknown'
    this.details = (detail && detail.details) || null
    this.requestId = (payload && payload.request_id) || null
  }
}

/** 401 时由会话层接管跳回登录；这里只抛事件，不直接操作路由。 */
let onUnauthorized = () => {}
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

let token = ''
export function setToken(value) {
  token = value || ''
}
export function getToken() {
  return token
}

async function request(path, { method = 'GET', body, query, raw = false } = {}) {
  const url = new URL(API_BASE + path)
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
    }
  }

  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData
  // 文件上传交给浏览器设置 multipart boundary，不能自己写 Content-Type。
  if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'

  let response
  try {
    response = await fetch(url.toString(), {
      method,
      headers,
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    })
  } catch (cause) {
    throw new ApiError(0, {
      error: { code: 'network_unreachable', message: '无法连接本机后端，请确认服务已启动' },
    })
  }

  if (raw) {
    if (!response.ok) throw new ApiError(response.status, await safeJson(response))
    return response
  }

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await safeJson(response) : null
  if (!response.ok) {
    if (response.status === 401) onUnauthorized()
    throw new ApiError(response.status, payload)
  }
  return payload
}

async function safeJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

/**
 * 把后端错误翻成页面能直接显示的一句话。
 * 409 明确要求刷新而不是静默覆盖；422 把逐字段的校验信息带出来。
 */
export function describeError(error) {
  const base = error && error.message ? error.message : '请求失败'
  const suffix =
    error && error.status === 401 ? ' · 登录已失效，请重新登录'
    : error && error.status === 409 ? ' · 数据已更新，请刷新后重试，不要直接覆盖'
    : error && error.status === 413 ? ' · 文件或请求过大'
    : error && error.status === 429 ? ' · 操作过于频繁，请稍后再试'
    : error && error.status >= 502 ? ' · 外部服务或模块不可用'
    : ''

  // 422 的 details 是 [{ field, type, message }]，逐字段展示才有意义。
  let fields = ''
  if (error && error.status === 422 && Array.isArray(error.details) && error.details.length) {
    fields =
      ' · ' +
      error.details
        .filter((d) => d && d.field)
        .map((d) => `${d.field}：${d.message || '校验未通过'}`)
        .join('；')
  }
  return base + suffix + fields
}

export const api = {
  get: (path, query) => request(path, { query }),
  post: (path, body) => request(path, { method: 'POST', body }),
  patch: (path, body) => request(path, { method: 'PATCH', body }),
  put: (path, body) => request(path, { method: 'PUT', body }),
  del: (path, query) => request(path, { method: 'DELETE', query }),
  form: (path, formData) => request(path, { method: 'POST', body: formData }),
  blob: (path, query) => request(path, { query, raw: true }),
}
